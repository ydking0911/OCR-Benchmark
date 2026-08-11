import pytest

from ocr_benchmark import aggregate3, config, report3
from ocr_benchmark.engines.base import EngineResult

REFERENCE = "제1조(목적) 본 계약은 비밀정보의 보호를 목적으로 한다."


@pytest.fixture
def aggregated(tmp_path):
    gt_dir = tmp_path / "gt"
    gt_dir.mkdir()
    entries = []
    for slug, pages in (("franchise", 2), ("jichul", 1)):
        for page in range(1, pages + 1):
            sid = f"{slug}_p{page:02d}"
            (gt_dir / f"{sid}.txt").write_text(REFERENCE, encoding="utf-8")
            entries.append(
                {
                    "sample_id": sid,
                    "doc_slug": slug,
                    "page_index": page,
                    "page_count_in_doc": pages,
                    "ground_truth_path": str(gt_dir / f"{sid}.txt"),
                }
            )

    results = []
    for engine in config.ENGINE_CONFIGS:
        for entry in entries:
            usage = (
                {"requests": 1}
                if engine.startswith("clova")
                else {"input_tokens": 4784, "output_tokens": 900}
                if engine == "claude_sonnet"
                else {"pages": 1}
            )
            result = EngineResult(
                engine_config_id=engine,
                sample_id=entry["sample_id"],
                raw_text=REFERENCE,
                usage_raw=usage,
                latency_ms=1500,
            )
            cost = config.compute_cost(engine, usage)
            result.cost_usd = cost["cost_usd"]
            result.cost_krw = cost["cost_krw"]
            result.cost_confirmed = cost["cost_confirmed"]
            results.append(result)

    return aggregate3.aggregate(results, entries, gt_dir)


def test_report_has_all_required_sections(aggregated):
    markdown = report3.render(aggregated)
    for heading in (
        "## 1. 가격순 비교",
        "## 2. 기능 제공 비교",
        "## 3. 문서별 평균 유사도",
        "## 4. 참고 지표",
        "## 5. 추천 방안",
        "## 6. 한계",
    ):
        assert heading in markdown


def test_report_contains_no_pass_fail_gate(aggregated):
    markdown = report3.render(aggregated)
    for forbidden in ("pass_rate", "quality_gate", "cost_per_acceptable_page", "PASS", "FAIL"):
        assert forbidden not in markdown
    # The words 합격/불합격 appear only in the disclaimer saying there is no gate.
    assert "합격/불합격 게이트가 없습니다" in markdown


def test_every_engine_appears_in_the_price_table(aggregated):
    markdown = report3.render(aggregated)
    for cfg in config.ENGINE_CONFIGS.values():
        assert cfg["label"] in markdown


def test_price_table_is_sorted_ascending(aggregated):
    rows = report3.build_comparison_table(aggregated["engines"])[2:]
    labels = [row.split("|")[1].strip() for row in rows]

    assert labels.index(config.ENGINE_CONFIGS["upstage_standard"]["label"]) < labels.index(
        config.ENGINE_CONFIGS["upstage_enhanced"]["label"]
    )
    # All five prices are confirmed as of 2026-08-11, so the table is a plain
    # ascending sort by 1만 페이지 환산 비용.
    per10k = [
        aggregated["engines"][e]["cost"]["per_10k_pages_usd"] for e in aggregated["engines"]
    ]
    assert all(v is not None for v in per10k)
    sorted_labels = [
        aggregated["engines"][e]["label"]
        for e in sorted(aggregated["engines"], key=lambda e: aggregated["engines"][e]["cost"]["per_10k_pages_usd"])
    ]
    assert labels == sorted_labels


def test_price_table_sorts_unconfirmed_prices_last(aggregated, monkeypatch):
    # Regression guard: an engine whose price is not yet confirmed must sort
    # after every confirmed price, never as if it were free (position 0).
    monkeypatch.setitem(config.CLOVA_PRICING, "krw_per_request", None)
    entries_by_engine = {}
    for page in aggregated["pages"]:
        entries_by_engine.setdefault(page["engine_config_id"], []).append(page)
    rescored = dict(aggregated)
    rescored["engines"] = {
        eid: {
            **summary,
            "cost": {
                **summary["cost"],
                "confirmed": False if eid.startswith("clova") else summary["cost"]["confirmed"],
                "per_10k_pages_usd": None if eid.startswith("clova") else summary["cost"]["per_10k_pages_usd"],
            },
        }
        for eid, summary in aggregated["engines"].items()
    }

    rows = report3.build_comparison_table(rescored["engines"])[2:]
    labels = [row.split("|")[1].strip() for row in rows]
    confirmed_count = sum(1 for e in rescored["engines"].values() if e["cost"]["per_10k_pages_usd"] is not None)

    clova_positions = [
        labels.index(config.ENGINE_CONFIGS[e]["label"]) for e in ("clova_text", "clova_table")
    ]
    assert min(clova_positions) >= confirmed_count


def test_confirmed_clova_cost_renders_with_the_console_rate(aggregated):
    markdown = report3.render(aggregated)
    assert "글자 추출 3원/건" in markdown
    assert "미확정" not in markdown


def test_unconfirmed_clova_cost_renders_as_undetermined(tmp_path, monkeypatch):
    monkeypatch.setitem(config.CLOVA_PRICING, "krw_per_request", None)
    gt_dir = tmp_path / "gt"
    gt_dir.mkdir()
    sid = "jichul_p01"
    (gt_dir / f"{sid}.txt").write_text(REFERENCE, encoding="utf-8")
    entries = [
        {
            "sample_id": sid,
            "doc_slug": "jichul",
            "page_index": 1,
            "page_count_in_doc": 1,
            "ground_truth_path": str(gt_dir / f"{sid}.txt"),
        }
    ]
    result = EngineResult(
        engine_config_id="clova_text", sample_id=sid, raw_text=REFERENCE, usage_raw={"requests": 1}
    )
    cost = config.compute_cost("clova_text", {"requests": 1})
    result.cost_usd, result.cost_krw, result.cost_confirmed = (
        cost["cost_usd"],
        cost["cost_krw"],
        cost["cost_confirmed"],
    )
    aggregated = aggregate3.aggregate([result], entries, gt_dir)

    markdown = report3.render(aggregated)
    assert "미확정" in markdown
    assert "단가 미확정" in markdown


def test_feature_checklist_covers_all_engines_and_columns(aggregated):
    rows = report3.build_feature_table(list(aggregated["engines"]))
    assert "조항 계층" in rows[0]
    assert "체크박스" in rows[0]
    assert "결정론" in rows[0]
    assert len(rows) == 2 + len(config.ENGINE_CONFIGS)
    assert "△(근사값)" in "\n".join(rows)


def test_recommendation_section_is_left_for_a_human(aggregated):
    markdown = report3.render(aggregated)
    assert "_(작성 필요)_" in markdown
    assert "사람이 작성하는 섹션" in markdown


def test_pricing_sources_and_dates_are_disclosed(aggregated):
    markdown = report3.render(aggregated)
    assert config.UPSTAGE_PRICING["source_url"] in markdown
    assert config.UPSTAGE_PRICING["retrieved_at"] in markdown
    assert "만료 후 list price" in markdown


def test_limitations_disclose_the_known_risks(aggregated):
    markdown = report3.render(aggregated)
    assert "재조립" in markdown  # R2 harness artifact
    assert "구조 보존" in markdown  # R3 table scoring validity
    assert "48페이지" in markdown  # R5 corpus skew
    assert "effort" in markdown  # pinned thinking budget


def test_reference_ratio_is_labeled_as_not_a_rank(aggregated):
    markdown = report3.render(aggregated)
    assert "순위로 읽지 마십시오" in markdown


def test_smoke_test_note_is_stamped_in_the_header(aggregated):
    markdown = report3.render(aggregated, "SMOKE TEST — 3페이지만 실행")
    assert "SMOKE TEST" in markdown


def test_write_creates_the_file(aggregated, tmp_path):
    out = tmp_path / "nested" / "comparison.md"
    report3.write(aggregated, out)
    assert out.exists()
    assert out.read_text(encoding="utf-8").startswith("# 계약서 OCR 3-엔진 비교")
