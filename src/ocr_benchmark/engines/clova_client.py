"""Naver CLOVA OCR General API client (text-only / +table).

API shape confirmed 2026-08-11:
  POST {NCP_CLOVA_OCR_INVOKE_URL}       (per-account APIGW invoke URL)
  X-OCR-SECRET: <NCP_CLOVA_OCR_SECRET>
  {"version": "V2", "requestId", "timestamp",
   "enableTableDetection": bool,
   "images": [{"format": "jpg", "name": ..., "data": <base64>}]}
  -> {"images": [{"inferResult", "message",
                  "fields": [{"inferText", "inferConfidence", "lineBreak",
                              "boundingPoly": {"vertices": [{"x","y"}, ...]}}],
                  "tables": [{"cells": [...]}]}]}

R2: Clova returns positioned fields, not a document. The text below is
*reassembled* by this harness, so CER/WER partly measure the reassembly, not
only Clova's character accuracy. The report must say so.
"""

from __future__ import annotations

import base64
import time
import uuid
from html import escape
from pathlib import Path
from typing import Any

import requests

from .. import config
from .base import EngineResult, apply_cost

DEFAULT_TIMEOUT = 120


def _vertices_top_left(field: dict[str, Any]) -> tuple[float, float]:
    vertices = ((field.get("boundingPoly") or {}).get("vertices")) or []
    if not vertices:
        return (0.0, 0.0)
    return (
        min(float(v.get("y", 0)) for v in vertices),
        min(float(v.get("x", 0)) for v in vertices),
    )


def reassemble_fields(fields: list[dict[str, Any]]) -> str:
    """Rebuild reading-order text from positioned OCR fields.

    V2 responses carry `lineBreak`, which marks the last field on a visual
    line. That is Clova's own line segmentation, so it is preferred over
    inferring lines from coordinates. Without it, fields are ordered
    top-left -> bottom-right and joined with spaces.
    """
    if not fields:
        return ""

    if any("lineBreak" in f for f in fields):
        lines: list[str] = []
        current: list[str] = []
        for field in fields:
            text = field.get("inferText") or ""
            if text:
                current.append(text)
            if field.get("lineBreak"):
                lines.append(" ".join(current))
                current = []
        if current:
            lines.append(" ".join(current))
        return "\n".join(line for line in lines if line)

    ordered = sorted(fields, key=_vertices_top_left)
    return " ".join(f.get("inferText") or "" for f in ordered).strip()


def _cell_text(cell: dict[str, Any]) -> str:
    words = []
    for line in cell.get("cellTextLines") or []:
        for word in line.get("cellWords") or []:
            if word.get("inferText"):
                words.append(word["inferText"])
    return " ".join(words)


def normalize_tables(tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reduce the `tables` array to the fields table scoring needs.

    The raw array carries a boundingPoly per word, which would bloat every
    cached page for no scoring benefit. Grid position, spans and text are kept
    so the HTML can be regenerated later without re-paying for the call.
    """
    normalized = []
    for table in tables:
        cells = []
        for cell in table.get("cells") or []:
            cells.append(
                {
                    "rowIndex": int(cell.get("rowIndex", 0) or 0),
                    "columnIndex": int(cell.get("columnIndex", 0) or 0),
                    "rowSpan": max(1, int(cell.get("rowSpan", 1) or 1)),
                    "columnSpan": max(1, int(cell.get("columnSpan", 1) or 1)),
                    "text": _cell_text(cell),
                }
            )
        normalized.append({"cells": cells})
    return normalized


def clova_tables_to_html(tables: list[dict[str, Any]]) -> list[str]:
    """Render CLOVA's cell grid as `<table>` HTML for TEDS comparison.

    General OCR returns a flat grid with no header concept, so every cell
    becomes a `<td>` inside a single `<tbody>` — CLOVA cannot express `<th>` /
    `<thead>` and must not be scored as if it had tried and failed. The
    header-agnostic TEDS variant is what makes that comparison fair.

    Accepts either the raw `tables` array or the output of `normalize_tables`.
    """
    htmls = []
    for table in tables:
        by_row: dict[int, list[tuple[int, dict[str, Any]]]] = {}
        for cell in table.get("cells") or []:
            text = cell["text"] if "text" in cell else _cell_text(cell)
            by_row.setdefault(int(cell.get("rowIndex", 0) or 0), []).append(
                (
                    int(cell.get("columnIndex", 0) or 0),
                    {
                        "text": text,
                        "rowspan": max(1, int(cell.get("rowSpan", 1) or 1)),
                        "colspan": max(1, int(cell.get("columnSpan", 1) or 1)),
                    },
                )
            )

        rows = []
        for row_index in sorted(by_row):
            cells = []
            for _, cell in sorted(by_row[row_index], key=lambda item: item[0]):
                attrs = ""
                if cell["rowspan"] > 1:
                    attrs += f" rowspan=\"{cell['rowspan']}\""
                if cell["colspan"] > 1:
                    attrs += f" colspan=\"{cell['colspan']}\""
                cells.append(f"<td{attrs}>{escape(cell['text'])}</td>")
            rows.append("<tr>" + "".join(cells) + "</tr>")
        htmls.append("<table><tbody>" + "".join(rows) + "</tbody></table>")
    return htmls


def _table_texts(tables: list[dict[str, Any]]) -> list[str]:
    """Flatten table cell text, row by row."""
    rows: list[str] = []
    for table in tables:
        by_row: dict[int, list[tuple[int, str]]] = {}
        for cell in table.get("cells") or []:
            text = _cell_text(cell)
            if not text:
                continue
            by_row.setdefault(cell.get("rowIndex", 0), []).append(
                (cell.get("columnIndex", 0), text)
            )
        for row_index in sorted(by_row):
            cells = [text for _, text in sorted(by_row[row_index])]
            rows.append("\t".join(cells))
    return rows


def parse_response(payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Extract reassembled text and usage from a General OCR response."""
    images = payload.get("images") or []
    if not images:
        raise ValueError("CLOVA response contained no images[]")

    image = images[0]
    infer_result = image.get("inferResult")
    if infer_result != "SUCCESS":
        raise ValueError(
            f"CLOVA inferResult={infer_result!r}: {image.get('message')!r}"
        )

    fields = image.get("fields") or []
    tables = image.get("tables") or []
    text = reassemble_fields(fields)

    # With table detection on, cell text may live only in `tables`. Append the
    # rows the field pass did not already cover, so the two modes are not
    # scored on accidentally different content.
    if tables:
        seen = set(text.split())
        extra = [row for row in _table_texts(tables) if not set(row.split()) <= seen]
        if extra:
            text = "\n".join(filter(None, [text, *extra]))

    usage = {
        "requests": 1,
        "field_count": len(fields),
        "table_count": len(tables),
        "infer_result": infer_result,
        "uid": image.get("uid"),
        # Kept so the HTML rendering can be corrected and re-derived later
        # without re-paying for the call. `table_htmls` is the derived form.
        "tables_normalized": normalize_tables(tables),
    }
    return text, usage


def extract_table_htmls(payload: dict[str, Any]) -> list[str]:
    images = payload.get("images") or []
    if not images:
        return []
    return clova_tables_to_html(images[0].get("tables") or [])


class ClovaClient:
    def __init__(
        self,
        engine_config_id: str,
        secret: str,
        invoke_url: str,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.engine_config_id = engine_config_id
        self.cfg = config.ENGINE_CONFIGS[engine_config_id]
        self.secret = secret
        self.invoke_url = invoke_url
        self.timeout = timeout

    def build_request(self, image_path: Path, sample_id: str) -> dict[str, Any]:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        return {
            "version": "V2",
            "requestId": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),
            "lang": "ko",
            "enableTableDetection": bool(self.cfg["enable_table_detection"]),
            "images": [{"format": "jpg", "name": sample_id, "data": encoded}],
        }

    def transcribe(self, image_path: Path, sample_id: str) -> EngineResult:
        result = EngineResult(engine_config_id=self.engine_config_id, sample_id=sample_id)
        started = time.monotonic()
        try:
            response = requests.post(
                self.invoke_url,
                headers={
                    "X-OCR-SECRET": self.secret,
                    "Content-Type": "application/json",
                },
                json=self.build_request(image_path, sample_id),
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
