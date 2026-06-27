from __future__ import annotations

import asyncio
import math
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import WebSocket

from backend.models.schemas import (
    CaptureEvent,
    CreateSessionResponse,
    DeviceInfo,
    FoodTrack,
    FrameUpload,
    Guidance,
    MeasurementQuality,
    Report,
    SessionState,
    VideoInfo,
)
from backend.services.analyzer import DecodedFrame, FoodAnalyzer
from backend.services.nutrition import nutrition_for_weight, profile_for_key


CHINA_TZ = timezone(timedelta(hours=8))


@dataclass
class TrackAggregate:
    track_id: str
    track: FoodTrack
    first_seen_seconds: float
    last_seen_seconds: float
    visible_frames: int = 1
    missed_frames: int = 0


class SessionRecord:
    def __init__(self, session_id: str, token: str, public_base_url: str) -> None:
        now = datetime.now(CHINA_TZ)
        capture_url = f"{public_base_url}/capture?session_id={session_id}&token={token}"
        self.token = token
        self.created_monotonic = time.monotonic()
        self.latest_frame_bytes: bytes | None = None
        self.pending_frame: tuple[DecodedFrame, int, float] | None = None
        self.analysis_lock = asyncio.Lock()
        self.track_memory: dict[str, TrackAggregate] = {}
        self.next_track_index = 1
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
            record.state.guidance = Guidance(message="摄像头已授权，请开始连续推流。", needed_action="start_stream")
        elif event.event == "stream_started":
            record.state.status = "streaming"
            record.state.guidance = Guidance(message="正在接收手机视频帧，请缓慢移动手机，系统会持续修正估重。", needed_action="scan_plate")
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

        # Keep only the newest pending frame while the analyzer is busy. The
        # dashboard still receives every camera frame immediately.
        record.pending_frame = (decoded, record.state.frame_count, record.state.elapsed_seconds)
        await self.broadcast(session_id, "frame_received", {"state": record.state.model_dump(mode="json")})
        if not record.analysis_lock.locked():
            asyncio.create_task(self._drain_analysis(session_id))
        return record.state

    async def _drain_analysis(self, session_id: str) -> None:
        try:
            record = self.get(session_id)
        except KeyError:
            return
        async with record.analysis_lock:
            while record.pending_frame is not None:
                decoded, frame_count, elapsed_seconds = record.pending_frame
                record.pending_frame = None
                await self._analyze_and_update(session_id, record, decoded, frame_count, elapsed_seconds)

    async def _analyze_and_update(
        self,
        session_id: str,
        record: SessionRecord,
        decoded: DecodedFrame,
        frame_count: int,
        elapsed_seconds: float,
    ) -> None:
        try:
            foods, quality, guidance = await asyncio.to_thread(self.analyzer.analyze, decoded, frame_count, elapsed_seconds)
        except Exception as exc:
            record.state.guidance = Guidance(message=f"当前帧分析失败：{exc}", needed_action="continue_scan")
            await self.broadcast(session_id, "frame_analyzed", {"state": record.state.model_dump(mode="json")})
            return

        record.state.analyzer = self.analyzer.backend_name
        record.state.model_name = self.analyzer.model_name
        record.state.analyzed_frame_count += 1
        record.state.foods = self._merge_tracks(record, foods, elapsed_seconds)
        record.state.measurement_quality = self._merge_quality(quality, record.state.foods)
        if record.state.foods:
            guidance = self._temporal_guidance(record.state.foods, guidance)
        record.state.guidance = Guidance(message=guidance, needed_action=self._guidance_action(guidance))
        await self.broadcast(session_id, "frame_analyzed", {"state": record.state.model_dump(mode="json")})

    def _merge_tracks(self, record: SessionRecord, detections: list[FoodTrack], elapsed_seconds: float) -> list[FoodTrack]:
        matched_track_ids: set[str] = set()
        for detection in detections:
            best_id = self._best_match(record.track_memory, detection, matched_track_ids)
            if best_id is None:
                best_id = f"food_{record.next_track_index}"
                record.next_track_index += 1
                detection.track_id = best_id
                detection.first_seen_seconds = round(elapsed_seconds, 1)
                detection.last_seen_seconds = round(elapsed_seconds, 1)
                detection.visible_frames = 1
                detection.sample_count = 1
                detection.stable_seconds = 0
                detection.convergence = self._convergence(detection.visible_frames, detection.stable_seconds)
                record.track_memory[best_id] = TrackAggregate(
                    track_id=best_id,
                    track=detection,
                    first_seen_seconds=elapsed_seconds,
                    last_seen_seconds=elapsed_seconds,
                )
            else:
                aggregate = record.track_memory[best_id]
                aggregate.track = self._smooth_track(aggregate.track, detection, aggregate, elapsed_seconds)
                aggregate.visible_frames += 1
                aggregate.missed_frames = 0
                aggregate.last_seen_seconds = elapsed_seconds
            matched_track_ids.add(best_id)

        for track_id, aggregate in list(record.track_memory.items()):
            if track_id not in matched_track_ids:
                aggregate.missed_frames += 1
                if aggregate.missed_frames > 10:
                    del record.track_memory[track_id]
                    continue
                aggregate.track.state = "lost"
                aggregate.track.confidence = round(max(0.12, aggregate.track.confidence * 0.92), 2)
                aggregate.track.weight_confidence = round(max(0.12, aggregate.track.weight_confidence * 0.92), 2)

        tracks = [aggregate.track for aggregate in record.track_memory.values() if aggregate.missed_frames <= 6]
        tracks.sort(key=lambda item: (item.state != "tracking", -item.weight_confidence, item.track_id))
        return tracks[:6]

    def _smooth_track(
        self,
        previous: FoodTrack,
        detection: FoodTrack,
        aggregate: TrackAggregate,
        elapsed_seconds: float,
    ) -> FoodTrack:
        alpha = 0.74 if aggregate.visible_frames >= 4 else 0.62
        stable_seconds = max(0.0, elapsed_seconds - aggregate.first_seen_seconds)
        sample_count = aggregate.visible_frames + 1
        smoothed_weight = self._ema(previous.estimated_weight_g, detection.estimated_weight_g, alpha)
        smoothed_volume = self._ema(previous.volume_ml, detection.volume_ml, alpha)
        smoothed_confidence = min(0.96, self._ema(previous.weight_confidence, detection.weight_confidence, 0.7) + min(0.14, math.log1p(sample_count) * 0.035))
        base_error = self._ema(previous.weight_error_g, detection.weight_error_g, 0.62)
        error_floor = max(3.5, smoothed_weight * 0.08)
        temporal_error = max(error_floor, base_error / math.sqrt(min(sample_count, 18)) + smoothed_weight * 0.035)
        bbox = [round(self._ema(a, b, alpha)) for a, b in zip(previous.bbox, detection.bbox)]

        profile = profile_for_key(detection.profile_key or previous.profile_key)
        updated = detection.model_copy(deep=True)
        updated.track_id = aggregate.track_id
        updated.name = profile.display_name
        updated.category = profile.category
        updated.profile_key = profile.key
        updated.state = "tracking"
        updated.bbox = [int(v) for v in bbox]
        updated.polygon = detection.polygon or previous.polygon
        updated.mask_svg_path = detection.mask_svg_path or previous.mask_svg_path
        updated.confidence = round(max(previous.confidence * 0.96, detection.confidence), 2)
        updated.volume_ml = round(smoothed_volume, 1)
        updated.volume_confidence = round(min(0.94, self._ema(previous.volume_confidence, detection.volume_confidence, 0.72) + min(0.10, math.log1p(sample_count) * 0.025)), 2)
        updated.density_g_per_ml = profile.density_g_per_ml
        updated.estimated_weight_g = round(smoothed_weight, 1)
        updated.weight_error_g = round(temporal_error, 1)
        updated.weight_confidence = round(smoothed_confidence, 2)
        updated.visible_frames = sample_count
        updated.sample_count = sample_count
        updated.stable_seconds = round(stable_seconds, 1)
        updated.convergence = self._convergence(sample_count, stable_seconds)
        updated.first_seen_seconds = round(aggregate.first_seen_seconds, 1)
        updated.last_seen_seconds = round(elapsed_seconds, 1)
        updated.nutrition = nutrition_for_weight(profile, updated.estimated_weight_g)
        return updated

    @staticmethod
    def _best_match(memory: dict[str, TrackAggregate], detection: FoodTrack, already_matched: set[str]) -> str | None:
        best_id: str | None = None
        best_score = 0.0
        for track_id, aggregate in memory.items():
            if track_id in already_matched:
                continue
            current = aggregate.track
            same_profile = current.profile_key == detection.profile_key
            same_category = current.category == detection.category
            iou = SessionStore._bbox_iou(current.bbox, detection.bbox)
            proximity = SessionStore._center_proximity(current.bbox, detection.bbox)
            score = iou * 0.62 + proximity * 0.26 + (0.12 if same_profile else 0.05 if same_category else 0)
            if score > best_score:
                best_id = track_id
                best_score = score
        return best_id if best_score >= 0.28 else None

    @staticmethod
    def _bbox_iou(a: list[int], b: list[int]) -> float:
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
        intersection = iw * ih
        union = max(1, (ax2 - ax1) * (ay2 - ay1) + (bx2 - bx1) * (by2 - by1) - intersection)
        return intersection / union

    @staticmethod
    def _center_proximity(a: list[int], b: list[int]) -> float:
        ax = (a[0] + a[2]) / 2
        ay = (a[1] + a[3]) / 2
        bx = (b[0] + b[2]) / 2
        by = (b[1] + b[3]) / 2
        scale = max(1, max(a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1]))
        return max(0.0, 1.0 - math.hypot(ax - bx, ay - by) / (scale * 1.8))

    @staticmethod
    def _ema(previous: float, current: float, alpha: float) -> float:
        return previous * alpha + current * (1 - alpha)

    @staticmethod
    def _convergence(sample_count: int, stable_seconds: float) -> float:
        sample_score = min(1.0, sample_count / 18)
        time_score = min(1.0, stable_seconds / 14)
        return round(sample_score * 0.62 + time_score * 0.38, 2)

    @staticmethod
    def _merge_quality(quality: MeasurementQuality, foods: list[FoodTrack]) -> MeasurementQuality:
        if not foods:
            return quality
        convergence = sum(food.convergence for food in foods) / len(foods)
        confidence = sum(food.weight_confidence for food in foods) / len(foods)
        quality.mask_stability = round(max(quality.mask_stability, min(0.96, convergence * 0.9 + 0.08)), 2)
        quality.motion_quality = round(max(quality.motion_quality, min(0.93, 0.42 + convergence * 0.48)), 2)
        quality.overall = round(min(0.96, (quality.overall * 0.72 + convergence * 0.18 + confidence * 0.10)), 2)
        return quality

    @staticmethod
    def _temporal_guidance(foods: list[FoodTrack], fallback: str) -> str:
        avg_convergence = sum(food.convergence for food in foods) / len(foods)
        avg_error_ratio = sum(food.weight_error_g / max(food.estimated_weight_g, 1) for food in foods) / len(foods)
        if avg_convergence < 0.28:
            return "已识别食物，正在积累视频帧；请保持连续推流，缓慢绕餐盘移动 5-10 秒。"
        if avg_error_ratio > 0.28:
            return "重量误差仍偏大，请继续采集不同角度，系统会用多帧结果继续收敛。"
        if avg_convergence >= 0.72:
            return "结果已较稳定，可继续采集以微调，或生成报告。"
        return fallback

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
                    "sample_count": food.sample_count,
                    "stable_seconds": food.stable_seconds,
                    "convergence": food.convergence,
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
        if "靠近" in message:
            return "move_closer"
        if "角度" in message:
            return "change_angle"
        if "连续" in message or "积累" in message:
            return "continue_scan"
        if "稳定" in message:
            return "hold_still"
        return "continue_scan"

    @staticmethod
    def _totals(foods: list[Any]) -> dict[str, float]:
        confidence = sum(food.weight_confidence for food in foods) / len(foods) if foods else 0
        convergence = sum(food.convergence for food in foods) / len(foods) if foods else 0
        return {
            "total_weight_g": round(sum(food.estimated_weight_g for food in foods), 1),
            "total_weight_error_g": round(math.sqrt(sum(food.weight_error_g**2 for food in foods)), 1) if foods else 0,
            "total_calories_kcal": round(sum(food.nutrition.calories_kcal for food in foods), 1),
            "total_protein_g": round(sum(food.nutrition.protein_g for food in foods), 1),
            "total_carbs_g": round(sum(food.nutrition.carbs_g for food in foods), 1),
            "total_fat_g": round(sum(food.nutrition.fat_g for food in foods), 1),
            "overall_confidence": round(confidence, 2),
            "convergence": round(convergence, 2),
        }

    @staticmethod
    def _warnings(state: SessionState) -> list[str]:
        warnings: list[str] = []
        if state.analyzer == "opencv-fallback":
            warnings.append("当前使用 OpenCV fallback 算法；下载并配置 YOLOv11 食物分割模型后可启用模型推理。")
        if state.measurement_quality.depth_completeness < 0.62:
            warnings.append("深度完整度不足，体积和克重误差可能偏高。")
        if state.measurement_quality.angle_coverage < 0.6:
            warnings.append("视角覆盖不足，请补充侧面视角以提高估重稳定性。")
        if state.foods and sum(food.convergence for food in state.foods) / len(state.foods) < 0.5:
            warnings.append("采集时间较短，建议继续推流 5-10 秒让结果收敛。")
        if not warnings:
            warnings.append("第一版估重仅用于产品验证，不能替代精密称重。")
        return warnings
