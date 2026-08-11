"""Claude table-structure extraction — a second, separately billed call.

Claude Vision has no structured-table output, so table structure cannot be
recovered from the full-page transcription this benchmark already runs. This
client asks for the page's tables as bare HTML instead, on the table pages
only. It is a distinct API call with its own prompt, its own cost line, and its
own engine config id (`claude_sonnet_table`) — folding it into the
transcription prompt would contaminate the CER/WER measurement.

Model, max_tokens and effort are pinned to the same values as
`claude_client.py` so the two calls stay comparable.
"""

from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

import anthropic

from .. import config, table_scoring
from .base import EngineResult, apply_cost
from .claude_client import extract_text, usage_from_message

DEFAULT_TIMEOUT = 600


class ClaudeTableClient:
    def __init__(
        self,
        engine_config_id: str = config.CLAUDE_TABLE_ENGINE_CONFIG_ID,
        api_key: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        client: Any | None = None,
    ):
        self.engine_config_id = engine_config_id
        self.cfg = config.engine_config(engine_config_id)
        self.client = client or anthropic.Anthropic(api_key=api_key, timeout=timeout)

    def transcribe(self, image_path: Path, sample_id: str) -> EngineResult:
        """Return the page's tables as HTML.

        `raw_text` keeps the model's unedited reply so a malformed response can
        be inspected later; `table_htmls` holds the `<table>` blocks pulled out
        of it. A page the model reports as having no table yields an empty
        `table_htmls` and no error — an empty answer is a valid answer here,
        unlike in the transcription client.
        """
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
                            {"type": "text", "text": config.CLAUDE_TABLE_PROMPT},
                        ],
                    }
                ],
            ) as stream:
                message = stream.get_final_message()

            result.latency_ms = int((time.monotonic() - started) * 1000)
            result.http_status = 200
            result.usage_raw = usage_from_message(message)
            result.raw_text = extract_text(message.content)
            result.table_htmls = table_scoring.split_table_blocks(result.raw_text)

            if message.stop_reason == "refusal":
                result.error = f"refusal: {getattr(message, 'stop_details', None)}"
        except Exception as exc:
            result.latency_ms = result.latency_ms or int((time.monotonic() - started) * 1000)
            result.error = f"{type(exc).__name__}: {exc}"
            return result

        return apply_cost(result)
