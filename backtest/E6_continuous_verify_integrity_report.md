# E6 Continuous Verify Guardrail - 기준 파일셋 정합성 점검

점검 대상(절대경로): `/mnt/f/SafeBot/openclaw-news-workspace/python/backtest`
- `out_at_fix`
- `out_at_final`
- `out_at_continuous`

점검 시각(KST): 2026-02-19 02:0x

## 1) 구조 정합성 (파일셋 존재/개수/경로)
- 세 디렉터리 모두 존재 확인: OK
- 파일 수:
  - `out_at_fix`: 106 files
  - `out_at_final`: 106 files
  - `out_at_continuous`: 106 files
- 상대경로 기준 파일 목록 비교 결과:
  - 누락/초과 파일 없음 (3셋 모두 동일 파일 경로 집합): OK
- 구성 패턴:
  - 공통으로 15개 run 폴더(`R0~R4` 실험군) + `runner_summary.json`
  - run 폴더별 공통 산출물 7종(`daily_state.csv`, `guards.csv`, `metrics_by_mode.json`, `metrics_total.json`, `summary.json`, `switches.csv`, `trades.csv`)

## 2) 내용 정합성 (SHA-256 해시 비교)
### `out_at_fix` vs `out_at_final`
- 경로 차이: 0
- 내용(해시) 차이: 76
  - `daily_state.csv` 15
  - `guards.csv` 15
  - `metrics_by_mode.json` 15
  - `metrics_total.json` 15
  - `summary.json` 15
  - `runner_summary.json` 1

### `out_at_fix` vs `out_at_continuous`
- 경로 차이: 0
- 내용(해시) 차이: 76
  - 분포는 위와 동일

### `out_at_final` vs `out_at_continuous`
- 경로 차이: 0
- 내용(해시) 차이: 16
  - `summary.json` 15
  - `runner_summary.json` 1

## 3) 해석
- **구조 정합성(파일셋/경로)** 관점에서는 세 기준셋이 정상 정렬되어 있음.
- **내용 정합성** 관점에서:
  - `fix`는 입력 run_summary 기준이 달라(`20260204...`) `final/continuous`와 광범위 차이(76) 발생.
  - `final`과 `continuous`는 대부분 동일하고, 차이는 `summary.json` 계열(및 runner 요약)로 한정됨.

## 4) 샘플 차이(참고)
`out_at_final/R0_AGG/summary.json` vs `out_at_continuous/R0_AGG/summary.json` 예시에서 추가 필드 확인:
- `returns_mapping_source`
- `gates.kz_scope_required`

(코드 로직 수정 없이 파일셋 상태 점검만 수행)
