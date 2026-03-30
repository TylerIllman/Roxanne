from __future__ import annotations

import os

import uvicorn

from roxanne_backend.main import app


def main() -> None:
    host = os.getenv("ROXANNE_HOST", "127.0.0.1")
    port = int(os.getenv("ROXANNE_PORT", "8000"))
    log_level = os.getenv("ROXANNE_LOG_LEVEL", "info")
    uvicorn.run(app, host=host, port=port, log_level=log_level)


if __name__ == "__main__":
    main()
