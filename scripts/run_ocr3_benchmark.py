"""Run the 3-engine OCR benchmark and generate the comparison report.

    py scripts/run_ocr3_benchmark.py --dry-run          # 3 pages, smoke test
    py scripts/run_ocr3_benchmark.py --engine upstage   # one engine family
    py scripts/run_ocr3_benchmark.py                    # full corpus

Every uncached page is a real, billed API call. `--dry-run` limits the run to
one page from each of the largest documents so a smoke test costs cents.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

from ocr_benchmark import aggregate3, cache3, config, ground_truth, report3  # noqa: E402
from ocr_benchmark.engines.base import EngineResult  # noqa: E402
from ocr_benchmark.engines.claude_client import ClaudeClient  # noqa: E402
from ocr_benchmark.engines.clova_client import ClovaClient  # noqa: E402
from ocr_benchmark.engines.upstage_client import UpstageClient  # noqa: E402

log = logging.getLogger("run_ocr3")

DRY_RUN_PAGES = 3


def select_engine_configs(selector: str) -> list[str]:
    if selector == "all":
        return list(config.ENGINE_CONFIGS)
    if selector in config.ENGINE_FAMILIES:
        return [
            cid for cid, cfg in config.ENGINE_CONFIGS.items() if cfg["engine"] == selector
        ]
    if selector in config.ENGINE_CONFIGS:
        return [selector]
    raise SystemExit(
        f"unknown --engine {selector!r}. Use 'all', one of "
        f"{sorted(config.ENGINE_FAMILIES)}, or a config id from "
        f"{sorted(config.ENGINE_CONFIGS)}."
    )


def select_pages(entries: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    """Round-robin across documents, largest document first.

    Descending page count guarantees the 48-page franchise contract is picked
    at N=1 — it is where reading-order and truncation risk concentrate, so a
    smoke test that skipped it would prove very little.
    """
    if limit is None:
        return entries

    by_doc: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_doc.setdefault(entry["doc_slug"], []).append(entry)

    order = sorted(
        by_doc, key=lambda slug: (-by_doc[slug][0]["page_count_in_doc"], slug)
    )
    selected: list[dict[str, Any]] = []
    depth = 0
    while len(selected) < limit:
        progressed = False
        for slug in order:
            if depth < len(by_doc[slug]):
                selected.append(by_doc[slug][depth])
                progressed = True
                if len(selected) == limit:
                    return selected
        if not progressed:
            break
        depth += 1
    return selected


def build_client(engine_config_id: str) -> Any:
    engine = config.ENGINE_CONFIGS[engine_config_id]["engine"]

    if engine == "upstage":
        key = os.environ.get("UPSTAGE_API_KEY")
        if not key:
            raise SystemExit("UPSTAGE_API_KEY is not set (see .env.example)")
        return UpstageClient(engine_config_id, key)

    if engine == "clova":
        secret = os.environ.get("NCP_CLOVA_OCR_SECRET")
        url = os.environ.get("NCP_CLOVA_OCR_INVOKE_URL")
        if not secret or not url:
            raise SystemExit(
                "NCP_CLOVA_OCR_SECRET and NCP_CLOVA_OCR_INVOKE_URL must both be set "
                "(see .env.example)"
            )
        return ClovaClient(engine_config_id, secret, url)

    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY is not set (see .env.example)")
    return ClaudeClient(engine_config_id, key)


def load_all_cached_results(
    entries: list[dict[str, Any]], cache_root: Path
) -> list[EngineResult]:
    """Load every cached result across all engine configs and the full manifest.

    Separate per-engine invocations (`--engine upstage`, then `--engine clova`,
    then `--engine claude_sonnet`, ...) each populate the cache but only
    computed results for the engine(s) they touched. Aggregating from the
    cache instead of from this invocation's `results` means the report always
    reflects everything measured so far, not just the last invocation.
    """
    results: list[EngineResult] = []
    for engine_config_id in config.ENGINE_CONFIGS:
        for entry in entries:
            cached = cache3.load(
                cache_root, engine_config_id, entry["sample_id"], entry["image_sha256"]
            )
            if cached is not None:
                results.append(cached)
    return results


def run_engine(
    engine_config_id: str,
    entries: list[dict[str, Any]],
    cache_root: Path,
    force: bool,
) -> list[EngineResult]:
    client = None
    results: list[EngineResult] = []

    for index, entry in enumerate(entries, start=1):
        sample_id = entry["sample_id"]
        image_sha256 = entry["image_sha256"]

        if not force:
            cached = cache3.load(cache_root, engine_config_id, sample_id, image_sha256)
            if cached is not None:
                log.info("[%s] %s (%d/%d) cache HIT", engine_config_id, sample_id, index, len(entries))
                results.append(cached)
                continue

        if client is None:
            client = build_client(engine_config_id)

        log.info("[%s] %s (%d/%d) calling API", engine_config_id, sample_id, index, len(entries))
        result = client.transcribe(Path(entry["image_path"]), sample_id)
        cache3.store(cache_root, result, image_sha256)
        if not result.ok:
            log.warning("[%s] %s FAILED: %s", engine_config_id, sample_id, result.error)
        results.append(result)

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", default="all", help="all | upstage | clova | claude | <config_id>")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=f"Limit to {DRY_RUN_PAGES} pages from different documents (smoke test).",
    )
    parser.add_argument("--force", action="store_true", help="Ignore cached responses and re-pay.")
    parser.add_argument("--manifest", type=Path, default=REPO_ROOT / "samples" / "manifest.json")
    parser.add_argument(
        "--ground-truth-dir", type=Path, default=REPO_ROOT / "samples" / "ground_truth"
    )
    parser.add_argument("--cache-root", type=Path, default=REPO_ROOT / "results" / "raw3")
    parser.add_argument(
        "--report", type=Path, default=REPO_ROOT / "results" / "report3" / "comparison.md"
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_dotenv(REPO_ROOT / ".env")

    if not args.manifest.exists():
        raise SystemExit(
            f"{args.manifest} not found. Run `py scripts/prepare_ground_truth.py` first."
        )

    entries = ground_truth.load_manifest(args.manifest)
    selected = select_pages(entries, DRY_RUN_PAGES if args.dry_run else None)
    engine_ids = select_engine_configs(args.engine)

    log.info(
        "%d page(s) x %d engine config(s) = %d call(s) before cache",
        len(selected),
        len(engine_ids),
        len(selected) * len(engine_ids),
    )

    for engine_config_id in engine_ids:
        run_engine(engine_config_id, selected, args.cache_root, args.force)

    # Aggregate from the full cache, not just this invocation's `results`, so
    # a report built after running engines separately shows all of them.
    all_results = load_all_cached_results(entries, args.cache_root)
    aggregated = aggregate3.aggregate(all_results, entries, args.ground_truth_dir)
    note = (
        f"이번 실행: --dry-run, engine={args.engine} ({len(selected)}페이지) — "
        "다른 엔진의 수치는 이전 실행 결과일 수 있음"
        if args.dry_run
        else ""
    )
    report3.write(aggregated, args.report, note)

    print(f"\nreport -> {args.report}")
    for engine_config_id, summary in aggregated["engines"].items():
        mean = summary["page_mean"]
        cost = summary["cost"]
        cost_text = "미확정" if not cost["confirmed"] else f"${cost['total_usd']:.4f}"
        print(
            f"  {engine_config_id:18s} similarity={mean['similarity_pct'] or 0:6.2f}% "
            f"cer={mean['cer'] if mean['cer'] is not None else float('nan'):.4f} "
            f"cost={cost_text} failures={summary['failures']}/{summary['n_pages']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
