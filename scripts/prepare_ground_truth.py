"""Extract ground-truth text, render page images, and write the manifest.

Reads only local PDFs — no API calls, no cost.

    py scripts/prepare_ground_truth.py
    py scripts/prepare_ground_truth.py --accept-low-text jichul_p01,eopmu_p02
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from ocr_benchmark import ground_truth  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path, default=REPO_ROOT / "samples" / "pdfs")
    parser.add_argument("--images-dir", type=Path, default=REPO_ROOT / "samples" / "images")
    parser.add_argument(
        "--ground-truth-dir", type=Path, default=REPO_ROOT / "samples" / "ground_truth"
    )
    parser.add_argument(
        "--manifest", type=Path, default=REPO_ROOT / "samples" / "manifest.json"
    )
    parser.add_argument(
        "--accept-low-text",
        default="",
        help="Comma-separated sample_ids to approve as legitimately sparse.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    approved = {s.strip() for s in args.accept_low_text.split(",") if s.strip()}

    try:
        summary = ground_truth.prepare(
            args.pdf_dir, args.images_dir, args.ground_truth_dir, args.manifest, approved
        )
    except ground_truth.GroundTruthAbort as exc:
        print(f"ABORT: {exc}", file=sys.stderr)
        return 1

    print(f"docs={summary['n_docs']} pages={summary['n_pages']}")
    print(f"corpus hangul_ratio={summary['corpus_hangul_ratio']:.4f}")
    print(f"low_text pages: {summary['low_text_pages'] or 'none'}")
    print(f"manifest -> {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
