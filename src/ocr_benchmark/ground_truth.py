"""PyMuPDF ground-truth extraction, page rendering, and manifest building.

Follows Step 2 of `.omc/plans/ralplan-claude-vision-contract-ocr-benchmark.md`:
`sample_id = {doc_slug}_p{NN}`, a hangul-ratio validity gate that aborts at the
corpus level but only flags at the page level, and a deterministic manifest
ordered by `(doc_slug, page_index)`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pymupdf

from . import config

log = logging.getLogger(__name__)

HANGUL_RE = re.compile(r"[가-힣]")
WHITESPACE_RE = re.compile(r"\s")


class GroundTruthAbort(RuntimeError):
    """Corpus-level validity failure — the extractor itself is suspect."""


@dataclass
class PageRecord:
    sample_id: str
    doc_slug: str
    doc_title: str
    page_index: int
    page_count_in_doc: int
    text: str
    hangul_ratio: float
    nonspace_char_count: int
    low_text: bool
    accept_low_text: bool = False
    image_path: str = ""
    image_sha256: str = ""
    render_px: tuple[int, int] = (0, 0)
    ground_truth_path: str = ""

    def to_manifest_entry(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "doc_slug": self.doc_slug,
            "doc_title": self.doc_title,
            "page_index": self.page_index,
            "page_count_in_doc": self.page_count_in_doc,
            "image_path": self.image_path,
            "image_sha256": self.image_sha256,
            "render_px": list(self.render_px),
            "ground_truth_path": self.ground_truth_path,
            "hangul_ratio": round(self.hangul_ratio, 6),
            "nonspace_char_count": self.nonspace_char_count,
            "low_text": self.low_text,
            "accept_low_text": self.accept_low_text,
        }


def hangul_ratio(text: str) -> tuple[float, int]:
    """Return `(ratio, nonspace_char_count)`.

    The denominator excludes whitespace: `page.get_text()` emits heavy padding
    on table layouts, and counting it would fail a correct extraction purely on
    whitespace share.
    """
    nonspace = len(WHITESPACE_RE.sub("", text))
    if nonspace == 0:
        return 0.0, 0
    return len(HANGUL_RE.findall(text)) / nonspace, nonspace


def is_low_text(ratio: float, nonspace: int) -> bool:
    return (
        ratio < config.PAGE_LOW_TEXT_HANGUL_RATIO
        or nonspace < config.PAGE_LOW_TEXT_MIN_NONSPACE_CHARS
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_page(page: pymupdf.Page, out_path: Path) -> tuple[int, int]:
    """Render one page to JPEG with its long edge at `RENDER_LONG_EDGE_PX`."""
    rect = page.rect
    zoom = config.RENDER_LONG_EDGE_PX / max(rect.width, rect.height)
    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out_path), output="jpg", jpg_quality=config.RENDER_JPEG_QUALITY)
    return pix.width, pix.height


def build_records(
    pdf_dir: Path,
    images_dir: Path,
    ground_truth_dir: Path,
    accept_low_text: set[str] | None = None,
) -> list[PageRecord]:
    """Extract text, render images, and produce per-page records.

    Aborts on a duplicate slug rather than silently overwriting the earlier
    document's pages.
    """
    accept_low_text = accept_low_text or set()
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        raise GroundTruthAbort(f"no PDFs found under {pdf_dir}")

    seen_slugs: dict[str, str] = {}
    records: list[PageRecord] = []

    for pdf_path in pdfs:
        stem = config.normalize_stem(pdf_path.stem)
        slug = config.doc_slug(pdf_path.stem)
        if slug in seen_slugs and seen_slugs[slug] != stem:
            raise GroundTruthAbort(
                f"duplicate doc_slug {slug!r}: {seen_slugs[slug]!r} and {stem!r}"
            )
        seen_slugs[slug] = stem

        with pymupdf.open(pdf_path) as doc:
            page_count = doc.page_count
            for index, page in enumerate(doc, start=1):
                sid = config.sample_id(slug, index)
                text = page.get_text()
                ratio, nonspace = hangul_ratio(text)
                low = is_low_text(ratio, nonspace)

                gt_path = ground_truth_dir / f"{sid}.txt"
                gt_path.parent.mkdir(parents=True, exist_ok=True)
                gt_path.write_text(text, encoding="utf-8")

                img_path = images_dir / f"{sid}.jpg"
                width, height = render_page(page, img_path)

                if low:
                    log.warning(
                        "LOW TEXT %s: hangul_ratio=%.3f nonspace=%d (flagged, not fatal)",
                        sid,
                        ratio,
                        nonspace,
                    )

                records.append(
                    PageRecord(
                        sample_id=sid,
                        doc_slug=slug,
                        doc_title=stem,
                        page_index=index,
                        page_count_in_doc=page_count,
                        text=text,
                        hangul_ratio=ratio,
                        nonspace_char_count=nonspace,
                        low_text=low,
                        accept_low_text=sid in accept_low_text,
                        image_path=str(img_path).replace("\\", "/"),
                        image_sha256=sha256_file(img_path),
                        render_px=(width, height),
                        ground_truth_path=str(gt_path).replace("\\", "/"),
                    )
                )

    records.sort(key=lambda r: (r.doc_slug, r.page_index))
    return records


def check_corpus_validity(records: list[PageRecord]) -> dict[str, Any]:
    """Corpus-level gate. Raises `GroundTruthAbort` on a whole-extractor failure.

    Two independent abort conditions:
      - corpus-wide hangul ratio below threshold (the pdftotext signature), which
        no per-page approval can clear; and
      - too many *unapproved* low-text pages. Approving pages via
        `--accept-low-text` provably reduces this counter, so enough approvals
        clear the abort.
    """
    total_text = "".join(r.text for r in records)
    corpus_ratio, corpus_nonspace = hangul_ratio(total_text)
    unapproved = [r.sample_id for r in records if r.low_text and not r.accept_low_text]

    summary = {
        "corpus_hangul_ratio": round(corpus_ratio, 6),
        "corpus_nonspace_char_count": corpus_nonspace,
        "low_text_pages": [r.sample_id for r in records if r.low_text],
        "unapproved_low_text_pages": unapproved,
        "n_pages": len(records),
        "n_docs": len({r.doc_slug for r in records}),
    }

    if corpus_ratio < config.CORPUS_HANGUL_RATIO_MIN:
        raise GroundTruthAbort(
            f"corpus hangul_ratio {corpus_ratio:.3f} < {config.CORPUS_HANGUL_RATIO_MIN}: "
            "the text extractor is probably dropping Hangul entirely. "
            "This is not clearable with --accept-low-text."
        )
    if len(unapproved) >= config.CORPUS_LOW_TEXT_ABORT_N:
        raise GroundTruthAbort(
            f"{len(unapproved)} unapproved low_text pages "
            f">= {config.CORPUS_LOW_TEXT_ABORT_N}: {', '.join(unapproved)}. "
            "Review them and re-run with --accept-low-text if they are legitimately sparse."
        )
    return summary


def write_manifest(records: list[PageRecord], manifest_path: Path, summary: dict[str, Any]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "render_long_edge_px": config.RENDER_LONG_EDGE_PX,
        "validity": summary,
        "entries": [r.to_manifest_entry() for r in records],
    }
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return payload["entries"]


def prepare(
    pdf_dir: Path,
    images_dir: Path,
    ground_truth_dir: Path,
    manifest_path: Path,
    accept_low_text: set[str] | None = None,
) -> dict[str, Any]:
    records = build_records(pdf_dir, images_dir, ground_truth_dir, accept_low_text)
    summary = check_corpus_validity(records)
    write_manifest(records, manifest_path, summary)
    return summary
