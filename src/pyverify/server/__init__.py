"""pyverify web server: FastAPI API + pty web terminal + static frontend."""

from .app import create_app

__all__ = ["create_app"]
