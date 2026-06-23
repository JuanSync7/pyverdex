"""FastAPI application exposing pyverify to a web UI.

Endpoints:
  GET  /api/health
  GET  /api/default                  -> default project path (if launched with one)
  POST /api/discover  {path}         -> detected wiring + source/test file lists
  GET  /api/file?root=&path=         -> read one source/test file (sandboxed)
  POST /api/run       {path, apply, provider, max_cycles} -> {run_id}
  GET  /api/runs/{id}?offset=        -> run status + incremental logs + report
  GET  /api/runs/{id}/events         -> SSE stream of logs until completion
  WS   /ws/terminal?path=            -> pty shell in the project (web terminal)

Static frontend (if built) is served at /.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..discovery import discover_config, project_info
from .runs import MANAGER
from .terminal import pty_terminal

STATIC_DIR = Path(__file__).resolve().parent / "static"


class DiscoverReq(BaseModel):
    path: str


class RunReq(BaseModel):
    path: str
    apply: bool = False
    provider: Optional[str] = None
    max_cycles: Optional[int] = None


def create_app(default_project: Optional[str] = None) -> FastAPI:
    app = FastAPI(title="pyverify", version="0.1.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/default")
    def default() -> dict:
        return {"path": str(Path(default_project).resolve()) if default_project else None}

    @app.post("/api/discover")
    def discover(req: DiscoverReq) -> dict:
        try:
            cfg = discover_config(req.path)
        except (NotADirectoryError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return project_info(cfg)

    @app.get("/api/file")
    def read_file(root: str = Query(...), path: str = Query(...)) -> dict:
        base = Path(root).resolve()
        target = (base / path).resolve()
        if not str(target).startswith(str(base)):
            raise HTTPException(403, "path escapes project root")
        if not target.is_file():
            raise HTTPException(404, "not a file")
        try:
            content = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise HTTPException(400, f"unreadable: {exc}") from exc
        return {"path": path, "content": content}

    @app.post("/api/run")
    def start_run(req: RunReq) -> dict:
        try:
            run = MANAGER.start(req.path, apply=req.apply, provider=req.provider,
                                max_cycles=req.max_cycles)
        except (NotADirectoryError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"run_id": run.id, "info": run.info}

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: str, offset: int = 0) -> dict:
        run = MANAGER.get(run_id)
        if not run:
            raise HTTPException(404, "no such run")
        return run.snapshot(log_offset=offset)

    @app.get("/api/runs/{run_id}/events")
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
        path = ws.query_params.get("path") or default_project or "."
        cwd = str(Path(path).resolve())
        await pty_terminal(ws, cwd)

    if (STATIC_DIR / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
    else:
        @app.get("/")
        def _no_ui() -> dict:
            return {"message": "pyverify API is up. Frontend not built — see web/ "
                    "(npm run build) or run the Vite dev server."}

    return app


__all__ = ["create_app"]
