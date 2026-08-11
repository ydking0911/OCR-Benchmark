import json

import pymupdf
import pytest

from ocr_benchmark import config, ground_truth


def make_pdf(path, pages_text):
    doc = pymupdf.open()
    for text in pages_text:
        page = doc.new_page()
        # The built-in "korea" CJK font is required: Helvetica has no Hangul
        # glyphs, so the extracted text layer would come back empty and every
        # page would trip the low-text flag.
        page.insert_text((72, 72), text, fontsize=11, fontname="korea")
    doc.save(str(path))
    doc.close()


def record(sample_id, text, low_text=False, accept=False, slug="doc"):
    ratio, nonspace = ground_truth.hangul_ratio(text)
    return ground_truth.PageRecord(
        sample_id=sample_id,
        doc_slug=slug,
        doc_title=slug,
        page_index=1,
        page_count_in_doc=1,
        text=text,
        hangul_ratio=ratio,
        nonspace_char_count=nonspace,
        low_text=low_text,
        accept_low_text=accept,
    )


# --- sample_id / slug derivation -------------------------------------------


def test_trailing_space_in_filename_is_stripped():
    assert config.doc_slug("프랜차이즈계약서 ") == "franchise"
    assert config.doc_slug("프랜차이즈계약서") == "franchise"


def test_the_three_bimil_stems_get_distinct_slugs():
    slugs = {
        config.doc_slug("비밀유지계약서"),
        config.doc_slug("비밀유지서약서_입사자"),
        config.doc_slug("비밀유지서약서_재직자"),
    }
    assert slugs == {"bimil_gyeyak", "bimil_seoyak_ipsa", "bimil_seoyak_jaejik"}


def test_unmapped_stem_falls_back_to_a_stable_hash():
    first = config.doc_slug("새로운문서")
    assert first == config.doc_slug("새로운문서")
    assert len(first) == 10
    assert first not in config.DOC_SLUG_MAP.values()


def test_sample_id_is_zero_padded_and_one_based():
    assert config.sample_id("franchise", 1) == "franchise_p01"
    assert config.sample_id("franchise", 48) == "franchise_p48"


# --- hangul ratio ----------------------------------------------------------


def test_hangul_ratio_denominator_excludes_whitespace():
    # A table-ish page: heavy padding, but every non-space char is Hangul.
    ratio, nonspace = ground_truth.hangul_ratio("가   나\t\t다\n\n라")
    assert ratio == 1.0
    assert nonspace == 4


def test_hangul_ratio_of_empty_text_is_zero():
    assert ground_truth.hangul_ratio("   \n  ") == (0.0, 0)


def test_low_text_flags_on_ratio_and_on_tiny_denominator():
    assert ground_truth.is_low_text(0.10, 500) is True
    assert ground_truth.is_low_text(0.95, 5) is True
    assert ground_truth.is_low_text(0.95, 500) is False


# --- corpus gate -----------------------------------------------------------


def test_healthy_corpus_passes():
    records = [record(f"doc_p{i:02d}", "계약서 본문 내용입니다 " * 5) for i in range(10)]
    summary = ground_truth.check_corpus_validity(records)
    assert summary["n_pages"] == 10
    assert summary["unapproved_low_text_pages"] == []


def test_one_sparse_page_is_flagged_not_aborted():
    records = [record(f"doc_p{i:02d}", "계약서 본문 내용입니다 " * 5) for i in range(9)]
    records.append(record("doc_p09", "..", low_text=True))
    summary = ground_truth.check_corpus_validity(records)
    assert summary["low_text_pages"] == ["doc_p09"]


def test_corpus_wide_hangul_failure_aborts():
    records = [record(f"doc_p{i:02d}", "Latin only text here " * 5) for i in range(10)]
    with pytest.raises(ground_truth.GroundTruthAbort, match="hangul_ratio"):
        ground_truth.check_corpus_validity(records)


def test_corpus_wide_hangul_failure_is_not_clearable_by_approval():
    records = [
        record(f"doc_p{i:02d}", "Latin only text here " * 5, low_text=True, accept=True)
        for i in range(10)
    ]
    with pytest.raises(ground_truth.GroundTruthAbort, match="hangul_ratio"):
        ground_truth.check_corpus_validity(records)


def test_too_many_unapproved_low_text_pages_aborts():
    records = [record(f"doc_p{i:02d}", "계약서 본문 내용입니다 " * 20) for i in range(5)]
    records += [
        record(f"doc_s{i:02d}", "..", low_text=True)
        for i in range(config.CORPUS_LOW_TEXT_ABORT_N)
    ]
    with pytest.raises(ground_truth.GroundTruthAbort, match="unapproved low_text"):
        ground_truth.check_corpus_validity(records)


def test_approving_enough_pages_clears_the_abort():
    n = config.CORPUS_LOW_TEXT_ABORT_N
    healthy = [record(f"doc_p{i:02d}", "계약서 본문 내용입니다 " * 20) for i in range(5)]

    def sparse(approved_count):
        # One more low-text page than the abort threshold, so approving exactly
        # one still leaves the counter at the threshold.
        return healthy + [
            record(f"doc_s{i:02d}", "..", low_text=True, accept=i < approved_count)
            for i in range(n + 1)
        ]

    one_approval_short = sparse(approved_count=1)
    with pytest.raises(ground_truth.GroundTruthAbort, match="unapproved low_text"):
        ground_truth.check_corpus_validity(one_approval_short)

    summary = ground_truth.check_corpus_validity(sparse(approved_count=2))
    assert len(summary["unapproved_low_text_pages"]) == n - 1
    assert len(summary["low_text_pages"]) == n + 1


# --- end-to-end on a synthetic corpus --------------------------------------


def test_prepare_writes_manifest_images_and_text(tmp_path):
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    make_pdf(pdf_dir / "업무협약서.pdf", ["가나다라마바사아자차카타파하 " * 4] * 2)

    manifest_path = tmp_path / "manifest.json"
    summary = ground_truth.prepare(
        pdf_dir, tmp_path / "images", tmp_path / "gt", manifest_path
    )

    assert summary["n_pages"] == 2
    assert summary["n_docs"] == 1

    entries = json.loads(manifest_path.read_text(encoding="utf-8"))["entries"]
    assert [e["sample_id"] for e in entries] == ["eopmu_p01", "eopmu_p02"]
    for entry in entries:
        assert (tmp_path / "images" / f"{entry['sample_id']}.jpg").exists()
        assert (tmp_path / "gt" / f"{entry['sample_id']}.txt").exists()
        assert len(entry["image_sha256"]) == 64
        assert max(entry["render_px"]) == config.RENDER_LONG_EDGE_PX
        assert entry["page_count_in_doc"] == 2


def test_manifest_is_ordered_by_doc_slug_then_page(tmp_path):
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    make_pdf(pdf_dir / "업무협약서.pdf", ["가나다라마 " * 8] * 2)
    make_pdf(pdf_dir / "지출결의서.pdf", ["가나다라마 " * 8])

    manifest_path = tmp_path / "manifest.json"
    ground_truth.prepare(pdf_dir, tmp_path / "images", tmp_path / "gt", manifest_path)
    entries = ground_truth.load_manifest(manifest_path)
    assert [e["sample_id"] for e in entries] == ["eopmu_p01", "eopmu_p02", "jichul_p01"]


def test_empty_pdf_dir_aborts(tmp_path):
    (tmp_path / "pdfs").mkdir()
    with pytest.raises(ground_truth.GroundTruthAbort, match="no PDFs"):
        ground_truth.build_records(tmp_path / "pdfs", tmp_path / "i", tmp_path / "g")
