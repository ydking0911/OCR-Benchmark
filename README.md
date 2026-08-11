# 📑 OcrBenchmark: 한국어 계약서 OCR 4-엔진 벤치마크

## Update Logs

- 2026-08-11: **Mistral OCR 4** 추가 — 텍스트(65p) + 표 구조(9p) 실측 완료. 최초 실행에서 표 구조 TEDS가 전 페이지 0.000으로 나온 스키마 버그(표 객체 키가 `html`이 아니라 `content`)를 발견해 **재과금 없이** 캐시에서 수정([부록 B.5](.omc/plans/plan-upstage-clova-claude-ocr-benchmark.md))
- 2026-08-11: 표 구조(TEDS) 채점 결과 공개 — [Table Structure Leaderboard](#table-structure-leaderboard-teds) ([`results/report3/comparison.md`](results/report3/comparison.md) 7절)
- 2026-08-11: Naver CLOVA 실제 단가 확정 반영 (NCP 콘솔 확인, 글자 추출 3원/건)
- 2026-08-11: Upstage Document Parse / Naver CLOVA General OCR / Claude Vision(Sonnet 5) 65페이지 전체 벤치마크 결과 공개 — [Text Accuracy Leaderboard](#text-accuracy-leaderboard)

---

<br>

OcrBenchmark은 한국어 계약서 PDF 7종·65페이지를 대상으로 **Upstage Document Parse**, **Naver CLOVA General OCR**, **Claude Vision(Sonnet 5)**, **Mistral OCR 4** 네 엔진의 텍스트 전사 정확도, 표 구조 인식 정확도, 실비용을 실제 API 호출로 측정한 벤치마크입니다.

정답은 두 종류입니다 — 텍스트 채점은 PyMuPDF로 PDF에서 직접 추출한 원문을, 표 구조 채점은 사람이 렌더링된 페이지 이미지를 직접 검수해 작성한 표 HTML을 정답으로 씁니다. 사람이 앵커링하는 합격/불합격 게이트는 두지 않습니다 — 원시 수치와 실비용만 제시하고, 어떤 엔진을 쓸지는 표를 보고 사람이 판단합니다.
<br/>

## 벤치마크 실행 코드

### 셋업

```bash
py -m pip install -r requirements.txt
cp .env.example .env
```

`.env`에 필요한 값:

| 변수                                               | 용도                                                                                          |
| -------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `ANTHROPIC_API_KEY`                                | Claude Sonnet 5 / 표 구조 추출 전용 호출                                                      |
| `UPSTAGE_API_KEY`                                  | Upstage Document Parse                                                                        |
| `NCP_CLOVA_OCR_SECRET`, `NCP_CLOVA_OCR_INVOKE_URL` | Naver CLOVA General OCR (invoke URL은 계정마다 다름 — NCP 콘솔의 CLOVA OCR > Domain에서 확인) |
| `MISTRAL_API_KEY`                                  | Mistral OCR 4                                                                                 |

Windows 환경에서는 `python`이 WindowsApps 스텁으로 잡히므로 반드시 `py`를 사용합니다.

### 실행

```bash
py scripts/prepare_ground_truth.py          # 정답 데이터 준비 (API 비용 없음, 로컬 PDF만 사용)
py scripts/run_ocr3_benchmark.py --dry-run  # 스모크 테스트 (3페이지 x 6구성 = 18콜)
py scripts/run_ocr3_benchmark.py            # 전체 실행 (65페이지 x 6구성 = 390콜, 캐시로 재실행 무료)
py scripts/run_ocr3_benchmark.py --tables   # + 표 구조(TEDS) 채점 (9페이지 x 5구성, 별도 과금)

# 엔진 하나만
py scripts/run_ocr3_benchmark.py --engine upstage          # upstage | clova | claude | mistral | <config_id>
py scripts/run_ocr3_benchmark.py --tables --engine mistral
```

리포트는 `results/report3/comparison.md`에 생성됩니다(가격순 비교표 + 기능 체크리스트 + 문서별 유사도 + 표 구조(TEDS) + 추천 방안). `--tables`는 opt-in이며 기존 텍스트 채점과 완전히 분리된 캐시(`results/raw3/tables/`)·별도 과금을 씁니다 — Upstage/Clova는 기존 텍스트 API를 다른 옵션으로 재호출하고, Claude와 Mistral은 표 구조만 요청하는 별도 호출입니다(`claude_sonnet_table` / `mistral_ocr`의 `transcribe_table`).

> **주의**: `report3.py`는 추천 방안(5절)을 항상 빈 템플릿(`_(작성 필요)_`)으로 생성합니다 — 사람이 결과를 보고 채우는 게 설계 의도입니다. 아래 두 리더보드의 서술은 실행 결과를 사람이 직접 읽고 `results/report3/comparison.md`에 채워 넣은 것이며, **스크립트를 다시 실행하면(캐시 히트뿐이라도) 5절이 다시 빈 템플릿으로 덮어써집니다.** 그 분석을 보존하려면 다시 실행하기 전에 파일을 따로 백업하세요.
> <br/>

## Text Accuracy Leaderboard

전사 결과를 PyMuPDF 원문과 비교한 CER(문자 오류율)·WER(단어 오류율)·유사도(%)로 채점했습니다. 값이 작을수록(유사도는 클수록) 정확합니다.

| Engine Config                     | Cost / 10k pages |        CER |    WER | Similarity | Failures |
| --------------------------------- | ---------------: | ---------: | -----: | ---------: | -------: |
| **Naver CLOVA — 문자 인식만**     |       **$21.74** |     0.0449 | 0.1733 |      97.13 |     0/65 |
| Mistral OCR 4                     |           $40.00 |     0.2017 | 0.4212 |      92.99 |     0/65 |
| Upstage Document Parse — Standard |          $100.00 |     0.1781 | 0.3412 |      92.61 |     0/65 |
| Claude Sonnet 5 (고해상도)        |          $165.66 | **0.0437** | 0.1864 |  **97.71** |     0/65 |
| Naver CLOVA — 문자 인식 + 표 추출 |          $181.16 |     0.0449 | 0.1733 |      97.13 |     0/65 |
| Upstage Document Parse — Enhanced |          $300.00 |     0.2711 | 0.4181 |      91.01 |     0/65 |

가격순 오름차순 정렬, 각 지표의 최고값을 굵게 표시했습니다(가격은 CLOVA, 정확도는 Claude — 이 벤치마크는 단일 승자를 정하지 않습니다).

> Upstage가 `jichul`(지출결의서)·`eopmu`(업무협약서)에서 91%→30~78%대로 붕괴하는 현상을 `content.html`/`elements` 구조화 출력과 직접 대조해 원인을 확정했습니다 — 인식 실패가 아니라 Upstage 자체의 markdown `text` 변환기가 `rowspan`/`colspan` 병합 셀을 스팬된 모든 칸에 중복 삽입하는 버그입니다. 아래 Table Structure 채점이 이걸 정량적으로도 재확인합니다.
>
> Mistral OCR 4는 텍스트 정확도에서 가격 2위($40.00)지만 순위는 중위권(92.99%) — 표 양식 문서(`jichul`·`eopmu`)에서 CLOVA/Claude보다 처지는 게 원인입니다. 표 구조 채점에서는 얘기가 다릅니다(아래).
> <br/>

## Table Structure Leaderboard (TEDS)

텍스트 정확도(CER/WER)는 표 구조를 채점하지 않습니다(위 §지표 설명). 사람이 직접 검수해 확정한 9개 표 페이지에 대해, **TEDS**(Tree-Edit-Distance-based Similarity — PubTabNet·Upstage DP-Bench와 같은 계열 지표, 표를 HTML 트리로 놓고 트리 편집 거리 기반 유사도를 계산, 0~1, 클수록 정확)로 별도 채점했습니다. `rowspan`/`colspan`은 셀의 구조적 정체성에 포함되므로, 병합 셀을 여러 칸으로 쪼개 복제하면 감점됩니다 — Upstage의 markdown 중복 버그가 바로 이렇게 잡힙니다.

| 엔진 구성                                |       TEDS 평균 | TEDS(헤더 무시) | 표 미검출 |
| ---------------------------------------- | --------------: | --------------: | --------: |
| Claude Sonnet 5 (표 구조 추출 전용 호출) | **0.789**(최고) |           0.800 |       0/9 |
| Mistral OCR 4                            |           0.669 |           0.717 |       1/9 |
| Upstage Enhanced                         |           0.654 |           0.756 |       0/9 |
| Upstage Standard                         |           0.599 |           0.713 |       0/9 |
| Naver CLOVA 문자+표 추출                 |     0.587(최저) |           0.675 |       0/9 |

**표 구조는 텍스트 순위를 완전히 뒤집습니다**: 텍스트에서 최상위였던 Clova가 표 구조에서는 최하위이고, 원래 표 추출 기능이 없어 새 프롬프트로 즉석 대응한 Claude가 평균 1위입니다. 다만 페이지별 편차가 극심합니다 — 가장 복잡한 병합 표(`jichul_p01`, rowspan 9회·colspan 13회)에서는 Claude가 최저점(0.143), 오히려 Upstage Standard가 최고점(0.974)으로 완전히 역전됩니다. 대형 희소 그리드(`franchise_p47/48`, 20행)에서는 반대로 Upstage가 붕괴(0.13대)하고 Claude/Clova가 거의 완벽(0.9+)합니다. **결론: 모든 표 유형에서 이기는 단일 엔진은 없습니다** — 표가 복잡한 병합 구조인지, 단순 대형 그리드인지에 따라 유리한 엔진이 다릅니다. 상세 페이지별 수치와 근거는 `results/report3/comparison.md` 7절 참고.

> **Mistral OCR 4는 텍스트 가격 2위인데 표 구조도 2위**라는, 이번 4파전에서 가장 눈에 띄는 조합입니다. 다만 최초 실행에서는 전 페이지 TEDS 0.000(표 미검출 9/9)이 나왔습니다 — 원인은 Mistral 응답의 표 객체 키가 공개 문서에 없어 `html`로 추측 구현했는데 실제로는 `content`였던 것. 원본 응답을 캐시에 그대로 보존해둔 덕분에 **API 재호출·재과금 없이** 캐시에서 파서만 고쳐 0.669로 정정했습니다(이 프로젝트가 CLOVA의 `tables` 스키마에도 같은 방식으로 미리 대비해둔 것과 동일한 안전장치). 유일한 표 미검출(`franchise_p01`)도 파싱 실패가 아니라, 테두리선 없는 1행×2열 서명란이라 Mistral이 표로 분류하지 않은 것으로 확인됨(텍스트 자체는 정확히 읽음).

전체 리포트(위 표 + 기능 체크리스트 + 문서별 유사도 + 표 구조(TEDS) + 추천 방안 + 한계)는 `py scripts/run_ocr3_benchmark.py [--tables]` 실행 후 `results/report3/comparison.md`에서 확인할 수 있습니다(생성물이라 커밋되지 않음 — 재생성하려면 아래 [실행](#실행) 참고).

## 비교 대상 6개 엔진 구성 (+표 구조 전용 1개)

| id                    | 엔진        | 설정                                                                                                                 |
| --------------------- | ----------- | -------------------------------------------------------------------------------------------------------------------- |
| `upstage_standard`    | Upstage     | Document Parse — Standard                                                                                            |
| `upstage_enhanced`    | Upstage     | Document Parse — Enhanced                                                                                            |
| `clova_text`          | Naver CLOVA | General OCR — 문자 인식만                                                                                            |
| `clova_table`         | Naver CLOVA | General OCR — 문자 인식 + 표 추출                                                                                    |
| `claude_sonnet`       | Claude      | Sonnet 5, 고해상도(장변 2576px)                                                                                      |
| `claude_sonnet_table` | Claude      | Sonnet 5 — 표 구조만 요청하는 별도 프롬프트 호출 (표 채점 전용)                                                      |
| `mistral_ocr`         | Mistral     | OCR 4 (`mistral-ocr-4-0`, 버전 고정) — 텍스트는 `table_format` 미지정, 표 구조는 `table_format="html"`로 별도 재호출 |

Claude는 Sonnet 5 고해상도 1개 구성만 다룹니다(Haiku/Opus 비교, 사람 앵커 품질 게이트 등은 [별도 계획](.omc/plans/ralplan-claude-vision-contract-ocr-benchmark.md) 소관). Mistral OCR 4는 티어 구분 없이 단일 구성입니다.

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
    mistral_client.py      # Mistral OCR API (텍스트: transcribe / 표 구조: transcribe_table)
  cache3.py               # fingerprint 기반 응답 캐시 (재실행 시 재과금 방지)
  aggregate3.py           # 페이지/문서/전체 집계 + 표 구조(TEDS) 집계, 게이트 없음
  report3.py              # markdown 비교 리포트 생성 (텍스트 + 표 구조 섹션)
scripts/
  prepare_ground_truth.py   # samples/pdfs -> ground_truth/images/manifest.json
  run_ocr3_benchmark.py     # 벤치마크 실행 + 리포트 생성 (--tables로 표 구조 채점 포함)
tests/                       # 181개 유닛테스트 (API 호출 없이 fixture 기반)
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

## 테스트

```bash
py -m pytest tests/ -v
```

전부 fixture/mock 기반이라 API 호출이나 과금이 발생하지 않습니다.
<br/>

## 주의사항

- 응답에 원인이 명확하지 않은 필드 구조가 나오면(공개 문서에 스키마가 없는 경우) 원본 응답을 캐시에 그대로 보존해 재과금 없이 파서를 고칠 수 있게 설계돼 있습니다 — Mistral의 표 객체 키(`content` vs 추측했던 `html`)가 실제로 이 방식으로 수정됐습니다(Update Logs 참고).
- Clova/Upstage/Mistral 단가의 VAT 포함 여부는 미확인입니다(Upstage는 VAT 별도로 명시, Clova/Mistral은 공개 자료에 없음).
- Claude는 비용 통제를 위해 `effort=low`로 고정했습니다 — 축소된 사고 예산이 품질을 체계적으로 낮췄을 수 있습니다.
- Mistral OCR 4의 한국어 지원 수준은 공개 벤치마크로 검증되지 않았습니다(지원 언어 목록에 한국어가 명시적으로 나열되지 않음) — 이 벤치마크가 사실상 최초의 실측입니다.
- 정답은 PDF에 내장된 텍스트 레이어(PyMuPDF)이며 사람이 검수한 전사가 아닙니다. 실물 스캔이 아닌 클린 렌더 코퍼스입니다.
- 표 정답(9페이지)은 사람이 렌더 이미지를 직접 보고 작성했으며, 셀 텍스트 표기에 작성자의 판단이 일부 들어가 있습니다.
- `franchise` 문서가 65페이지 중 48페이지를 차지하므로 문서 간 비교는 상관된 표본입니다.
