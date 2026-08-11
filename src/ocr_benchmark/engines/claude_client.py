"""Claude Sonnet 5 vision client (high-resolution single configuration).

Sonnet 5 accepts images up to 2576px on the long edge, which is what
`ground_truth.render_page` produces, so pages are sent at native render size.

Adaptive thinking is left on with `effort: "low"`. Effort is pinned for cost
control — thinking tokens bill as output, so a variable effort would
destabilize the per-page price this benchmark is trying to measure. The report
must disclose that the pinned low effort may understate Sonnet 5's quality.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import anthropic

from .. import config
from .base import EngineResult, apply_cost

DEFAULT_TIMEOUT = 600


def extract_text(content_blocks: list[Any]) -> str:
    """Join the `text` blocks only.

    Thinking blocks come first on Sonnet 5, so reading `content[0]` would
    return an empty string.
    """
    parts = []
    for block in content_blocks:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def usage_from_message(message: Any) -> dict[str, Any]:
    usage = message.usage
    return {
        "input_tokens": getattr(usage, "input_tokens", 0) or 0,
        "output_tokens": getattr(usage, "output_tokens", 0) or 0,
        # No cache_control is set anywhere in this benchmark, so these should be
        # zero. They are recorded and priced rather than ignored, so a nonzero
        # value shows up in the cost instead of vanishing.
        "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", 0) or 0,
        "stop_reason": getattr(message, "stop_reason", None),
        "model": getattr(message, "model", None),
        "max_tokens": config.CLAUDE_MAX_TOKENS,
    }


class ClaudeClient:
    def __init__(
        self,
        engine_config_id: str,
        api_key: str,
        timeout: int = DEFAULT_TIMEOUT,
        client: Any | None = None,
    ):
        self.engine_config_id = engine_config_id
        self.cfg = config.ENGINE_CONFIGS[engine_config_id]
        self.client = client or anthropic.Anthropic(api_key=api_key, timeout=timeout)

    def transcribe(self, image_path: Path, sample_id: str) -> EngineResult:
        result = EngineResult(engine_config_id=self.engine_config_id, sample_id=sample_id)
        started = time.monotonic()
        try:
            encoded = base64.standard_b64encode(image_path.read_bytes()).decode("ascii")
            with self.client.messages.stream(
                model=self.cfg["model"],
                max_tokens=config.CLAUDE_MAX_TOKENS,
                thinking={"type": "adaptive"},
                output_config={"effort": config.CLAUDE_EFFORT},
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": encoded,
                                },
                            },
                            {"type": "text", "text": config.CLAUDE_PROMPT},
                        ],
                    }
                ],
            ) as stream:
                message = stream.get_final_message()

            result.latency_ms = int((time.monotonic() - started) * 1000)
            result.http_status = 200
            result.usage_raw = usage_from_message(message)
            result.raw_text = extract_text(message.content)

            if message.stop_reason == "refusal":
                result.error = f"refusal: {getattr(message, 'stop_details', None)}"
            elif not result.raw_text:
                result.error = f"empty response (stop_reason={message.stop_reason})"
        except Exception as exc:
            result.latency_ms = result.latency_ms or int((time.monotonic() - started) * 1000)
            result.error = f"{type(exc).__name__}: {exc}"
            return result

        return apply_cost(result)
