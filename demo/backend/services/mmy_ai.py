from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import error, request


def load_env_file(path: Path, *, override: bool = False) -> bool:
    if not path.exists():
        return False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if override or key not in os.environ:
            os.environ[key] = value
    return True


@dataclass
class AiConfig:
    base_url: str = ""
    api_key: str = ""
    default_model: str = ""
    nutrition_model: str = ""
    agent_model: str = ""
    timeout_ms: int = 60000

    @classmethod
    def from_env(cls) -> "AiConfig":
        return cls(
            base_url=os.getenv("AI_BASE_URL", "").rstrip("/"),
            api_key=os.getenv("AI_API_KEY", ""),
            default_model=os.getenv("AI_DEFAULT_MODEL", ""),
            nutrition_model=os.getenv("AI_NUTRITION_MODEL", ""),
            agent_model=os.getenv("AI_AGENT_MODEL", ""),
            timeout_ms=int(os.getenv("AI_REQUEST_TIMEOUT_MS", "60000")),
        )

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.default_model)

    @property
    def missing_fields(self) -> list[str]:
        missing: list[str] = []
        if not self.base_url:
            missing.append("AI_BASE_URL")
        if not self.api_key:
            missing.append("AI_API_KEY")
        if not self.default_model:
            missing.append("AI_DEFAULT_MODEL")
        return missing

    def public_status(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "baseUrl": self.base_url,
            "defaultModel": self.default_model,
            "nutritionModel": self.nutrition_model or self.default_model,
            "agentModel": self.agent_model or self.default_model,
            "hasApiKey": bool(self.api_key),
            "apiKeyPreview": f"{self.api_key[:6]}...{self.api_key[-4:]}" if self.api_key else "",
            "missingFields": self.missing_fields,
            "timeoutMs": self.timeout_ms,
        }


class MmyAiClient:
    def __init__(self, config: AiConfig) -> None:
        self.config = config

    def nutrition_plan(self, profile: dict[str, Any], prescription_text: str | None = None) -> dict[str, Any]:
        fallback = self._fallback_plan(profile, prescription_text)
        if not self.config.configured:
            return {"status": "local_fallback", "plan": fallback, "raw": None}
        prompt = (
            "你是院外营养管理 App 的营养方案生成模块。请基于用户基础信息、饮食偏好、过敏史、疾病史和处方文本生成 JSON。"
            "字段必须包含 dailyGoal, mealSuggestions, recipes, nutrientTargets, forbiddenFoods, supplementSuggestions, mealBreakdown。"
            "三餐仅包含早餐、午餐、晚餐；recipes 必须给出具体食物名称、推荐原因；不要输出 Markdown。"
        )
        user_content = json.dumps(
            {"profile": profile, "prescriptionText": prescription_text or ""},
            ensure_ascii=False,
        )
        try:
            raw = self._chat(prompt, user_content, self.config.nutrition_model or self.config.default_model)
            parsed = self._json_from_text(raw)
            return {"status": "model", "plan": parsed or fallback, "raw": raw}
        except Exception as exc:  # Keep the app usable when the configured provider is unreachable.
            fallback["demoNotes"] = [
                *(fallback.get("demoNotes") or []),
                f"AI 服务暂不可用，已使用本地个性化规则兜底：{type(exc).__name__}",
            ]
            return {"status": "model_error_fallback", "plan": fallback, "raw": None, "error": str(exc)}

    def agent_reply(self, user_message: str, context: dict[str, Any]) -> dict[str, Any]:
        fallback = self._fallback_agent_reply(user_message, context)
        if not self.config.configured:
            return {"status": "local_fallback", **fallback, "raw": None}
        prompt = (
            "你是慢慢养 App 的院外营养陪伴 Agent，只处理食谱反馈、身体感受、饮食结构调整和陪伴。"
            "你必须在合理健康阈值内调整：每日总热量变化不超过 10%，蛋白质变化不超过 15%，"
            "慢病用户优先低糖、少油、优质蛋白、高纤维，不提供诊断。"
            "请只输出 JSON，字段包含 content, planPatch, safetyNotes。"
            "planPatch 可包含 dailyGoal、mealBreakdown、recipes、mealSuggestions、forbiddenFoods、adjustmentReason。"
        )
        user_content = json.dumps({"message": user_message, "context": context}, ensure_ascii=False)
        try:
            raw = self._chat(prompt, user_content, self.config.agent_model or self.config.default_model)
            parsed = self._json_from_text(raw) or {}
            content = str(parsed.get("content") or raw).strip() or fallback["content"]
            return {
                "status": "model",
                "content": content,
                "planPatch": parsed.get("planPatch") if isinstance(parsed.get("planPatch"), dict) else {},
                "safetyNotes": parsed.get("safetyNotes") or [],
                "raw": raw,
            }
        except Exception as exc:
            return {"status": "model_error_fallback", **fallback, "raw": None, "error": str(exc)}

    def probe(self) -> dict[str, Any]:
        if not self.config.configured:
            return {"ok": False, "status": "not_configured", "message": "AI_BASE_URL、AI_API_KEY 或 AI_DEFAULT_MODEL 未配置完整。"}
        try:
            raw = self._chat("只回复 JSON。", '{"ping":"慢慢养"}', self.config.default_model)
            return {"ok": True, "status": "connected", "sample": raw[:160]}
        except Exception as exc:  # pragma: no cover - surfaced by API diagnostics.
            return {"ok": False, "status": "error", "message": str(exc)}

    def _chat(self, system_prompt: str, user_content: str, model: str) -> str:
        url = f"{self.config.base_url}/chat/completions"
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": 0.3,
        }
        data = json.dumps(body).encode("utf-8")
        req = request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=max(1, self.config.timeout_ms / 1000)) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"AI HTTP {exc.code}: {body or exc.reason}") from exc
        return payload["choices"][0]["message"]["content"]

    @staticmethod
    def _json_from_text(text: str) -> dict[str, Any] | None:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`").strip()
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
        try:
            value = json.loads(cleaned)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            start = cleaned.find("{")
            end = cleaned.rfind("}")
            if start >= 0 and end > start:
                try:
                    value = json.loads(cleaned[start : end + 1])
                    return value if isinstance(value, dict) else None
                except json.JSONDecodeError:
                    return None
        return None

    @staticmethod
    def _fallback_plan(profile: dict[str, Any], prescription_text: str | None) -> dict[str, Any]:
        disease = profile.get("diseaseType") or "other"
        disease_other = profile.get("diseaseOtherText") or ""
        preferences = extract_preferences(profile)
        source_note = "基于导入处方生成" if prescription_text else "基于基础身体指征生成"
        disease_label = {
            "diabetes": "糖尿病",
            "hypertension": "高血压",
            "internal_postoperative_recovery": "内科术后康复",
            "tumor_recovery": "肿瘤康复",
            "other": disease_other or "其他",
        }.get(disease, disease_other or disease)
        targets = targets_for_profile(profile)
        recipes = recipes_for_profile(profile, preferences)
        meal_breakdown = meal_breakdown_from_targets(targets, recipes)
        return {
            "dailyGoal": {
                "summary": f"{source_note}，结合{disease_label}、饮食偏好和近期反馈生成。优先少油、稳定能量、保证优质蛋白与膳食纤维。",
                **targets,
            },
            "mealSuggestions": [
                {"mealType": "breakfast", "name": "早餐", "suggestion": f"主食控制在约 {meal_breakdown[0]['carbohydrateG']}g 碳水，搭配蛋白质和无糖饮品。"},
                {"mealType": "lunch", "name": "午餐", "suggestion": f"作为全天主餐，保留约 {meal_breakdown[1]['proteinG']}g 蛋白质，蔬菜不少于一拳半。"},
                {"mealType": "dinner", "name": "晚餐", "suggestion": "清淡、易消化，减少甜点、油炸和浓汤，晚间不再追加高糖零食。"},
            ],
            "recipes": recipes,
            "nutrientTargets": {
                **targets,
                "dietaryFiber": 25,
                "calcium": 800,
                "magnesium": 320,
                "vitamin": "按老年人常规均衡膳食目标执行",
            },
            "forbiddenFoods": ["高糖饮料", "油炸食品", "奶油甜点", "过量精制主食", "夜间加餐甜食"],
            "supplementSuggestions": ["如需特医或特膳产品，请按处方或专业建议执行。"],
            "mealBreakdown": meal_breakdown,
            "demoNotes": [
                f"病症类型：{disease_label}",
                f"饮食偏好：{preferences or '未填写，按清淡均衡默认推荐'}",
                "视觉识别结果会继续用于修正当日剩余餐次。",
            ],
        }

    @staticmethod
    def _fallback_agent_reply(user_message: str, context: dict[str, Any]) -> dict[str, Any]:
        text = user_message.strip()
        latest_plan = (context.get("latestPlan") or {}).get("plan") or {}
        normalized = text.replace("，", " ").replace("。", " ").strip()
        has_cn = any("\u4e00" <= char <= "\u9fff" for char in normalized)
        meaningful = has_cn and len(normalized) >= 3
        if not meaningful:
            return {
                "content": "我还需要更具体一点的反馈，例如“晚餐太油”“不想吃鱼”“菜太淡不好吃”，这样才能安全调整食谱。",
                "planPatch": {},
                "safetyNotes": ["未识别到明确饮食反馈，本次不调整营养方案。"],
            }
        dislikes = [word for word in ("太甜", "太油", "吃不下", "不想吃鱼", "不吃鱼", "咸", "腻", "难吃", "不好吃", "没味道", "太淡", "单调") if word in text]
        content = "我已记录你的反馈，会在不突破健康阈值的范围内微调食谱。"
        patch: dict[str, Any] = {}
        recipes = [dict(recipe) for recipe in (latest_plan.get("recipes") or [])]
        before_recipes = [dict(recipe) for recipe in recipes]
        if "不想吃鱼" in text or "不吃鱼" in text:
            recipes = replace_recipe_item(recipes, "清蒸鱼", "去皮鸡腿肉")
            content = "收到，后续把鱼类替换为去皮鸡腿肉、鸡蛋羹或豆腐，蛋白质目标保持不变。"
        elif "太甜" in text:
            recipes = replace_recipe_item(recipes, "南瓜", "山药")
            content = "收到，下一版减少偏甜主食，用山药、燕麦、杂粮替代一部分南瓜和甜口食物。"
        elif "太油" in text or "腻" in text:
            content = "收到，下一餐改成蒸、煮、炖为主，油脂目标下调约 5%，蛋白质不减少。"
            daily = dict(latest_plan.get("dailyGoal") or {})
            if daily.get("fatG"):
                daily["fatG"] = max(35, int(round(float(daily["fatG"]) * 0.95)))
                patch["dailyGoal"] = daily
        elif "吃不下" in text:
            content = "收到，先把单餐体积调小，改成少量多样，全天能量目标只小幅下调。"
            daily = dict(latest_plan.get("dailyGoal") or {})
            if daily.get("energyKcal"):
                daily["energyKcal"] = max(1300, int(round(float(daily["energyKcal"]) * 0.94)))
                patch["dailyGoal"] = daily
            recipes = make_recipes_smaller(recipes)
        elif any(word in text for word in ("难吃", "不好吃", "没味道", "太淡", "单调")):
            content = "收到，下一版会保留控糖和少油目标，但把菜品换成更有味道的酸香、菌菇和清炖组合。"
            recipes = make_recipes_more_palatable(recipes)
        if recipes:
            targets = normalize_targets(patch.get("dailyGoal") or latest_plan.get("dailyGoal") or {})
            patch["recipes"] = recipes
            patch["mealBreakdown"] = meal_breakdown_from_targets(targets, recipes)
        patch["adjustmentReason"] = f"Agent 根据用户反馈调整：{text[:60]}"
        if dislikes:
            patch["feedbackTags"] = dislikes
        changes = describe_recipe_changes(before_recipes, recipes)
        if changes:
            patch["adjustmentSummary"] = changes
        return {"content": content, "planPatch": patch, "safetyNotes": ["调整幅度已限制在日常健康阈值内。"]}


def extract_preferences(profile: dict[str, Any]) -> str:
    keys = ["dietPreference", "dietPreferences", "tastePreference", "foodPreference", "preferredFoods"]
    parts: list[str] = []
    for key in keys:
        value = profile.get(key)
        if isinstance(value, list):
            parts.extend(str(item) for item in value if item)
        elif value:
            parts.append(str(value))
    history = " ".join(str(profile.get(key) or "") for key in ("allergyHistory", "diseaseHistory"))
    if "不吃鱼" in history or "忌鱼" in history:
        parts.append("不吃鱼")
    if "素" in history:
        parts.append("偏素")
    return "、".join(dict.fromkeys(part.strip() for part in parts if part.strip()))


def targets_for_profile(profile: dict[str, Any]) -> dict[str, int]:
    weight = float(profile.get("weight") or 65)
    age = int(float(profile.get("age") or 68))
    intensity = profile.get("workIntensity") or "low"
    disease = profile.get("diseaseType") or "other"
    kcal_per_kg = {"low": 24, "medium": 27, "high": 30}.get(str(intensity), 24)
    if age >= 70:
        kcal_per_kg -= 1
    energy = int(round(max(1300, min(2100, weight * kcal_per_kg)) / 10) * 10)
    protein = int(round(max(55, min(95, weight * 1.05))))
    fat = int(round(max(35, min(65, energy * 0.26 / 9))))
    carbs = int(round(max(135, min(260, (energy - protein * 4 - fat * 9) / 4))))
    if disease == "diabetes":
        carbs = int(round(carbs * 0.88))
        fat = int(round(fat * 0.95))
    if disease == "hypertension":
        fat = int(round(fat * 0.92))
    return {"energyKcal": energy, "proteinG": protein, "fatG": fat, "carbohydrateG": carbs}


def recipes_for_profile(profile: dict[str, Any], preferences: str) -> list[dict[str, Any]]:
    disease = profile.get("diseaseType") or "other"
    allergies = str(profile.get("allergyHistory") or "")
    no_fish = "不吃鱼" in preferences or "忌鱼" in preferences or "鱼" in allergies
    prefer_soft = disease in {"internal_postoperative_recovery", "tumor_recovery"} or "软" in preferences
    lunch_protein = "清蒸鱼" if not no_fish else "去皮鸡腿肉"
    dinner_protein = "嫩豆腐" if prefer_soft else "鸡蛋羹"
    breakfast_staple = "燕麦南瓜粥" if disease == "diabetes" else "小米山药粥"
    return [
        {
            "mealType": "breakfast",
            "name": "早餐",
            "items": [breakfast_staple, "水煮蛋", "无糖豆浆"],
            "reason": "低糖慢释放主食搭配优质蛋白，早晨更稳。",
        },
        {
            "mealType": "lunch",
            "name": "午餐",
            "items": ["糙米饭半碗", lunch_protein, "清炒西兰花", "番茄菌菇汤"],
            "reason": "午餐保留足量蛋白与蔬菜，控制油盐。",
        },
        {
            "mealType": "dinner",
            "name": "晚餐",
            "items": ["南瓜小米粥", dinner_protein, "蒜蓉生菜"],
            "reason": "晚餐软烂清淡，减少夜间血糖和胃肠负担。",
        },
    ]


def meal_breakdown_from_targets(targets: dict[str, int], recipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ratios = [0.28, 0.42, 0.30]
    meal_types = ["breakfast", "lunch", "dinner"]
    result: list[dict[str, Any]] = []
    for idx, ratio in enumerate(ratios):
        recipe = recipes[idx] if idx < len(recipes) else {}
        result.append(
            {
                "mealType": meal_types[idx],
                "name": recipe.get("name") or meal_types[idx],
                "energyKcal": int(round(targets["energyKcal"] * ratio)),
                "proteinG": int(round(targets["proteinG"] * ratio)),
                "fatG": int(round(targets["fatG"] * ratio)),
                "carbohydrateG": int(round(targets["carbohydrateG"] * ratio)),
                "recommendedItems": recipe.get("items") or [],
                "reason": recipe.get("reason") or "",
            }
        )
    return result


def replace_recipe_item(recipes: list[dict[str, Any]], old: str, new: str) -> list[dict[str, Any]]:
    updated = []
    for recipe in recipes:
        item = dict(recipe)
        item["items"] = [new if old in str(food) else food for food in item.get("items", [])]
        updated.append(item)
    return updated


def make_recipes_more_palatable(recipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    replacements = {
        "清炒西兰花": "番茄烩西兰花",
        "蒜蓉生菜": "香菇扒生菜",
        "南瓜小米粥": "山药小米粥",
        "无糖豆浆": "温热无糖豆浆",
        "番茄菌菇汤": "紫菜虾皮菌菇汤",
    }
    updated: list[dict[str, Any]] = []
    for recipe in recipes:
        item = dict(recipe)
        item["items"] = [replacements.get(str(food), food) for food in item.get("items", [])]
        if item.get("mealType") == "lunch" and "凉拌黄瓜木耳" not in item["items"]:
            item["items"].append("凉拌黄瓜木耳")
        if item.get("mealType") == "dinner" and "醋汁番茄" not in item["items"]:
            item["items"].append("醋汁番茄")
        item["reason"] = "保留控糖少油原则，用酸香、菌菇和清淡调味提升入口感。"
        updated.append(item)
    return updated


def make_recipes_smaller(recipes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    updated: list[dict[str, Any]] = []
    for recipe in recipes:
        item = dict(recipe)
        if item.get("mealType") == "lunch":
            item["items"] = ["杂粮饭小半碗", "鸡蛋豆腐羹", "番茄菌菇汤", "少量清炒时蔬"]
            item["reason"] = "单餐体积下调，保留蛋白质和蔬菜，减少饱胀感。"
        elif item.get("mealType") == "dinner":
            item["items"] = ["山药小米粥半碗", "嫩豆腐", "焯青菜"]
            item["reason"] = "晚餐改成软烂小份，降低胃肠负担。"
        updated.append(item)
    return updated


def describe_recipe_changes(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    before_by_meal = {recipe.get("mealType"): recipe for recipe in before}
    for recipe in after:
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


def normalize_targets(raw: dict[str, Any]) -> dict[str, int]:
    return {
        "energyKcal": int(float(raw.get("energyKcal") or 1600)),
        "proteinG": int(float(raw.get("proteinG") or 65)),
        "fatG": int(float(raw.get("fatG") or 45)),
        "carbohydrateG": int(float(raw.get("carbohydrateG") or 210)),
    }
