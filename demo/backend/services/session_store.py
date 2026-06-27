from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import WebSocket

from backend.models.schemas import (
    CaptureEvent,
    CreateSessionResponse,
    DeviceInfo,
    FrameUpload,
    Guidance,
    Report,
    SessionState,
    VideoInfo,
)
from backend.services.analyzer import FoodAnalyzer


CHINA_TZ = timezone(timedelta(hours=8))


class SessionRecord:
    def __init__(self, session_id: str, token: str, public_base_url: str) -> None:
        now = datetime.now(CHINA_TZ)
        capture_url = f"{public_base_url}/capture?session_id={session_id}&token={token}"
        self.token = token
        self.created_monotonic = time.monotonic()
        self.latest_frame_bytes: bytes | None = None
        self.report: Report | None = None
        self.state = SessionState(
            session_id=session_id,
            status="waiting_mobile",
            created_at=now,
            expires_at=now + timedelta(minutes=30),
            capture_url=capture_url,
            qr_code_url=f"/api/sessions/{session_id}/qrcode",
            analyzer="not_loaded",
            model_name="none",
        )


class SessionStore:
    def __init__(self, analyzer: FoodAnalyzer) -> None:
        self.analyzer = analyzer
        self.sessions: dict[str, SessionRecord] = {}
        self.websockets: dict[str, set[WebSocket]] = {}

    def create_session(self, public_base_url: str) -> CreateSessionResponse:
        session_id = f"sess_{datetime.now(CHINA_TZ).strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}"
        token = f"once_{secrets.token_urlsafe(12)}"
        record = SessionRecord(session_id, token, public_base_url.rstrip("/"))
        record.state.analyzer = self.analyzer.backend_name
        record.state.model_name = self.analyzer.model_name
        self.sessions[session_id] = record
        return CreateSessionResponse(
            session_id=session_id,
            token=token,
            capture_url=record.state.capture_url,
            qr_code_url=record.state.qr_code_url,
            events_url=f"/ws/sessions/{session_id}/events",
            expires_at=record.state.expires_at,
        )

    def get(self, session_id: str) -> SessionRecord:
        if session_id not in self.sessions:
            raise KeyError(session_id)
        return self.sessions[session_id]

    def validate_token(self, session_id: str, token: str) -> SessionRecord:
        record = self.get(session_id)
        if not secrets.compare_digest(record.token, token):
            raise PermissionError("invalid token")
        return record

    async def add_socket(self, session_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.websockets.setdefault(session_id, set()).add(websocket)
        await websocket.send_json({"type": "state_snapshot", "state": self.get(session_id).state.model_dump(mode="json")})

    def remove_socket(self, session_id: str, websocket: WebSocket) -> None:
        sockets = self.websockets.get(session_id)
        if sockets and websocket in sockets:
            sockets.remove(websocket)

    async def broadcast(self, session_id: str, event_type: str, payload: dict[str, Any]) -> None:
        sockets = list(self.websockets.get(session_id, set()))
        dead: list[WebSocket] = []
        for websocket in sockets:
            try:
                await websocket.send_json({"type": event_type, **payload})
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.remove_socket(session_id, websocket)

    async def join_mobile(self, session_id: str, token: str, device: DeviceInfo) -> SessionState:
        record = self.validate_token(session_id, token)
        record.state.status = "mobile_connected"
        record.state.device = device
        record.state.guidance = Guidance(message="手机已连接，请授权摄像头。", needed_action="grant_camera")
        await self.broadcast(session_id, "mobile_connected", {"state": record.state.model_dump(mode="json")})
        return record.state

    async def capture_event(self, session_id: str, event: CaptureEvent) -> SessionState:
        record = self.validate_token(session_id, event.token)
        if event.event == "camera_permission_granted":
            record.state.status = "camera_ready"
            record.state.guidance = Guidance(message="摄像头已授权，请开始采集。", needed_action="start_stream")
        elif event.event == "stream_started":
            record.state.status = "streaming"
            record.state.guidance = Guidance(message="正在接收手机视频帧，请缓慢移动手机。", needed_action="scan_plate")
        elif event.event == "stream_stopped":
            record.state.status = "mobile_connected"
            record.state.guidance = Guidance(message="采集已暂停，可重新开始推流。", needed_action="start_stream")
        elif event.event == "camera_permission_denied":
            record.state.status = "error"
            record.state.guidance = Guidance(message="摄像头权限被拒绝，请在浏览器设置中允许摄像头。", needed_action="grant_camera")
        else:
            record.state.status = "error"
            record.state.guidance = Guidance(message=str(event.payload.get("message", "采集端发生错误。")), needed_action="check_mobile")
        await self.broadcast(session_id, event.event, {"state": record.state.model_dump(mode="json")})
        return record.state

    async def process_frame(self, session_id: str, upload: FrameUpload) -> SessionState:
        record = self.validate_token(session_id, upload.token)
        decoded = self.analyzer.decode_data_url(upload.image)
        record.latest_frame_bytes = decoded.jpg_bytes
        record.state.frame_count += 1
        record.state.status = "measuring"
        record.state.elapsed_seconds = round(time.monotonic() - record.created_monotonic, 1)
        record.state.latest_frame_url = f"/api/sessions/{session_id}/latest-frame?t={record.state.frame_count}"
        record.state.video = VideoInfo(
            fps=self._estimate_fps(record.state.frame_count, record.state.elapsed_seconds),
            resolution=f"{decoded.width}x{decoded.height}",
            quality="good",
            last_frame_at=datetime.now(CHINA_TZ).isoformat(),
        )
        await self.broadcast(session_id, "frame_received", {"state": record.state.model_dump(mode="json")})
        foods, quality, guidance = self.analyzer.analyze(decoded, record.state.frame_count, record.state.elapsed_seconds)
        record.state.analyzer = self.analyzer.backend_name
        record.state.model_name = self.analyzer.model_name
        record.state.foods = foods
        record.state.measurement_quality = quality
        record.state.guidance = Guidance(message=guidance, needed_action=self._guidance_action(guidance))
        await self.broadcast(session_id, "frame_analyzed", {"state": record.state.model_dump(mode="json")})
        return record.state

    async def finish(self, session_id: str) -> Report:
        record = self.get(session_id)
        record.state.status = "completed"
        totals = self._totals(record.state.foods)
        report = Report(
            report_id=f"report_{session_id.split('_')[-1]}",
            session_id=session_id,
            created_at=datetime.now(CHINA_TZ),
            meal_summary=totals,
            foods=[
                {
                    "track_id": food.track_id,
                    "name": food.name,
                    "category": food.category,
                    "weight_g": food.estimated_weight_g,
                    "weight_error_g": food.weight_error_g,
                    "volume_ml": food.volume_ml,
                    "calories_kcal": food.nutrition.calories_kcal,
                    "protein_g": food.nutrition.protein_g,
                    "carbs_g": food.nutrition.carbs_g,
                    "fat_g": food.nutrition.fat_g,
                    "confidence": food.weight_confidence,
                }
                for food in record.state.foods
            ],
            scan_quality=record.state.measurement_quality.model_dump(),
            warnings=self._warnings(record.state),
        )
        record.report = report
        await self.broadcast(session_id, "measurement_completed", {"state": record.state.model_dump(mode="json"), "report": report.model_dump(mode="json")})
        return report

    def report(self, report_id: str) -> Report:
        for record in self.sessions.values():
            if record.report and record.report.report_id == report_id:
                return record.report
        raise KeyError(report_id)

    @staticmethod
    def _estimate_fps(frame_count: int, elapsed_seconds: float) -> float:
        if elapsed_seconds <= 0:
            return 0
        return round(min(12, frame_count / elapsed_seconds), 1)

    @staticmethod
    def _guidance_action(message: str) -> str:
        if "光照" in message:
            return "improve_lighting"
        if "右" in message:
            return "move_right"
        if "降低" in message:
            return "lower_angle"
        if "稳定" in message:
            return "hold_still"
        return "continue_scan"

    @staticmethod
    def _totals(foods: list[Any]) -> dict[str, float]:
        confidence = sum(food.weight_confidence for food in foods) / len(foods) if foods else 0
        return {
            "total_weight_g": round(sum(food.estimated_weight_g for food in foods), 1),
            "total_calories_kcal": round(sum(food.nutrition.calories_kcal for food in foods), 1),
            "total_protein_g": round(sum(food.nutrition.protein_g for food in foods), 1),
            "total_carbs_g": round(sum(food.nutrition.carbs_g for food in foods), 1),
            "total_fat_g": round(sum(food.nutrition.fat_g for food in foods), 1),
            "overall_confidence": round(confidence, 2),
        }

    @staticmethod
    def _warnings(state: SessionState) -> list[str]:
        warnings: list[str] = []
        if state.analyzer == "opencv-fallback":
            warnings.append("当前使用 OpenCV fallback 算法；下载 YOLOv11 分割模型后可启用模型推理。")
        if state.measurement_quality.depth_completeness < 0.62:
            warnings.append("深度完整度不足，体积和克重误差可能偏高。")
        if state.measurement_quality.angle_coverage < 0.6:
            warnings.append("视角覆盖不足，请补充侧面视角以提高估重稳定性。")
        if not warnings:
            warnings.append("第一版估重仅用于产品验证，不能替代精密称重。")
        return warnings
