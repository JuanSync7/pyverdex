"""FastAPI application exposing pyverdex to a web UI.

Endpoints:
  GET  /api/health                   -> liveness (open)
  GET  /api/session                  -> per-process auth token (same-origin only)
  GET  /api/default                  -> default project path (if launched with one)
  POST /api/discover  {path}         -> detected wiring + source/test file lists
  GET  /api/file?root=&path=         -> read one source/test file (sandboxed)
  POST /api/run       {path, ...}     -> {run_id}
  GET  /api/runs/{id}?offset=        -> run status + incremental logs + report
  GET  /api/runs/{id}/events         -> SSE stream of logs until completion
  WS   /ws/terminal?path=&token=     -> pty shell in the project (web terminal)

Security model (this is a LOCAL dev tool, usually `pyverdex serve` on 127.0.0.1):
  * Every sensitive endpoint requires a per-process bearer token (random, printed
    at startup). The token is handed to the bundled same-origin UI by
    ``/api/session`` — which only answers requests whose ``Origin`` is loopback
    (or an explicitly allowed origin). A cross-origin page therefore cannot read
    the token (CORS hides the response and the Origin check rejects it outright),
    so it cannot drive ``/api/run`` (RCE), ``/api/file`` (file read) or the
    terminal (shell). This closes cross-site request / WebSocket hijacking.
  * ``/api/file`` and the terminal are pinned to server-approved project roots
    (the launch default + anything explicitly discovered) and use
    ``Path.is_relative_to`` containment — no client-chosen arbitrary root.

Static frontend (if built) is served at /.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..discovery import discover_config, project_info
from .runs import MANAGER
from .terminal import pty_terminal

STATIC_DIR = Path(__file__).resolve().parent / "static"
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}


class DiscoverReq(BaseModel):
    path: str


class RunReq(BaseModel):
    path: str
    apply: bool = False
    provider: Optional[str] = None
    max_cycles: Optional[int] = None
    level: Optional[str] = None  # comma-separated test levels; None => all stages


def create_app(
    default_project: Optional[str] = None,
    *,
    host: str = "127.0.0.1",
    allow_origins: Optional[list[str]] = None,
    allowed_hosts: Optional[list[str]] = None,
) -> FastAPI:
    app = FastAPI(title="pyverdex", version="0.1.0")

    # Per-process secret. The bundled UI fetches it from /api/session; for a
    # cross-origin client (e.g. the hosted wiki talking to your local server)
    # the user pastes the token printed at startup.
    token = secrets.token_urlsafe(32)
    app.state.auth_token = token

    # Extra origins allowed beyond loopback (opt-in via `serve --allow-origin`).
    extra_origins = {o.rstrip("/") for o in (allow_origins or [])}

    # Roots the server will read/run/spawn-shells under. Seeded with the launch
    # default; /api/discover adds any project the user explicitly opens.
    approved_roots: set[str] = set()
    if default_project:
        approved_roots.add(str(Path(default_project).resolve()))

    # CORS only needs to name cross-origin callers; the same-origin UI never
    # triggers it. No credentials (we authenticate with a header token).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(extra_origins),
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
    )

    # Host-header allowlist — the defence against DNS rebinding (a domain rebound
    # to 127.0.0.1 still sends its own Host, which is rejected here before any
    # route or the token dispenser runs). Added last so it is the outermost layer.
    host_allow = {"localhost", "127.0.0.1", "::1", host}
    host_allow |= {h for o in extra_origins if (h := urlsplit(o).hostname)}
    host_allow |= set(allowed_hosts or [])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(host_allow))

    def _origin_ok(origin: Optional[str]) -> bool:
        # No Origin header → not a cross-origin browser request (curl, same-origin
        # GET, in-process test). The token requirement still applies downstream.
        if not origin:
            return True
        host = (urlsplit(origin).hostname or "").lower()
        if host in _LOOPBACK_HOSTS:
            return True
        return origin.rstrip("/") in extra_origins

    def _check_token(supplied: Optional[str]) -> bool:
        return bool(supplied) and secrets.compare_digest(supplied, token)

    def require_auth(
        request: Request,
        x_pyverdex_token: Optional[str] = Header(default=None),
        token_q: Optional[str] = Query(default=None, alias="token"),
    ) -> None:
        # Origin first: a disallowed cross-origin caller is rejected even if it
        # somehow guessed a token. EventSource/WebSocket can't set headers, so a
        # ?token= query param is accepted as a fallback.
        if not _origin_ok(request.headers.get("origin")):
            raise HTTPException(403, "origin not allowed")
        if not _check_token(x_pyverdex_token or token_q):
            raise HTTPException(403, "missing or invalid token")

    def _within_approved(p: Path) -> bool:
        return any(p == Path(r) or p.is_relative_to(Path(r)) for r in approved_roots)

    def _resolve_approved(path: str) -> Path:
        """Resolve `path`, requiring it to be (within) an approved project root."""
        p = Path(path).resolve()
        if _within_approved(p):
            return p
        raise HTTPException(403, "path is not an approved project root")

    auth = [Depends(require_auth)]

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/session")
    def session(request: Request) -> dict:
        # Token dispenser. Only same-origin (loopback) / explicitly-allowed callers
        # may read it — this is what keeps the token out of a malicious page.
        if not _origin_ok(request.headers.get("origin")):
            raise HTTPException(403, "origin not allowed")
        return {"token": token}

    @app.get("/api/default", dependencies=auth)
    def default() -> dict:
        return {"path": str(Path(default_project).resolve()) if default_project else None}

    @app.post("/api/discover", dependencies=auth)
    def discover(req: DiscoverReq) -> dict:
        try:
            cfg = discover_config(req.path)
        except (NotADirectoryError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        info = project_info(cfg)
        root = Path(info["project_root"]).resolve()
        # Opening a project approves it for file-read / run / terminal. When the
        # server is *pinned* to a launch default, only roots under it may be
        # approved; a server started with no default is a browse-anything
        # dashboard for the local user, so any opened project is approved.
        if default_project is None or _within_approved(root):
            approved_roots.add(str(root))
        return info

    @app.get("/api/file", dependencies=auth)
    def read_file(root: str = Query(...), path: str = Query(...)) -> dict:
        base = _resolve_approved(root)
        target = (base / path).resolve()
        if not (target == base or target.is_relative_to(base)):
            raise HTTPException(403, "path escapes project root")
        if not target.is_file():
            raise HTTPException(404, "not a file")
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise HTTPException(400, f"unreadable: {exc}") from exc
        return {"path": path, "content": content}

    @app.post("/api/run", dependencies=auth)
    def start_run(req: RunReq) -> dict:
        _resolve_approved(req.path)  # only run in an approved project
        try:
            run = MANAGER.start(req.path, apply=req.apply, provider=req.provider,
                                max_cycles=req.max_cycles, level=req.level)
        except (NotADirectoryError, FileNotFoundError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"run_id": run.id, "info": run.info}

    @app.get("/api/runs/{run_id}", dependencies=auth)
    def get_run(run_id: str, offset: int = 0) -> dict:
        run = MANAGER.get(run_id)
        if not run:
            raise HTTPException(404, "no such run")
        return run.snapshot(log_offset=offset)

    @app.get("/api/runs/{run_id}/events", dependencies=auth)
    async def run_events(run_id: str) -> StreamingResponse:
        run = MANAGER.get(run_id)
        if not run:
            raise HTTPException(404, "no such run")

        async def gen():
            offset = 0
            while True:
                snap = run.snapshot(log_offset=offset)
                offset = snap["log_count"]
                for line in snap["logs"]:
                    yield f"data: {json.dumps({'log': line})}\n\n"
                if run.status != "running":
                    yield "data: " + json.dumps({
                        "status": run.status, "report": run.report, "error": run.error
                    }) + "\n\n"
                    return
                await asyncio.sleep(0.4)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.websocket("/ws/terminal")
    async def terminal(ws: WebSocket) -> None:
        # WebSocket handshakes aren't covered by CORS, so the Origin check here is
        # the defence against cross-site WebSocket hijacking. Reject before accept.
        if not _origin_ok(ws.headers.get("origin")):
            await ws.close(code=4403)
            return
        if not _check_token(ws.query_params.get("token")):
            await ws.close(code=4403)
            return
        path = ws.query_params.get("path") or default_project or "."
        try:
            cwd = str(_resolve_approved(path))
        except HTTPException:
            await ws.close(code=4403)
            return
        await pty_terminal(ws, cwd)

    if (STATIC_DIR / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    else:
        @app.get("/")
        def _no_ui() -> dict:
            return {"message": "pyverdex API is up. Frontend not built — see web/ "
                    "(npm run build) or run the Vite dev server."}

    return app


__all__ = ["create_app"]
