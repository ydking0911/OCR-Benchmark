"""Human-curated table-structure ground truth for TEDS scoring.

Scope: 9 pages out of 65 (see `.omc/plans/plan-upstage-clova-claude-ocr-benchmark.md`,
Appendix A). PyMuPDF `find_tables()` auto-extraction was rejected as ground
truth after manual review found extensive false positives (numbered clauses
in `franchise` pp.8-11/14-39 misdetected as ~1-row tables). Every page below
was visually confirmed against its rendered image (or, for `eopmu_p01` /
`jichul_p01`, against Upstage's independently-verified `content.html`, which
was cross-checked and found structurally correct — see plan §5.0).

Each entry is a list of table HTML strings in reading order (most pages have
exactly one table; `franchise_p13` has two). HTML is the TEDS input format:
plain `<table>`/`<thead>`/`<tbody>`/`<tr>`/`<td>`/`<th>` with `rowspan`/
`colspan` where applicable, no styling attributes (structure and cell text
only — matches what `table_scoring.py` parses into a tree).

`franchise_p12` / `franchise_p13`'s first table is a known-hard case: a real
row is split by the physical page boundary. Per the plan's explicit decision,
ground truth reflects exactly what is visible on each page — p12's row is
left incomplete (cut off), p13's continuation starts with no header. No
single-page OCR call can fully reconstruct this; low scores on this pair are
an expected property of page-boundary splitting, not an engine defect
(disclose in the report, do not treat as a scoring bug).

`franchise_p01` is the sole scored instance of a signature/acknowledgment
table ("본인은 본 페이지의 내용에 대한 설명을 듣고, 이를 완전히 이해하였음")
that recurs near-verbatim on most of the 48 franchise pages. Per the plan,
its recurrences on `franchise_p46/47/48` are deliberately NOT separately
scored (same structure, no additional signal).
"""

from __future__ import annotations


def _empty_rows(n: int, cols: int) -> str:
    row = "<tr>" + "<td></td>" * cols + "</tr>"
    return row * n


TABLE_GROUND_TRUTH: dict[str, list[str]] = {
    "bimil_seoyak_jaejik_p01": [
        "<table><thead><tr>"
        "<th>구분</th><th>영업비밀/영업자산의 명칭</th><th>영업비밀/영업자산의 설명</th>"
        "</tr></thead><tbody>"
        "<tr><td>1</td><td></td><td></td></tr>"
        "<tr><td>2</td><td></td><td></td></tr>"
        "<tr><td>3</td><td></td><td></td></tr>"
        "<tr><td>4</td><td></td><td></td></tr>"
        "</tbody></table>"
    ],
    "eopmu_p01": [
        "<table><tbody>"
        "<tr><th scope='row'>제목</th><td rowspan='6'>"
        "A와 B 의 상호협력을 위한 업무협약서 A 와 B 는 상호발전을 위하여 긴밀한 협조가 "
        "필요하다는 점을 인식하고 다음과 같이 양해각서를 체결한다. "
        "제1조(목적) 본 양해각서는 양 기관이 상호 발전 및 협력관계를 증진시키기 위해 "
        "필요한 기본적인 사항을 규정함을 목적으로 한다. "
        "제2조(기본 운영원칙) 양 기관은 상호 협력함에 있어 당해 기관의 제 규정을 준수하고 "
        "상호 호혜적인 교류 및 협력관계를 유지한다. "
        "제3조(협력분야) 양 기관이 추진하는 협력 사업의 내용은 다음과 같으며 구체적인 "
        "사항은 상호 협의에 의하여 결정한다. 1. 2. 3. "
        "제4조(인력활용 및 교류) 양 기관은 필요한 경우 상호 협의하여 연구요원 등의 활용 "
        "및 교류를 할 수 있으며 방법은 양 기관의 규정에 따른다. "
        "제5조(학술정보교류) 양 기관은 학술 및 기술정보의 원활한 교류를 통해 긴밀한 "
        "유지하며 학술 및 기술정보의 공동활용에 적극 노력한다. "
        "제6조(자문) 양 기관은 상호간 업무상 자문에 성실히 응한다. "
        "제7조(기타) 기타 필요한 사항에 대해서는 양 기관이 상호 협의하여 결정한다. "
        "제8조(해석) 본 양해각서에 명시되지 않은 사항과 양해각서의 조문해석이 서로 다른 "
        "경우에는 상호 협의하여 결정한다. "
        "제9조(효력 및 유효기간) ① 본 협약은 양 기관의 협약당사자가 서명한 날부터 효력이 "
        "발생한다. ② 협약의 유효기간은 효력이 발생한 날부터 0년으로 하며, 유효기간 "
        "종료일에 자동 종료된다. ③ 본 협약의 필요성이 상실되는 경우에는 상호 협의하여 "
        "조기 종료할 수 있으며, 연장이 필요한 경우 상대측에 00개월 이전에 서면으로 "
        "통보하거나 상호 협의하여 0년 단위로 연장할 수 있다. "
        "제10조(개정) 본 협약의 내용은 상호 협의에 의하여 개정할 수 있다. "
        "제11조(비밀유지) 양 기관은 상호 협력 업무를 수행함에 있어 취득한 정보에 "
        "대하여는 제3자에게 제공하거나 공개하지 아니한다. "
        "제12조(비용부담) 업무협력을 위해 소요되는 비용은 상호 협의하여 결정한다. "
        "제13조(운영) 본 양해각서의 내용을 효과적으로 운영하기 위하여 상호 협의하에 "
        "연락담당자를 둔다."
        "</td></tr>"
        "<tr><th scope='row'>전문</th></tr>"
        "<tr><th scope='row'>총칙조항</th></tr>"
        "<tr><th scope='row'>실체조항</th></tr>"
        "<tr><th scope='row'>효력및 해지조항</th></tr>"
        "<tr><th scope='row'>개정조항 기타부칙</th></tr>"
        "</tbody></table>"
    ],
    # Structurally confirmed against Upstage's own content.html (2026-08-11
    # diagnostic re-call) — a blank two-table expense form. Two independent
    # tables on the same page (document header block, then payee block).
    "jichul_p01": [
        "<table><thead>"
        "<tr><td colspan='2'>문서번호</td><td rowspan='2'>결 재</td>"
        "<td>담당</td><td>팀장</td><td>센터장</td></tr>"
        "<tr><td colspan='2'>제 호</td><td></td><td></td><td></td></tr>"
        "</thead><tbody>"
        "<tr><td colspan='6'>지출금액 일금 원정(\\ )</td></tr>"
        "<tr><td rowspan='2'>발의일</td><td rowspan='2'></td><td rowspan='2'>(인)</td>"
        "<td colspan='3'>지출예산항목</td></tr>"
        "<tr><td rowspan='2'>단위사업</td><td colspan='2'></td></tr>"
        "<tr><td colspan='2'>지출일</td><td>(인)</td><td colspan='2'>예산항목</td></tr>"
        "<tr><td colspan='6'>내 역</td></tr>"
        "<tr><td colspan='4'>적요</td><td colspan='2'>금액</td></tr>"
        "<tr><td colspan='4'></td><td colspan='2'>원</td></tr>"
        "</tbody></table>",
        "<table><tbody>"
        "<tr><td rowspan='3'>지출처</td><td rowspan='3'></td>"
        "<td rowspan='3'>지출방 법</td><td rowspan='3'></td>"
        "<td>은행명</td><td></td></tr>"
        "<tr><td>예금주</td><td></td></tr>"
        "<tr><td>계좌번호</td><td></td></tr>"
        "<tr><td>영수</td><td colspan='5'>상기금액을 영수함 년 월 일 영수인 (인)</td></tr>"
        "</tbody></table>",
    ],
    # Representative instance only — the same 1x2 table recurs near-verbatim
    # on most of the 48 franchise pages (confirmed identical on p1/p40/p45).
    # Its recurrences on p46/p47/p48 are deliberately not scored again.
    "franchise_p01": [
        "<table><tbody><tr>"
        "<td>본인은 본 페이지의 내용에 대한 설명을 듣고, 이를 완전히 이해하였음</td>"
        "<td>( 인 )</td>"
        "</tr></tbody></table>"
    ],
    # KNOWN-HARD, page-boundary-split case. Ground truth is exactly what is
    # visible on p12 alone: one data row, incomplete (its 포함내역 cell text
    # continues onto p13). No single-page OCR call can see the rest.
    "franchise_p12": [
        "<table><thead><tr>"
        "<th>최초가맹금 내역</th><th>금액(단위: 천원)</th><th>포함내역</th>"
        "<th>지급기한</th><th>반환조건</th><th>반환될 수 없는 사유</th>"
        "</tr></thead><tbody>"
        "<tr><td>가입비</td><td></td>"
        "<td>(예시) 장소선정 지원비, 가맹사업운영</td>"
        "<td></td><td></td><td></td></tr>"
        "</tbody></table>"
    ],
    # KNOWN-HARD, continuation half of the same split table (see p12 above),
    # plus one independent table on the same page. Ground truth for the
    # continuation starts with no header, exactly as visible on p13 alone.
    "franchise_p13": [
        "<table><tbody>"
        "<tr><td></td><td></td><td>매뉴얼 제공비, 오픈지원비 등</td>"
        "<td></td><td></td><td></td></tr>"
        "<tr><td>최초교육비</td><td></td><td></td><td></td><td></td><td></td></tr>"
        "<tr><td></td><td></td><td></td><td></td><td></td><td></td></tr>"
        "<tr><td>합계</td><td></td><td></td><td></td><td></td><td></td></tr>"
        "</tbody></table>",
        "<table><thead><tr><th>예치가맹금 내역</th><th>금액(단위: 천원)</th></tr></thead>"
        "<tbody>"
        "<tr><td>가입비</td><td></td></tr>"
        "<tr><td>최초교육비</td><td></td></tr>"
        "<tr><td></td><td></td></tr>"
        "<tr><td>합계</td><td></td></tr>"
        "</tbody></table>",
    ],
    "franchise_p46": [
        "<table><tbody>"
        "<tr><td>영업표지 견본</td><td></td></tr>"
        "<tr><td>등록번호(출원번호)</td><td></td></tr>"
        "<tr><td>등록결정(심결) 연월일</td><td></td></tr>"
        "<tr><td>존속기간 (예정) 만료일</td><td></td></tr>"
        "<tr><td>지정상품 또는 지정서비스업</td><td></td></tr>"
        "<tr><td>등록권리자</td><td></td></tr>"
        "</tbody></table>"
    ],
    "franchise_p47": [
        "<table><thead><tr><th>연번</th><th>기기명</th><th>공급가격</th></tr></thead>"
        f"<tbody>{_empty_rows(19, 3)}</tbody></table>"
    ],
    "franchise_p48": [
        "<table><thead><tr><th>연번</th><th>물품명</th><th>공급가격</th></tr></thead>"
        f"<tbody>{_empty_rows(19, 3)}</tbody></table>"
    ],
}

# Pages with zero real tables, confirmed by direct visual review of all 65
# pages (2026-08-11) — listed for completeness / assertions in tests, not
# used by the scorer itself.
NO_TABLE_SAMPLE_IDS = frozenset(
    {
        "gyeongeop_p01", "gyeongeop_p02", "gyeongeop_p03",
        "bimil_gyeyak_p01", "bimil_gyeyak_p02", "bimil_gyeyak_p03",
        "bimil_gyeyak_p04", "bimil_gyeyak_p05",
        "bimil_seoyak_ipsa_p01", "bimil_seoyak_ipsa_p02", "bimil_seoyak_ipsa_p03",
    }
)

TABLE_SAMPLE_IDS: tuple[str, ...] = tuple(TABLE_GROUND_TRUTH)
