# OcrBenchmark

한국어 계약서 PDF를 대상으로 **Upstage Document Parse**, **Naver CLOVA General OCR**, **Claude Vision(Sonnet 5)** 세 엔진의 텍스트 전사 정확도(CER/WER/유사도)와 실비용을 실제 API 호출로 측정해 비교하는 벤치마크입니다.

이 리포지토리에는 성격이 다른 두 계획이 있습니다:

| 계획 | 문서 | 상태 |
|---|---|---|
| **3-엔진 비교** (이 README가 다루는 것) | [`.omc/plans/plan-upstage-clova-claude-ocr-benchmark.md`](.omc/plans/plan-upstage-clova-claude-ocr-benchmark.md) | **완료 — 65페이지 전체 실행, 리포트 생성됨** |
| Claude 전용 벤치마크 (Haiku/Sonnet/Opus, 해상도별) | [`.omc/plans/ralplan-claude-vision-contract-ocr-benchmark.md`](.omc/plans/ralplan-claude-vision-contract-ocr-benchmark.md) | 별도 계획, 미구현 |

두 계획은 `samples/pdfs/`와 정답 추출 방식(`sample_id`, `DOC_SLUG_MAP`, hangul_ratio 유효성 게이트)을 공유하도록 설계되어 있습니다.

## 결과 요약 (2026-08-11, 65페이지 전체 실행 완료)

### 지표 설명 — CER / WER / 유사도

정확도는 각 엔진의 전사 결과를 PyMuPDF로 뽑은 원문(정답)과 비교해 계산합니다. 값이 **작을수록** 좋습니다(CER/WER는 오류율).

| 지표 | 뜻 | 계산 방식 |
|---|---|---|
| **CER** (Character Error Rate, 문자 오류율) | 정답과 비교했을 때 **글자 단위**로 얼마나 틀렸는지 | (삽입+삭제+치환된 문자 수) / 정답 전체 문자 수. 예: CER 0.045 = 100자 중 약 4.5자꼴로 틀림 |
| **WER** (Word Error Rate, 단어 오류율) | 정답과 비교했을 때 **단어(어절) 단위**로 얼마나 틀렸는지 | (삽입+삭제+치환된 단어 수) / 정답 전체 단어 수. 한 글자만 틀려도 그 단어 전체가 오류로 잡히므로 보통 CER보다 값이 큽니다 |
| **유사도(%)** | 위 오류율의 반대 개념, 직관적으로 읽기 위한 값 | 대략 `(1 - CER) × 100`에 가까운 값으로, 리포트의 헤드라인 지표입니다 |

이 벤치마크는 표·체크박스 같은 **구조화 출력은 정량 채점하지 않고** 정적 기능 체크리스트로만 비교합니다(아래 2절) — CER/WER/유사도는 어디까지나 **평문 텍스트 전사** 정확도만 나타냅니다.

### 최종 결과 (전체 65페이지 평균)

| 순위(1만 페이지 환산 비용) | 엔진 구성 | CER | WER | 유사도(%) | 실패 | 비고 |
|---|---|---:|---:|---:|---:|---|
| 1 | Naver CLOVA 문자 인식만 — $21.74 | 0.0449 | 0.1733 | 97.13 | 0/65 | 가격·정확도 모두 최상위권, 콘솔 확정 단가 반영 |
| 2 | Upstage Standard — $100.00 | 0.1781 | 0.3412 | 92.61 | 0/65 | `jichul`/`eopmu`(표 양식)에서 30~78%대로 붕괴 — 원인 확인됨(아래) |
| 3 | Claude Sonnet 5 — $165.66 | **0.0437**(최저) | 0.1864 | **97.71**(최고) | 0/65 | 지연 ~11초/페이지, 비결정적 |
| 4 | Naver CLOVA 문자+표 추출 — $181.16 | 0.0449 | 0.1733 | 97.13 | 0/65 | 표 추출이 텍스트 정확도엔 영향 없음(문자 인식만과 CER/WER/유사도 전부 동일) |
| 5 | Upstage Enhanced — $300.00 | 0.2711 | 0.4181 | 91.01 | 0/65 | 3배 비싸면서 Standard보다도 낮은 정확도 |

**핵심 발견**: Upstage가 `jichul`/`eopmu`에서 붕괴한 원인을 `content.html`/`elements` 구조화 출력과 직접 대조해 확정했습니다 — **인식 실패가 아니라 Upstage 자체의 markdown `text` 변환기 버그**입니다. `rowspan`/`colspan`으로 병합된 표 셀을 HTML에서는 정확히 인식하지만, markdown으로 변환할 때 병합 셀 내용을 스팬된 모든 행/열에 중복 삽입합니다. 구조화 출력(`html`/`elements`)을 직접 소비하는 파이프라인이라면 이 정확도 열세는 적용되지 않습니다.

전체 리포트(위 표 + 기능 체크리스트 + 문서별 유사도 + 추천 방안 + 한계)는 `py scripts/run_ocr3_benchmark.py` 실행 후 `results/report3/comparison.md`에서 확인할 수 있습니다(생성물이라 커밋되지 않음 — 재생성하려면 아래 [실행](#실행) 참고).

## 비교 대상 5개 엔진 구성

| id | 엔진 | 설정 |
|---|---|---|
| `upstage_standard` | Upstage | Document Parse — Standard |
| `upstage_enhanced` | Upstage | Document Parse — Enhanced |
| `clova_text` | Naver CLOVA | General OCR — 문자 인식만 |
| `clova_table` | Naver CLOVA | General OCR — 문자 인식 + 표 추출 |
| `claude_sonnet` | Claude | Sonnet 5, 고해상도(장변 2576px) |

Claude는 이 벤치마크에서 Sonnet 5 고해상도 1개 구성만 다룹니다(Haiku/Opus 비교, 사람 앵커 품질 게이트 등은 위 표의 별도 계획 소관).

측정 지표는 텍스트 정확도(CER/WER/유사도, PyMuPDF 추출 원문 대조)와 실비용뿐입니다. bbox·조항 계층·체크박스 같은 구조화 출력은 정량 채점하지 않고 정적 기능 체크리스트로만 병기합니다. **사람이 앵커링하는 합격/불합격 게이트는 의도적으로 두지 않습니다** — 원시 수치와 비용을 보여주고 판단은 사람이 합니다.

## 데이터셋

`samples/pdfs/`의 한국어 계약서 7건, 65페이지 전체를 사용합니다(표본이 적어 부분 샘플링 시 비교 비율이 신뢰할 수 없다는 판단에 따라 전량 사용).

| 파일 | doc_slug | 페이지 수 |
|---|---|---|
| 경업금지약정서_퇴직자.pdf | `gyeongeop` | 3 |
| 비밀유지계약서.pdf | `bimil_gyeyak` | 5 |
| 비밀유지서약서_입사자.pdf | `bimil_seoyak_ipsa` | 3 |
| 비밀유지서약서_재직자.pdf | `bimil_seoyak_jaejik` | 3 |
| 업무협약서.pdf | `eopmu` | 2 |
| 지출결의서.pdf | `jichul` | 1 |
| 프랜차이즈계약서 .pdf | `franchise` | 48 |

`franchise` 문서가 65페이지 중 48페이지를 차지하므로 문서 간 비교는 상관된 표본이며, 결과 해석 시 이 편중을 감안해야 합니다(리포트 한계 섹션에 명시됨).

## 구조

```
src/ocr_benchmark/
  ground_truth.py     # PyMuPDF 정답 추출 + manifest 생성 + hangul_ratio 유효성 게이트
  scoring.py           # CER/WER/유사도 (jiwer)
  config.py             # 엔진 구성, 가격 상수, DOC_SLUG_MAP
  engines/
    upstage_client.py   # Document Parse API
    clova_client.py      # CLOVA General OCR API
    claude_client.py     # Anthropic Messages API (vision)
  cache3.py             # fingerprint 기반 응답 캐시 (재실행 시 재과금 방지)
  aggregate3.py         # 페이지/문서/전체 집계, 게이트 없음
  report3.py            # markdown 비교 리포트 생성
scripts/
  prepare_ground_truth.py   # samples/pdfs -> ground_truth/images/manifest.json
  run_ocr3_benchmark.py     # 벤치마크 실행 + 리포트 생성
tests/                       # 85개 유닛테스트 (API 호출 없이 fixture 기반)
samples/
  pdfs/          # 원본 7개 PDF (커밋됨)
  ground_truth/  # 생성물 — .gitignore 처리(전문 포함)
  images/        # 생성물 — .gitignore 처리
  manifest.json  # 생성물 — .gitignore 처리
results/
  raw3/          # 엔진별 캐시된 원본 응답 — .gitignore 처리
  report3/       # 최종 리포트 — .gitignore 처리
```

`samples/ground_truth/`, `samples/images/`, `samples/manifest.json`은 `scripts/prepare_ground_truth.py` 한 번으로 재생성 가능하고 계약서 전문을 담고 있어 커밋하지 않습니다.

## 셋업

```bash
py -m pip install -r requirements.txt
cp .env.example .env   # 그다음 아래 세 API 키를 채워 넣기
```

`.env`에 필요한 값:

| 변수 | 용도 |
|---|---|
| `ANTHROPIC_API_KEY` | Claude Sonnet 5 |
| `UPSTAGE_API_KEY` | Upstage Document Parse |
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
```

결과 리포트는 `results/report3/comparison.md`에 생성됩니다(가격순 비교표 + 기능 체크리스트 + 문서별 유사도 + 추천 방안).

> **주의**: `report3.py`는 추천 방안(5절)을 항상 빈 템플릿(`_(작성 필요)_`)으로 생성합니다 — 사람이 결과를 보고 채우는 게 설계 의도입니다. 위 "결과 요약" 절의 분석 내용은 2026-08-11 실행 결과를 사람이 직접 읽고 `results/report3/comparison.md`에 채워 넣은 것이며, **스크립트를 다시 실행하면(캐시 히트뿐이라도) 5절이 다시 빈 템플릿으로 덮어써집니다.** 그 분석을 보존하려면 다시 실행하기 전에 파일을 따로 백업하세요.

## 테스트

```bash
py -m pytest tests/ -v
```

전부 fixture/mock 기반이라 API 호출이나 과금이 발생하지 않습니다.

## 현재 상태

- [x] 정답 데이터/manifest 생성 완료 — 65페이지, 7문서, `low_text` 플래그 페이지 0개, 코퍼스 hangul_ratio 0.91(임계값 0.3 대비 양호)
- [x] 3개 엔진 클라이언트 + 캐싱 + 집계 + 리포트 생성기 구현 완료
- [x] 유닛테스트 90개 전부 통과
- [x] `.env`에 실제 API 키 입력 완료
- [x] 65페이지 전체 실행 완료 — 5개 구성 × 65페이지 = 325콜, 실패 0건
- [x] Naver CLOVA 실제 단가 NCP 콘솔에서 확인 및 반영 (글자 추출 3원/건, 표 추출 옵션 시 +22원/건)
- [x] Upstage 이상치(`jichul`/`eopmu`) 원인을 `content.html`/`elements` 직접 대조로 확정 — markdown `text` 변환기의 병합 셀 중복 버그
- [ ] git 커밋 — 코드/테스트/문서가 아직 커밋되지 않음(작업 디렉터리에만 존재)
- [ ] Upstage/Clova 단가의 VAT 포함 여부 확인
- [ ] (선택) Sonnet 5 인트로 가격 만료(2026-08-31) 이후 가격으로 순위가 뒤집히는지 별도 표로 확인

## 알려진 한계

- **텍스트 재조립 아티팩트(Upstage, 실증 확인됨)**: Upstage 자체의 markdown `text` 변환기가 `rowspan`/`colspan` 병합 셀의 내용을 스팬된 모든 행/열에 중복 삽입합니다. `content.html`/`elements`는 병합 구조를 정확히 인식하지만 `text`만 부풀려지므로, 표 양식 문서(지출결의서 등)의 정확도 수치는 실제 인식 품질보다 낮게 나옵니다. plain text가 아니라 구조화 출력을 소비하는 파이프라인이라면 이 열세는 적용되지 않습니다.
- **텍스트 재조립 아티팩트(Clova)**: Clova는 위치 기반 필드를 반환하므로 이 벤치마크가 읽기 순서로 재조립합니다. CER/WER에는 엔진의 순수 인식 정확도뿐 아니라 이 재조립 품질도 섞여 들어갑니다.
- **표 추출의 채점 타당성**: Clova 표 추출 모드의 가치는 구조 보존인데 텍스트로 평탄화해서 채점하므로 정확도 지표에는 반영되지 않습니다(실측 결과 `문자 인식만`과 정확도가 소수점까지 동일) — 기능 체크리스트로 따로 판단해야 합니다.
- **VAT 미확인**: Upstage는 "VAT 별도" 명시가 있지만 Clova는 콘솔 표기에 VAT 포함 여부가 없어 확인되지 않았습니다.
- **표본 편중**: 65페이지 중 48페이지가 프랜차이즈계약서 한 건에서 나와, 문서 간 비교는 상관된 표본입니다.
- **Claude 사고 예산 고정**: 비용 통제를 위해 `effort=low`로 고정했습니다. 이 축소된 사고 예산이 Sonnet 5의 품질을 체계적으로 낮췄을 수 있습니다.
