"""Per-page / per-document / overall aggregation with cost.

No pass/fail gate and no ranking. This benchmark reports raw accuracy and real
cost and leaves the judgement to a human — a deliberate design decision, not an
omission.
"""

from __future__ import annotations

import statistics
from pathlib import Path
from typing import Any

from . import config, scoring, table_scoring
from .engines.base import EngineResult
from .table_ground_truth import TABLE_GROUND_TRUTH

# Scale used to make per-page prices legible; matches the reference table the
# comparison is meant to slot into.
COST_SCALE_PAGES = 10_000

# One real table split across a physical page boundary. Ground truth is what is
# visible on each page alone (see `table_ground_truth`'s docstring), so no
# single-page call can score well here. Reported separately rather than folded
# into the headline mean, where it would read as an engine defect.
KNOWN_HARD_TABLE_SAMPLE_IDS = ("franchise_p12", "franchise_p13")


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


def score_table_page(result: EngineResult) -> dict[str, Any]:
    """TEDS-score one page's tables against the curated ground truth.

    A failed call is floor-scored (TEDS 0) rather than dropped, for the same
    reason failed text pages are: an engine must not improve its average by
    failing on the hard pages.
    """
    ground_truth = TABLE_GROUND_TRUTH[result.sample_id]
    metrics = (
        table_scoring.score_tables(ground_truth, [])
        if not result.ok
        else table_scoring.score_tables(ground_truth, result.table_htmls)
    )

    if result.ok:
        cost = config.compute_cost(result.engine_config_id, result.usage_raw)
    else:
        cost = {
            "cost_usd": result.cost_usd,
            "cost_krw": result.cost_krw,
            "cost_confirmed": result.cost_confirmed,
        }

    return {
        "sample_id": result.sample_id,
        "engine_config_id": result.engine_config_id,
        "error": result.error,
        "is_failure": not result.ok,
        "known_hard": result.sample_id in KNOWN_HARD_TABLE_SAMPLE_IDS,
        "latency_ms": result.latency_ms,
        **cost,
        **metrics,
    }


def aggregate_tables(table_results: list[EngineResult]) -> dict[str, Any]:
    """Aggregate table-structure accuracy over the curated table pages.

    Scope is deliberately narrower than the text benchmark: only the pages in
    `TABLE_GROUND_TRUTH` and only configs that can emit table structure at all.
    Anything else in `table_results` is ignored rather than rejected, so the
    caller can hand over a whole cache without pre-filtering.

    No gate and no ranking here either — same principle as the text pipeline.
    """
    in_scope = [
        r
        for r in table_results
        if r.sample_id in TABLE_GROUND_TRUTH
        and r.engine_config_id in config.TABLE_CAPABLE_ENGINE_CONFIGS
    ]
    pages = [score_table_page(result) for result in in_scope]

    engines: dict[str, Any] = {}
    for engine_config_id in sorted({p["engine_config_id"] for p in pages}):
        engine_pages = [p for p in pages if p["engine_config_id"] == engine_config_id]
        engines[engine_config_id] = _summarize_table_engine(engine_config_id, engine_pages)

    return {
        "n_pages": len({p["sample_id"] for p in pages}),
        "n_ground_truth_pages": len(TABLE_GROUND_TRUTH),
        "known_hard_sample_ids": list(KNOWN_HARD_TABLE_SAMPLE_IDS),
        "scored_sample_ids": sorted({p["sample_id"] for p in pages}),
        "pages": pages,
        "engines": engines,
    }


def _summarize_table_engine(
    engine_config_id: str, engine_pages: list[dict[str, Any]]
) -> dict[str, Any]:
    normal = [p for p in engine_pages if not p["known_hard"]]
    confirmed = all(p["cost_confirmed"] for p in engine_pages)

    return {
        "engine_config_id": engine_config_id,
        "label": config.engine_config(engine_config_id)["label"],
        "n_pages": len(engine_pages),
        "failures": sum(1 for p in engine_pages if p["is_failure"]),
        "pages_with_no_prediction": sum(1 for p in engine_pages if p["no_prediction"]),
        "missing_tables": sum(p["missing_tables"] for p in engine_pages),
        "teds_mean": _mean([p["teds"] for p in engine_pages]),
        "teds_header_agnostic_mean": _mean(
            [p["teds_header_agnostic"] for p in engine_pages]
        ),
        "teds_mean_excluding_known_hard": _mean([p["teds"] for p in normal]),
        "n_pages_excluding_known_hard": len(normal),
        "latency_ms_mean": _mean([float(p["latency_ms"]) for p in engine_pages]),
        "cost": {
            "confirmed": confirmed,
            "total_usd": (
                sum(p["cost_usd"] or 0.0 for p in engine_pages) if confirmed else None
            ),
            "total_krw": (
                sum(p["cost_krw"] or 0.0 for p in engine_pages) if confirmed else None
            ),
        },
        "pages": sorted(engine_pages, key=lambda p: p["sample_id"]),
    }


def aggregate(
    results: list[EngineResult],
    manifest_entries: list[dict[str, Any]],
    ground_truth_dir: Path,
    table_results: list[EngineResult] | None = None,
) -> dict[str, Any]:
    """Aggregate results for every engine config present in `results`.

    `table_results` is optional and independent: the table-structure section
    only appears when table extraction has actually been run, so a text-only
    run produces exactly the report it always did.
    """
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

    aggregated = {
        "n_pages": len({p["sample_id"] for p in pages}),
        "n_docs": len({by_sample[p["sample_id"]]["doc_slug"] for p in pages}),
        "pages": pages,
        "engines": engines,
        "cost_scale_pages": COST_SCALE_PAGES,
        "pricing": {
            "upstage": config.UPSTAGE_PRICING,
            "clova": config.CLOVA_PRICING,
            "mistral": config.MISTRAL_PRICING,
            "claude": config.CLAUDE_PRICING,
            "claude_post_expiry": config.CLAUDE_PRICING_POST_EXPIRY,
            "usd_krw_rate": config.USD_KRW_RATE,
            "usd_krw_rate_as_of": config.USD_KRW_RATE_AS_OF,
        },
    }

    if table_results:
        aggregated["tables"] = aggregate_tables(table_results)
    return aggregated


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
        # doc_title carries the real Korean document name through to the
        # report so readers are not left decoding ASCII doc_slugs
        # (gyeongeop, bimil_seoyak_jaejik, ...) by hand.
        doc_title = by_sample[doc_pages[0]["sample_id"]].get("doc_title") or doc_slug
        documents[doc_slug] = {
            "doc_title": doc_title,
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
