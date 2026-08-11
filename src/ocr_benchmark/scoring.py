"""CER / WER / similarity scoring against PyMuPDF ground truth.

Normalization is fixed here so both benchmarks in this repo produce comparable
numbers: NFKC, then whitespace collapsed to single spaces.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Any

import jiwer

WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    return WHITESPACE_RE.sub(" ", unicodedata.normalize("NFKC", text or "")).strip()


def similarity_pct(reference: str, hypothesis: str) -> float:
    if not reference and not hypothesis:
        return 100.0
    return difflib.SequenceMatcher(None, reference, hypothesis).ratio() * 100.0


def score(reference: str, hypothesis: str) -> dict[str, Any]:
    """Score one page.

    An empty hypothesis against a non-empty reference is a total miss
    (CER/WER 1.0, similarity 0). An empty reference cannot be scored as a rate,
    so the error rates are None — jiwer divides by reference length.
    """
    ref = normalize(reference)
    hyp = normalize(hypothesis)

    if not ref:
        return {
            "cer": None,
            "wer": None,
            "similarity_pct": similarity_pct(ref, hyp),
            "reference_empty": True,
            "ref_chars": 0,
            "hyp_chars": len(hyp),
        }

    return {
        "cer": jiwer.cer(ref, hyp),
        "wer": jiwer.wer(ref, hyp),
        "similarity_pct": similarity_pct(ref, hyp),
        "reference_empty": False,
        "ref_chars": len(ref),
        "hyp_chars": len(hyp),
    }


def floor_score(reference: str) -> dict[str, Any]:
    """Score assigned to a page whose engine call failed.

    Failures are floor-scored rather than dropped, so an engine cannot improve
    its average by failing on the hardest pages.
    """
    ref = normalize(reference)
    return {
        "cer": 1.0 if ref else None,
        "wer": 1.0 if ref else None,
        "similarity_pct": 0.0,
        "reference_empty": not ref,
        "ref_chars": len(ref),
        "hyp_chars": 0,
    }
