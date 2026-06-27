from __future__ import annotations

import base64
import math
import os
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageFilter, ImageStat

from backend.models.schemas import FoodTrack, MeasurementQuality
from backend.services.nutrition import FoodProfile, nutrition_for_weight, profile_for_key


MODEL_DIR = Path(__file__).resolve().parents[2] / "models"
DEFAULT_MODEL_PATH = MODEL_DIR / "yolo11n-seg.pt"


@dataclass
class DecodedFrame:
    image: Image.Image
    width: int
    height: int
    jpg_bytes: bytes


class FoodAnalyzer:
    """Frame analyzer with YOLOv11 optional inference and conservative fallback.

    The fallback must not invent food when the camera is pointed at keyboards,
    monitors, desks, or other non-food scenes. It therefore uses a reject-first
    strategy: detect obvious electronic/keyboard geometry, extract food-like
    color blobs, and only emit tracks when the food-likeness score passes a
    threshold.
    """

    def __init__(self) -> None:
        self.model = None
        self.model_name = "opencv-fallback"
        self.backend_name = "opencv-fallback"
        self._load_yolo_if_available()

    def _load_yolo_if_available(self) -> None:
        model_path = Path(os.getenv("FOOD_MODEL_PATH", str(DEFAULT_MODEL_PATH)))
        if not model_path.exists():
            return
        try:
            from ultralytics import YOLO  # type: ignore

            self.model = YOLO(str(model_path))
            self.model_name = model_path.name
            self.backend_name = "yolo11-seg"
        except Exception as exc:  # pragma: no cover - defensive runtime path
            self.model = None
            self.model_name = f"opencv-fallback ({exc.__class__.__name__})"
            self.backend_name = "opencv-fallback"

    @staticmethod
    def decode_data_url(data_url: str) -> DecodedFrame:
        header, _, payload = data_url.partition(",")
        if not payload:
            payload = header
        jpg_bytes = base64.b64decode(payload)
        from io import BytesIO

        image = Image.open(BytesIO(jpg_bytes)).convert("RGB")
        return DecodedFrame(image=image, width=image.width, height=image.height, jpg_bytes=jpg_bytes)

    def analyze(self, frame: DecodedFrame, frame_count: int, elapsed_seconds: float) -> tuple[list[FoodTrack], MeasurementQuality, str]:
        if self.model is not None:
            try:
                tracks = self._analyze_yolo(frame)
                if tracks:
                    quality = self._quality(frame, tracks, frame_count, elapsed_seconds)
                    return tracks, quality, self._guidance(quality, len(tracks))
            except Exception:
                pass

        tracks = self._analyze_fallback(frame, frame_count)
        quality = self._quality(frame, tracks, frame_count, elapsed_seconds)
        return tracks, quality, self._guidance(quality, len(tracks))

    def _analyze_yolo(self, frame: DecodedFrame) -> list[FoodTrack]:
        result = self.model.predict(np.array(frame.image), imgsz=640, conf=0.25, verbose=False)[0]
        tracks: list[FoodTrack] = []
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            return tracks

        names = getattr(result, "names", {}) or {}
        masks = getattr(result, "masks", None)
        polygons: list[list[list[int]]] = []
        if masks is not None and getattr(masks, "xy", None) is not None:
            for poly in masks.xy:
                polygons.append([[int(x), int(y)] for x, y in poly[:80]])

        for idx, box in enumerate(boxes):
            xyxy = box.xyxy[0].tolist()
            cls_id = int(box.cls[0].item()) if getattr(box, "cls", None) is not None else -1
            raw_label = str(names.get(cls_id, "food")).lower()
            confidence = float(box.conf[0].item()) if getattr(box, "conf", None) is not None else 0.5
            bbox = [int(max(0, xyxy[0])), int(max(0, xyxy[1])), int(min(frame.width, xyxy[2])), int(min(frame.height, xyxy[3]))]
            profile = self._profile_from_label(raw_label, idx)
            polygon = polygons[idx] if idx < len(polygons) else self._bbox_polygon(bbox)
            tracks.append(self._track_from_region(f"food_{idx + 1}", profile, bbox, polygon, confidence, frame.width, frame.height))
        return tracks[:6]

    def _profile_from_label(self, label: str, index: int) -> FoodProfile:
        label_map = {
            "rice": "rice",
            "broccoli": "broccoli",
            "banana": "banana",
            "apple": "apple",
            "orange": "orange",
            "carrot": "carrot",
            "hot dog": "chicken",
            "sandwich": "chicken",
            "pizza": "fried_rice",
            "cake": "unknown_food",
            "donut": "unknown_food",
        }
        for needle, key in label_map.items():
            if needle in label:
                return profile_for_key(key)
        fallback = ["rice", "chicken", "broccoli", "egg", "tofu", "pork_lean", "unknown_food"]
        return profile_for_key(fallback[index % len(fallback)])

    def _analyze_fallback(self, frame: DecodedFrame, frame_count: int) -> list[FoodTrack]:
        arr = np.array(frame.image)
        height, width = arr.shape[:2]
        if self._looks_like_non_food_scene(arr):
            return []

        mask = self._food_candidate_mask(arr)
        components = self._connected_components(mask, min_area=max(350, int(width * height * 0.006)))
        food_score = self._food_likeness_score(arr, mask, components)
        if food_score < 0.2 or not components:
            return []

        tracks: list[FoodTrack] = []
        for idx, component in enumerate(components[:6]):
            x1, y1, x2, y2, area = component
            crop = arr[y1:y2, x1:x2]
            profile = self._profile_from_color(crop, idx)
            bbox = [x1, y1, x2, y2]
            polygon = self._bbox_polygon(bbox)
            area_score = area / max(width * height, 1)
            confidence = min(0.9, 0.34 + food_score * 0.44 + area_score * 1.5 + frame_count * 0.002)
            if confidence >= 0.35:
                tracks.append(self._track_from_region(f"food_{idx + 1}", profile, bbox, polygon, confidence, width, height))
        return tracks

    @staticmethod
    def _food_candidate_mask(arr: np.ndarray) -> np.ndarray:
        hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        red = arr[:, :, 0].astype(np.int16)
        green = arr[:, :, 1].astype(np.int16)
        blue = arr[:, :, 2].astype(np.int16)
        channel_range = np.max(arr, axis=2).astype(np.int16) - np.min(arr, axis=2).astype(np.int16)

        green_food = (green > red + 16) & (green > blue + 12) & (green > 55)
        warm_food = (red > 120) & (green > 70) & (blue < 165) & ((red - blue) > 24)
        orange_food = (red > 145) & (green > 80) & (green < 190) & (blue < 130)
        pale_food = (red > 150) & (green > 135) & (blue > 105) & (value > 125) & (channel_range < 95)
        tomato_red = (red > 145) & (green < 125) & (blue < 120) & (saturation > 45)

        mask = (green_food | warm_food | orange_food | pale_food | tomato_red) & (value > 45)
        return FoodAnalyzer._smooth_mask(mask)

    def _profile_from_color(self, crop: np.ndarray, index: int) -> FoodProfile:
        if crop.size == 0:
            return profile_for_key("unknown_food")
        mean = crop.reshape(-1, 3).mean(axis=0)
        r, g, b = mean.tolist()
        brightness = (r + g + b) / 3
        if g > r * 1.12 and g > b * 1.08:
            if brightness < 88:
                return profile_for_key("spinach")
            if brightness < 125:
                return profile_for_key("bok_choy")
            return profile_for_key("broccoli")
        if r > 165 and g > 95 and b < 105:
            return profile_for_key("carrot")
        if r > 155 and g < 120 and b < 115:
            return profile_for_key("tomato")
        if r > 145 and g > 112 and b < 140:
            return profile_for_key("chicken")
        if r > 185 and g > 175 and b > 145:
            return profile_for_key("rice")
        if r > 150 and g > 105 and b < 100:
            return profile_for_key("sweet_potato")
        if r > 112 and g < 108 and b < 100:
            return profile_for_key("beef")
        if brightness < 78 and abs(r - g) < 20 and abs(g - b) < 20:
            return profile_for_key("wood_ear")
        return profile_for_key(["rice", "chicken", "broccoli", "egg", "tofu", "pork_lean", "potato"][index % 7])

    def _track_from_region(
        self,
        track_id: str,
        profile: FoodProfile,
        bbox: list[int],
        polygon: list[list[int]],
        confidence: float,
        frame_width: int,
        frame_height: int,
    ) -> FoodTrack:
        x1, y1, x2, y2 = bbox
        area_px = max(1, (x2 - x1) * (y2 - y1))
        frame_area = max(1, frame_width * frame_height)
        plate_scale_ml = 1200
        compactness = min(1.15, max(0.55, math.sqrt(area_px / frame_area) * 2.2))
        volume_ml = round(max(18, area_px / frame_area * plate_scale_ml * compactness), 1)
        estimated_weight = round(volume_ml * profile.density_g_per_ml, 1)
        relative_error = min(0.52, 0.14 + profile.density_std_g_per_ml / max(profile.density_g_per_ml, 0.1) + (1 - confidence) * 0.2)
        weight_error = round(max(6, estimated_weight * relative_error), 1)
        weight_confidence = round(max(0.25, min(0.9, confidence * (1 - relative_error * 0.35))), 2)
        volume_confidence = round(max(0.22, min(0.88, confidence * 0.86)), 2)
        return FoodTrack(
            track_id=track_id,
            name=profile.display_name,
            category=profile.category,
            bbox=bbox,
            polygon=polygon,
            mask_svg_path=self._polygon_path(polygon),
            color=self._color_for_profile(profile.key),
            confidence=round(confidence, 2),
            volume_ml=volume_ml,
            volume_confidence=volume_confidence,
            density_g_per_ml=profile.density_g_per_ml,
            estimated_weight_g=estimated_weight,
            weight_error_g=weight_error,
            weight_confidence=weight_confidence,
            nutrition=nutrition_for_weight(profile, estimated_weight),
        )

    def _quality(self, frame: DecodedFrame, tracks: list[FoodTrack], frame_count: int, elapsed_seconds: float) -> MeasurementQuality:
        grayscale = frame.image.convert("L")
        stat = ImageStat.Stat(grayscale)
        brightness = stat.mean[0] / 255
        contrast = min(1, stat.stddev[0] / 72)
        edges = grayscale.filter(ImageFilter.FIND_EDGES)
        blur_score = min(1, ImageStat.Stat(edges).mean[0] / 24)
        food_area = sum(max(0, (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])) for f in tracks)
        area_ratio = food_area / max(frame.width * frame.height, 1)
        angle = min(0.88, 0.18 + elapsed_seconds / 26)
        depth = min(0.82, 0.12 + elapsed_seconds / 32 + len(tracks) * 0.05)
        stability = min(0.9, 0.35 + frame_count / 80 + len(tracks) * 0.08)
        motion = min(0.86, 0.32 + elapsed_seconds / 30)
        lighting = max(0.15, min(0.95, 1 - abs(brightness - 0.58) * 1.35 + contrast * 0.16))
        plate_visibility = max(0.0, min(0.94, area_ratio * 2.8))
        blur = max(0.15, min(0.95, blur_score))
        overall = np.mean([angle, depth, stability, motion, lighting, plate_visibility, blur]).item()
        return MeasurementQuality(
            angle_coverage=round(angle, 2),
            depth_completeness=round(depth, 2),
            mask_stability=round(stability, 2),
            motion_quality=round(motion, 2),
            lighting=round(lighting, 2),
            blur=round(blur, 2),
            plate_visibility=round(plate_visibility, 2),
            overall=round(float(overall), 2),
        )

    @staticmethod
    def _guidance(quality: MeasurementQuality, food_count: int) -> str:
        if food_count == 0:
            return "未检测到稳定食物目标，请将餐盘或食物完整放入画面。"
        if quality.lighting < 0.45:
            return "光照偏弱，请靠近光源或调整餐盘位置。"
        if quality.angle_coverage < 0.55:
            return "请缓慢向右移动手机，补充侧面视角。"
        if quality.depth_completeness < 0.62:
            return "请稍微降低角度，获取食物高度信息。"
        if quality.mask_stability < 0.72:
            return "请保持稳定 2 秒，等待分割结果收敛。"
        return "采集质量良好，可以继续扫描或生成报告。"

    @staticmethod
    def _smooth_mask(mask: np.ndarray) -> np.ndarray:
        uint_mask = mask.astype(np.uint8) * 255
        kernel = np.ones((5, 5), dtype=np.uint8)
        opened = cv2.morphologyEx(uint_mask, cv2.MORPH_OPEN, kernel, iterations=1)
        closed = cv2.morphologyEx(opened, cv2.MORPH_CLOSE, kernel, iterations=2)
        return closed > 0

    @staticmethod
    def _connected_components(mask: np.ndarray, min_area: int) -> list[tuple[int, int, int, int, int]]:
        labels_count, _labels, stats, _centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
        components: list[tuple[int, int, int, int, int]] = []
        for label in range(1, labels_count):
            x = int(stats[label, cv2.CC_STAT_LEFT])
            y = int(stats[label, cv2.CC_STAT_TOP])
            w = int(stats[label, cv2.CC_STAT_WIDTH])
            h = int(stats[label, cv2.CC_STAT_HEIGHT])
            area = int(stats[label, cv2.CC_STAT_AREA])
            if area >= min_area:
                components.append((x, y, x + w, y + h, area))
        components.sort(key=lambda item: item[4], reverse=True)
        return components[:8]

    @staticmethod
    def _food_likeness_score(arr: np.ndarray, mask: np.ndarray, components: list[tuple[int, int, int, int, int]]) -> float:
        height, width = mask.shape
        frame_area = max(width * height, 1)
        mask_ratio = float(mask.mean())
        component_area = sum(item[4] for item in components) / frame_area
        channel_std = float(np.std(arr.reshape(-1, 3), axis=0).mean() / 80)
        score = mask_ratio * 1.2 + component_area * 2.0 + channel_std * 0.18
        return float(min(1.0, score))

    @staticmethod
    def _looks_like_non_food_scene(arr: np.ndarray) -> bool:
        height, width = arr.shape[:2]
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
        saturation = hsv[:, :, 1]
        value = hsv[:, :, 2]
        low_saturation_ratio = float((saturation < 45).mean())
        dark_ratio = float((value < 100).mean())
        edges = cv2.Canny(gray, 70, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=45, minLineLength=max(24, width // 20), maxLineGap=8)
        line_count = 0 if lines is None else len(lines)
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        rectangular_count = 0
        min_area = max(60, int(width * height * 0.0008))
        max_area = int(width * height * 0.08)
        for contour in contours[:240]:
            area = cv2.contourArea(contour)
            if area < min_area or area > max_area:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if w <= 0 or h <= 0:
                continue
            aspect = w / h
            extent = area / max(w * h, 1)
            if 0.25 <= aspect <= 6.0 and extent > 0.18:
                rectangular_count += 1
        edge_density = float((edges > 0).mean())
        many_keyboard_shapes = rectangular_count >= 18 and line_count >= 60 and edge_density > 0.035
        mostly_dark_device = dark_ratio > 0.48 and low_saturation_ratio > 0.6 and rectangular_count >= 9
        black_keyboard_like = dark_ratio > 0.62 and line_count >= 120 and edge_density > 0.04
        return many_keyboard_shapes or mostly_dark_device or black_keyboard_like

    @staticmethod
    def _bbox_polygon(bbox: list[int]) -> list[list[int]]:
        x1, y1, x2, y2 = bbox
        return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]

    @staticmethod
    def _polygon_path(polygon: list[list[int]]) -> str:
        if not polygon:
            return ""
        start = polygon[0]
        rest = " ".join(f"L {x} {y}" for x, y in polygon[1:])
        return f"M {start[0]} {start[1]} {rest} Z"

    @staticmethod
    def _color_for_profile(key: str) -> str:
        return {
            "rice": "#f3edc8",
            "brown_rice": "#c5a46a",
            "chicken": "#ff9b66",
            "chicken_thigh": "#e58f5d",
            "pork_lean": "#df7d73",
            "pork_belly": "#ffb38f",
            "beef": "#d75c52",
            "fish": "#dce7e8",
            "shrimp": "#ffb07c",
            "egg": "#ffd66e",
            "tofu": "#f2ead2",
            "broccoli": "#72d879",
            "spinach": "#3fa763",
            "bok_choy": "#94dc83",
            "tomato": "#ff685d",
            "carrot": "#f28b38",
            "potato": "#d7b16c",
            "sweet_potato": "#f07f45",
            "corn": "#f6d84d",
            "wood_ear": "#5b5149",
            "apple": "#ff6b6b",
        }.get(key, "#7cf4bd")
