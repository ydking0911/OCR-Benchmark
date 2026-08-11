import json

from ocr_benchmark import cache3
from ocr_benchmark.engines.base import EngineResult

SHA_A = "a" * 64
SHA_B = "b" * 64


def result(sample_id="franchise_p01", engine="upstage_standard", text="본문"):
    return EngineResult(
        engine_config_id=engine,
        sample_id=sample_id,
        raw_text=text,
        usage_raw={"pages": 1},
        cost_usd=0.01,
        cost_krw=13.8,
        cost_confirmed=True,
        latency_ms=1234,
        http_status=200,
    )


def test_fingerprint_is_stable_and_content_sensitive():
    assert cache3.fingerprint("upstage_standard", SHA_A) == cache3.fingerprint(
        "upstage_standard", SHA_A
    )
    assert cache3.fingerprint("upstage_standard", SHA_A) != cache3.fingerprint(
        "upstage_enhanced", SHA_A
    )
    assert cache3.fingerprint("upstage_standard", SHA_A) != cache3.fingerprint(
        "upstage_standard", SHA_B
    )


def test_miss_on_empty_cache(tmp_path):
    assert cache3.load(tmp_path, "upstage_standard", "franchise_p01", SHA_A) is None


def test_store_then_load_round_trips_every_field(tmp_path):
    original = result()
    cache3.store(tmp_path, original, SHA_A)
    loaded = cache3.load(tmp_path, "upstage_standard", "franchise_p01", SHA_A)

    assert loaded is not None
    assert loaded.to_dict() == original.to_dict()


def test_changed_image_hash_misses_instead_of_serving_stale(tmp_path):
    cache3.store(tmp_path, result(), SHA_A)
    assert cache3.load(tmp_path, "upstage_standard", "franchise_p01", SHA_B) is None


def test_entries_are_namespaced_per_engine_config(tmp_path):
    cache3.store(tmp_path, result(engine="upstage_standard", text="standard"), SHA_A)
    cache3.store(tmp_path, result(engine="upstage_enhanced", text="enhanced"), SHA_A)

    standard = cache3.load(tmp_path, "upstage_standard", "franchise_p01", SHA_A)
    enhanced = cache3.load(tmp_path, "upstage_enhanced", "franchise_p01", SHA_A)
    assert standard.raw_text == "standard"
    assert enhanced.raw_text == "enhanced"


def test_cache_path_layout_is_engine_then_sample(tmp_path):
    path = cache3.store(tmp_path, result(), SHA_A)
    assert path == tmp_path / "upstage_standard" / "franchise_p01.json"


def test_stored_payload_records_the_image_hash_for_debugging(tmp_path):
    path = cache3.store(tmp_path, result(), SHA_A)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["image_sha256"] == SHA_A
    assert payload["fingerprint"] == cache3.fingerprint("upstage_standard", SHA_A)


def test_failed_results_are_cached_too_so_reruns_do_not_silently_repay(tmp_path):
    failed = EngineResult(
        engine_config_id="clova_text",
        sample_id="jichul_p01",
        error="HTTPError: 500",
        http_status=500,
    )
    cache3.store(tmp_path, failed, SHA_A)
    loaded = cache3.load(tmp_path, "clova_text", "jichul_p01", SHA_A)
    assert loaded.error == "HTTPError: 500"
    assert loaded.ok is False


def test_from_dict_ignores_unknown_fields(tmp_path):
    payload = result().to_dict()
    payload["future_field"] = "added by a later version"
    assert EngineResult.from_dict(payload).sample_id == "franchise_p01"
