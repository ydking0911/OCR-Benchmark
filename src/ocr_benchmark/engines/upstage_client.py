"""Upstage Document Parse client (Standard / Enhanced).

API shape confirmed 2026-08-11:
  POST https://api.upstage.ai/v1/document-digitization
  Authorization: Bearer <UPSTAGE_API_KEY>
  multipart/form-data: document=<file>, model=document-parse,
                       mode=standard|enhanced|auto, output_formats=['text','html']
  -> {"api", "model", "usage": {"pages": N},
      "content": {"text", "html", "markdown"},
       "elements": [{"category": ..., "content": {"text", "html", ...}}]}

`html` is requested alongside `text` so `elements[].content.html` is populated
for `category == "table"` elements — that is the only place Document Parse
exposes table structure, and it was previously discarded. Text extraction is
unaffected: `content.text` is still what feeds CER/WER.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests

from .. import config
from .base import EngineResult, apply_cost

API_URL = "https://api.upstage.ai/v1/document-digitization"
DEFAULT_TIMEOUT = 180


def parse_response(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Extract reading-order text and usage from a Document Parse response."""
    content = payload.get("content") or {}
    text = content.get("text") or ""
    if not text:
        # `output_formats` did not include text: rebuild from the element list,
        # which the API returns in reading order.
        parts = []
        for element in payload.get("elements") or []:
            element_text = (element.get("content") or {}).get("text")
            if element_text:
                parts.append(element_text)
        text = "\n".join(parts)

    usage = {
        "pages": (payload.get("usage") or {}).get("pages", 1),
        "model": payload.get("model"),
        "api": payload.get("api"),
        "element_count": len(payload.get("elements") or []),
    }
    return text, usage


def extract_table_htmls(payload: dict[str, Any]) -> list[str]:
    """Collect the `<table>` HTML of every table element, in reading order.

    Kept out of `parse_response` so the text pipeline's contract is unchanged;
    tables are an additional output, not a different parse.
    """
    htmls: list[str] = []
    for element in payload.get("elements") or []:
        if (element.get("category") or "").lower() != "table":
            continue
        html = (element.get("content") or {}).get("html")
        if html:
            htmls.append(html)
    return htmls


class UpstageClient:
    def __init__(self, engine_config_id: str, api_key: str, timeout: int = DEFAULT_TIMEOUT):
        self.engine_config_id = engine_config_id
        self.cfg = config.ENGINE_CONFIGS[engine_config_id]
        self.api_key = api_key
        self.timeout = timeout

    def transcribe(self, image_path: Path, sample_id: str) -> EngineResult:
        result = EngineResult(engine_config_id=self.engine_config_id, sample_id=sample_id)
        started = time.monotonic()
        try:
            with open(image_path, "rb") as handle:
                response = requests.post(
                    API_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files={"document": (image_path.name, handle, "image/jpeg")},
                    data={
                        "model": self.cfg["model"],
                        "mode": self.cfg["mode"],
                        "output_formats": '["text","html"]',
                    },
                    timeout=self.timeout,
                )
            result.latency_ms = int((time.monotonic() - started) * 1000)
            result.http_status = response.status_code
            response.raise_for_status()
            payload = response.json()
            result.raw_text, result.usage_raw = parse_response(payload)
            result.table_htmls = extract_table_htmls(payload)
        except Exception as exc:
            result.latency_ms = result.latency_ms or int((time.monotonic() - started) * 1000)
            result.error = f"{type(exc).__name__}: {exc}"
            return result

        return apply_cost(result)
