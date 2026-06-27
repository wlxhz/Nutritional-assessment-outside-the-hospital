from __future__ import annotations

import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


CHINA_TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(CHINA_TZ).isoformat()


def make_id(prefix: str) -> str:
    stamp = datetime.now(CHINA_TZ).strftime("%Y%m%d%H%M%S")
    return f"{prefix}_{stamp}_{secrets.token_hex(3)}"


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def loads(raw: str | None, fallback: Any = None) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


class MmyStore:
    """SQLite store for the Manmanyang app demo.

    The product document asks for local SQLite first, with server details added
    later through configuration. This store keeps the schema intentionally flat
    and JSON-friendly so the React Native layer can move to a mobile SQLite
    adapter without reshaping the domain too much.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.sms_codes: dict[str, dict[str, Any]] = {}
        self._init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 15000")
        return conn

    def _init_db(self) -> None:
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    phone TEXT NOT NULL,
                    login_method TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profiles (
                    user_id TEXT PRIMARY KEY,
                    profile_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS prescriptions (
                    prescription_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    text TEXT NOT NULL,
                    preview_json TEXT NOT NULL,
                    feedback TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS nutrition_plans (
                    plan_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_id TEXT,
                    plan_json TEXT NOT NULL,
                    ai_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS intake_records (
                    record_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    meal_type TEXT NOT NULL,
                    items_json TEXT NOT NULL,
                    nutrient_actual_json TEXT NOT NULL,
                    adjustment_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS food_stickers (
                    sticker_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    record_id TEXT,
                    source_session_id TEXT,
                    source_track_id TEXT,
                    item_name TEXT NOT NULL,
                    compliance_level TEXT NOT NULL,
                    sticker_color TEXT NOT NULL,
                    image_svg TEXT,
                    meta_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS reports (
                    report_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    range_type TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    generated_at TEXT NOT NULL,
                    confirmed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS agent_messages (
                    message_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    sender TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS temporary_recognition_data (
                    temp_data_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    report_id TEXT,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    delete_reason TEXT
                );
                """
            )

    def login(self, phone: str, method: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM users WHERE phone = ?", (phone,)).fetchone()
            if row:
                return dict(row)
            user = {
                "user_id": make_id("user"),
                "phone": phone,
                "login_method": method,
                "created_at": now_iso(),
            }
            conn.execute(
                "INSERT INTO users (user_id, phone, login_method, created_at) VALUES (?, ?, ?, ?)",
                (user["user_id"], user["phone"], user["login_method"], user["created_at"]),
            )
            return user

    def issue_code(self, phone: str) -> dict[str, Any]:
        code = f"{secrets.randbelow(900000) + 100000}"
        expires_at = datetime.now(CHINA_TZ) + timedelta(seconds=60)
        self.sms_codes[phone] = {"code": code, "expires_at": expires_at}
        return {"phone": phone, "code": code, "expires_in_seconds": 60}

    def verify_code(self, phone: str, code: str) -> bool:
        record = self.sms_codes.get(phone)
        if not record:
            return False
        if datetime.now(CHINA_TZ) > record["expires_at"]:
            return False
        return secrets.compare_digest(record["code"], code)

    def save_profile(self, user_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        payload = {**profile, "userId": user_id, "updatedAt": now_iso()}
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO profiles (user_id, profile_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET profile_json = excluded.profile_json,
                    updated_at = excluded.updated_at
                """,
                (user_id, dumps(payload), payload["updatedAt"]),
            )
        return payload

    def get_profile(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT profile_json FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
        return loads(row["profile_json"]) if row else None

    def save_prescription(
        self,
        user_id: str,
        filename: str,
        content_type: str,
        status: str,
        text: str,
        preview: dict[str, Any],
        feedback: str,
    ) -> dict[str, Any]:
        record = {
            "prescriptionId": make_id("rx"),
            "userId": user_id,
            "filename": filename,
            "contentType": content_type,
            "status": status,
            "text": text,
            "preview": preview,
            "feedback": feedback,
            "createdAt": now_iso(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO prescriptions
                (prescription_id, user_id, filename, content_type, status, text, preview_json, feedback, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["prescriptionId"],
                    user_id,
                    filename,
                    content_type,
                    status,
                    text,
                    dumps(preview),
                    feedback,
                    record["createdAt"],
                ),
            )
        return record

    def delete_prescription(self, prescription_id: str) -> bool:
        with self.connect() as conn:
            result = conn.execute("DELETE FROM prescriptions WHERE prescription_id = ?", (prescription_id,))
            return result.rowcount > 0

    def get_prescription(self, prescription_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM prescriptions WHERE prescription_id = ?", (prescription_id,)
            ).fetchone()
        if not row:
            return None
        return {
            "prescriptionId": row["prescription_id"],
            "userId": row["user_id"],
            "filename": row["filename"],
            "contentType": row["content_type"],
            "status": row["status"],
            "text": row["text"],
            "preview": loads(row["preview_json"], {}),
            "feedback": row["feedback"],
            "createdAt": row["created_at"],
        }

    def save_plan(
        self,
        user_id: str,
        source_type: str,
        plan: dict[str, Any],
        ai_status: str,
        source_id: str | None = None,
    ) -> dict[str, Any]:
        record = {
            "planId": make_id("plan"),
            "userId": user_id,
            "sourceType": source_type,
            "sourceId": source_id,
            "plan": plan,
            "aiStatus": ai_status,
            "createdAt": now_iso(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO nutrition_plans
                (plan_id, user_id, source_type, source_id, plan_json, ai_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["planId"],
                    user_id,
                    source_type,
                    source_id,
                    dumps(plan),
                    ai_status,
                    record["createdAt"],
                ),
            )
        return record

    def latest_plan(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM nutrition_plans
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "planId": row["plan_id"],
            "userId": row["user_id"],
            "sourceType": row["source_type"],
            "sourceId": row["source_id"],
            "plan": loads(row["plan_json"], {}),
            "aiStatus": row["ai_status"],
            "createdAt": row["created_at"],
        }

    def save_intake(
        self,
        user_id: str,
        meal_type: str,
        items: list[dict[str, Any]],
        nutrient_actual: dict[str, float],
        adjustment: dict[str, Any],
    ) -> dict[str, Any]:
        record = {
            "recordId": make_id("meal"),
            "userId": user_id,
            "mealType": meal_type,
            "items": items,
            "nutrientActual": nutrient_actual,
            "adjustment": adjustment,
            "createdAt": now_iso(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO intake_records
                (record_id, user_id, meal_type, items_json, nutrient_actual_json, adjustment_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["recordId"],
                    user_id,
                    meal_type,
                    dumps(items),
                    dumps(nutrient_actual),
                    dumps(adjustment),
                    record["createdAt"],
                ),
            )
        return record

    def save_food_stickers(
        self,
        user_id: str,
        record_id: str,
        stickers: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        saved: list[dict[str, Any]] = []
        created_at = now_iso()
        with self.connect() as conn:
            for sticker in stickers:
                item_name = sticker.get("itemName") or sticker.get("name") or "未命名食物"
                compliance_level = sticker.get("complianceLevel") or "generally_compliant"
                sticker_color = sticker.get("stickerColor") or "#EFD67C"
                record = {
                    "stickerId": make_id("sticker"),
                    "userId": user_id,
                    "recordId": record_id,
                    "sourceSessionId": sticker.get("sourceSessionId"),
                    "sourceTrackId": sticker.get("sourceTrackId"),
                    "itemName": item_name,
                    "complianceLevel": compliance_level,
                    "stickerColor": sticker_color,
                    "imageSvg": sticker.get("imageSvg"),
                    "meta": sticker.get("meta") or {},
                    "createdAt": created_at,
                }
                conn.execute(
                    """
                    INSERT INTO food_stickers
                    (sticker_id, user_id, record_id, source_session_id, source_track_id,
                     item_name, compliance_level, sticker_color, image_svg, meta_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["stickerId"],
                        user_id,
                        record_id,
                        record["sourceSessionId"],
                        record["sourceTrackId"],
                        item_name,
                        compliance_level,
                        sticker_color,
                        record["imageSvg"],
                        dumps(record["meta"]),
                        created_at,
                    ),
                )
                saved.append(record)
        return saved

    def list_food_stickers(self, user_id: str, day: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM food_stickers WHERE user_id = ?"
        params: list[Any] = [user_id]
        if day:
            query += " AND substr(created_at, 1, 10) = ?"
            params.append(day)
        query += " ORDER BY created_at DESC"
        with self.connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "stickerId": row["sticker_id"],
                "userId": row["user_id"],
                "recordId": row["record_id"],
                "sourceSessionId": row["source_session_id"],
                "sourceTrackId": row["source_track_id"],
                "itemName": row["item_name"],
                "complianceLevel": row["compliance_level"],
                "stickerColor": row["sticker_color"],
                "imageSvg": row["image_svg"],
                "meta": loads(row["meta_json"], {}),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def list_intakes(self, user_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM intake_records WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,),
            ).fetchall()
        return [
            {
                "recordId": row["record_id"],
                "userId": row["user_id"],
                "mealType": row["meal_type"],
                "items": loads(row["items_json"], []),
                "nutrientActual": loads(row["nutrient_actual_json"], {}),
                "adjustment": loads(row["adjustment_json"], {}),
                "createdAt": row["created_at"],
            }
            for row in rows
        ]

    def save_report(self, user_id: str, range_type: str, data: dict[str, Any]) -> dict[str, Any]:
        report = {
            "reportId": make_id("report"),
            "userId": user_id,
            "rangeType": range_type,
            "data": data,
            "status": "pending_confirm",
            "generatedAt": now_iso(),
            "confirmedAt": None,
        }
        expires_at = (datetime.now(CHINA_TZ) + timedelta(minutes=15)).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO reports
                (report_id, user_id, range_type, data_json, status, generated_at, confirmed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report["reportId"],
                    user_id,
                    range_type,
                    dumps(data),
                    report["status"],
                    report["generatedAt"],
                    None,
                ),
            )
            conn.execute(
                """
                INSERT INTO temporary_recognition_data
                (temp_data_id, user_id, report_id, created_at, expires_at, delete_reason)
                VALUES (?, ?, ?, ?, ?, NULL)
                """,
                (make_id("tmp"), user_id, report["reportId"], now_iso(), expires_at),
            )
        return report

    def confirm_report(self, report_id: str) -> dict[str, Any] | None:
        confirmed_at = now_iso()
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM reports WHERE report_id = ?", (report_id,)).fetchone()
            if not row:
                return None
            conn.execute(
                "UPDATE reports SET status = ?, confirmed_at = ? WHERE report_id = ?",
                ("confirmed", confirmed_at, report_id),
            )
            conn.execute(
                """
                UPDATE temporary_recognition_data
                SET delete_reason = ?
                WHERE report_id = ? AND delete_reason IS NULL
                """,
                ("report_confirmed", report_id),
            )
        return {"reportId": report_id, "status": "confirmed", "confirmedAt": confirmed_at}

    def cleanup_expired_temp_data(self) -> int:
        with self.connect() as conn:
            result = conn.execute(
                """
                UPDATE temporary_recognition_data
                SET delete_reason = ?
                WHERE delete_reason IS NULL AND expires_at < ?
                """,
                ("expired_15min", now_iso()),
            )
            return result.rowcount

    def add_message(self, user_id: str, sender: str, message_type: str, content: str) -> dict[str, Any]:
        message = {
            "messageId": make_id("msg"),
            "userId": user_id,
            "sender": sender,
            "messageType": message_type,
            "content": content,
            "createdAt": now_iso(),
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_messages
                (message_id, user_id, sender, message_type, content, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    message["messageId"],
                    user_id,
                    sender,
                    message_type,
                    content,
                    message["createdAt"],
                ),
            )
        return message

    def list_messages(self, user_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM agent_messages WHERE user_id = ? ORDER BY created_at ASC",
                (user_id,),
            ).fetchall()
        return [
            {
                "messageId": row["message_id"],
                "userId": row["user_id"],
                "sender": row["sender"],
                "messageType": row["message_type"],
                "content": row["content"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]


def default_db_path(base_dir: Path) -> Path:
    configured = os.getenv("MMY_DB_PATH") or os.getenv("APP_DB_PATH")
    if configured:
        return Path(configured)
    return base_dir / "data" / "mmy.sqlite"
