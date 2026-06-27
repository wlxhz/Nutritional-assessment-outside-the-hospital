from __future__ import annotations

from datetime import datetime
from io import BytesIO
import os
from pathlib import Path
import socket
from typing import Any
from urllib.parse import quote

import qrcode
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.models.schemas import CaptureEvent, FrameUpload, JoinSessionRequest
from backend.services.analyzer import FoodAnalyzer
from backend.services.mmy_ai import AiConfig, MmyAiClient, load_env_file
from backend.services.mmy_parser import LocalPrescriptionParser
from backend.services.mmy_store import MmyStore, default_db_path
from backend.services.nutrition import FOOD_PROFILES, all_profiles
from backend.services.session_store import CHINA_TZ, SessionStore


BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "static"
PROJECT_DIR = BASE_DIR.parent
REPO_DIR = PROJECT_DIR.parent
ENV_SOURCES = [
    REPO_DIR / ".env",
    REPO_DIR / ".env.example",
    PROJECT_DIR / ".env",
    PROJECT_DIR / ".env.example",
]
LOADED_ENV_FILES = [str(path) for path in ENV_SOURCES if load_env_file(path)]

analyzer = FoodAnalyzer()
store = SessionStore(analyzer)
mmy_store = MmyStore(default_db_path(BASE_DIR))
mmy_ai = MmyAiClient(AiConfig.from_env())
mmy_parser = LocalPrescriptionParser()
sms_test_log: list[dict[str, Any]] = []

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
    configured_base_url = os.getenv("MOBILE_PUBLIC_BASE_URL", "").strip()
    if configured_base_url:
        return configured_base_url.rstrip("/")

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


def _sum_nutrients(items: list[dict[str, Any]]) -> dict[str, float]:
    total = {
        "energyKcal": 0.0,
        "proteinG": 0.0,
        "fatG": 0.0,
        "carbohydrateG": 0.0,
        "dietaryFiber": 0.0,
        "calcium": 0.0,
        "magnesium": 0.0,
    }
    for item in items:
        nutrients = item.get("nutrients") or {}
        grams = float(item.get("grams") or 0)
        # If only grams are supplied by the future vision interface, keep the
        # item visible and let nutrition-rule APIs fill exact values later.
        if not nutrients and grams:
            nutrients = {
                "energyKcal": grams * 1.2,
                "proteinG": grams * 0.04,
                "fatG": grams * 0.02,
                "carbohydrateG": grams * 0.16,
            }
        for key in total:
            total[key] += float(nutrients.get(key) or 0)
    return {key: round(value, 1) for key, value in total.items()}


def _has_red_item(items: list[dict[str, Any]]) -> bool:
    return any(item.get("complianceLevel") == "non_compliant" for item in items)


def _adjustment_for_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    if _has_red_item(items):
        return {
            "riskLevel": "red",
            "reason": "包含红色风险食物。",
            "nextMeal": "下一餐将减少同类高风险食物，并提高蔬菜和优质蛋白比例。",
            "remainingDaily": "已调整当天剩余可补充量。",
            "remainingCycle": "已调整当前 7 天周期剩余可补充量。",
        }
    return {
        "riskLevel": "normal",
        "reason": "当前记录未触发红色风险食物。",
        "nextMeal": "维持当前每餐建议。",
        "remainingDaily": "当天剩余可补充量保持不变。",
        "remainingCycle": "周期剩余可补充量保持不变。",
    }


def _vision_compliance_for_food(food: dict[str, Any]) -> str:
    profile_key = str(food.get("profile_key") or "")
    name = str(food.get("name") or "")
    category = str(food.get("category") or "")
    cooking_method = str(food.get("cooking_method") or "")
    confidence = float(food.get("confidence") or 0)
    calories = float(food.get("calories_kcal") or 0)
    weight = float(food.get("weight_g") or 0)
    calories_per_100g = calories / max(weight, 1) * 100

    risky_words = ("高糖", "甜点", "蛋糕", "奶茶", "糖", "炸", "油炸", "肥肉")
    if (
        profile_key == "pork_floss_pastry"
        or name == "肉松糕点"
        or cooking_method == "deep_fried"
        or category in {"甜点", "零食"}
        or calories_per_100g >= 320
        or any(word in name for word in risky_words)
    ):
        return "non_compliant"
    if confidence < 0.62 or calories_per_100g >= 220 or cooking_method in {"pan_fried", "stir_fried", "braised"}:
        return "generally_compliant"
    return "compliant"


def _sticker_color_for_level(level: str) -> str:
    return {
        "compliant": "#9DCF55",
        "generally_compliant": "#EFD67C",
        "non_compliant": "#C82727",
    }.get(level, "#EFD67C")


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        elif value not in (None, "", []):
            merged[key] = value
    return merged


def _clamp_number(value: Any, reference: Any, ratio: float, floor: float, ceiling: float) -> int:
    ref = float(reference or value or floor)
    raw = float(value or ref)
    low = max(floor, ref * (1 - ratio))
    high = min(ceiling, ref * (1 + ratio))
    return int(round(min(max(raw, low), high)))


def _apply_health_thresholds(plan: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    result = dict(plan or {})
    daily = dict(result.get("dailyGoal") or {})
    old_daily = previous.get("dailyGoal") or {}
    if daily:
        daily["energyKcal"] = _clamp_number(daily.get("energyKcal"), old_daily.get("energyKcal"), 0.10, 1300, 2200)
        daily["proteinG"] = _clamp_number(daily.get("proteinG"), old_daily.get("proteinG"), 0.15, 50, 100)
        daily["fatG"] = _clamp_number(daily.get("fatG"), old_daily.get("fatG"), 0.15, 35, 70)
        daily["carbohydrateG"] = _clamp_number(daily.get("carbohydrateG"), old_daily.get("carbohydrateG"), 0.15, 120, 280)
        result["dailyGoal"] = daily
    return result


def _recipe_change_summary(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    before_by_meal = {recipe.get("mealType"): recipe for recipe in before or []}
    changes: list[dict[str, Any]] = []
    for recipe in after or []:
        meal_type = recipe.get("mealType")
        old_items = [str(item) for item in before_by_meal.get(meal_type, {}).get("items", [])]
        new_items = [str(item) for item in recipe.get("items", [])]
        removed = [item for item in old_items if item not in new_items]
        added = [item for item in new_items if item not in old_items]
        if added or removed:
            changes.append(
                {
                    "mealType": meal_type,
                    "name": recipe.get("name") or meal_type,
                    "removed": removed,
                    "added": added,
                }
            )
    return changes


def _adjusted_plan_from_agent(latest_plan: dict[str, Any] | None, plan_patch: dict[str, Any]) -> dict[str, Any] | None:
    if not latest_plan or not plan_patch:
        return None
    base_plan = latest_plan.get("plan") or {}
    previous_daily = dict(base_plan.get("dailyGoal") or {})
    merged = _deep_merge(base_plan, plan_patch)
    merged = _apply_health_thresholds(merged, base_plan)
    summary = plan_patch.get("adjustmentSummary") or _recipe_change_summary(
        base_plan.get("recipes") or [],
        merged.get("recipes") or [],
    )
    notes = list(merged.get("demoNotes") or [])
    reason = plan_patch.get("adjustmentReason")
    if reason:
        notes.append(reason)
    merged["demoNotes"] = notes[-6:]
    adjustment = {
        "reason": reason or "",
        "feedbackTags": plan_patch.get("feedbackTags") or [],
        "summary": summary,
        "previousDailyGoal": previous_daily,
        "updatedDailyGoal": merged.get("dailyGoal") or {},
    }
    merged["latestAdjustment"] = adjustment
    history = list(base_plan.get("adjustmentHistory") or [])
    history.append(adjustment)
    merged["adjustmentHistory"] = history[-5:]
    return merged


def _vision_report_to_intake_items(report: Any) -> list[dict[str, Any]]:
    report_data = report.model_dump(mode="json") if hasattr(report, "model_dump") else dict(report)
    session_id = report_data.get("session_id")
    intake_time = report_data.get("created_at")
    items: list[dict[str, Any]] = []
    for food in report_data.get("foods") or []:
        level = _vision_compliance_for_food(food)
        nutrition = food.get("nutrition") or {}
        weight = round(float(food.get("weight_g") or food.get("estimated_weight_g") or food.get("grams") or 0), 1)
        profile_key = food.get("profile_key")
        item_name = "肉松糕点" if profile_key == "pork_floss_pastry" else food.get("name") or "未命名食物"
        items.append(
            {
                "itemName": item_name,
                "itemType": food.get("item_type") or "food",
                "grams": weight,
                "intakeTime": intake_time,
                "complianceLevel": level,
                "stickerColor": _sticker_color_for_level(level),
                "confidence": round(float(food.get("confidence") or 0), 2),
                "source": "vision",
                "sourceSessionId": session_id,
                "sourceTrackId": food.get("track_id"),
                "visionMeta": {
                    "category": food.get("category"),
                    "profileKey": profile_key,
                    "cookingMethod": food.get("cooking_method"),
                    "cookingMethodName": food.get("cooking_method_name"),
                    "weightErrorG": food.get("weight_error_g"),
                    "sampleCount": food.get("sample_count"),
                    "stableSeconds": food.get("stable_seconds"),
                    "convergence": food.get("convergence"),
                },
                "nutrients": {
                    "energyKcal": round(float(food.get("calories_kcal") or nutrition.get("calories_kcal") or 0), 1),
                    "proteinG": round(float(food.get("protein_g") or nutrition.get("protein_g") or 0), 1),
                    "fatG": round(float(food.get("fat_g") or nutrition.get("fat_g") or 0), 1),
                    "carbohydrateG": round(float(food.get("carbs_g") or nutrition.get("carbs_g") or 0), 1),
                },
            }
        )
    return items


def _stickers_from_vision_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stickers: list[dict[str, Any]] = []
    for item in items:
        stickers.append(
            {
                "itemName": item.get("itemName") or "未命名食物",
                "complianceLevel": item.get("complianceLevel") or "generally_compliant",
                "stickerColor": item.get("stickerColor") or _sticker_color_for_level(item.get("complianceLevel") or ""),
                "sourceSessionId": item.get("sourceSessionId"),
                "sourceTrackId": item.get("sourceTrackId"),
                "meta": {
                    "grams": item.get("grams"),
                    "confidence": item.get("confidence"),
                    "visionMeta": item.get("visionMeta") or {},
                    "nutrients": item.get("nutrients") or {},
                    "source": item.get("source"),
                },
            }
        )
    return stickers


def _report_data(range_type: str, intakes: list[dict[str, Any]]) -> dict[str, Any]:
    totals = _sum_nutrients([
        {"nutrients": record.get("nutrientActual", {})}
        for record in intakes
    ])
    pie_keys = ["proteinG", "fatG", "carbohydrateG", "dietaryFiber"]
    pie_total = sum(max(totals.get(key, 0), 0) for key in pie_keys) or 1
    labels = {
        "energyKcal": ("能量", "kcal", 1600),
        "proteinG": ("蛋白质", "g", 65),
        "fatG": ("脂肪", "g", 45),
        "carbohydrateG": ("碳水", "g", 210),
        "dietaryFiber": ("膳食纤维", "g", 25),
    }
    pie = [
        {
            "label": labels[key][0],
            "value": totals.get(key, 0),
            "unit": labels[key][1],
            "percent": round((totals.get(key, 0) / pie_total) * 100, 1),
        }
        for key in pie_keys
    ]
    bar = [
        {
            "label": labels[key][0],
            "targetValue": labels[key][2],
            "actualValue": totals.get(key, 0),
            "unit": labels[key][1],
        }
        for key in pie_keys
    ]
    return {
        "rangeType": range_type,
        "nutrientSummary": totals,
        "pieChartData": pie,
        "barChartData": bar,
        "source": "local_sqlite",
    }


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "app.html")


@app.get("/vision-dashboard", response_class=HTMLResponse)
async def vision_dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/capture", response_class=HTMLResponse)
async def capture() -> FileResponse:
    return FileResponse(STATIC_DIR / "capture.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"ok": "true", "analyzer": analyzer.backend_name, "model": analyzer.model_name}


@app.get("/api/mmy/config")
async def mmy_config() -> dict[str, Any]:
    return {
        "app": "慢慢养",
        "runtime": "local",
        "storage": "sqlite",
        "aiConfigured": mmy_ai.config.configured,
        "ai": mmy_ai.config.public_status(),
        "loadedEnvFiles": LOADED_ENV_FILES,
        "vision": {
            "status": "integrated",
            "message": "视觉识别会话、手机采集、报告生成和摄入记录同步已接入。",
        },
        "mealTypes": ["breakfast", "lunch", "dinner"],
        "colors": {
            "compliant": "#9DCF55",
            "generally_compliant": "#EFD67C",
            "non_compliant": "#C82727",
        },
    }


@app.get("/api/mmy/ai/status")
async def mmy_ai_status(probe: bool = False) -> dict[str, Any]:
    status = mmy_ai.config.public_status()
    return {
        "ok": True,
        "ai": status,
        "loadedEnvFiles": LOADED_ENV_FILES,
        "probe": mmy_ai.probe() if probe else None,
    }


@app.post("/api/mmy/auth/phone-one-tap")
async def mmy_one_tap(payload: dict[str, str]) -> dict[str, Any]:
    phone = (payload.get("phone") or "").strip()
    carrier = (payload.get("carrier") or "三大运营商").strip()
    if not phone:
        raise HTTPException(status_code=422, detail="phone is required")
    user = mmy_store.login(phone, "one_tap")
    return {
        "ok": True,
        "user": user,
        "carrier": carrier,
        "gateway": {
            "provider": "carrier_one_tap_sdk",
            "carrier": carrier,
            "sdkStatus": "mock_authorized",
            "mock": True,
        },
        "feedback": "已模拟三大运营商一键授权。正式环境接入移动/联通/电信统一认证 SDK。",
    }


@app.get("/api/mmy/auth/operator/capabilities")
async def mmy_operator_capabilities() -> dict[str, Any]:
    return {
        "ok": True,
        "mode": "mock_gateway",
        "carriers": [
            {"id": "auto", "name": "自动识别", "supports": ["one_tap"]},
            {"id": "cmcc", "name": "中国移动", "supports": ["one_tap"]},
            {"id": "cucc", "name": "中国联通", "supports": ["one_tap"]},
            {"id": "ctcc", "name": "中国电信", "supports": ["one_tap"]},
        ],
        "contract": {
            "oneTap": "POST /api/mmy/auth/phone-one-tap",
            "tokenPlacement": "正式环境由服务端换取运营商 access token，App 不保存运营商密钥。",
        },
    }


@app.post("/api/mmy/user/profile")
async def mmy_save_profile(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = (payload.get("userId") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="userId is required")
    profile = mmy_store.save_profile(user_id, payload)
    return {"ok": True, "profile": profile}


@app.get("/api/mmy/user/{user_id}/profile")
async def mmy_get_profile(user_id: str) -> dict[str, Any]:
    profile = mmy_store.get_profile(user_id)
    if not profile:
        raise HTTPException(status_code=404, detail="profile not found")
    return {"profile": profile}


@app.post("/api/mmy/prescriptions/upload")
async def mmy_upload_prescription(userId: str = Form(...), file: UploadFile = File(...)) -> dict[str, Any]:
    data = await file.read()
    result = mmy_parser.parse(file.filename or "prescription", file.content_type or "", data)
    record = mmy_store.save_prescription(
        userId,
        file.filename or "prescription",
        file.content_type or "",
        result.status,
        result.text,
        result.preview,
        result.feedback,
    )
    return {
        "ok": result.status == "parsed",
        "prescription": record,
        "status": result.status,
        "feedback": result.feedback,
    }


@app.delete("/api/mmy/prescriptions/{prescription_id}")
async def mmy_delete_prescription(prescription_id: str) -> dict[str, Any]:
    deleted = mmy_store.delete_prescription(prescription_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="prescription not found")
    return {"ok": True, "deleted": True}


@app.post("/api/mmy/nutrition-plans/generate")
async def mmy_generate_plan(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = (payload.get("userId") or "").strip()
    if not user_id:
        raise HTTPException(status_code=422, detail="userId is required")
    profile = mmy_store.get_profile(user_id) or payload.get("profile") or {}
    ai_result = mmy_ai.nutrition_plan(profile)
    record = mmy_store.save_plan(user_id, "ai_generated", ai_result["plan"], ai_result["status"])
    return {"ok": True, "plan": record}


@app.post("/api/mmy/nutrition-plans/from-prescription")
async def mmy_plan_from_prescription(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = (payload.get("userId") or "").strip()
    prescription_id = (payload.get("prescriptionId") or "").strip()
    if not user_id or not prescription_id:
        raise HTTPException(status_code=422, detail="userId and prescriptionId are required")
    prescription = mmy_store.get_prescription(prescription_id)
    if not prescription:
        raise HTTPException(status_code=404, detail="prescription not found")
    profile = mmy_store.get_profile(user_id) or {}
    ai_result = mmy_ai.nutrition_plan(profile, prescription.get("text") or "")
    record = mmy_store.save_plan(
        user_id,
        "hospital_prescription",
        ai_result["plan"],
        ai_result["status"],
        prescription_id,
    )
    return {"ok": True, "plan": record}


@app.get("/api/mmy/users/{user_id}/nutrition-plan")
async def mmy_latest_plan(user_id: str) -> dict[str, Any]:
    plan = mmy_store.latest_plan(user_id)
    if not plan:
        raise HTTPException(status_code=404, detail="plan not found")
    return {"plan": plan}


@app.get("/api/mmy/vision/contract")
async def mmy_vision_contract() -> dict[str, Any]:
    return {
        "status": "integrated",
        "message": "视觉识别已接入 App 业务层；完成采集后可通过 /api/mmy/vision/intake-sync 写入摄入记录。",
        "expectedResult": {
            "itemName": "品类名称",
            "itemType": "food | medical_food | special_diet",
            "grams": "number",
            "intakeTime": "ISO datetime",
            "nutrientPayload": "用于计算营养摄入的数据",
            "compliancePayload": "用于判断贴纸颜色的数据",
        },
        "syncEndpoint": "POST /api/mmy/vision/intake-sync",
        "stickerColors": {
            "compliant": "#9DCF55",
            "generally_compliant": "#EFD67C",
            "non_compliant": "#C82727",
        },
    }


@app.post("/api/mmy/intake-records")
async def mmy_create_intake(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = (payload.get("userId") or "").strip()
    meal_type = payload.get("mealType")
    if meal_type not in {"breakfast", "lunch", "dinner"}:
        raise HTTPException(status_code=422, detail="mealType must be breakfast, lunch, or dinner")
    items = payload.get("items") or []
    nutrient_actual = payload.get("nutrientActual") or _sum_nutrients(items)
    adjustment = payload.get("adjustment") or _adjustment_for_items(items)
    record = mmy_store.save_intake(user_id, meal_type, items, nutrient_actual, adjustment)
    return {"ok": True, "record": record}


@app.get("/api/mmy/intake-records")
async def mmy_list_intakes(userId: str) -> dict[str, Any]:
    return {"ok": True, "records": mmy_store.list_intakes(userId)}


@app.post("/api/mmy/vision/intake-sync")
async def mmy_vision_intake_sync(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = (payload.get("userId") or "").strip()
    meal_type = payload.get("mealType") or "lunch"
    if not user_id:
        raise HTTPException(status_code=422, detail="userId is required")
    if meal_type not in {"breakfast", "lunch", "dinner"}:
        raise HTTPException(status_code=422, detail="mealType must be breakfast, lunch, or dinner")

    report_payload = payload.get("report")
    report_id = (payload.get("reportId") or "").strip()
    session_id = (payload.get("sessionId") or "").strip()
    report_obj: Any | None = None
    if report_payload:
        report_obj = report_payload
    elif report_id:
        try:
            report_obj = store.report(report_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="vision report not found") from exc
    elif session_id:
        try:
            report_obj = await store.finish(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc
    else:
        raise HTTPException(status_code=422, detail="reportId, sessionId, or report is required")

    report_data = report_obj.model_dump(mode="json") if hasattr(report_obj, "model_dump") else dict(report_obj)
    items = _vision_report_to_intake_items(report_data)
    if not items:
        raise HTTPException(status_code=422, detail="vision report has no food items")
    nutrient_actual = _sum_nutrients(items)
    adjustment = _adjustment_for_items(items)
    adjustment["source"] = "vision"
    adjustment["visionReportId"] = report_data.get("report_id")
    adjustment["visionSessionId"] = report_data.get("session_id")
    record = mmy_store.save_intake(user_id, meal_type, items, nutrient_actual, adjustment)
    sticker_payload = payload.get("stickers") or _stickers_from_vision_items(items)
    saved_stickers = mmy_store.save_food_stickers(user_id, record["recordId"], sticker_payload)
    return {
        "ok": True,
        "record": record,
        "stickers": saved_stickers,
        "items": items,
        "nutrientActual": nutrient_actual,
        "adjustment": adjustment,
        "visionReport": report_data,
    }


@app.get("/api/mmy/reports/nutrients")
async def mmy_reports(userId: str, rangeType: str = "day") -> dict[str, Any]:
    intakes = mmy_store.list_intakes(userId)
    data = _report_data(rangeType, intakes)
    report = mmy_store.save_report(userId, rangeType, data)
    return {"ok": True, "report": report, "data": data}


@app.post("/api/mmy/reports/{report_id}/confirm")
async def mmy_confirm_report(report_id: str) -> dict[str, Any]:
    result = mmy_store.confirm_report(report_id)
    if not result:
        raise HTTPException(status_code=404, detail="report not found")
    return {"ok": True, **result}


@app.post("/api/mmy/temp-data/cleanup")
async def mmy_cleanup_temp_data() -> dict[str, Any]:
    return {"ok": True, "deletedCount": mmy_store.cleanup_expired_temp_data()}


@app.get("/api/mmy/garden/progress")
async def mmy_garden(userId: str) -> dict[str, Any]:
    intakes = mmy_store.list_intakes(userId)
    today = datetime.now(CHINA_TZ).date().isoformat()
    today_stickers = mmy_store.list_food_stickers(userId, today)
    completed_today = bool(intakes) and not any(_has_red_item(record.get("items", [])) for record in intakes[:3])
    days = []
    for index in range(1, 8):
        earned = completed_today if index == 1 else False
        days.append({"dayIndex": index, "smallFlowerEarned": earned, "status": "done" if earned else "waiting"})
    return {
        "cycleLength": 7,
        "days": days,
        "todayStickers": today_stickers,
        "bigFlowerEarned": all(day["smallFlowerEarned"] for day in days),
        "criteria": ["摄入量达标", "记录完整", "无红色风险食物"],
    }


@app.get("/api/mmy/agent/prompts")
async def mmy_agent_prompts(userId: str) -> dict[str, Any]:
    prompts = [
        {"messageType": "recipe_feedback", "content": "今天的食谱吃起来怎么样？"},
        {"messageType": "body_feeling", "content": "吃完后身体感觉怎么样？"},
    ]
    return {"prompts": prompts}


@app.post("/api/mmy/agent/messages")
async def mmy_agent_message(payload: dict[str, Any]) -> dict[str, Any]:
    user_id = (payload.get("userId") or "").strip()
    content = (payload.get("content") or "").strip()
    message_type = payload.get("messageType") or "companionship"
    if not user_id or not content:
        raise HTTPException(status_code=422, detail="userId and content are required")
    user_message = mmy_store.add_message(user_id, "user", message_type, content)
    latest_plan = mmy_store.latest_plan(user_id)
    context = {
        "profile": mmy_store.get_profile(user_id),
        "latestPlan": latest_plan,
        "recentIntakes": mmy_store.list_intakes(user_id)[:3],
        "recentMessages": mmy_store.list_messages(user_id)[-8:],
    }
    ai = mmy_ai.agent_reply(content, context)
    agent_message = mmy_store.add_message(user_id, "agent", message_type, ai["content"])
    adjusted_plan = _adjusted_plan_from_agent(latest_plan, ai.get("planPatch") or {})
    saved_plan = None
    if adjusted_plan:
        saved_plan = mmy_store.save_plan(user_id, "agent_adjusted", adjusted_plan, ai["status"])
    return {
        "ok": True,
        "messages": [user_message, agent_message],
        "aiStatus": ai["status"],
        "planPatch": ai.get("planPatch") or {},
        "safetyNotes": ai.get("safetyNotes") or [],
        "plan": saved_plan,
    }


@app.get("/api/mmy/agent/messages")
async def mmy_agent_messages(userId: str) -> dict[str, Any]:
    return {"messages": mmy_store.list_messages(userId)}


@app.post("/api/mmy/sms/confirm")
async def mmy_sms_confirm(payload: dict[str, Any]) -> dict[str, Any]:
    contact = payload.get("contact") or {}
    message = payload.get("message") or "检测到红色风险食物，请关注慢慢养 App 提示。"
    phone = contact.get("phone", "")
    mode = payload.get("mode") or "risk_alert"
    entry = {
        "phone": phone,
        "message": message,
        "mode": mode,
        "createdAt": datetime.now(CHINA_TZ).isoformat(),
    }
    sms_test_log.append(entry)
    del sms_test_log[:-20]
    return {
        "ok": True,
        "status": "ready_to_open_system_sms",
        "smsUrl": f"sms:{phone}?body={quote(message)}",
        "entry": entry,
        "feedback": "请在系统短信界面中由用户手动确认发送，App 不会自动发送短信。",
    }


@app.get("/api/mmy/sms/test-log")
async def mmy_sms_test_log() -> dict[str, Any]:
    if os.getenv("APP_ENV") == "production":
        raise HTTPException(status_code=404, detail="not found")
    return {"ok": True, "items": sms_test_log}


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
