from pathlib import Path

import uvicorn


CERT_DIR = Path(__file__).resolve().parent / "certs"
CERT_FILE = CERT_DIR / "localhost.pem"
KEY_FILE = CERT_DIR / "localhost-key.pem"


if __name__ == "__main__":
    if not CERT_FILE.exists() or not KEY_FILE.exists():
        raise SystemExit("缺少 HTTPS 证书，请先运行：python scripts/generate_dev_cert.py")
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8443,
        reload=False,
        ssl_certfile=str(CERT_FILE),
        ssl_keyfile=str(KEY_FILE),
    )
