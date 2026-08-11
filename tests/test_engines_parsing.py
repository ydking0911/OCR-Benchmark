"""Fixture-based parsing tests. No network calls.

Fixtures mirror the real response shapes confirmed 2026-08-11:
  - Upstage Document Parse: console.upstage.ai/api/document-digitization
  - CLOVA General OCR V2:   api.ncloud-docs.com/docs/en/ai-application-service-ocr-ocr
  - Anthropic Messages:     content blocks + usage
"""

import pytest

from ocr_benchmark import config
from ocr_benchmark.engines import claude_client, clova_client, upstage_client
from ocr_benchmark.engines.base import EngineResult, apply_cost

# --- Upstage ---------------------------------------------------------------

UPSTAGE_RESPONSE = {
    "api": "2.0",
    "model": "document-parse-250618",
    "usage": {"pages": 1},
    "content": {
        "text": "비밀유지계약서\n제1조(목적)\n본 계약은 비밀정보의 보호를 목적으로 한다.",
        "html": "<h1>비밀유지계약서</h1><p>제1조(목적)</p>",
        "markdown": "# 비밀유지계약서\n\n제1조(목적)",
    },
    "elements": [
        {
            "id": 0,
            "page": 1,
            "category": "heading1",
            "content": {"text": "비밀유지계약서", "html": "<h1>비밀유지계약서</h1>", "markdown": "# 비밀유지계약서"},
            "coordinates": [
                {"x": 0.11, "y": 0.05},
                {"x": 0.88, "y": 0.05},
                {"x": 0.88, "y": 0.09},
                {"x": 0.11, "y": 0.09},
            ],
        },
        {
            "id": 1,
            "page": 1,
            "category": "paragraph",
            "content": {"text": "제1조(목적)", "html": "<p>제1조(목적)</p>", "markdown": "제1조(목적)"},
            "coordinates": [],
        },
    ],
}


def test_upstage_parses_text_and_usage():
    text, usage = upstage_client.parse_response(UPSTAGE_RESPONSE)
    assert text.startswith("비밀유지계약서")
    assert "제1조(목적)" in text
    assert usage["pages"] == 1
    assert usage["model"] == "document-parse-250618"
    assert usage["element_count"] == 2


def test_upstage_rebuilds_text_from_elements_when_text_format_absent():
    payload = dict(UPSTAGE_RESPONSE, content={"markdown": "# 비밀유지계약서"})
    text, _ = upstage_client.parse_response(payload)
    assert text == "비밀유지계약서\n제1조(목적)"


def test_upstage_multipage_usage_is_carried_through():
    payload = dict(UPSTAGE_RESPONSE, usage={"pages": 4})
    _, usage = upstage_client.parse_response(payload)
    assert usage["pages"] == 4


@pytest.mark.parametrize(
    "engine_config_id,expected",
    [("upstage_standard", 0.01), ("upstage_enhanced", 0.03)],
)
def test_upstage_cost_uses_the_tier_price_per_page(engine_config_id, expected):
    result = EngineResult(engine_config_id=engine_config_id, sample_id="x_p01", usage_raw={"pages": 1})
    apply_cost(result)
    assert result.cost_usd == pytest.approx(expected)
    assert result.cost_confirmed is True


def test_upstage_standard_and_enhanced_send_different_modes():
    assert config.ENGINE_CONFIGS["upstage_standard"]["mode"] == "standard"
    assert config.ENGINE_CONFIGS["upstage_enhanced"]["mode"] == "enhanced"


# --- CLOVA -----------------------------------------------------------------


def field(text, line_break, x, y):
    return {
        "valueType": "ALL",
        "inferText": text,
        "inferConfidence": 0.99,
        "type": "NORMAL",
        "lineBreak": line_break,
        "boundingPoly": {
            "vertices": [
                {"x": x, "y": y},
                {"x": x + 40, "y": y},
                {"x": x + 40, "y": y + 20},
                {"x": x, "y": y + 20},
            ]
        },
    }


CLOVA_RESPONSE = {
    "version": "V2",
    "requestId": "c0ffee",
    "timestamp": 1786000000000,
    "images": [
        {
            "uid": "abc123",
            "name": "bimil_gyeyak_p01",
            "inferResult": "SUCCESS",
            "message": "SUCCESS",
            "validationResult": {"result": "NO_REQUESTED"},
            "convertedImageInfo": {"width": 1822, "height": 2576, "pageIndex": 0},
            "fields": [
                field("비밀유지", False, 100, 100),
                field("계약서", True, 160, 100),
                field("제1조(목적)", True, 100, 200),
            ],
        }
    ],
}


def test_clova_reassembles_lines_using_line_break():
    text, usage = clova_client.parse_response(CLOVA_RESPONSE)
    assert text == "비밀유지 계약서\n제1조(목적)"
    assert usage["field_count"] == 3
    assert usage["table_count"] == 0
    assert usage["requests"] == 1


def test_clova_falls_back_to_bbox_order_without_line_break():
    fields = [
        {"inferText": "아래", "boundingPoly": {"vertices": [{"x": 10, "y": 500}]}},
        {"inferText": "위", "boundingPoly": {"vertices": [{"x": 10, "y": 100}]}},
        {"inferText": "오른쪽", "boundingPoly": {"vertices": [{"x": 900, "y": 100}]}},
    ]
    assert clova_client.reassemble_fields(fields) == "위 오른쪽 아래"


def test_clova_empty_fields_yield_empty_text():
    assert clova_client.reassemble_fields([]) == ""


def test_clova_table_cells_are_appended_when_not_already_in_fields():
    payload = {
        "images": [
            {
                "inferResult": "SUCCESS",
                "fields": [field("지출결의서", True, 100, 100)],
                "tables": [
                    {
                        "cells": [
                            {
                                "rowIndex": 0,
                                "columnIndex": 0,
                                "cellTextLines": [{"cellWords": [{"inferText": "항목"}]}],
                            },
                            {
                                "rowIndex": 0,
                                "columnIndex": 1,
                                "cellTextLines": [{"cellWords": [{"inferText": "금액"}]}],
                            },
                            {
                                "rowIndex": 1,
                                "columnIndex": 0,
                                "cellTextLines": [{"cellWords": [{"inferText": "교통비"}]}],
                            },
                        ]
                    }
                ],
            }
        ]
    }
    text, usage = clova_client.parse_response(payload)
    assert text.splitlines() == ["지출결의서", "항목\t금액", "교통비"]
    assert usage["table_count"] == 1


def test_clova_does_not_duplicate_table_text_already_in_fields():
    payload = {
        "images": [
            {
                "inferResult": "SUCCESS",
                "fields": [field("항목", False, 10, 10), field("금액", True, 60, 10)],
                "tables": [
                    {
                        "cells": [
                            {
                                "rowIndex": 0,
                                "columnIndex": 0,
                                "cellTextLines": [{"cellWords": [{"inferText": "항목"}]}],
                            },
                            {
                                "rowIndex": 0,
                                "columnIndex": 1,
                                "cellTextLines": [{"cellWords": [{"inferText": "금액"}]}],
                            },
                        ]
                    }
                ],
            }
        ]
    }
    text, _ = clova_client.parse_response(payload)
    assert text == "항목 금액"


def test_clova_failure_result_raises_so_the_caller_records_an_error():
    payload = {
        "images": [
            {"inferResult": "FAILURE", "message": "Invalid image", "fields": []}
        ]
    }
    with pytest.raises(ValueError, match="FAILURE"):
        clova_client.parse_response(payload)


def test_clova_response_without_images_raises():
    with pytest.raises(ValueError, match="no images"):
        clova_client.parse_response({"version": "V2", "images": []})


def test_clova_cost_uses_the_confirmed_console_rate():
    # 2026-08-11: confirmed from the NCP console (Premium plan) — 3 KRW/request
    # base 글자 추출, +22 KRW/request when table detection is on.
    text_result = EngineResult(engine_config_id="clova_text", sample_id="x_p01", usage_raw={"requests": 1})
    apply_cost(text_result)
    assert text_result.cost_confirmed is True
    assert text_result.cost_krw == 3

    table_result = EngineResult(engine_config_id="clova_table", sample_id="x_p01", usage_raw={"requests": 1})
    apply_cost(table_result)
    assert table_result.cost_confirmed is True
    assert table_result.cost_krw == 25


def test_clova_cost_falls_back_to_unconfirmed_when_pricing_is_unknown(monkeypatch):
    # Regression guard for the pre-2026-08-11 state and for any future price
    # this harness has not yet verified: a None rate must never be treated as
    # free or silently defaulted, it must mark the result unconfirmed.
    monkeypatch.setitem(config.CLOVA_PRICING, "krw_per_request", None)
    result = EngineResult(engine_config_id="clova_text", sample_id="x_p01", usage_raw={"requests": 1})
    apply_cost(result)
    assert result.cost_confirmed is False
    assert result.cost_usd is None
    assert result.cost_krw is None


def test_clova_request_body_matches_the_documented_v2_shape(tmp_path):
    image = tmp_path / "x_p01.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0jpegbytes")
    client = clova_client.ClovaClient("clova_table", "secret", "https://example/general")

    body = client.build_request(image, "x_p01")
    assert body["version"] == "V2"
    assert body["enableTableDetection"] is True
    assert body["lang"] == "ko"
    assert isinstance(body["timestamp"], int)
    assert body["images"][0]["format"] == "jpg"
    assert body["images"][0]["name"] == "x_p01"
    assert body["images"][0]["data"]

    text_client = clova_client.ClovaClient("clova_text", "secret", "https://example/general")
    assert text_client.build_request(image, "x_p01")["enableTableDetection"] is False


# --- Claude ----------------------------------------------------------------


class Block:
    def __init__(self, type_, text=None, thinking=None):
        self.type = type_
        self.text = text
        self.thinking = thinking


class Usage:
    def __init__(self, input_tokens, output_tokens):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cache_creation_input_tokens = 0
        self.cache_read_input_tokens = 0


class Message:
    def __init__(self, content, stop_reason="end_turn"):
        self.content = content
        self.stop_reason = stop_reason
        self.model = "claude-sonnet-5"
        self.usage = Usage(4784, 900)
        self.stop_details = None


def test_claude_extracts_text_blocks_and_skips_thinking():
    message = Message(
        [
            Block("thinking", thinking="이 페이지를 전사해야 한다"),
            Block("text", text="비밀유지계약서"),
            Block("text", text="제1조(목적)"),
        ]
    )
    assert claude_client.extract_text(message.content) == "비밀유지계약서\n제1조(목적)"


def test_claude_thinking_only_response_extracts_to_empty():
    assert claude_client.extract_text([Block("thinking", thinking="...")]) == ""


def test_claude_usage_records_tokens_stop_reason_and_cap():
    usage = claude_client.usage_from_message(Message([Block("text", text="x")]))
    assert usage["input_tokens"] == 4784
    assert usage["output_tokens"] == 900
    assert usage["cache_creation_input_tokens"] == 0
    assert usage["cache_read_input_tokens"] == 0
    assert usage["stop_reason"] == "end_turn"
    assert usage["max_tokens"] == config.CLAUDE_MAX_TOKENS


def test_claude_cost_uses_the_sonnet5_token_rates():
    result = EngineResult(
        engine_config_id="claude_sonnet",
        sample_id="x_p01",
        usage_raw={"input_tokens": 1_000_000, "output_tokens": 1_000_000},
    )
    apply_cost(result)
    rates = config.CLAUDE_PRICING["claude-sonnet-5"]
    assert result.cost_usd == pytest.approx(rates["input"] + rates["output"])
    assert result.cost_confirmed is True


def test_claude_cache_tokens_are_priced_rather_than_ignored():
    result = EngineResult(
        engine_config_id="claude_sonnet",
        sample_id="x_p01",
        usage_raw={"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 1_000_000},
    )
    apply_cost(result)
    assert result.cost_usd == pytest.approx(
        config.CLAUDE_PRICING["claude-sonnet-5"]["cache_read_input"]
    )


class FakeStream:
    def __init__(self, message):
        self._message = message

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._message


class FakeMessages:
    def __init__(self, message=None, error=None):
        self._message = message
        self._error = error
        self.captured = None

    def stream(self, **kwargs):
        self.captured = kwargs
        if self._error:
            raise self._error
        return FakeStream(self._message)


class FakeAnthropic:
    def __init__(self, message=None, error=None):
        self.messages = FakeMessages(message, error)


def make_image(tmp_path):
    image = tmp_path / "franchise_p01.jpg"
    image.write_bytes(b"\xff\xd8\xff\xe0jpegbytes")
    return image


def test_claude_transcribe_builds_a_vision_request_and_scores_cost(tmp_path):
    fake = FakeAnthropic(Message([Block("text", text="비밀유지계약서")]))
    client = claude_client.ClaudeClient("claude_sonnet", "key", client=fake)

    result = client.transcribe(make_image(tmp_path), "franchise_p01")

    assert result.ok
    assert result.raw_text == "비밀유지계약서"
    assert result.cost_usd > 0
    assert result.http_status == 200

    sent = fake.messages.captured
    assert sent["model"] == config.CLAUDE_MODEL
    assert sent["max_tokens"] == config.CLAUDE_MAX_TOKENS
    assert sent["thinking"] == {"type": "adaptive"}
    assert sent["output_config"] == {"effort": config.CLAUDE_EFFORT}
    image_block, text_block = sent["messages"][0]["content"]
    assert image_block["source"]["media_type"] == "image/jpeg"
    assert image_block["source"]["type"] == "base64"
    assert text_block["text"] == config.CLAUDE_PROMPT


def test_claude_refusal_is_recorded_as_an_error(tmp_path):
    fake = FakeAnthropic(Message([Block("text", text="")], stop_reason="refusal"))
    client = claude_client.ClaudeClient("claude_sonnet", "key", client=fake)
    result = client.transcribe(make_image(tmp_path), "franchise_p01")
    assert not result.ok
    assert "refusal" in result.error


def test_claude_empty_response_is_recorded_as_an_error(tmp_path):
    fake = FakeAnthropic(Message([Block("thinking", thinking="...")]))
    client = claude_client.ClaudeClient("claude_sonnet", "key", client=fake)
    result = client.transcribe(make_image(tmp_path), "franchise_p01")
    assert not result.ok
    assert "empty response" in result.error


def test_claude_api_exception_is_caught_not_raised(tmp_path):
    fake = FakeAnthropic(error=RuntimeError("connection reset"))
    client = claude_client.ClaudeClient("claude_sonnet", "key", client=fake)
    result = client.transcribe(make_image(tmp_path), "franchise_p01")
    assert not result.ok
    assert "RuntimeError: connection reset" in result.error
    assert result.raw_text == ""


# --- HTTP failure handling for the requests-based clients ------------------


@pytest.mark.parametrize(
    "module,make_client",
    [
        (upstage_client, lambda: upstage_client.UpstageClient("upstage_standard", "key")),
        (clova_client, lambda: clova_client.ClovaClient("clova_text", "s", "https://e/general")),
    ],
)
def test_request_failures_land_in_the_error_field(monkeypatch, tmp_path, module, make_client):
    def boom(*args, **kwargs):
        raise module.requests.exceptions.ConnectTimeout("timed out")

    monkeypatch.setattr(module.requests, "post", boom)
    result = make_client().transcribe(make_image(tmp_path), "franchise_p01")

    assert not result.ok
    assert "ConnectTimeout" in result.error
    assert result.raw_text == ""


def test_upstage_http_error_status_is_recorded(monkeypatch, tmp_path):
    class Response:
        status_code = 429

        def raise_for_status(self):
            raise upstage_client.requests.exceptions.HTTPError("429 Too Many Requests")

        def json(self):
            return {}

    monkeypatch.setattr(upstage_client.requests, "post", lambda *a, **k: Response())
    client = upstage_client.UpstageClient("upstage_standard", "key")
    result = client.transcribe(make_image(tmp_path), "franchise_p01")

    assert not result.ok
    assert result.http_status == 429
    assert "HTTPError" in result.error


def test_successful_upstage_transcribe_parses_the_fixture(monkeypatch, tmp_path):
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return UPSTAGE_RESPONSE

    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(upstage_client.requests, "post", post)
    client = upstage_client.UpstageClient("upstage_enhanced", "key")
    result = client.transcribe(make_image(tmp_path), "franchise_p01")

    assert result.ok
    assert "비밀유지계약서" in result.raw_text
    assert result.cost_usd == pytest.approx(0.03)
    assert captured["url"] == upstage_client.API_URL
    assert captured["headers"]["Authorization"] == "Bearer key"
    assert captured["data"]["mode"] == "enhanced"
    assert captured["data"]["model"] == "document-parse"


def test_successful_clova_transcribe_parses_the_fixture(monkeypatch, tmp_path):
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return CLOVA_RESPONSE

    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(clova_client.requests, "post", post)
    client = clova_client.ClovaClient("clova_text", "secret", "https://example/general")
    result = client.transcribe(make_image(tmp_path), "bimil_gyeyak_p01")

    assert result.ok
    assert result.raw_text == "비밀유지 계약서\n제1조(목적)"
    assert captured["headers"]["X-OCR-SECRET"] == "secret"
    assert captured["url"] == "https://example/general"
