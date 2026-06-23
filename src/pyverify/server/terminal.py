"""A pty-backed web terminal bridged over a WebSocket.

Spawns an interactive shell in the project directory so you can run pytest /
``pyverify run`` straight from the browser. The client (xterm.js) sends raw
keystrokes as text/binary and ``{"type":"resize","rows","cols"}`` JSON for
window resizes; the shell's output is streamed back as binary frames.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import os
import pty
import signal
import struct
import termios
import threading
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


async def pty_terminal(ws: WebSocket, cwd: str, *, shell: Optional[str] = None) -> None:
    shell = shell or os.environ.get("SHELL", "/bin/bash")
    await ws.accept()

    pid, fd = pty.fork()
    if pid == 0:  # child → become the shell
        try:
            os.chdir(cwd)
        except OSError:
            pass
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["PYVERIFY_WEB_TERMINAL"] = "1"
        os.execvpe(shell, [shell, "-i"], env)
        os._exit(1)  # pragma: no cover

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            try:
                data = os.read(fd, 65536)
            except OSError:
                break
            if not data:
                break
            loop.call_soon_threadsafe(queue.put_nowait, data)
        loop.call_soon_threadsafe(queue.put_nowait, None)

    threading.Thread(target=reader, daemon=True).start()

    async def to_client() -> None:
        while True:
            data = await queue.get()
            if data is None:
                break
            try:
                await ws.send_bytes(data)
            except Exception:  # noqa: BLE001 — client gone
                break

    sender = asyncio.create_task(to_client())
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            text = msg.get("text")
            if text is not None:
                try:
                    obj = json.loads(text)
                except (json.JSONDecodeError, TypeError):
                    os.write(fd, text.encode())
                    continue
                if isinstance(obj, dict) and obj.get("type") == "resize":
                    _set_winsize(fd, int(obj.get("rows", 24)), int(obj.get("cols", 80)))
                elif isinstance(obj, dict) and obj.get("type") == "input":
                    os.write(fd, str(obj.get("data", "")).encode())
                else:
                    os.write(fd, text.encode())
            elif msg.get("bytes") is not None:
                os.write(fd, msg["bytes"])
    except WebSocketDisconnect:
        pass
    finally:
        stop.set()
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        sender.cancel()


__all__ = ["pty_terminal"]
