"""Mistral OCR 4 client (text transcription / table structure).

API shape confirmed 2026-08-11 (부록 B.1):
  POST https://api.mistral.ai/v1/ocr
  Authorization: Bearer <MISTRAL_API_KEY>
  {"model": "mistral-ocr-4-0",
   "document": {"type": "image_url",
                "image_url": "data:image/jpeg;base64,<...>"},
   "table_format": null | "markdown" | "html"}
  -> {"pages": [{"index", "markdown", "tables": [...], "images": [...]}],
      "model", "usage_info": {"pages_processed", "doc_size_bytes"}}

Two call modes, both billed at the same per-page rate:

`transcribe` omits `table_format` entirely. At the default (`null`) tables come
back as markdown table syntax inline in `pages[].markdown`, which is what the
CER/WER pipeline should measure — asking for separated tables would leave
`[tbl-N.html](tbl-N.html)` placeholders in the text and score the harness's
choice of output format rather than Mistral's character accuracy.

`transcribe_table` sets `table_format="html"` and is used only by the
table-structure (TEDS) path. `table_format` values are mutually exclusive, so
unlike Upstage — which returns text and HTML from one call — this needs a
second, separately billed request.

Field layout confirmed 2026-08-11 from a live response (`jichul_p01`, cached at
`results/raw3/tables/mistral_ocr/jichul_p01.json`):

    {"id": "tbl-0.html", "content": "<table>...</table>",
     "format": "html", "word_confidence_scores": null}

The HTML lives under `content`, not `html` — the pre-live-call guess used
`html` and scored every page 0 (`extract_table_htmls` returned `[]`
everywhere) despite `tables_raw` being populated, which is exactly why that
array is kept verbatim in `usage_raw["tables_raw"]`: the parser was fixed from
the cache alone, no re-call needed. `extract_table_htmls` now reads `content`
first and still falls back to `html` / a bare string, so a future format
change degrades instead of silently zeroing every page again.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import requests

from .. import config
from .base import EngineResult, apply_cost

API_URL = "https://api.mistral.ai/v1/ocr"
DEFAULT_TIMEOUT = 180


def parse_response(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Extract the page markdown and usage from an OCR response."""
    pages = payload.get("pages") or []
    if not pages:
        raise ValueError("Mistral response contained no pages[]")

    usage_info = payload.get("usage_info") or {}
    usage = {
        "pages_processed": usage_info.get("pages_processed", 1),
        "doc_size_bytes": usage_info.get("doc_size_bytes"),
        "model": payload.get("model"),
    }
    return pages[0].get("markdown") or "", usage


def raw_tables(payload: dict[str, Any]) -> list[Any]:
    """The `pages[0].tables` array exactly as received, with no reshaping."""
    pages = payload.get("pages") or []
    if not pages:
        return []
    return list(pages[0].get("tables") or [])


def extract_table_htmls(payload: dict[str, Any]) -> list[str]:
    """Pull each table's `<table>` HTML out of a `table_format="html"` response.

    Confirmed shape (2026-08-11, live response): `content` holds the HTML
    string, alongside `id`/`format`/`word_confidence_scores`. `html` is kept as
    a fallback key in case a future API revision renames the field, and a bare
    string entry is taken as-is either way. An entry that matches neither is
    skipped rather than raised on — skipping loses one table's score, raising
    would floor-score the entire page and hide that a response arrived at all.
    `usage_raw["tables_raw"]` always keeps the untouched array, so a schema
    change can be diagnosed and re-parsed from the cache without re-paying,
    the same way this file's own `content` vs `html` mismatch was fixed.
    """
    htmls: list[str] = []
    for table in raw_tables(payload):
        if isinstance(table, dict):
            html = table.get("content") or table.get("html")
            if isinstance(html, str) and html.strip():
                htmls.append(html)
        elif isinstance(table, str) and table.strip():
            htmls.append(table)
    return htmls


class MistralClient:
    def __init__(
        self,
        engine_config_id: str = "mistral_ocr",
        api_key: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.engine_config_id = engine_config_id
        self.cfg = config.engine_config(engine_config_id)
        self.api_key = api_key
        self.timeout = timeout

    def build_request(
        self, image_path: Path, table_format: str | None = None
    ) -> dict[str, Any]:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        body: dict[str, Any] = {
            "model": self.cfg["model"],
            "document": {
                "type": "image_url",
                "image_url": f"data:image/jpeg;base64,{encoded}",
            },
        }
        if table_format is not None:
            body["table_format"] = table_format
        return body

    def _call(
        self, image_path: Path, sample_id: str, table_format: str | None
    ) -> EngineResult:
        result = EngineResult(engine_config_id=self.engine_config_id, sample_id=sample_id)
        started = time.monotonic()
        try:
            response = requests.post(
                API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=self.build_request(image_path, table_format),
                timeout=self.timeout,
            )
            result.latency_ms = int((time.monotonic() - started) * 1000)
            result.http_status = response.status_code
            response.raise_for_status()
            payload = response.json()
            result.raw_text, result.usage_raw = parse_response(payload)
            if table_format is not None:
                result.usage_raw["tables_raw"] = raw_tables(payload)
                result.table_htmls = extract_table_htmls(payload)
        except Exception as exc:
            result.latency_ms = result.latency_ms or int((time.monotonic() - started) * 1000)
            result.error = f"{type(exc).__name__}: {exc}"
            return result

        return apply_cost(result)

    def transcribe(self, image_path: Path, sample_id: str) -> EngineResult:
        """Full-page transcription for the CER/WER benchmark."""
        return self._call(image_path, sample_id, None)

    def transcribe_table(self, image_path: Path, sample_id: str) -> EngineResult:
        """Table structure for TEDS scoring.

        `raw_text` still holds the page markdown, but with tables separated out
        it contains `[tbl-N.html](tbl-N.html)` placeholders where the tables
        were. That is expected: only `table_htmls` is scored from this call.
        """
        return self._call(image_path, sample_id, "html")
