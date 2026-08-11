"""TEDS scoring tests. Pure functions over HTML fixtures — no network."""

import pytest

from ocr_benchmark import table_scoring
from ocr_benchmark.table_ground_truth import TABLE_GROUND_TRUTH

SIMPLE = (
    "<table><thead><tr><th>연번</th><th>기기명</th></tr></thead>"
    "<tbody><tr><td>1</td><td>냉장고</td></tr>"
    "<tr><td>2</td><td>제빙기</td></tr></tbody></table>"
)

MISSING_ROW = (
    "<table><thead><tr><th>연번</th><th>기기명</th></tr></thead>"
    "<tbody><tr><td>1</td><td>냉장고</td></tr></tbody></table>"
)

# franchise_p13's shape: one continuation table plus one independent table.
TWO_TABLES = TABLE_GROUND_TRUTH["franchise_p13"]


# --- parsing ---------------------------------------------------------------


def test_cell_spans_are_part_of_the_node_label():
    tree = table_scoring.parse_tables(
        "<table><tr><td rowspan='2' colspan='3'>x</td></tr></table>"
    )[0]
    cell = tree.children[0].children[0].children[0]
    assert cell.name == "td[rowspan=2,colspan=3]"
    assert cell.content == "x"


def test_bare_rows_get_an_implicit_tbody_so_markup_style_is_not_penalized():
    explicit = "<table><tbody><tr><td>x</td></tr></tbody></table>"
    bare = "<table><tr><td>x</td></tr></table>"
    assert table_scoring.score_tables([explicit], [bare])["teds"] == 1.0


def test_unclosed_cell_and_row_tags_are_closed_implicitly():
    tree = table_scoring.parse_tables("<table><tr><td>a<td>b<tr><td>c</table>")[0]
    body = tree.children[0]
    assert [len(row.children) for row in body.children] == [2, 1]
    assert body.children[0].children[1].content == "b"


def test_nested_markup_inside_a_cell_contributes_text_but_not_structure():
    tree = table_scoring.parse_tables(
        "<table><tr><td><p>가</p><br/><b>나</b></td></tr></table>"
    )[0]
    cell = tree.children[0].children[0].children[0]
    assert cell.content == "가 나"
    assert cell.children == []


def test_parse_returns_every_top_level_table():
    assert len(table_scoring.parse_tables("".join(TWO_TABLES))) == 2


def test_split_table_blocks_survives_markdown_fences_and_preamble():
    reply = "표는 다음과 같습니다:\n```html\n<table><tr><td>a</td></tr></table>\n```"
    assert table_scoring.split_table_blocks(reply) == [
        "<table><tr><td>a</td></tr></table>"
    ]


def test_split_table_blocks_on_empty_output_returns_nothing():
    assert table_scoring.split_table_blocks("") == []
    assert table_scoring.split_table_blocks("표가 없습니다.") == []


# --- similarity ------------------------------------------------------------


def test_identical_tables_score_one():
    assert table_scoring.score_tables([SIMPLE], [SIMPLE])["teds"] == 1.0


@pytest.mark.parametrize("sample_id", sorted(TABLE_GROUND_TRUTH))
def test_every_ground_truth_page_scores_one_against_itself(sample_id):
    ground_truth = TABLE_GROUND_TRUTH[sample_id]
    result = table_scoring.score_tables(ground_truth, ground_truth)
    assert result["teds"] == 1.0
    assert result["n_tables_gt"] == result["n_tables_pred"]


def test_a_missing_row_scores_between_zero_and_one():
    teds = table_scoring.score_tables([SIMPLE], [MISSING_ROW])["teds"]
    assert 0.0 < teds < 1.0


def test_a_completely_different_structure_scores_low():
    flat = "<table><tr><td>전부 한 칸에 들어간 텍스트</td></tr></table>"
    assert table_scoring.score_tables([SIMPLE], [flat])["teds"] < 0.4


def test_an_empty_prediction_scores_zero_and_is_flagged_as_no_prediction():
    result = table_scoring.score_tables([SIMPLE], [])
    assert result["teds"] == 0.0
    assert result["no_prediction"] is True
    assert result["missing_tables"] == 1


def test_blank_html_strings_are_treated_as_no_prediction_not_as_a_table():
    result = table_scoring.score_tables([SIMPLE], ["", "   "])
    assert result["no_prediction"] is True
    assert result["teds"] == 0.0


def test_cell_text_differences_cost_less_than_structural_ones():
    wrong_text = SIMPLE.replace("냉장고", "냉장꼬")
    dropped_cell = (
        "<table><thead><tr><th>연번</th><th>기기명</th></tr></thead>"
        "<tbody><tr><td>1</td></tr><tr><td>2</td><td>제빙기</td></tr></tbody></table>"
    )
    text_only = table_scoring.score_tables([SIMPLE], [wrong_text])["teds"]
    structural = table_scoring.score_tables([SIMPLE], [dropped_cell])["teds"]
    assert 1.0 > text_only > structural


# --- rowspan/colspan regression -------------------------------------------


def test_a_merged_cell_reemitted_as_repeated_cells_is_a_structural_error():
    """The Upstage markdown-duplication behaviour this benchmark found.

    A `rowspan=6` cell whose content is instead repeated in six separate cells
    carries the same text but a different table, so it must lose points — not
    score ~1.0 on the strength of matching text.
    """
    merged = (
        "<table><tbody>"
        "<tr><th>제목</th><td rowspan='6'>본문</td></tr>"
        "<tr><th>전문</th></tr><tr><th>총칙조항</th></tr>"
        "<tr><th>실체조항</th></tr><tr><th>효력조항</th></tr>"
        "<tr><th>부칙</th></tr></tbody></table>"
    )
    duplicated = (
        "<table><tbody>"
        "<tr><th>제목</th><td>본문</td></tr>"
        "<tr><th>전문</th><td>본문</td></tr><tr><th>총칙조항</th><td>본문</td></tr>"
        "<tr><th>실체조항</th><td>본문</td></tr><tr><th>효력조항</th><td>본문</td></tr>"
        "<tr><th>부칙</th><td>본문</td></tr></tbody></table>"
    )
    teds = table_scoring.score_tables([merged], [duplicated])["teds"]
    assert 0.0 < teds < 0.9


def test_colspan_mismatch_alone_is_detected():
    gt = "<table><tr><td colspan='2'>합계</td></tr></table>"
    pred = "<table><tr><td>합계</td></tr></table>"
    assert table_scoring.score_tables([gt], [pred])["teds"] < 1.0


# --- header-agnostic variant ----------------------------------------------


def test_header_markup_only_differences_are_forgiven_by_the_agnostic_variant():
    """CLOVA returns a bare grid; it cannot emit `<th>`/`<thead>` at all."""
    grid = SIMPLE.replace("<thead>", "<tbody>").replace("</thead>", "</tbody>")
    grid = grid.replace("<th>", "<td>").replace("</th>", "</td>")

    result = table_scoring.score_tables([SIMPLE], [grid])
    assert result["teds"] < 1.0
    assert result["teds_header_agnostic"] == 1.0


def test_the_agnostic_variant_still_penalizes_a_real_grid_error():
    result = table_scoring.score_tables([SIMPLE], [MISSING_ROW])
    assert result["teds_header_agnostic"] < 1.0


# --- multi-table matching --------------------------------------------------


def test_two_tables_are_matched_regardless_of_the_order_they_are_returned():
    result = table_scoring.score_tables(TWO_TABLES, list(reversed(TWO_TABLES)))
    assert result["teds"] == 1.0
    assert [t["pred_index"] for t in result["tables"]] == [1, 0]


def test_two_tables_returned_in_one_html_string_are_still_split_and_matched():
    result = table_scoring.score_tables(TWO_TABLES, ["".join(TWO_TABLES)])
    assert result["n_tables_pred"] == 2
    assert result["teds"] == 1.0


def test_only_one_of_two_tables_found_halves_the_page_score():
    result = table_scoring.score_tables(TWO_TABLES, [TWO_TABLES[1]])
    assert result["teds"] == pytest.approx(0.5)
    assert result["missing_tables"] == 1
    assert result["no_prediction"] is False
    assert [t["pred_index"] for t in result["tables"]] == [None, 0]


def test_an_extra_predicted_table_is_reported_but_not_penalized():
    extra = "<table><tr><td>정답에 없는 표</td></tr></table>"
    result = table_scoring.score_tables([SIMPLE], [SIMPLE, extra])
    assert result["teds"] == 1.0
    assert result["extra_tables"] == [1]
    assert result["n_tables_pred"] == 2


def test_matching_maximizes_the_total_score_rather_than_taking_the_first_fit():
    near = SIMPLE.replace("제빙기", "제빙기 2")
    result = table_scoring.score_tables([SIMPLE, MISSING_ROW], [MISSING_ROW, near])
    assert [t["pred_index"] for t in result["tables"]] == [1, 0]


def test_greedy_fallback_engages_past_the_exhaustive_limit(monkeypatch):
    monkeypatch.setattr(table_scoring, "MAX_EXHAUSTIVE_TABLES", 2)
    tables = [SIMPLE, MISSING_ROW, SIMPLE]
    result = table_scoring.score_tables(tables, tables)
    assert result["teds"] == 1.0


# --- normalization edge cases ---------------------------------------------


def test_whitespace_and_width_differences_in_cell_text_are_normalized_away():
    gt = "<table><tr><td>가맹비</td></tr></table>"
    pred = "<table><tr><td>  가맹비\n </td></tr></table>"
    assert table_scoring.score_tables([gt], [pred])["teds"] == 1.0


def test_no_ground_truth_yields_no_score_rather_than_a_perfect_one():
    result = table_scoring.score_tables([], [SIMPLE])
    assert result["teds"] is None
    assert result["n_tables_gt"] == 0
