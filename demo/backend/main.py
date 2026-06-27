from __future__ import annotations

from io import BytesIO
import os
from pathlib import Path
import socket

import qrcode
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.models.schemas import CaptureEvent, FrameUpload, JoinSessionRequest
from backend.services.analyzer import FoodAnalyzer
from backend.services.nutrition import FOOD_PROFILES, all_profiles
from backend.services.session_store import SessionStore


BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "static"

analyzer = FoodAnalyzer()
store = SessionStore(analyzer)

app = FastAPI(title="Realtime Food Weight Demo", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def local_lan_ip() -> str:
    """Best-effort LAN IP for phone QR codes.

    If Dashboard is opened through 127.0.0.1, the phone would otherwise scan a
    loopback address and try to connect to itself. This picks the machine's LAN
    address so the phone can reach this computer.
    """
    configured = os.getenv("MOBILE_HOST")
    if configured:
        return configured

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass

    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = item[4][0]
            if ip and not ip.startswith("127.") and not ip.startswith("169.254."):
                return ip
    except OSError:
        pass

    return "127.0.0.1"


def mobile_base_url(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        scheme = forwarded_proto or request.url.scheme
        return f"{scheme}://{forwarded_host}"

    host = request.url.hostname or "127.0.0.1"
    scheme = request.url.scheme
    port = request.url.port

    if host in {"127.0.0.1", "localhost", "::1"}:
        scheme = os.getenv("MOBILE_SCHEME", "https")
        host = local_lan_ip()
        port = int(os.getenv("MOBILE_PORT", "8443" if scheme == "https" else "8000"))
    elif scheme == "http" and port == 8000:
        scheme = os.getenv("MOBILE_SCHEME", "https")
        port = int(os.getenv("MOBILE_PORT", "8443" if scheme == "https" else "8000"))

    default_port = 443 if scheme == "https" else 80
    port_part = "" if port in {None, default_port} else f":{port}"
    return f"{scheme}://{host}{port_part}"


def public_base_url(request: Request) -> str:
    forwarded_proto = request.headers.get("x-forwarded-proto")
    forwarded_host = request.headers.get("x-forwarded-host")
    if forwarded_host:
        scheme = forwarded_proto or request.url.scheme
        return f"{scheme}://{forwarded_host}"
    return str(request.base_url).rstrip("/")


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/capture", response_class=HTMLResponse)
async def capture() -> FileResponse:
    return FileResponse(STATIC_DIR / "capture.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"ok": "true", "analyzer": analyzer.backend_name, "model": analyzer.model_name}


@app.get("/api/network-info")
async def network_info(request: Request) -> dict[str, str]:
    return {
        "dashboard_base_url": public_base_url(request),
        "mobile_base_url": mobile_base_url(request),
        "lan_ip": local_lan_ip(),
    }


@app.get("/api/foods")
async def foods_database():
    return {"count": len(FOOD_PROFILES), "foods": all_profiles()}


@app.post("/api/sessions")
async def create_session(request: Request):
    return store.create_session(mobile_base_url(request))


@app.get("/api/sessions/{session_id}/state")
async def get_state(session_id: str):
    try:
        return store.get(session_id).state
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


@app.get("/api/sessions/{session_id}/qrcode")
async def qrcode_png(session_id: str):
    try:
        capture_url = store.get(session_id).state.capture_url
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    image = qrcode.make(capture_url)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="image/png")


@app.post("/api/sessions/{session_id}/join")
async def join_session(session_id: str, payload: JoinSessionRequest):
    try:
        state = await store.join_mobile(session_id, payload.token, payload.device)
        return {"ok": True, "session_status": state.status, "state": state}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="invalid token") from exc


@app.post("/api/sessions/{session_id}/capture-event")
async def capture_event(session_id: str, payload: CaptureEvent):
    try:
        return await store.capture_event(session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="invalid token") from exc


@app.post("/api/sessions/{session_id}/frames")
async def upload_frame(session_id: str, payload: FrameUpload):
    try:
        return await store.process_frame(session_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="invalid token") from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"frame analyze failed: {exc}") from exc


@app.get("/api/sessions/{session_id}/latest-frame")
async def latest_frame(session_id: str):
    try:
        frame = store.get(session_id).latest_frame_bytes
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc
    if not frame:
        return Response(status_code=204)
    return Response(content=frame, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/sessions/{session_id}/finish")
async def finish_session(session_id: str):
    try:
        return await store.finish(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="session not found") from exc


@app.get("/api/reports/{report_id}")
async def get_report(report_id: str):
    try:
        return store.report(report_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="report not found") from exc


@app.websocket("/ws/sessions/{session_id}/events")
async def session_events(websocket: WebSocket, session_id: str):
    try:
        store.get(session_id)
    except KeyError:
        await websocket.close(code=4404)
        return
    await store.add_socket(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        store.remove_socket(session_id, websocket)
