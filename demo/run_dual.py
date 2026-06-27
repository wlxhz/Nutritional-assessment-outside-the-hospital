from __future__ import annotations

import asyncio
import os
from pathlib import Path

import uvicorn

from backend.main import app


CERT_DIR = Path(__file__).resolve().parent / "certs"
CERT_FILE = CERT_DIR / "localhost.pem"
KEY_FILE = CERT_DIR / "localhost-key.pem"
HTTP_PORT = int(os.getenv("HTTP_PORT", "8001"))
HTTPS_PORT = int(os.getenv("HTTPS_PORT", "8443"))


async def main() -> None:
    if not CERT_FILE.exists() or not KEY_FILE.exists():
        raise SystemExit("缺少 HTTPS 证书，请先运行：python scripts/generate_dev_cert.py")

    http_server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",
            port=HTTP_PORT,
            log_level="info",
        )
    )
    https_server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",
            port=HTTPS_PORT,
            log_level="info",
            ssl_certfile=str(CERT_FILE),
            ssl_keyfile=str(KEY_FILE),
        )
    )
    await asyncio.gather(http_server.serve(), https_server.serve())


if __name__ == "__main__":
    asyncio.run(main())
