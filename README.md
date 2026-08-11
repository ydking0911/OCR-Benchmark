# OcrBenchmark

한국어 계약서 PDF를 대상으로 **Upstage Document Parse**, **Naver CLOVA General OCR**, **Claude Vision(Sonnet 5)** 세 엔진의 텍스트 전사 정확도(CER/WER/유사도)와 실비용을 실제 API 호출로 측정해 비교하는 벤치마크입니다.

이 리포지토리에는 성격이 다른 두 계획이 있습니다:

| 계획                                               | 문서                                                                                                                       | 상태                                         |
| -------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------- |
| **3-엔진 비교** (이 README가 다루는 것)            | [`.omc/plans/plan-upstage-clova-claude-ocr-benchmark.md`](.omc/plans/plan-upstage-clova-claude-ocr-benchmark.md)           | **완료 — 65페이지 전체 실행, 리포트 생성됨** |
| Claude 전용 벤치마크 (Haiku/Sonnet/Opus, 해상도별) | [`.omc/plans/ralplan-claude-vision-contract-ocr-benchmark.md`](.omc/plans/ralplan-claude-vision-contract-ocr-benchmark.md) | 별도 계획, 미구현                            |

두 계획은 `samples/pdfs/`와 정답 추출 방식(`sample_id`, `DOC_SLUG_MAP`, hangul_ratio 유효성 게이트)을 공유하도록 설계되어 있습니다.

## 결과 요약 (2026-08-11, 65페이지 전체 실행 완료)

### 지표 설명 — CER / WER / 유사도

정확도는 각 엔진의 전사 결과를 PyMuPDF로 뽑은 원문(정답)과 비교해 계산합니다. 값이 **작을수록** 좋습니다(CER/WER는 오류율).

| 지표                                        | 뜻                                                       | 계산 방식                                                                                                                |
| ------------------------------------------- | -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| **CER** (Character Error Rate, 문자 오류율) | 정답과 비교했을 때 **글자 단위**로 얼마나 틀렸는지       | (삽입+삭제+치환된 문자 수) / 정답 전체 문자 수. 예: CER 0.045 = 100자 중 약 4.5자꼴로 틀림                               |
| **WER** (Word Error Rate, 단어 오류율)      | 정답과 비교했을 때 **단어(어절) 단위**로 얼마나 틀렸는지 | (삽입+삭제+치환된 단어 수) / 정답 전체 단어 수. 한 글자만 틀려도 그 단어 전체가 오류로 잡히므로 보통 CER보다 값이 큽니다 |
| **유사도(%)**                               | 위 오류율의 반대 개념, 직관적으로 읽기 위한 값           | 대략 `(1 - CER) × 100`에 가까운 값으로, 리포트의 헤드라인 지표입니다                                                     |

이 벤치마크는 표·체크박스 같은 **구조화 출력은 정량 채점하지 않고** 정적 기능 체크리스트로만 비교합니다(아래 2절) — CER/WER/유사도는 어디까지나 **평문 텍스트 전사** 정확도만 나타냅니다.

### 최종 결과 (전체 65페이지 평균)

| 순위(1만 페이지 환산 비용) | 엔진 구성                          |              CER |    WER |       유사도(%) | 실패 | 비고                                                                        |
| -------------------------- | ---------------------------------- | ---------------: | -----: | --------------: | ---: | --------------------------------------------------------------------------- |
| 1                          | Naver CLOVA 문자 인식만 — $21.74   |           0.0449 | 0.1733 |           97.13 | 0/65 | 가격·정확도 모두 최상위권, 콘솔 확정 단가 반영                              |
| 2                          | Upstage Standard — $100.00         |           0.1781 | 0.3412 |           92.61 | 0/65 | `jichul`/`eopmu`(표 양식)에서 30~78%대로 붕괴 — 원인 확인됨(아래)           |
| 3                          | Claude Sonnet 5 — $165.66          | **0.0437**(최저) | 0.1864 | **97.71**(최고) | 0/65 | 지연 ~11초/페이지, 비결정적                                                 |
| 4                          | Naver CLOVA 문자+표 추출 — $181.16 |           0.0449 | 0.1733 |           97.13 | 0/65 | 표 추출이 텍스트 정확도엔 영향 없음(문자 인식만과 CER/WER/유사도 전부 동일) |
| 5                          | Upstage Enhanced — $300.00         |           0.2711 | 0.4181 |           91.01 | 0/65 | 3배 비싸면서 Standard보다도 낮은 정확도                                     |

**핵심 발견**: Upstage가 `jichul`/`eopmu`에서 붕괴한 원인을 `content.html`/`elements` 구조화 출력과 직접 대조해 확정했습니다 — **인식 실패가 아니라 Upstage 자체의 markdown `text` 변환기 버그**입니다. `rowspan`/`colspan`으로 병합된 표 셀을 HTML에서는 정확히 인식하지만, markdown으로 변환할 때 병합 셀 내용을 스팬된 모든 행/열에 중복 삽입합니다. 구조화 출력(`html`/`elements`)을 직접 소비하는 파이프라인이라면 이 정확도 열세는 적용되지 않습니다.

### 표 구조 정확도 — TEDS (9페이지, 2026-08-11)

텍스트 정확도(CER/WER)는 표 구조를 채점하지 않습니다(위 §지표 설명). 사람이 직접 검수해 확정한 9개 표 페이지에 대해, **TEDS**(Tree-Edit-Distance-based Similarity — PubTabNet·Upstage DP-Bench와 같은 계열 지표, 표를 HTML 트리로 놓고 트리 편집 거리 기반 유사도를 계산, 0~1, 클수록 정확)로 별도 채점했습니다. `rowspan`/`colspan`은 셀의 구조적 정체성에 포함되므로, 병합 셀을 여러 칸으로 쪼개 복제하면 감점됩니다 — Upstage의 markdown 중복 버그가 바로 이렇게 잡힙니다.

| 엔진 구성 | TEDS 평균 | TEDS(헤더 무시) | 표 미검출 |
|---|---:|---:|---:|
| Claude Sonnet 5 (표 구조 추출 전용 호출) | **0.789**(최고) | 0.800 | 0/9 |
| Upstage Enhanced | 0.654 | 0.756 | 0/9 |
| Upstage Standard | 0.599 | 0.713 | 0/9 |
| Naver CLOVA 문자+표 추출 | 0.587(최저) | 0.675 | 0/9 |

**표 구조는 텍스트 순위를 완전히 뒤집습니다**: 텍스트에서 최상위였던 Clova가 표 구조에서는 최하위이고, 원래 표 추출 기능이 없어 새 프롬프트로 즉석 대응한 Claude가 평균 1위입니다. 다만 페이지별 편차가 극심합니다 — 가장 복잡한 병합 표(`jichul_p01`, rowspan 9회·colspan 13회)에서는 Claude가 최저점(0.143), 오히려 Upstage Standard가 최고점(0.974)으로 완전히 역전됩니다. 대형 희소 그리드(`franchise_p47/48`, 20행)에서는 반대로 Upstage가 붕괴(0.13대)하고 Claude/Clova가 거의 완벽(0.9+)합니다. **결론: 모든 표 유형에서 이기는 단일 엔진은 없습니다** — 표가 복잡한 병합 구조인지, 단순 대형 그리드인지에 따라 유리한 엔진이 다릅니다. 상세 페이지별 수치와 근거는 `results/report3/comparison.md` 7절 참고.

전체 리포트(위 표 + 기능 체크리스트 + 문서별 유사도 + 표 구조(TEDS) + 추천 방안 + 한계)는 `py scripts/run_ocr3_benchmark.py [--tables]` 실행 후 `results/report3/comparison.md`에서 확인할 수 있습니다(생성물이라 커밋되지 않음 — 재생성하려면 아래 [실행](#실행) 참고).

## 비교 대상 5개 엔진 구성

| id                 | 엔진        | 설정                              |
| ------------------ | ----------- | --------------------------------- |
| `upstage_standard` | Upstage     | Document Parse — Standard         |
| `upstage_enhanced` | Upstage     | Document Parse — Enhanced         |
| `clova_text`       | Naver CLOVA | General OCR — 문자 인식만         |
| `clova_table`      | Naver CLOVA | General OCR — 문자 인식 + 표 추출 |
| `claude_sonnet`    | Claude      | Sonnet 5, 고해상도(장변 2576px)   |

Claude는 이 벤치마크에서 Sonnet 5 고해상도 1개 구성만 다룹니다(Haiku/Opus 비교, 사람 앵커 품질 게이트 등은 위 표의 별도 계획 소관).

측정 지표는 텍스트 정확도(CER/WER/유사도, PyMuPDF 추출 원문 대조)와 실비용뿐입니다. bbox·조항 계층·체크박스 같은 구조화 출력은 정량 채점하지 않고 정적 기능 체크리스트로만 병기합니다. **사람이 앵커링하는 합격/불합격 게이트는 의도적으로 두지 않습니다** — 원시 수치와 비용을 보여주고 판단은 사람이 합니다.

## 데이터셋

`samples/pdfs/`의 한국어 계약서 7건, 65페이지 전체를 사용합니다(표본이 적어 부분 샘플링 시 비교 비율이 신뢰할 수 없다는 판단에 따라 전량 사용).

| 파일                       | doc_slug              | 페이지 수 |
| -------------------------- | --------------------- | --------- |
| 경업금지약정서\_퇴직자.pdf | `gyeongeop`           | 3         |
| 비밀유지계약서.pdf         | `bimil_gyeyak`        | 5         |
| 비밀유지서약서\_입사자.pdf | `bimil_seoyak_ipsa`   | 3         |
| 비밀유지서약서\_재직자.pdf | `bimil_seoyak_jaejik` | 3         |
| 업무협약서.pdf             | `eopmu`               | 2         |
| 지출결의서.pdf             | `jichul`              | 1         |
| 프랜차이즈계약서 .pdf      | `franchise`           | 48        |

`franchise` 문서가 65페이지 중 48페이지를 차지하므로 문서 간 비교는 상관된 표본이며, 결과 해석 시 이 편중을 감안해야 합니다(리포트 한계 섹션에 명시됨).

## 구조

```
src/ocr_benchmark/
  ground_truth.py       # PyMuPDF 정답 추출 + manifest 생성 + hangul_ratio 유효성 게이트
  scoring.py             # CER/WER/유사도 (jiwer)
  table_ground_truth.py  # 사람이 직접 검수해 작성한 9페이지 표 구조 정답(HTML)
  table_scoring.py       # TEDS(트리 편집 거리 기반 표 구조 유사도), apted 기반
  config.py               # 엔진 구성, 가격 상수, DOC_SLUG_MAP, 표 채점 가능 엔진 목록
  engines/
    upstage_client.py     # Document Parse API (text+html)
    clova_client.py        # CLOVA General OCR API (텍스트 + 표 구조)
    claude_client.py       # Anthropic Messages API (전체 텍스트 전사)
    claude_table_client.py # Anthropic Messages API (표 구조 전용 별도 호출)
  cache3.py               # fingerprint 기반 응답 캐시 (재실행 시 재과금 방지)
  aggregate3.py           # 페이지/문서/전체 집계 + 표 구조(TEDS) 집계, 게이트 없음
  report3.py              # markdown 비교 리포트 생성 (텍스트 + 표 구조 섹션)
scripts/
  prepare_ground_truth.py   # samples/pdfs -> ground_truth/images/manifest.json
  run_ocr3_benchmark.py     # 벤치마크 실행 + 리포트 생성 (--tables로 표 구조 채점 포함)
tests/                       # 163개 유닛테스트 (API 호출 없이 fixture 기반)
samples/
  pdfs/          # 원본 7개 PDF (커밋됨)
  ground_truth/  # 생성물 — .gitignore 처리(전문 포함)
  images/        # 생성물 — .gitignore 처리
  manifest.json  # 생성물 — .gitignore 처리
results/
  raw3/          # 엔진별 캐시된 원본 응답 — .gitignore 처리
  raw3/tables/   # 표 구조 전용 호출 캐시 — 텍스트 캐시와 완전히 분리 — .gitignore 처리
  report3/       # 최종 리포트 — .gitignore 처리
```

`samples/ground_truth/`, `samples/images/`, `samples/manifest.json`은 `scripts/prepare_ground_truth.py` 한 번으로 재생성 가능하고 계약서 전문을 담고 있어 커밋하지 않습니다.

## 셋업

```bash
py -m pip install -r requirements.txt
cp .env.example .env   # 그다음 아래 세 API 키를 채워 넣기
```

`.env`에 필요한 값:

| 변수                                               | 용도                                                                                          |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `ANTHROPIC_API_KEY`                                | Claude Sonnet 5                                                                               |
| `UPSTAGE_API_KEY`                                  | Upstage Document Parse                                                                        |
| `NCP_CLOVA_OCR_SECRET`, `NCP_CLOVA_OCR_INVOKE_URL` | Naver CLOVA General OCR (invoke URL은 계정마다 다름 — NCP 콘솔의 CLOVA OCR > Domain에서 확인) |

Windows 환경에서는 `python`이 WindowsApps 스텁으로 잡히므로 반드시 `py`를 사용합니다.

## 실행

```bash
# 1) 정답 데이터 준비 (API 비용 없음, 로컬 PDF만 사용)
py scripts/prepare_ground_truth.py

# 2) 스모크 테스트 (3페이지 x 5구성 = 15콜, 소액 과금)
py scripts/run_ocr3_benchmark.py --dry-run

# 3) 전체 실행 (65페이지 x 5구성 = 325콜, 캐시로 재실행은 무료)
py scripts/run_ocr3_benchmark.py

# 엔진 하나만 실행하고 싶을 때
py scripts/run_ocr3_benchmark.py --engine upstage   # upstage | clova | claude | <config_id>

# 표 구조(TEDS) 채점 추가 — 사람이 검수한 9페이지 한정, 별도 과금·별도 캐시(results/raw3/tables/)
py scripts/run_ocr3_benchmark.py --tables --engine upstage
py scripts/run_ocr3_benchmark.py --tables --engine clova
py scripts/run_ocr3_benchmark.py --tables --engine claude
```

`--tables`는 opt-in입니다 — 안 켜도 이전에 이미 캐시된 표 결과는 계속 리포트에 반영됩니다. Upstage/Clova는 기존 텍스트 API를 다른 옵션으로 재호출하고, Claude는 표 구조만 요청하는 완전히 별도의 새 프롬프트 호출입니다(`claude_sonnet_table`) — 세 경우 모두 기존 65페이지 텍스트 채점과는 별도로 과금됩니다.

결과 리포트는 `results/report3/comparison.md`에 생성됩니다(가격순 비교표 + 기능 체크리스트 + 문서별 유사도 + 표 구조(TEDS) + 추천 방안).

> **주의**: `report3.py`는 추천 방안(5절)을 항상 빈 템플릿(`_(작성 필요)_`)으로 생성합니다 — 사람이 결과를 보고 채우는 게 설계 의도입니다. 위 "결과 요약" 절의 분석 내용은 2026-08-11 실행 결과를 사람이 직접 읽고 `results/report3/comparison.md`에 채워 넣은 것이며, **스크립트를 다시 실행하면(캐시 히트뿐이라도) 5절이 다시 빈 템플릿으로 덮어써집니다.** 그 분석을 보존하려면 다시 실행하기 전에 파일을 따로 백업하세요.

## 테스트

```bash
py -m pytest tests/ -v
```

전부 fixture/mock 기반이라 API 호출이나 과금이 발생하지 않습니다.
