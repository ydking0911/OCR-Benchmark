"""Shared constants for the 3-engine OCR benchmark.

Ground-truth / manifest constants follow the design in
`.omc/plans/ralplan-claude-vision-contract-ocr-benchmark.md` (Step 2) so that
both benchmarks produce interchangeable `sample_id`s and manifests.
"""

from __future__ import annotations

import hashlib
import unicodedata
from typing import Any

# --- Rendering -------------------------------------------------------------

# Long edge in pixels for the primary render. 2576px is the high-resolution
# vision ceiling on Claude Sonnet 5 / Opus 4.7+; sending larger buys nothing.
RENDER_LONG_EDGE_PX = 2576
RENDER_JPEG_QUALITY = 90

# --- Ground-truth validity gate --------------------------------------------

# Page-level flag thresholds (loud warning + `low_text: true`, never an abort).
PAGE_LOW_TEXT_HANGUL_RATIO = 0.15
PAGE_LOW_TEXT_MIN_NONSPACE_CHARS = 20

# Corpus-level abort thresholds. Deliberately different values from the
# page-level ones: these detect a whole-extractor failure (the pdftotext
# signature), not a legitimately sparse page.
CORPUS_HANGUL_RATIO_MIN = 0.3
CORPUS_LOW_TEXT_ABORT_N = 5

# --- Document slugs --------------------------------------------------------

# NFC-normalized, whitespace-stripped PDF stem -> stable ASCII slug.
# Unmapped files fall back to sha1(stem)[:10], so adding a PDF needs no code
# change. The three 비밀유지* stems get suffixed slugs because their common
# prefix makes collision most likely here.
DOC_SLUG_MAP: dict[str, str] = {
    "경업금지약정서_퇴직자": "gyeongeop",
    "비밀유지계약서": "bimil_gyeyak",
    "비밀유지서약서_입사자": "bimil_seoyak_ipsa",
    "비밀유지서약서_재직자": "bimil_seoyak_jaejik",
    "업무협약서": "eopmu",
    "지출결의서": "jichul",
    "프랜차이즈계약서": "franchise",
}


def normalize_stem(stem: str) -> str:
    """NFC-normalize and strip a PDF filename stem.

    Strip matters: one corpus file is `프랜차이즈계약서 .pdf` (trailing space).
    """
    return unicodedata.normalize("NFC", stem).strip()


def doc_slug(stem: str) -> str:
    normalized = normalize_stem(stem)
    if normalized in DOC_SLUG_MAP:
        return DOC_SLUG_MAP[normalized]
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]


def sample_id(slug: str, page_index: int) -> str:
    """`{doc_slug}_p{NN}` with a 1-based, zero-padded page number."""
    return f"{slug}_p{page_index:02d}"


# --- Pricing ---------------------------------------------------------------

# Upstage Document Parse. Confirmed on the public pricing page; prices exclude
# 10% VAT.
UPSTAGE_PRICING = {
    "standard": {"usd_per_page": 0.01},
    "enhanced": {"usd_per_page": 0.03},
    "source_url": "https://www.upstage.ai/pricing",
    "retrieved_at": "2026-08-11",
    "notes": "VAT (10%) excluded. Document OCR (not benchmarked here) is $0.0015/page.",
}

# Naver CLOVA OCR General API.
#
# R1 resolved: confirmed directly from the NCP console (Premium plan, General
# OCR) on 2026-08-11. `krw_per_request` is the base 글자 추출 charge, which
# applies to every General OCR call regardless of `enableTableDetection`.
# `table_krw_per_request` is billed *in addition* when table detection is on
# (compute_cost() below sums the two), matching the console's separate 글자
# 추출 / 표 추출 line items. 3 + 22 = 25 KRW, which matches the ~25 KRW/request
# figure the user had already seen used elsewhere for table extraction.
#
# Not a public pricing page — self-reported from the user's own NCP console,
# so there is no retrievable source_url. VAT treatment is not stated in the
# console table; treated as-is (VAT status unconfirmed, unlike Upstage's
# explicitly VAT-excluded figures).
CLOVA_PRICING: dict[str, Any] = {
    "krw_per_request": 3,
    "table_krw_per_request": 22,
    "source_url": None,
    "retrieved_at": "2026-08-11",
    "notes": (
        "NCP 콘솔 프리미엄 플랜 / General OCR 실측(사용자 확인). 무료 제공: 글자 100건/월, "
        "표 100회/월 — 이 벤치마크의 1만 페이지 환산 비용은 그 free tier를 초과하는 대량 "
        "사용 기준의 한계비용이다. VAT 포함 여부는 콘솔 표기에 없어 미확인."
    ),
}

# Claude Sonnet 5, USD per million tokens. The introductory rate is in effect
# through 2026-08-31; the list rate applies after. Both are recorded so the
# report can show the post-expiry sensitivity.
CLAUDE_PRICING = {
    "claude-sonnet-5": {
        "input": 2.00,
        "output": 10.00,
        "cache_creation_input": 2.50,
        "cache_read_input": 0.20,
    },
    "pricing_as_of": "2026-08-11",
    "pricing_expires_on": "2026-08-31",
    "source_url": "https://platform.claude.com/docs/en/about-claude/models/overview",
    "retrieved_at": "2026-08-11",
    "notes": "Introductory pricing through 2026-08-31.",
}

CLAUDE_PRICING_POST_EXPIRY = {
    "claude-sonnet-5": {
        "input": 3.00,
        "output": 15.00,
        "cache_creation_input": 3.75,
        "cache_read_input": 0.30,
    },
    "effective_from": "2026-09-01",
    "source_url": "https://platform.claude.com/docs/en/about-claude/models/overview",
    "retrieved_at": "2026-08-11",
}

# Used only to render a single-currency column in the report. Not a measured
# cost — the authoritative per-engine figures stay in their native currency.
USD_KRW_RATE = 1380.0
USD_KRW_RATE_AS_OF = "2026-08-11"

# --- Engine configurations -------------------------------------------------

CLAUDE_MODEL = "claude-sonnet-5"
CLAUDE_MAX_TOKENS = 32000
CLAUDE_EFFORT = "low"
CLAUDE_PROMPT = (
    "이 계약서 페이지 이미지의 전체 텍스트를 처음부터 끝까지 정확히 그대로 "
    "전사하라. 요약하거나 해석하지 말고, 원문에 있는 문자만 읽는 순서대로 "
    "옮겨 적어라. 설명이나 머리말 없이 전사 결과만 출력하라."
)

ENGINE_CONFIGS: dict[str, dict[str, Any]] = {
    "upstage_standard": {
        "engine": "upstage",
        "label": "Upstage Document Parse — Standard",
        "mode": "standard",
        "model": "document-parse",
        "currency": "USD",
    },
    "upstage_enhanced": {
        "engine": "upstage",
        "label": "Upstage Document Parse — Enhanced",
        "mode": "enhanced",
        "model": "document-parse",
        "currency": "USD",
    },
    "clova_text": {
        "engine": "clova",
        "label": "Naver CLOVA General OCR — 문자 인식만",
        "enable_table_detection": False,
        "currency": "KRW",
    },
    "clova_table": {
        "engine": "clova",
        "label": "Naver CLOVA General OCR — 문자 인식 + 표 추출",
        "enable_table_detection": True,
        "currency": "KRW",
    },
    "claude_sonnet": {
        "engine": "claude",
        "label": "Claude Sonnet 5 (고해상도)",
        "model": CLAUDE_MODEL,
        "currency": "USD",
    },
}

ENGINE_FAMILIES = {"upstage", "clova", "claude"}

# --- Static feature checklist (declared capability, not measured) ----------

FEATURE_CHECKLIST: dict[str, dict[str, str]] = {
    "upstage_standard": {"bbox": "○", "clause_hierarchy": "○", "checkbox": "△", "deterministic": "○"},
    "upstage_enhanced": {"bbox": "○", "clause_hierarchy": "○", "checkbox": "○", "deterministic": "○"},
    "clova_text": {"bbox": "○", "clause_hierarchy": "✕", "checkbox": "✕", "deterministic": "○"},
    "clova_table": {"bbox": "○", "clause_hierarchy": "△(표 구조만)", "checkbox": "✕(Template 전용)", "deterministic": "○"},
    "claude_sonnet": {"bbox": "△(근사값)", "clause_hierarchy": "△(텍스트로만)", "checkbox": "△", "deterministic": "✕"},
}


def compute_cost(engine_config_id: str, usage_raw: dict[str, Any] | None) -> dict[str, Any]:
    """Convert an engine's raw usage into cost.

    Returns `{cost_usd, cost_krw, cost_confirmed}`. `cost_confirmed` is False
    when the unit price is not publicly verified (Clova, per R1); both cost
    fields are None in that case so nothing downstream can mistake an estimate
    for a measurement.
    """
    cfg = ENGINE_CONFIGS[engine_config_id]
    engine = cfg["engine"]
    usage = usage_raw or {}

    if engine == "upstage":
        pages = usage.get("pages") or 1
        usd = pages * UPSTAGE_PRICING[cfg["mode"]]["usd_per_page"]
        return {"cost_usd": usd, "cost_krw": usd * USD_KRW_RATE, "cost_confirmed": True}

    if engine == "clova":
        unit = CLOVA_PRICING["krw_per_request"]
        if unit is None:
            return {"cost_usd": None, "cost_krw": None, "cost_confirmed": False}
        krw = unit
        if cfg["enable_table_detection"] and CLOVA_PRICING["table_krw_per_request"]:
            krw += CLOVA_PRICING["table_krw_per_request"]
        return {"cost_usd": krw / USD_KRW_RATE, "cost_krw": krw, "cost_confirmed": True}

    if engine == "claude":
        rates = CLAUDE_PRICING[cfg["model"]]
        usd = (
            usage.get("input_tokens", 0) * rates["input"]
            + usage.get("output_tokens", 0) * rates["output"]
            + usage.get("cache_creation_input_tokens", 0) * rates["cache_creation_input"]
            + usage.get("cache_read_input_tokens", 0) * rates["cache_read_input"]
        ) / 1_000_000
        return {"cost_usd": usd, "cost_krw": usd * USD_KRW_RATE, "cost_confirmed": True}

    raise ValueError(f"unknown engine for config {engine_config_id!r}")
