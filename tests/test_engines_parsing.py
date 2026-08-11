"""Fixture-based parsing tests. No network calls.

Fixtures mirror the real response shapes confirmed 2026-08-11:
  - Upstage Document Parse: console.upstage.ai/api/document-digitization
  - CLOVA General OCR V2:   api.ncloud-docs.com/docs/en/ai-application-service-ocr-ocr
  - Anthropic Messages:     content blocks + usage
  - Mistral OCR 4:          mistral.ai/news/ocr-4 (top-level shape confirmed;
                            the per-table object layout is a documented guess,
                            see the Mistral section below)
"""

import pytest

from ocr_benchmark import config
from ocr_benchmark.engines import (
    claude_client,
    claude_table_client,
    clova_client,
    mistral_client,
    upstage_client,
)
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


UPSTAGE_TABLE_HTML = (
    "<table><thead><tr><th>연번</th><th>기기명</th></tr></thead>"
    "<tbody><tr><td>1</td><td></td></tr></tbody></table>"
)

# `output_formats=["text","html"]` populates `elements[].content.html`; table
# elements are the only place Document Parse exposes table structure.
UPSTAGE_TABLE_RESPONSE = dict(
    UPSTAGE_RESPONSE,
    elements=[
        *UPSTAGE_RESPONSE["elements"],
        {
            "id": 2,
            "page": 1,
            "category": "table",
            "content": {
                "text": "연번 기기명 1",
                "html": UPSTAGE_TABLE_HTML,
                "markdown": "| 연번 | 기기명 |",
            },
        },
        {
            "id": 3,
            "page": 1,
            "category": "figure",
            "content": {"text": "", "html": "<figure></figure>"},
        },
    ],
)


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


def test_upstage_extracts_html_of_table_elements_only():
    assert upstage_client.extract_table_htmls(UPSTAGE_TABLE_RESPONSE) == [
        UPSTAGE_TABLE_HTML
    ]


def test_upstage_extracts_nothing_from_a_page_without_tables():
    assert upstage_client.extract_table_htmls(UPSTAGE_RESPONSE) == []


def test_upstage_table_extraction_does_not_change_the_text_pipeline():
    with_tables, usage = upstage_client.parse_response(UPSTAGE_TABLE_RESPONSE)
    without, _ = upstage_client.parse_response(UPSTAGE_RESPONSE)
    assert with_tables == without
    assert usage["element_count"] == 4


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


def clova_cell(row, column, text, row_span=1, column_span=1):
    """A V2 `tables[].cells[]` entry.

    Shape per the documented CLOVA OCR V2 schema: rowIndex / columnIndex /
    rowSpan / columnSpan / cellTextLines[].cellWords[].inferText.
    """
    return {
        "rowIndex": row,
        "columnIndex": column,
        "rowSpan": row_span,
        "columnSpan": column_span,
        "cellTextLines": [
            {
                "cellWords": [{"inferText": word} for word in text.split()],
                "boundingPoly": {"vertices": [{"x": 0, "y": 0}]},
            }
        ]
        if text
        else [],
    }


CLOVA_TABLE = {
    "cells": [
        clova_cell(0, 0, "지출금액", column_span=2),
        clova_cell(1, 0, "발의일", row_span=2),
        clova_cell(1, 1, "2026-08-11"),
        clova_cell(2, 1, ""),
    ]
}


def test_clova_tables_to_html_renders_the_cell_grid_with_spans():
    html = clova_client.clova_tables_to_html([CLOVA_TABLE])
    assert html == [
        "<table><tbody>"
        '<tr><td colspan="2">지출금액</td></tr>'
        '<tr><td rowspan="2">발의일</td><td>2026-08-11</td></tr>'
        "<tr><td></td></tr>"
        "</tbody></table>"
    ]


def test_clova_tables_to_html_orders_cells_by_row_then_column():
    scrambled = {
        "cells": [
            clova_cell(1, 1, "d"),
            clova_cell(0, 1, "b"),
            clova_cell(1, 0, "c"),
            clova_cell(0, 0, "a"),
        ]
    }
    html = clova_client.clova_tables_to_html([scrambled])[0]
    assert html == (
        "<table><tbody><tr><td>a</td><td>b</td></tr>"
        "<tr><td>c</td><td>d</td></tr></tbody></table>"
    )


def test_clova_tables_to_html_escapes_cell_text():
    cells = {"cells": [clova_cell(0, 0, "a<b>&c")]}
    assert "&lt;b&gt;" in clova_client.clova_tables_to_html([cells])[0]


def test_clova_tables_to_html_accepts_the_normalized_form():
    normalized = clova_client.normalize_tables([CLOVA_TABLE])
    assert clova_client.clova_tables_to_html(
        normalized
    ) == clova_client.clova_tables_to_html([CLOVA_TABLE])


def test_clova_normalized_tables_keep_structure_and_drop_bounding_boxes():
    normalized = clova_client.normalize_tables([CLOVA_TABLE])
    assert normalized == [
        {
            "cells": [
                {"rowIndex": 0, "columnIndex": 0, "rowSpan": 1, "columnSpan": 2, "text": "지출금액"},
                {"rowIndex": 1, "columnIndex": 0, "rowSpan": 2, "columnSpan": 1, "text": "발의일"},
                {"rowIndex": 1, "columnIndex": 1, "rowSpan": 1, "columnSpan": 1, "text": "2026-08-11"},
                {"rowIndex": 2, "columnIndex": 1, "rowSpan": 1, "columnSpan": 1, "text": ""},
            ]
        }
    ]


def test_clova_missing_spans_default_to_one():
    bare = {"cells": [{"rowIndex": 0, "columnIndex": 0, "cellTextLines": []}]}
    assert clova_client.normalize_tables([bare])[0]["cells"][0]["rowSpan"] == 1
    assert clova_client.clova_tables_to_html([bare]) == [
        "<table><tbody><tr><td></td></tr></tbody></table>"
    ]


def test_clova_parse_response_persists_the_table_structure_in_usage():
    payload = {
        "images": [
            {
                "inferResult": "SUCCESS",
                "fields": [field("지출결의서", True, 100, 100)],
                "tables": [CLOVA_TABLE],
            }
        ]
    }
    _, usage = clova_client.parse_response(payload)
    assert usage["table_count"] == 1
    assert usage["tables_normalized"][0]["cells"][0]["columnSpan"] == 2


def test_clova_extract_table_htmls_is_empty_without_table_detection():
    assert clova_client.extract_table_htmls(CLOVA_RESPONSE) == []
    assert clova_client.extract_table_htmls({"images": []}) == []


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


# --- Mistral ---------------------------------------------------------------

# Default call: `table_format` is omitted, so tables stay inline in the page
# markdown as markdown table syntax. That inline form is deliberately what
# CER/WER measures — see mistral_client's module docstring.
MISTRAL_RESPONSE = {
    "pages": [
        {
            "index": 0,
            "markdown": (
                "# 비밀유지계약서\n\n제1조(목적)\n\n"
                "| 연번 | 기기명 |\n| --- | --- |\n| 1 |  |"
            ),
            "tables": [],
            "images": [],
            "dimensions": {"dpi": 200, "height": 2576, "width": 1822},
        }
    ],
    "model": "mistral-ocr-4-0",
    "usage_info": {"pages_processed": 1, "doc_size_bytes": 184213},
}

# `table_format="html"` call: tables move out of the markdown, which keeps only
# a `[tbl-N.html](tbl-N.html)` link where each table was.
#
# Shape confirmed 2026-08-11 against a live response (jichul_p01, cached at
# results/raw3/tables/mistral_ocr/jichul_p01.json): each entry is
# `{"id", "content": "<table>...</table>", "format": "html",
# "word_confidence_scores"}`. The pre-live-call guess used a top-level `"html"`
# key instead of `"content"` and scored every table-page 0 despite `tables[]`
# being populated — the two tests after this one pin the fallbacks that were
# added once that mismatch was found, so a future rename degrades instead of
# silently zeroing every page again.
MISTRAL_TABLE_RESPONSE = {
    "pages": [
        {
            "index": 0,
            "markdown": "# 별첨 [3]: 공급 기기 등의 내역\n\n[tbl-0.html](tbl-0.html)",
            "tables": [
                {
                    "id": "tbl-0.html",
                    "content": UPSTAGE_TABLE_HTML,
                    "format": "html",
                    "word_confidence_scores": None,
                }
            ],
            "images": [],
        }
    ],
    "model": "mistral-ocr-4-0",
    "usage_info": {"pages_processed": 1, "doc_size_bytes": 184213},
}


def test_mistral_parses_page_markdown_and_usage():
    text, usage = mistral_client.parse_response(MISTRAL_RESPONSE)
    assert text.startswith("# 비밀유지계약서")
    assert "| 연번 | 기기명 |" in text  # inline table, not a placeholder
    assert usage["pages_processed"] == 1
    assert usage["doc_size_bytes"] == 184213
    assert usage["model"] == "mistral-ocr-4-0"


def test_mistral_response_without_pages_raises():
    with pytest.raises(ValueError, match="no pages"):
        mistral_client.parse_response({"pages": [], "usage_info": {}})


def test_mistral_cost_is_the_confirmed_per_page_rate():
    # $4/1,000 pages on the synchronous API, publicly announced — confirmed,
    # unlike CLOVA's console-only rate.
    result = EngineResult(
        engine_config_id="mistral_ocr", sample_id="x_p01", usage_raw={"pages_processed": 1}
    )
    apply_cost(result)
    assert result.cost_usd == pytest.approx(0.004)
    assert result.cost_confirmed is True


def test_mistral_cost_scales_with_pages_processed():
    result = EngineResult(
        engine_config_id="mistral_ocr", sample_id="x_p01", usage_raw={"pages_processed": 5}
    )
    apply_cost(result)
    assert result.cost_usd == pytest.approx(0.02)


def test_mistral_model_is_version_pinned_not_latest():
    # A rotating alias would change results underneath an unchanged cache.
    assert config.ENGINE_CONFIGS["mistral_ocr"]["model"] == "mistral-ocr-4-0"
    assert "latest" not in config.ENGINE_CONFIGS["mistral_ocr"]["model"]


def test_mistral_extracts_table_html_under_the_confirmed_schema():
    assert mistral_client.extract_table_htmls(MISTRAL_TABLE_RESPONSE) == [
        UPSTAGE_TABLE_HTML
    ]


def test_mistral_extracts_table_html_from_the_real_jichul_p01_response():
    # Regression fixture: the exact `tables[]` array from the first live
    # `--tables --engine mistral` run (2026-08-11), not a reconstruction —
    # pins the confirmed schema against the actual bytes that exposed the
    # content/html key mismatch, rowspan/colspan and all.
    real_table_content = (
        '<table><tr><td colspan="3">문서번호</td><td rowspan="2">결<br/>재</td>'
        "<td>담당</td><td>팀장</td><td>센터장</td></tr>"
        '<tr><td colspan="3">제 호</td><td></td><td></td><td></td></tr>'
        '<tr><td colspan="7">지출금액 일금 원정(\\)</td></tr></table>'
    )
    payload = {
        "pages": [
            {
                "index": 0,
                "markdown": "지 출 결 의 서\n\n[tbl-0.html](tbl-0.html)",
                "tables": [
                    {
                        "id": "tbl-0.html",
                        "content": real_table_content,
                        "format": "html",
                        "word_confidence_scores": None,
                    }
                ],
            }
        ],
        "model": "mistral-ocr-4-0",
        "usage_info": {"pages_processed": 1, "doc_size_bytes": 123456},
    }
    assert mistral_client.extract_table_htmls(payload) == [real_table_content]


def test_mistral_falls_back_to_the_html_key_if_content_is_absent():
    # If a future response reverts to (or ever used) `"html"` instead of
    # `"content"`, that must still be read rather than silently dropped.
    payload = {
        "pages": [{"markdown": "x", "tables": [{"id": "tbl-0", "html": UPSTAGE_TABLE_HTML}]}],
        "usage_info": {"pages_processed": 1},
    }
    assert mistral_client.extract_table_htmls(payload) == [UPSTAGE_TABLE_HTML]


def test_mistral_falls_back_to_a_bare_string_table_entry():
    # If `tables[]` ever holds the HTML strings directly rather than objects
    # wrapping them, neither the `content` nor `html` key appears and the
    # entry itself is the payload.
    payload = {
        "pages": [{"markdown": "x", "tables": [UPSTAGE_TABLE_HTML]}],
        "usage_info": {"pages_processed": 1},
    }
    assert mistral_client.extract_table_htmls(payload) == [UPSTAGE_TABLE_HTML]


def test_mistral_skips_a_table_object_whose_schema_is_unrecognized():
    # An entry that matches none of the known shapes is dropped rather than
    # raised on, so one unrecognised table cannot floor-score the page or
    # abort the run. The untouched array survives in usage_raw for a later
    # re-parse — this is exactly how the content/html mismatch itself was
    # diagnosed and fixed without re-paying for the call.
    payload = {
        "pages": [
            {
                "markdown": "x",
                "tables": [
                    {"id": "tbl-0", "content": {"format": "html", "value": "<table></table>"}},
                    {"id": "tbl-1", "content": UPSTAGE_TABLE_HTML},
                    {"id": "tbl-2", "content": ""},
                    None,
                ],
            }
        ],
        "usage_info": {"pages_processed": 1},
    }
    assert mistral_client.extract_table_htmls(payload) == [UPSTAGE_TABLE_HTML]


def test_mistral_extracts_nothing_from_a_page_with_no_tables():
    assert mistral_client.extract_table_htmls(MISTRAL_RESPONSE) == []
    assert mistral_client.extract_table_htmls({"pages": []}) == []


def mistral_post(monkeypatch, payload, captured):
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(mistral_client.requests, "post", post)


def test_mistral_transcribe_omits_table_format_and_scores_the_markdown(monkeypatch, tmp_path):
    captured = {}
    mistral_post(monkeypatch, MISTRAL_RESPONSE, captured)
    client = mistral_client.MistralClient("mistral_ocr", "key")

    result = client.transcribe(make_image(tmp_path), "bimil_gyeyak_p01")

    assert result.ok
    assert result.raw_text.startswith("# 비밀유지계약서")
    assert result.cost_usd == pytest.approx(0.004)
    assert captured["url"] == mistral_client.API_URL
    assert captured["headers"]["Authorization"] == "Bearer key"

    body = captured["json"]
    assert body["model"] == config.MISTRAL_MODEL
    assert body["document"]["type"] == "image_url"
    assert body["document"]["image_url"].startswith("data:image/jpeg;base64,")
    # Absent, not null: the text pipeline must never receive tables separated
    # into placeholders, which would score the output format not the OCR.
    assert "table_format" not in body
    assert result.table_htmls == []


def test_mistral_transcribe_table_requests_html_and_keeps_the_raw_array(monkeypatch, tmp_path):
    captured = {}
    mistral_post(monkeypatch, MISTRAL_TABLE_RESPONSE, captured)
    client = mistral_client.MistralClient("mistral_ocr", "key")

    result = client.transcribe_table(make_image(tmp_path), "franchise_p47")

    assert result.ok
    assert captured["json"]["table_format"] == "html"
    assert result.table_htmls == [UPSTAGE_TABLE_HTML]
    # The unmodified array is persisted so a corrected parser can be re-run off
    # the cache without re-paying — same rule as CLOVA's tables_normalized.
    assert result.usage_raw["tables_raw"] == MISTRAL_TABLE_RESPONSE["pages"][0]["tables"]
    assert result.cost_usd == pytest.approx(0.004)


def test_mistral_table_call_keeps_the_placeholder_markdown_as_raw_text(monkeypatch, tmp_path):
    # Expected, not a defect: with tables separated out the markdown carries
    # `[tbl-N.html]` links. Only table_htmls is scored from this call.
    mistral_post(monkeypatch, MISTRAL_TABLE_RESPONSE, {})
    client = mistral_client.MistralClient("mistral_ocr", "key")
    result = client.transcribe_table(make_image(tmp_path), "franchise_p47")
    assert "[tbl-0.html](tbl-0.html)" in result.raw_text


def test_mistral_is_table_capable_under_its_own_config_id(monkeypatch, tmp_path):
    # Unlike Claude, Mistral needs no table-only twin config: table extraction
    # is a parameter on the same endpoint and model, so one id serves both the
    # 65-page text loop and the 9-page table loop.
    assert "mistral_ocr" in config.ENGINE_CONFIGS
    assert "mistral_ocr" in config.TABLE_CAPABLE_ENGINE_CONFIGS
    assert "mistral_ocr" not in config.TABLE_ONLY_ENGINE_CONFIGS


# --- HTTP failure handling for the requests-based clients ------------------


@pytest.mark.parametrize(
    "module,make_client",
    [
        (upstage_client, lambda: upstage_client.UpstageClient("upstage_standard", "key")),
        (clova_client, lambda: clova_client.ClovaClient("clova_text", "s", "https://e/general")),
        (mistral_client, lambda: mistral_client.MistralClient("mistral_ocr", "key")),
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


# --- table structure end-to-end (still fixture-only, no network) -----------


def test_upstage_requests_html_alongside_text_and_fills_table_htmls(monkeypatch, tmp_path):
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return UPSTAGE_TABLE_RESPONSE

    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr(upstage_client.requests, "post", post)
    client = upstage_client.UpstageClient("upstage_standard", "key")
    result = client.transcribe(make_image(tmp_path), "franchise_p47")

    assert captured["data"]["output_formats"] == '["text","html"]'
    assert result.table_htmls == [UPSTAGE_TABLE_HTML]
    assert "비밀유지계약서" in result.raw_text


def test_clova_transcribe_fills_table_htmls_from_the_tables_array(monkeypatch, tmp_path):
    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "images": [
                    {
                        "inferResult": "SUCCESS",
                        "fields": [field("지출결의서", True, 10, 10)],
                        "tables": [CLOVA_TABLE],
                    }
                ]
            }

    monkeypatch.setattr(clova_client.requests, "post", lambda *a, **k: Response())
    client = clova_client.ClovaClient("clova_table", "secret", "https://example/general")
    result = client.transcribe(make_image(tmp_path), "jichul_p01")

    assert result.ok
    assert result.table_htmls == clova_client.clova_tables_to_html([CLOVA_TABLE])


def test_engine_result_round_trips_table_htmls_through_the_cache_format():
    original = EngineResult(
        engine_config_id="upstage_standard",
        sample_id="franchise_p47",
        table_htmls=[UPSTAGE_TABLE_HTML],
    )
    assert EngineResult.from_dict(original.to_dict()).table_htmls == [UPSTAGE_TABLE_HTML]


def test_a_cache_entry_written_before_table_scoring_still_loads():
    legacy = {
        "engine_config_id": "upstage_standard",
        "sample_id": "franchise_p47",
        "raw_text": "x",
        "usage_raw": {"pages": 1},
    }
    assert EngineResult.from_dict(legacy).table_htmls == []


def test_claude_table_client_sends_the_table_prompt_and_parses_html(tmp_path):
    reply = f"```html\n{UPSTAGE_TABLE_HTML}\n```"
    fake = FakeAnthropic(Message([Block("text", text=reply)]))
    client = claude_table_client.ClaudeTableClient(
        config.CLAUDE_TABLE_ENGINE_CONFIG_ID, "key", client=fake
    )

    result = client.transcribe(make_image(tmp_path), "franchise_p47")

    assert result.ok
    assert result.table_htmls == [UPSTAGE_TABLE_HTML]
    assert result.cost_usd > 0

    sent = fake.messages.captured
    assert sent["model"] == config.CLAUDE_MODEL
    assert sent["max_tokens"] == config.CLAUDE_MAX_TOKENS
    assert sent["output_config"] == {"effort": config.CLAUDE_EFFORT}
    _, text_block = sent["messages"][0]["content"]
    assert text_block["text"] == config.CLAUDE_TABLE_PROMPT
    assert text_block["text"] != config.CLAUDE_PROMPT


def test_claude_table_client_treats_no_table_found_as_a_valid_empty_answer(tmp_path):
    fake = FakeAnthropic(Message([Block("text", text="")]))
    client = claude_table_client.ClaudeTableClient(client=fake)
    result = client.transcribe(make_image(tmp_path), "gyeongeop_p01")

    assert result.ok
    assert result.table_htmls == []


def test_claude_table_client_records_a_refusal_as_an_error(tmp_path):
    fake = FakeAnthropic(Message([Block("text", text="")], stop_reason="refusal"))
    client = claude_table_client.ClaudeTableClient(client=fake)
    result = client.transcribe(make_image(tmp_path), "franchise_p47")
    assert not result.ok
    assert "refusal" in result.error


def test_claude_table_config_is_kept_out_of_the_text_benchmark_registry():
    # A sixth entry in ENGINE_CONFIGS would add 65 billed calls to every run.
    assert config.CLAUDE_TABLE_ENGINE_CONFIG_ID not in config.ENGINE_CONFIGS
    assert config.engine_config(config.CLAUDE_TABLE_ENGINE_CONFIG_ID)["engine"] == "claude"
    assert config.compute_cost(
        config.CLAUDE_TABLE_ENGINE_CONFIG_ID, {"input_tokens": 1_000_000}
    )["cost_usd"] == pytest.approx(config.CLAUDE_PRICING["claude-sonnet-5"]["input"])


def test_clova_text_is_not_table_capable():
    assert "clova_text" not in config.TABLE_CAPABLE_ENGINE_CONFIGS
    assert "clova_table" in config.TABLE_CAPABLE_ENGINE_CONFIGS
