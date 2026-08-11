"""Common result schema and client protocol for the three OCR engines."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .. import config


@dataclass
class EngineResult:
    engine_config_id: str
    sample_id: str
    raw_text: str = ""
    # Structured `<table>` HTML, one string per detected table, in reading
    # order. Empty for engines/configs that were not asked for table structure.
    # Cached entries written before table scoring existed deserialize to [].
    table_htmls: list[str] = field(default_factory=list)
    usage_raw: dict[str, Any] = field(default_factory=dict)
    cost_usd: float | None = None
    cost_krw: float | None = None
    cost_confirmed: bool = False
    latency_ms: int = 0
    http_status: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "EngineResult":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in payload.items() if k in known})


def apply_cost(result: EngineResult) -> EngineResult:
    """Fill the cost fields from the engine's raw usage."""
    cost = config.compute_cost(result.engine_config_id, result.usage_raw)
    result.cost_usd = cost["cost_usd"]
    result.cost_krw = cost["cost_krw"]
    result.cost_confirmed = cost["cost_confirmed"]
    return result


class EngineClient(Protocol):
    engine_config_id: str

    def transcribe(self, image_path: Path, sample_id: str) -> EngineResult:
        """Transcribe one page image.

        Implementations must never raise on a request failure — a failed page
        is recorded in `EngineResult.error` so one bad page cannot abort a
        65-page run.
        """
        ...
