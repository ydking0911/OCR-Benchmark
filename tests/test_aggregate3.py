import pytest

from ocr_benchmark import aggregate3, config
from ocr_benchmark.engines.base import EngineResult

REFERENCE = "제1조(목적) 본 계약은 비밀정보의 보호를 목적으로 한다."


@pytest.fixture
def corpus(tmp_path):
    """Two documents: a 3-page one and a 1-page one, mirroring the real skew."""
    gt_dir = tmp_path / "gt"
    gt_dir.mkdir()
    entries = []
    for page in range(1, 4):
        sid = f"franchise_p{page:02d}"
        (gt_dir / f"{sid}.txt").write_text(REFERENCE, encoding="utf-8")
        entries.append(
            {
                "sample_id": sid,
                "doc_slug": "franchise",
                "page_index": page,
                "page_count_in_doc": 3,
                "ground_truth_path": str(gt_dir / f"{sid}.txt"),
            }
        )
    (gt_dir / "jichul_p01.txt").write_text(REFERENCE, encoding="utf-8")
    entries.append(
        {
            "sample_id": "jichul_p01",
            "doc_slug": "jichul",
            "page_index": 1,
            "page_count_in_doc": 1,
            "ground_truth_path": str(gt_dir / "jichul_p01.txt"),
        }
    )
    return entries, gt_dir


def make_results(engine, entries, text=REFERENCE, usage=None, **kwargs):
    return [
        EngineResult(
            engine_config_id=engine,
            sample_id=entry["sample_id"],
            raw_text=text,
            usage_raw=usage if usage is not None else {"pages": 1},
            **kwargs,
        )
        for entry in entries
    ]


def aggregate(results, corpus):
    entries, gt_dir = corpus
    return aggregate3.aggregate(results, entries, gt_dir)


def test_perfect_transcription_scores_zero_error(corpus):
    entries, _ = corpus
    results = make_results("upstage_standard", entries)
    for r in results:
        r.cost_usd, r.cost_krw, r.cost_confirmed = 0.01, 13.8, True

    out = aggregate(results, corpus)
    summary = out["engines"]["upstage_standard"]
    assert summary["page_mean"]["cer"] == 0.0
    assert summary["page_mean"]["similarity_pct"] == 100.0
    assert summary["failures"] == 0
    assert out["n_pages"] == 4
    assert out["n_docs"] == 2


def test_cost_totals_and_10k_page_scaling(corpus):
    entries, _ = corpus
    results = make_results("upstage_enhanced", entries)
    for r in results:
        r.cost_usd, r.cost_krw, r.cost_confirmed = 0.03, 41.4, True

    cost = aggregate(results, corpus)["engines"]["upstage_enhanced"]["cost"]
    assert cost["total_usd"] == pytest.approx(0.12)
    assert cost["per_page_usd"] == pytest.approx(0.03)
    assert cost["per_10k_pages_usd"] == pytest.approx(300.0)
    assert cost["confirmed"] is True


def test_unconfirmed_price_yields_no_cost_rather_than_zero(corpus, monkeypatch):
    monkeypatch.setitem(config.CLOVA_PRICING, "krw_per_request", None)
    entries, _ = corpus
    results = make_results("clova_text", entries, usage={"requests": 1})

    cost = aggregate(results, corpus)["engines"]["clova_text"]["cost"]
    assert cost["confirmed"] is False
    assert cost["total_usd"] is None
    assert cost["per_10k_pages_usd"] is None


def test_cost_is_recomputed_from_usage_against_current_pricing_not_cached(corpus):
    # A cached EngineResult may carry a stale cost snapshot from whenever it
    # was first billed (e.g. Clova before its console rate was confirmed).
    # Aggregation must use current config pricing, not that stale snapshot.
    entries, _ = corpus
    results = make_results("upstage_standard", entries)
    for r in results:
        r.cost_usd, r.cost_krw, r.cost_confirmed = 999.0, 999.0, False  # stale/wrong on purpose

    cost = aggregate(results, corpus)["engines"]["upstage_standard"]["cost"]
    assert cost["confirmed"] is True
    assert cost["per_page_usd"] == pytest.approx(0.01)  # recomputed from usage_raw={"pages": 1}


def test_failed_pages_are_floor_scored_not_dropped(corpus):
    entries, _ = corpus
    results = make_results("claude_sonnet", entries)
    results[0].error = "HTTPError: 500"
    results[0].raw_text = ""

    summary = aggregate(results, corpus)["engines"]["claude_sonnet"]
    assert summary["failures"] == 1
    assert summary["n_pages"] == 4
    # Floor score is included, so the mean is pulled down rather than the page
    # quietly leaving the denominator.
    assert summary["page_mean"]["similarity_pct"] == pytest.approx(75.0)
    assert summary["page_mean"]["cer"] == pytest.approx(0.25)


def test_document_equal_weighting_differs_from_page_weighting(corpus):
    entries, _ = corpus
    results = make_results("upstage_standard", entries)
    # All three franchise pages fail; the single jichul page is perfect.
    for r in results[:3]:
        r.error = "boom"
        r.raw_text = ""

    summary = aggregate(results, corpus)["engines"]["upstage_standard"]
    # Page weighting: 1 of 4 pages good -> 25%.
    assert summary["page_mean"]["similarity_pct"] == pytest.approx(25.0)
    # Document weighting: franchise 0%, jichul 100% -> 50%.
    assert summary["doc_equal_mean"]["similarity_pct"] == pytest.approx(50.0)


def test_per_document_breakdown_counts_pages_and_failures(corpus):
    entries, _ = corpus
    results = make_results("upstage_standard", entries)
    results[0].error = "boom"
    results[0].raw_text = ""

    documents = aggregate(results, corpus)["engines"]["upstage_standard"]["documents"]
    assert documents["franchise"]["n_pages"] == 3
    assert documents["franchise"]["failures"] == 1
    assert documents["jichul"]["n_pages"] == 1
    assert documents["jichul"]["failures"] == 0


def test_multiple_engines_are_summarized_independently(corpus):
    entries, _ = corpus
    good = make_results("upstage_standard", entries)
    bad = make_results("clova_text", entries, text="완전히 다른 내용", usage={"requests": 1})

    engines = aggregate(good + bad, corpus)["engines"]
    assert set(engines) == {"upstage_standard", "clova_text"}
    assert engines["upstage_standard"]["page_mean"]["cer"] == 0.0
    assert engines["clova_text"]["page_mean"]["cer"] > 0.0


def test_reference_ratio_is_present_but_never_a_rank(corpus):
    entries, _ = corpus
    results = make_results("upstage_standard", entries)
    for r in results:
        r.cost_usd, r.cost_confirmed = 0.01, True

    summary = aggregate(results, corpus)["engines"]["upstage_standard"]
    assert summary["cost_per_1pct_similarity_usd"] == pytest.approx(0.0001)
    assert "rank" not in summary


def test_no_gate_or_pass_rate_is_computed(corpus):
    entries, _ = corpus
    out = aggregate(make_results("upstage_standard", entries), corpus)
    serialized = repr(out)
    for forbidden in ("pass_rate", "quality_gate", "cost_per_acceptable_page"):
        assert forbidden not in serialized


def test_result_for_a_sample_missing_from_the_manifest_is_an_error(corpus):
    entries, gt_dir = corpus
    stray = EngineResult(engine_config_id="upstage_standard", sample_id="ghost_p01")
    with pytest.raises(KeyError, match="ghost_p01"):
        aggregate3.aggregate([stray], entries, gt_dir)


def test_pricing_provenance_is_carried_into_the_aggregate(corpus):
    entries, _ = corpus
    pricing = aggregate(make_results("upstage_standard", entries), corpus)["pricing"]
    assert pricing["upstage"]["source_url"]
    assert pricing["upstage"]["retrieved_at"]
    # Confirmed 2026-08-11 from the NCP console: 3 KRW/request base rate.
    assert pricing["clova"]["krw_per_request"] == 3


def test_pricing_provenance_reflects_unconfirmed_when_price_is_unknown(corpus, monkeypatch):
    monkeypatch.setitem(config.CLOVA_PRICING, "krw_per_request", None)
    entries, _ = corpus
    pricing = aggregate(make_results("upstage_standard", entries), corpus)["pricing"]
    assert pricing["clova"]["krw_per_request"] is None
