"""FastAPI server tests via the in-process TestClient (deterministic run)."""

from __future__ import annotations

import time
import warnings
from pathlib import Path

from fastapi.testclient import TestClient

from pyverify.server import create_app

warnings.filterwarnings("ignore")
REPO = Path(__file__).resolve().parents[1]
SAMPLE = str(REPO / "examples" / "sample_project")


def _client():
    return TestClient(create_app(default_project=SAMPLE))


def test_health_and_default():
    c = _client()
    assert c.get("/api/health").json() == {"ok": True}
    assert c.get("/api/default").json()["path"].endswith("sample_project")


def test_discover_endpoint():
    c = _client()
    d = c.post("/api/discover", json={"path": SAMPLE}).json()
    assert d["source_root"] == "src" and d["test_root"] == "tests"


def test_file_read_is_sandboxed():
    c = _client()
    ok = c.get("/api/file", params={"root": SAMPLE, "path": "src/sample/calc.py"})
    assert ok.status_code == 200 and "def classify" in ok.json()["content"]
    escape = c.get("/api/file", params={"root": SAMPLE, "path": "../../../../etc/passwd"})
    assert escape.status_code == 403


def test_run_endpoint_produces_report():
    c = _client()
    rid = c.post("/api/run", json={"path": SAMPLE, "apply": False}).json()["run_id"]
    snap = {}
    for _ in range(80):
        snap = c.get(f"/api/runs/{rid}").json()
        if snap["status"] != "running":
            break
        time.sleep(0.5)
    assert snap["status"] == "done"
    assert snap["report"]["overall_status"] in {"pass", "fail", "warn"}
    assert any(d["name"] == "line" for d in snap["report"]["dimensions"])


def test_terminal_websocket_echo():
    c = _client()
    with c.websocket_connect(f"/ws/terminal?path={SAMPLE}") as ws:
        ws.send_text("echo PYVERIFY_WS_OK\n")
        got = ""
        for _ in range(30):
            try:
                got += ws.receive_bytes().decode(errors="ignore")
            except Exception:
                break
            if "PYVERIFY_WS_OK" in got:
                break
        assert "PYVERIFY_WS_OK" in got
