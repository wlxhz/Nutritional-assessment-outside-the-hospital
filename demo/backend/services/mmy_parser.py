from __future__ import annotations

import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


@dataclass
class ParseResult:
    status: str
    text: str
    preview: dict[str, Any]
    feedback: str


class LocalPrescriptionParser:
    """Local parser service for prescription files.

    This intentionally avoids implementing the visual-recognition pipeline. For
    scanned PDFs, OCR integration remains an explicit extension point and the
    API returns user-facing feedback instead of pretending the OCR succeeded.
    """

    def parse(self, filename: str, content_type: str, data: bytes) -> ParseResult:
        suffix = Path(filename).suffix.lower()
        try:
            if suffix == ".docx":
                text = self._docx_text(data)
            elif suffix == ".doc":
                return self._feedback(
                    "needs_converter",
                    "已收到 .doc 文件。Demo 后端已预留本地转换接口，请接入 .doc 转 .docx 或文本的本地解析工具。",
                )
            elif suffix == ".pdf" or "pdf" in content_type:
                text = self._pdf_text(data)
            else:
                return self._feedback("unsupported", "当前仅支持 PDF、扫描件 PDF、.doc、.docx。")
        except Exception as exc:
            return self._feedback("failed", f"文件解析失败：{exc}")

        if not text.strip():
            return self._feedback(
                "needs_ocr",
                "未读取到可解析文字。该文件可能是扫描件 PDF，请接入本地 OCR 服务后重试。",
            )
        preview = self._preview_from_text(text)
        return ParseResult(status="parsed", text=text, preview=preview, feedback="解析成功，可预览，不可直接修改。")

    def _feedback(self, status: str, message: str) -> ParseResult:
        return ParseResult(status=status, text="", preview={"sections": [], "rawExcerpt": ""}, feedback=message)

    @staticmethod
    def _docx_text(data: bytes) -> str:
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            with zipfile.ZipFile(tmp_path) as archive:
                xml = archive.read("word/document.xml")
            root = ElementTree.fromstring(xml)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs: list[str] = []
            for paragraph in root.findall(".//w:p", ns):
                parts = [node.text or "" for node in paragraph.findall(".//w:t", ns)]
                line = "".join(parts).strip()
                if line:
                    paragraphs.append(line)
            return "\n".join(paragraphs)
        finally:
            tmp_path.unlink(missing_ok=True)

    @staticmethod
    def _pdf_text(data: bytes) -> str:
        # Minimal local text extraction without adding a dependency. It works for
        # simple text PDFs and deliberately falls through to OCR feedback for
        # scanned/image PDFs.
        raw = data.decode("latin-1", errors="ignore")
        candidates = re.findall(r"\((.*?)\)\s*Tj", raw, flags=re.S)
        candidates += re.findall(r"\[(.*?)\]\s*TJ", raw, flags=re.S)
        text = "\n".join(LocalPrescriptionParser._clean_pdf_text(item) for item in candidates)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _clean_pdf_text(value: str) -> str:
        value = re.sub(r"\\[()\\]", lambda m: m.group(0)[1:], value)
        value = re.sub(r"\\[nrt]", " ", value)
        value = re.sub(r"<[0-9A-Fa-f]+>", " ", value)
        return value.strip()

    @staticmethod
    def _preview_from_text(text: str) -> dict[str, Any]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        excerpt = "\n".join(lines[:12])[:900]
        sections = []
        labels = [
            ("每日总目标", ["每日", "总目标", "能量", "kcal"]),
            ("每餐建议", ["早餐", "午餐", "晚餐", "每餐"]),
            ("营养素目标", ["蛋白质", "脂肪", "碳水", "膳食纤维", "钙", "镁", "维生素"]),
            ("禁忌食物", ["禁忌", "避免", "不宜"]),
            ("补充剂建议", ["补充", "特医", "特膳"]),
        ]
        for title, keywords in labels:
            hits = [line for line in lines if any(word.lower() in line.lower() for word in keywords)]
            sections.append({"title": title, "items": hits[:4]})
        return {"sections": sections, "rawExcerpt": excerpt}
