import pytest

from ocr_benchmark import aggregate3, config
from ocr_benchmark.engines.base import EngineResult
from ocr_benchmark.table_ground_truth import TABLE_GROUND_TRUTH

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


# --- table structure (TEDS) aggregation ------------------------------------


def table_result(engine, sample_id, htmls=None, **kwargs):
    usage = (
        {"pages": 1}
        if engine.startswith("upstage")
        else {"pages_processed": 1}
        if engine == "mistral_ocr"
        else {"requests": 1}
    )
    return EngineResult(
        engine_config_id=engine,
        sample_id=sample_id,
        table_htmls=TABLE_GROUND_TRUTH[sample_id] if htmls is None else htmls,
        usage_raw=usage,
        **kwargs,
    )


def perfect_table_results(engine):
    return [table_result(engine, sid) for sid in TABLE_GROUND_TRUTH]


def test_text_only_aggregation_has_no_table_section(corpus):
    """A run that never did table extraction reports exactly what it always did."""
    entries, gt_dir = corpus
    results = make_results("upstage_standard", entries)
    assert "tables" not in aggregate(results, corpus)
    assert "tables" not in aggregate3.aggregate(results, entries, gt_dir, [])


def test_perfect_table_extraction_scores_one(corpus):
    entries, gt_dir = corpus
    out = aggregate3.aggregate(
        make_results("upstage_standard", entries),
        entries,
        gt_dir,
        perfect_table_results("upstage_standard"),
    )
    summary = out["tables"]["engines"]["upstage_standard"]
    assert summary["teds_mean"] == 1.0
    assert summary["n_pages"] == len(TABLE_GROUND_TRUTH)
    assert summary["pages_with_no_prediction"] == 0
    assert summary["missing_tables"] == 0


def test_a_page_without_table_ground_truth_never_appears(corpus):
    entries, gt_dir = corpus
    results = perfect_table_results("upstage_standard")
    results.append(
        EngineResult(
            engine_config_id="upstage_standard",
            sample_id="gyeongeop_p01",  # confirmed to have no table
            table_htmls=["<table><tr><td>환각</td></tr></table>"],
            usage_raw={"pages": 1},
        )
    )
    tables = aggregate3.aggregate(
        make_results("upstage_standard", entries), entries, gt_dir, results
    )["tables"]

    assert "gyeongeop_p01" not in tables["scored_sample_ids"]
    assert set(tables["scored_sample_ids"]) == set(TABLE_GROUND_TRUTH)
    assert all(p["sample_id"] in TABLE_GROUND_TRUTH for p in tables["pages"])


def test_engines_that_cannot_return_table_structure_are_excluded(corpus):
    entries, gt_dir = corpus
    results = perfect_table_results("upstage_standard") + perfect_table_results("clova_text")
    engines = aggregate3.aggregate(
        make_results("upstage_standard", entries), entries, gt_dir, results
    )["tables"]["engines"]

    assert "clova_text" not in engines
    assert "upstage_standard" in engines


def test_an_engine_returning_no_table_is_distinguished_from_a_wrong_one(corpus):
    entries, gt_dir = corpus
    silent = [table_result("clova_table", sid, htmls=[]) for sid in TABLE_GROUND_TRUTH]
    wrong = [
        table_result("upstage_standard", sid, htmls=["<table><tr><td>x</td></tr></table>"])
        for sid in TABLE_GROUND_TRUTH
    ]
    engines = aggregate3.aggregate(
        make_results("upstage_standard", entries), entries, gt_dir, silent + wrong
    )["tables"]["engines"]

    assert engines["clova_table"]["pages_with_no_prediction"] == len(TABLE_GROUND_TRUTH)
    assert engines["clova_table"]["teds_mean"] == 0.0
    assert engines["upstage_standard"]["pages_with_no_prediction"] == 0
    assert 0.0 < engines["upstage_standard"]["teds_mean"] < 1.0


def test_failed_table_calls_are_floor_scored_not_dropped(corpus):
    entries, gt_dir = corpus
    results = perfect_table_results("upstage_standard")
    results[0].error = "HTTPError: 500"
    results[0].table_htmls = []

    summary = aggregate3.aggregate(
        make_results("upstage_standard", entries), entries, gt_dir, results
    )["tables"]["engines"]["upstage_standard"]

    assert summary["failures"] == 1
    assert summary["n_pages"] == len(TABLE_GROUND_TRUTH)
    assert summary["teds_mean"] < 1.0


def test_the_page_split_pair_is_reported_separately_from_the_headline_mean(corpus):
    entries, gt_dir = corpus
    results = []
    for sid in TABLE_GROUND_TRUTH:
        # Every page perfect except the known-hard page-boundary pair.
        htmls = [] if sid in aggregate3.KNOWN_HARD_TABLE_SAMPLE_IDS else None
        results.append(table_result("upstage_standard", sid, htmls=htmls))

    tables = aggregate3.aggregate(
        make_results("upstage_standard", entries), entries, gt_dir, results
    )["tables"]
    summary = tables["engines"]["upstage_standard"]

    assert tables["known_hard_sample_ids"] == ["franchise_p12", "franchise_p13"]
    assert summary["teds_mean"] < 1.0
    assert summary["teds_mean_excluding_known_hard"] == 1.0
    assert summary["n_pages_excluding_known_hard"] == len(TABLE_GROUND_TRUTH) - 2


def test_header_agnostic_scoring_does_not_penalize_a_bare_cell_grid(corpus):
    entries, gt_dir = corpus
    sid = "franchise_p47"
    grid = [
        TABLE_GROUND_TRUTH[sid][0]
        .replace("<thead>", "<tbody>")
        .replace("</thead>", "</tbody>")
        .replace("<th>", "<td>")
        .replace("</th>", "</td>")
    ]
    result = table_result("clova_table", sid, htmls=grid)

    summary = aggregate3.aggregate(
        make_results("upstage_standard", entries), entries, gt_dir, [result]
    )["tables"]["engines"]["clova_table"]

    assert summary["teds_mean"] < 1.0
    assert summary["teds_header_agnostic_mean"] == 1.0


def test_a_fifth_engine_is_aggregated_from_the_registry_alone(corpus):
    """Registering `mistral_ocr` is the whole integration — no code path names it.

    Both pipelines derive their engine list from the results handed to them
    (text) or from `TABLE_CAPABLE_ENGINE_CONFIGS` (tables), so a sixth engine
    later should need no further patching here either.
    """
    entries, gt_dir = corpus
    out = aggregate3.aggregate(
        make_results("mistral_ocr", entries, usage={"pages_processed": 1}),
        entries,
        gt_dir,
        perfect_table_results("mistral_ocr"),
    )

    summary = out["engines"]["mistral_ocr"]
    assert summary["label"] == config.ENGINE_CONFIGS["mistral_ocr"]["label"]
    assert summary["cost"]["confirmed"] is True
    assert summary["cost"]["per_page_usd"] == pytest.approx(0.004)
    assert summary["cost"]["per_10k_pages_usd"] == pytest.approx(40.0)
    assert out["pricing"]["mistral"]["source_url"]

    # Same config id serves the table pipeline, unlike Claude's separate one.
    assert out["tables"]["engines"]["mistral_ocr"]["teds_mean"] == 1.0
    assert out["tables"]["engines"]["mistral_ocr"]["n_pages"] == len(TABLE_GROUND_TRUTH)


def test_table_aggregation_computes_no_gate_or_pass_rate(corpus):
    entries, gt_dir = corpus
    out = aggregate3.aggregate(
        make_results("upstage_standard", entries),
        entries,
        gt_dir,
        perfect_table_results("upstage_standard"),
    )
    serialized = repr(out["tables"])
    for forbidden in ("pass_rate", "quality_gate", "threshold", "rank"):
        assert forbidden not in serialized
