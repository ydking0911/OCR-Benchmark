from ocr_benchmark import scoring


def test_normalize_collapses_whitespace_and_applies_nfkc():
    assert scoring.normalize("  가나\n\t다  라 ") == "가나 다 라"
    # NFKC folds the fullwidth form onto the ASCII one.
    assert scoring.normalize("ＡＢ") == "AB"


def test_identical_text_scores_perfectly():
    result = scoring.score("제1조 목적", "제1조 목적")
    assert result["cer"] == 0.0
    assert result["wer"] == 0.0
    assert result["similarity_pct"] == 100.0


def test_whitespace_only_difference_is_normalized_away():
    assert scoring.score("제1조  목적", "제1조\n목적")["cer"] == 0.0


def test_partial_match_scores_between_bounds():
    result = scoring.score("가나다라마", "가나다라")
    assert 0.0 < result["cer"] < 1.0
    assert 0.0 < result["similarity_pct"] < 100.0


def test_empty_hypothesis_is_a_total_miss():
    result = scoring.score("가나다라마", "")
    assert result["cer"] == 1.0
    assert result["similarity_pct"] == 0.0


def test_empty_reference_yields_no_rates_instead_of_dividing_by_zero():
    result = scoring.score("", "무언가")
    assert result["cer"] is None
    assert result["wer"] is None
    assert result["reference_empty"] is True


def test_floor_score_is_the_worst_possible_score():
    floored = scoring.floor_score("제1조 목적")
    assert floored["cer"] == 1.0
    assert floored["wer"] == 1.0
    assert floored["similarity_pct"] == 0.0
    assert floored["hyp_chars"] == 0


def test_floor_score_on_empty_reference_has_no_rates():
    assert scoring.floor_score("")["cer"] is None
