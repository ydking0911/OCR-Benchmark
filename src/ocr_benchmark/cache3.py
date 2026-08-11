"""Fingerprinted response cache — prevents paying twice for the same page.

Fingerprint = sha256(engine_config_id + image_sha256). A cached entry is reused
only when the fingerprint matches exactly; a mismatch logs which field changed
and misses, so a re-render or a config change can never silently serve stale
results.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from .engines.base import EngineResult

log = logging.getLogger(__name__)


def fingerprint(engine_config_id: str, image_sha256: str) -> str:
    return hashlib.sha256(f"{engine_config_id}{image_sha256}".encode("utf-8")).hexdigest()


def cache_path(root: Path, engine_config_id: str, sample_id: str) -> Path:
    return root / engine_config_id / f"{sample_id}.json"


def load(
    root: Path, engine_config_id: str, sample_id: str, image_sha256: str
) -> EngineResult | None:
    path = cache_path(root, engine_config_id, sample_id)
    if not path.exists():
        return None

    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = fingerprint(engine_config_id, image_sha256)
    actual = payload.get("fingerprint")
    if actual != expected:
        log.warning(
            "cache MISS %s/%s: fingerprint changed (cached image_sha256=%s, current=%s)",
            engine_config_id,
            sample_id,
            payload.get("image_sha256"),
            image_sha256,
        )
        return None

    return EngineResult.from_dict(payload["result"])


def store(root: Path, result: EngineResult, image_sha256: str) -> Path:
    path = cache_path(root, result.engine_config_id, result.sample_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "fingerprint": fingerprint(result.engine_config_id, image_sha256),
        "image_sha256": image_sha256,
        "result": result.to_dict(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
