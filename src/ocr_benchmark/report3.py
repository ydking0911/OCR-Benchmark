"""Markdown comparison report: price-ranked table, feature checklist, and an
empty recommendation section for a human to complete.

The recommendation is deliberately left blank. This benchmark has no quality
gate, so "which engine is better" is not something it can compute — a person
reads the numbers and decides.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import config

FEATURE_HEADERS = ["bbox", "조항 계층", "체크박스", "결정론"]
FEATURE_KEYS = ["bbox", "clause_hierarchy", "checkbox", "deterministic"]


def _fmt(value: float | None, digits: int = 4, suffix: str = "") -> str:
    return "미측정" if value is None else f"{value:.{digits}f}{suffix}"


def _fmt_cost(value: float | None, digits: int = 2, prefix: str = "$") -> str:
    return "미확정" if value is None else f"{prefix}{value:,.{digits}f}"


def _price_sort_key(summary: dict[str, Any]) -> tuple[int, float]:
    """Unconfirmed prices sort last rather than being treated as free."""
    per_10k = summary["cost"]["per_10k_pages_usd"]
    return (1, 0.0) if per_10k is None else (0, per_10k)


def build_comparison_table(engines: dict[str, Any]) -> list[str]:
    rows = [
        "| 엔진 구성 | 1만 페이지 환산 비용 | 페이지당 단가 | CER | WER | 유사도(%) | 실패 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in sorted(engines.values(), key=_price_sort_key):
        mean = summary["page_mean"]
        rows.append(
            "| {label} | {per10k} | {perpage} | {cer} | {wer} | {sim} | {fail} |".format(
                label=summary["label"],
                per10k=_fmt_cost(summary["cost"]["per_10k_pages_usd"]),
                perpage=_fmt_cost(summary["cost"]["per_page_usd"], digits=5),
                cer=_fmt(mean["cer"]),
                wer=_fmt(mean["wer"]),
                sim=_fmt(mean["similarity_pct"], digits=2),
                fail=f"{summary['failures']}/{summary['n_pages']}",
            )
        )
    return rows


def build_feature_table(engine_ids: list[str]) -> list[str]:
    rows = [
        "| 엔진 구성 | " + " | ".join(FEATURE_HEADERS) + " |",
        "|---|" + "---|" * len(FEATURE_HEADERS),
    ]
    for engine_id in engine_ids:
        features = config.FEATURE_CHECKLIST[engine_id]
        cells = " | ".join(features[key] for key in FEATURE_KEYS)
        rows.append(f"| {config.ENGINE_CONFIGS[engine_id]['label']} | {cells} |")
    return rows


def build_document_table(engines: dict[str, Any]) -> list[str]:
    doc_slugs = sorted({slug for s in engines.values() for slug in s["documents"]})
    # Header shows the Korean document title, not the bare ASCII doc_slug, so
    # a reader isn't left decoding "gyeongeop"/"bimil_seoyak_jaejik" by hand.
    titles = {}
    for slug in doc_slugs:
        for summary in engines.values():
            doc = summary["documents"].get(slug)
            if doc:
                titles[slug] = doc.get("doc_title", slug)
                break
    headers = [f"{titles.get(slug, slug)} ({slug})" for slug in doc_slugs]
    rows = [
        "| 엔진 구성 | " + " | ".join(headers) + " |",
        "|---|" + "---|" * len(doc_slugs),
    ]
    for summary in engines.values():
        cells = []
        for slug in doc_slugs:
            doc = summary["documents"].get(slug)
            cells.append(_fmt(doc["similarity_pct"], digits=1) if doc else "-")
        rows.append(f"| {summary['label']} | " + " | ".join(cells) + " |")
    return rows


def build_table_summary(table_engines: dict[str, Any]) -> list[str]:
    rows = [
        "| 엔진 구성 | id | TEDS 평균 | TEDS(헤더 무시) | 경계분할 제외 TEDS | 표 미검출 | 누락 표 | 채점 페이지 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for summary in sorted(
        table_engines.values(),
        key=lambda s: (s["teds_mean"] is None, -(s["teds_mean"] or 0.0)),
    ):
        rows.append(
            "| {label} | `{eid}` | {teds} | {agnostic} | {normal} | {nopred} | {missing} | {n} |".format(
                label=summary["label"],
                eid=summary["engine_config_id"],
                teds=_fmt(summary["teds_mean"], digits=3),
                agnostic=_fmt(summary["teds_header_agnostic_mean"], digits=3),
                normal=_fmt(summary["teds_mean_excluding_known_hard"], digits=3),
                nopred=f"{summary['pages_with_no_prediction']}/{summary['n_pages']}",
                missing=summary["missing_tables"],
                n=summary["n_pages"],
            )
        )
    return rows


def build_table_page_matrix(tables: dict[str, Any]) -> list[str]:
    engine_ids = list(tables["engines"])
    sample_ids = tables["scored_sample_ids"]
    known_hard = set(tables["known_hard_sample_ids"])

    by_key = {
        (page["engine_config_id"], page["sample_id"]): page for page in tables["pages"]
    }
    rows = [
        "| 페이지 | " + " | ".join(engine_ids) + " |",
        "|---|" + "---:|" * len(engine_ids),
    ]
    for sample_id in sample_ids:
        cells = []
        for engine_id in engine_ids:
            page = by_key.get((engine_id, sample_id))
            if page is None:
                cells.append("-")
            elif page["no_prediction"]:
                cells.append("표 미검출")
            else:
                cells.append(_fmt(page["teds"], digits=3))
        marker = " ※" if sample_id in known_hard else ""
        rows.append(f"| {sample_id}{marker} | " + " | ".join(cells) + " |")
    return rows


def build_table_section(tables: dict[str, Any]) -> list[str]:
    if not tables.get("engines"):
        return []

    known_hard = ", ".join(f"`{s}`" for s in tables["known_hard_sample_ids"])
    return [
        "## 7. 표 구조 정확도 (TEDS)",
        "",
        "> 6절 R3(표 추출의 구조 보존 가치가 텍스트 채점에 반영되지 않는다)를 보완하는 "
        "별도 채점입니다. 범위와 대상 엔진이 다르므로 1절 표와 직접 비교하지 마십시오.",
        "",
        f"- 대상: 사람이 직접 검수해 정의한 표 정답 {tables['n_ground_truth_pages']}페이지 중 "
        f"{tables['n_pages']}페이지 채점 (전체 65페이지 텍스트 채점과 범위가 다름)",
        "- 대상 엔진: 구조화된 표를 반환할 수 있는 구성만. "
        "`clova_text`는 표 검출을 요청하지 않으므로 채점 대상이 아님",
        "- 지표: TEDS = 1 - (트리 편집 거리 / max(정답 노드 수, 예측 노드 수)), 0~1. "
        "PubTabNet·DP-Bench와 같은 계열이며 `rowspan`/`colspan`은 셀의 구조적 정체성에 "
        "포함됩니다(병합 셀을 여러 칸으로 복제하면 감점).",
        "",
        *build_table_summary(tables["engines"]),
        "",
        "- **TEDS(헤더 무시)**: `<th>`/`<thead>`를 `<td>`/`<tbody>`로 평탄화한 변형입니다. "
        "CLOVA General OCR은 머리글 개념 자체가 없는 셀 격자를 반환하므로, 엄격 TEDS만 "
        "보면 제공하지 않는 기능 때문에 감점된 것처럼 보입니다. 두 값을 함께 읽으십시오.",
        "- **표 미검출**은 '표를 하나도 반환하지 않은 페이지 수'이고, 낮은 TEDS는 "
        "'표는 반환했으나 구조가 틀린' 경우입니다. 둘은 다른 문제입니다.",
        "",
        "### 7.1 페이지별 TEDS",
        "",
        "열 머리글은 위 표의 `id` 열과 같습니다.",
        "",
        *build_table_page_matrix(tables),
        "",
        f"※ {known_hard}: 하나의 실제 표가 물리적 페이지 경계에서 잘린 **알려진 난해 사례**입니다. "
        "정답을 각 페이지에 '보이는 그대로' 정의했기 때문에(설계 결정), 한 페이지만 보는 어떤 "
        "OCR 호출도 완전히 복원할 수 없습니다. 여기의 낮은 점수는 엔진 결함이 아니라 페이지 "
        "분할 자체의 한계이며, 위 표의 '경계분할 제외 TEDS' 열이 이 두 페이지를 뺀 값입니다.",
        "",
        "### 7.2 표 채점의 한계",
        "",
        f"- 표본이 {tables['n_pages']}페이지뿐이라 페이지 하나가 평균을 크게 움직입니다. "
        "서술적으로만 읽으십시오.",
        "- 표 정답은 사람이 렌더 이미지를 보고 작성한 것이며, 셀 텍스트 표기(띄어쓰기 등)에 "
        "작성자의 판단이 들어가 있습니다.",
        "- 텍스트 채점과 마찬가지로 합격 기준선은 없습니다. 수치만 제시합니다.",
        "",
    ]


def render(aggregated: dict[str, Any], run_note: str = "") -> str:
    engines = aggregated["engines"]
    engine_ids = list(engines)
    pricing = aggregated["pricing"]
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    lines: list[str] = [
        "# 계약서 OCR 3-엔진 비교 (Upstage / Naver Clova / Claude Vision)",
        "",
        f"- 생성 시각: {generated_at}",
        f"- 대상: {aggregated['n_docs']}개 문서 / {aggregated['n_pages']}개 페이지",
        f"- 정답 텍스트: PyMuPDF `page.get_text()`",
        f"- 렌더링: 장변 {config.RENDER_LONG_EDGE_PX}px JPEG",
    ]
    if run_note:
        lines.append(f"- 비고: {run_note}")
    lines += [
        "",
        "> 이 리포트에는 합격/불합격 게이트가 없습니다. 원시 정확도와 실비용만 제시하며,",
        "> 어떤 엔진을 쓸지는 아래 표를 사람이 읽고 판단합니다(설계 의도).",
        "",
        "## 1. 가격순 비교 (1만 페이지 환산 오름차순)",
        "",
        *build_comparison_table(engines),
        "",
        f"- 환산 기준: 페이지당 단가 x {aggregated['cost_scale_pages']:,}페이지",
        f"- USD/KRW 환율(참고 표기용): {pricing['usd_krw_rate']:,.0f} "
        f"({pricing['usd_krw_rate_as_of']} 기준)",
        "",
        "### 단가 출처",
        "",
        f"- Upstage: {pricing['upstage']['source_url']} "
        f"(조회 {pricing['upstage']['retrieved_at']}) — Standard "
        f"${pricing['upstage']['standard']['usd_per_page']}/page, Enhanced "
        f"${pricing['upstage']['enhanced']['usd_per_page']}/page. "
        f"{pricing['upstage']['notes']}",
        f"- Claude Sonnet 5: {pricing['claude']['source_url']} "
        f"(조회 {pricing['claude']['retrieved_at']}) — 입력 "
        f"${pricing['claude']['claude-sonnet-5']['input']}/MTok, 출력 "
        f"${pricing['claude']['claude-sonnet-5']['output']}/MTok. "
        f"{pricing['claude']['notes']} 만료 후 list price는 입력 "
        f"${pricing['claude_post_expiry']['claude-sonnet-5']['input']}/MTok, 출력 "
        f"${pricing['claude_post_expiry']['claude-sonnet-5']['output']}/MTok"
        f"({pricing['claude_post_expiry']['effective_from']}부터).",
    ]

    if pricing["clova"]["krw_per_request"] is None:
        lines += [
            "- **Naver CLOVA: 단가 미확정.** 공개 페이지에서 확인되지 않으며 콘솔의 계약 "
            "요금제에 따라 달라집니다. 추정치를 최종 수치처럼 표기하지 않기 위해 비용 "
            "칸을 `미확정`으로 남겼습니다. NCP 콘솔에서 실제 건당 단가를 확인한 뒤 "
            "`config.CLOVA_PRICING`을 채우고 재생성하십시오.",
        ]
    else:
        source = pricing["clova"]["source_url"] or "NCP 콘솔(공개 URL 없음, 사용자 확인)"
        lines += [
            f"- Naver CLOVA: {source} (조회 {pricing['clova']['retrieved_at']}) — "
            f"글자 추출 {pricing['clova']['krw_per_request']}원/건, 표 추출 옵션 시 "
            f"+{pricing['clova']['table_krw_per_request']}원/건 추가. "
            f"{pricing['clova'].get('notes', '')}",
        ]

    lines += [
        "",
        "## 2. 기능 제공 비교 (정적 체크리스트 — 본 벤치마크가 측정한 값이 아님)",
        "",
        *build_feature_table(engine_ids),
        "",
        "○ 제공 / △ 부분 제공 또는 근사 / ✕ 미제공",
        "",
        "## 3. 문서별 평균 유사도(%)",
        "",
        *build_document_table(engines),
        "",
        "## 4. 참고 지표 (순위 아님)",
        "",
        "| 엔진 구성 | 유사도 1%당 비용 | 문서 동등가중 CER | 평균 지연(ms) |",
        "|---|---:|---:|---:|",
    ]
    for summary in sorted(engines.values(), key=_price_sort_key):
        lines.append(
            "| {label} | {ratio} | {cer} | {latency} |".format(
                label=summary["label"],
                ratio=_fmt_cost(summary["cost_per_1pct_similarity_usd"], digits=6),
                cer=_fmt(summary["doc_equal_mean"]["cer"]),
                latency=_fmt(summary["latency_ms_mean"], digits=0),
            )
        )

    lines += [
        "",
        "> 유사도 1%당 비용은 **비용 지배적**이라 값싼 엔진이 구조적으로 유리합니다.",
        "> 참고용일 뿐 순위로 읽지 마십시오.",
        "",
        "## 5. 추천 방안",
        "",
        "<!-- 아래는 사람이 작성하는 섹션입니다. 위 수치를 보고 채우십시오. -->",
        "",
        "### 5.1 권장 엔진과 근거",
        "",
        "_(작성 필요)_",
        "",
        "### 5.2 대안 / 조건부 선택",
        "",
        "_(작성 필요)_",
        "",
        "### 5.3 남은 확인 사항",
        "",
        "- [ ] NCP 콘솔에서 CLOVA 실제 건당 단가 확인",
        "- [ ] 표/체크박스가 중요한 문서에서 Enhanced 대비 실익 검토",
        "",
        "## 6. 한계 (Limitations)",
        "",
        "- **정답 자체의 한계**: 정답은 PDF에 내장된 텍스트 레이어(PyMuPDF)이며 사람이 "
        "검수한 전사가 아닙니다. 실물 스캔이 아닌 클린 렌더 코퍼스입니다.",
        "- **텍스트 재조립 아티팩트(R2)**: Upstage/Clova는 위치 기반 필드를 반환하므로 "
        "본 하네스가 읽기 순서로 재조립합니다. CER/WER에는 엔진의 문자 인식 정확도뿐 "
        "아니라 이 재조립 품질이 함께 반영됩니다.",
        "- **표 추출 채점의 타당성(R3)**: Clova 표 추출 모드의 가치는 구조 보존인데 "
        "텍스트로 평탄화해 채점하므로 지표에 반영되지 않습니다. 표 관련 판단은 2절의 "
        "기능 체크리스트로 하십시오.",
        "- **게이트 부재(R4)**: 품질 기준선이 없으므로 리포트는 우열을 결론짓지 않습니다.",
        "- **표본 편중(R5)**: 65페이지 중 48페이지가 프랜차이즈계약서 한 건에서 나옵니다. "
        "문서 간 비교는 상관된 표본이며 서술적 수준으로만 읽어야 합니다.",
        f"- **Claude 사고 예산 고정**: `effort={config.CLAUDE_EFFORT}`로 비용 통제를 위해 "
        "고정했습니다. 이 축소된 사고 예산이 Sonnet 5의 품질을 체계적으로 낮췄을 수 "
        "있습니다.",
        "",
    ]

    if aggregated.get("tables"):
        lines += build_table_section(aggregated["tables"])

    return "\n".join(lines)


def write(aggregated: dict[str, Any], out_path: Path, run_note: str = "") -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(aggregated, run_note), encoding="utf-8")
    return out_path
