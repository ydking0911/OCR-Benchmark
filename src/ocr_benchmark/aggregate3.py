"""Per-page / per-document / overall aggregation with cost.

No pass/fail gate and no ranking. This benchmark reports raw accuracy and real
cost and leaves the judgement to a human — a deliberate design decision, not an
omission.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from . import config, scoring
from .engines.base import EngineResult

# Scale used to make per-page prices legible; matches the reference table the
# comparison is meant to slot into.
COST_SCALE_PAGES = 10_000


def _mean(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def score_page(result: EngineResult, reference_text: str) -> dict[str, Any]:
    metrics = (
        scoring.floor_score(reference_text)
        if not result.ok
        else scoring.score(reference_text, result.raw_text)
    )

    # Cost is recomputed from `usage_raw` against the *current* `config`
    # pricing rather than trusted from the cached `EngineResult`, so that
    # correcting a price in config.py (e.g. once Clova's console rate is
    # confirmed) and re-running off the cache reflects the fix immediately,
    # without needing to invalidate or re-pay for already-cached pages.
    # `usage_raw` is the immutable provenance; the derived cost is not.
    # A failed call was never billed (clients only call `apply_cost` on
    # success), so its cost stays at the EngineResult default (None/False)
    # rather than being recomputed from an empty `usage_raw`.
    if result.ok:
        cost = config.compute_cost(result.engine_config_id, result.usage_raw)
        cost_usd, cost_krw, cost_confirmed = (
            cost["cost_usd"],
            cost["cost_krw"],
            cost["cost_confirmed"],
        )
    else:
        cost_usd, cost_krw, cost_confirmed = (
            result.cost_usd,
            result.cost_krw,
            result.cost_confirmed,
        )

    return {
        "sample_id": result.sample_id,
        "engine_config_id": result.engine_config_id,
        "error": result.error,
        "is_failure": not result.ok,
        "latency_ms": result.latency_ms,
        "cost_usd": cost_usd,
        "cost_krw": cost_krw,
        "cost_confirmed": cost_confirmed,
        **metrics,
    }


def aggregate(
    results: list[EngineResult],
    manifest_entries: list[dict[str, Any]],
    ground_truth_dir: Path,
) -> dict[str, Any]:
    """Aggregate results for every engine config present in `results`."""
    by_sample = {entry["sample_id"]: entry for entry in manifest_entries}
    reference_cache: dict[str, str] = {}

    def reference_for(sample_id: str) -> str:
        if sample_id not in reference_cache:
            path = Path(by_sample[sample_id]["ground_truth_path"])
            if not path.is_absolute() and not path.exists():
                path = ground_truth_dir / f"{sample_id}.txt"
            reference_cache[sample_id] = path.read_text(encoding="utf-8")
        return reference_cache[sample_id]

    pages: list[dict[str, Any]] = []
    for result in results:
        if result.sample_id not in by_sample:
            raise KeyError(f"{result.sample_id} is not in the manifest")
        pages.append(score_page(result, reference_for(result.sample_id)))

    engines: dict[str, Any] = {}
    for engine_config_id in sorted({p["engine_config_id"] for p in pages}):
        engine_pages = [p for p in pages if p["engine_config_id"] == engine_config_id]
        engines[engine_config_id] = _summarize_engine(engine_config_id, engine_pages, by_sample)

    return {
        "n_pages": len({p["sample_id"] for p in pages}),
        "n_docs": len({by_sample[p["sample_id"]]["doc_slug"] for p in pages}),
        "pages": pages,
        "engines": engines,
        "cost_scale_pages": COST_SCALE_PAGES,
        "pricing": {
            "upstage": config.UPSTAGE_PRICING,
            "clova": config.CLOVA_PRICING,
            "claude": config.CLAUDE_PRICING,
            "claude_post_expiry": config.CLAUDE_PRICING_POST_EXPIRY,
            "usd_krw_rate": config.USD_KRW_RATE,
            "usd_krw_rate_as_of": config.USD_KRW_RATE_AS_OF,
        },
    }


def _summarize_engine(
    engine_config_id: str,
    engine_pages: list[dict[str, Any]],
    by_sample: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cers = [p["cer"] for p in engine_pages if p["cer"] is not None]
    wers = [p["wer"] for p in engine_pages if p["wer"] is not None]
    sims = [p["similarity_pct"] for p in engine_pages]

    # Two-stage: average within a document first, then across documents, so the
    # 48-page franchise contract does not dominate the headline number.
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for page in engine_pages:
        by_doc.setdefault(by_sample[page["sample_id"]]["doc_slug"], []).append(page)

    documents = {}
    for doc_slug, doc_pages in sorted(by_doc.items()):
        doc_cers = [p["cer"] for p in doc_pages if p["cer"] is not None]
        doc_wers = [p["wer"] for p in doc_pages if p["wer"] is not None]
        documents[doc_slug] = {
            "n_pages": len(doc_pages),
            "cer": _mean(doc_cers),
            "wer": _mean(doc_wers),
            "similarity_pct": _mean([p["similarity_pct"] for p in doc_pages]),
            "failures": sum(1 for p in doc_pages if p["is_failure"]),
        }

    confirmed = all(p["cost_confirmed"] for p in engine_pages)
    total_usd = (
        sum(p["cost_usd"] or 0.0 for p in engine_pages) if confirmed else None
    )
    total_krw = (
        sum(p["cost_krw"] or 0.0 for p in engine_pages) if confirmed else None
    )
    per_page_usd = total_usd / len(engine_pages) if total_usd is not None else None

    summary = {
        "engine_config_id": engine_config_id,
        "label": config.ENGINE_CONFIGS[engine_config_id]["label"],
        "n_pages": len(engine_pages),
        "failures": sum(1 for p in engine_pages if p["is_failure"]),
        "page_mean": {
            "cer": _mean(cers),
            "wer": _mean(wers),
            "similarity_pct": _mean(sims),
        },
        "doc_equal_mean": {
            "cer": _mean([d["cer"] for d in documents.values() if d["cer"] is not None]),
            "wer": _mean([d["wer"] for d in documents.values() if d["wer"] is not None]),
            "similarity_pct": _mean([d["similarity_pct"] for d in documents.values()]),
        },
        "documents": documents,
        "latency_ms_mean": _mean([float(p["latency_ms"]) for p in engine_pages]),
        "cost": {
            "confirmed": confirmed,
            "total_usd": total_usd,
            "total_krw": total_krw,
            "per_page_usd": per_page_usd,
            "per_10k_pages_usd": per_page_usd * COST_SCALE_PAGES
            if per_page_usd is not None
            else None,
        },
    }

    # Reference indicator only. Deliberately not presented as a rank: dividing
    # by price makes the cheapest engine win by construction, which is exactly
    # the pre-determined ordering this benchmark refuses to publish.
    similarity = summary["page_mean"]["similarity_pct"]
    if per_page_usd and similarity:
        summary["cost_per_1pct_similarity_usd"] = per_page_usd / similarity
    else:
        summary["cost_per_1pct_similarity_usd"] = None

    return summary
