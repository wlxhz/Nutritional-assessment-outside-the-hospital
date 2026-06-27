from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


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


class MmyAiClient:
    def __init__(self, config: AiConfig) -> None:
        self.config = config

    def nutrition_plan(self, profile: dict[str, Any], prescription_text: str | None = None) -> dict[str, Any]:
        fallback = self._fallback_plan(profile, prescription_text)
        if not self.config.configured:
            return {"status": "local_fallback", "plan": fallback, "raw": None}
        prompt = (
            "你是院外营养管理 App 的营养方案生成模块。"
            "请基于用户基础信息和处方文本生成 JSON，字段必须包含 dailyGoal, mealSuggestions, recipes, "
            "nutrientTargets, forbiddenFoods, supplementSuggestions, mealBreakdown。"
            "餐次仅包含早餐、午餐、晚餐。不要输出 Markdown。"
        )
        user_content = json.dumps(
            {"profile": profile, "prescriptionText": prescription_text or ""},
            ensure_ascii=False,
        )
        raw = self._chat(prompt, user_content, self.config.nutrition_model or self.config.default_model)
        parsed = self._json_from_text(raw)
        return {"status": "model", "plan": parsed or fallback, "raw": raw}

    def agent_reply(self, user_message: str, context: dict[str, Any]) -> dict[str, Any]:
        fallback = (
            "我已经记录了你的反馈。Demo 阶段我会围绕食谱调整和院外陪伴回应，"
            "视觉识别和营养规则细节会在后续接口接入后完善。"
        )
        if not self.config.configured:
            return {"status": "local_fallback", "content": fallback, "raw": None}
        prompt = (
            "你是慢慢养 App 的院外陪伴 Agent。只处理食谱反馈、身体感受、食谱调整和陪伴。"
            "回答要简短、温和、适合老年用户阅读，不提供诊断。"
        )
        user_content = json.dumps({"message": user_message, "context": context}, ensure_ascii=False)
        raw = self._chat(prompt, user_content, self.config.agent_model or self.config.default_model)
        return {"status": "model", "content": raw.strip() or fallback, "raw": raw}

    def _chat(self, system_prompt: str, user_content: str, model: str) -> str:
        # OpenAI-compatible chat completions. The exact provider is supplied
        # through .env, so the demo does not bake a vendor decision into code.
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
        with request.urlopen(req, timeout=max(1, self.config.timeout_ms / 1000)) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"]

    @staticmethod
    def _json_from_text(text: str) -> dict[str, Any] | None:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
        try:
            value = json.loads(cleaned)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _fallback_plan(profile: dict[str, Any], prescription_text: str | None) -> dict[str, Any]:
        disease = profile.get("diseaseType") or "other"
        source_note = "基于导入处方生成" if prescription_text else "基于基础身体指征生成"
        return {
            "dailyGoal": {
                "summary": f"{source_note}。当前为本地 Demo 方案，正式数值等待营养规则接口确认。",
                "energyKcal": 1600,
                "proteinG": 65,
                "fatG": 45,
                "carbohydrateG": 210,
            },
            "mealSuggestions": [
                {"mealType": "breakfast", "name": "早餐", "suggestion": "清淡主食搭配优质蛋白。"},
                {"mealType": "lunch", "name": "午餐", "suggestion": "保证蔬菜和蛋白质，控制油脂。"},
                {"mealType": "dinner", "name": "晚餐", "suggestion": "减少高糖高脂食物，保持易消化。"},
            ],
            "recipes": [
                {"mealType": "breakfast", "items": ["燕麦粥", "鸡蛋", "无糖豆浆"]},
                {"mealType": "lunch", "items": ["杂粮饭", "清蒸鱼", "时蔬"]},
                {"mealType": "dinner", "items": ["南瓜粥", "豆腐", "青菜"]},
            ],
            "nutrientTargets": {
                "energyKcal": 1600,
                "proteinG": 65,
                "fatG": 45,
                "carbohydrateG": 210,
                "dietaryFiber": 25,
                "calcium": 800,
                "magnesium": 320,
                "vitamin": "按国际认可度最高标准执行",
            },
            "forbiddenFoods": ["高糖饮料", "油炸食品", "过量精制主食"],
            "supplementSuggestions": ["如需使用特医、特膳产品，请按处方或专业建议执行。"],
            "mealBreakdown": [
                {"mealType": "breakfast", "energyKcal": 430, "proteinG": 18, "fatG": 12, "carbohydrateG": 58},
                {"mealType": "lunch", "energyKcal": 650, "proteinG": 28, "fatG": 18, "carbohydrateG": 86},
                {"mealType": "dinner", "energyKcal": 520, "proteinG": 19, "fatG": 15, "carbohydrateG": 66},
            ],
            "demoNotes": [
                f"病症类型：{disease}",
                "摄像头与视觉识别结果由算法接口接入。",
            ],
        }
