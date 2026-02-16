# DHR Launcher Handover

Last updated: 2026-02-11

## 1) Repo Root / Entry Points

### Current project root
- `C:\Users\nak\Desktop\DHR 런처\python\Auto Trading`

### Main entry scripts
- `Auto Trading\web_backend.py`: 로컬 웹 백엔드/UI (`http://127.0.0.1:8765`)
- `Auto Trading\launcher.py`: 콘솔 대시보드/메뉴 진입점
- `Auto Trading\run_tuning_worker.py`: OOS 튜닝 워커 1회 실행
- `Auto Trading\main.py`: 기존 메인 실행 경로(legacy)
- `Auto Trading\app.py`: 기존 앱 실행 경로(legacy)
- `Auto Trading\trader.py`: 트레이더 실행 경로(legacy)
- `Auto Trading\trader_v2.py`: 트레이더 v2 실행 경로(legacy)
- `Auto Trading\run_autotune_cli.py`: 예전 autotune CLI 경로
- `Auto Trading\monitor.py`: 모니터링 경로
- `Auto Trading\scheduler.py`: 기존 스케줄러 경로

### Batch entry files
- `Auto Trading\Run_Bot_V2.bat`
- `Auto Trading\Run_Lab.bat`
- `Auto Trading\Run_Menu.bat`

## 2) What Was Implemented

### OOS tuning pipeline (ML 제외)
- Training/OOS split and gate logic added.
- Candidate promotion is conditional (PASS only).
- Model registry with fixed dirs:
  - `models/_active`
  - `models/_staging/<run_id>`
  - `models/_archive/<run_id>`

### Weekly/on-demand worker basis
- Worker state/lock structure prepared:
  - `results/labs/trainer_state.json`
  - `results/locks/trainer.lock`

### Web backend integration
- `run_evolution` now uses OOS gate cycle.
- `run_backtest` evaluates active model on latest OOS window.
- `/api/models` endpoint added.

### Settings/UI additions
- OOS/tuning parameters are exposed in Settings.
- Scheduler uses **anchor time + interval**:
  - `evolution_anchor_time` (HH:MM, local)
  - `evolution_interval_hours`

## 3) Files Changed (core)

- `Auto Trading/web_backend.py`
- `Auto Trading/backtester.py`
- `Auto Trading/modules/model_manager.py`
- `Auto Trading/modules/oos_tuner.py`
- `Auto Trading/modules/tuning_worker.py`
- `Auto Trading/run_tuning_worker.py`
- `Auto Trading/test_oos_pipeline.py`

## 4) Run Commands

### Backend UI
```powershell
python "Auto Trading\web_backend.py"
```
Open:
```text
http://127.0.0.1:8765/
```

### Launcher
```powershell
python "Auto Trading\launcher.py"
```

### Worker one-shot
```powershell
python "Auto Trading\run_tuning_worker.py"
```

### Test
```powershell
python "Auto Trading\test_oos_pipeline.py"
```

## 5) Parameter Reference (설정값 설명)

### Scheduler / Evolution
- `evolution_enabled` (bool): 자동 evolution 스케줄 사용 여부
- `evolution_anchor_time` (str, `HH:MM`): 스케줄 계산 기준 시각(로컬)
- `evolution_interval_hours` (int, >=1): 기준 시각에서 몇 시간 간격으로 돌릴지

### OOS tuning policy
- `tuning_train_days` (int): Training 구간 길이(일), 기본 180
- `tuning_oos_days` (int): OOS 구간 길이(일), 기본 28
- `tuning_embargo_days` (int): Training-OOS 사이 embargo(일), 기본 2
- `tuning_trials` (int): 튜닝 candidate 시도 횟수
- `tuning_oos_min_trades` (int): OOS 게이트 최소 거래수
- `tuning_delta_min` (float): Active 대비 최소 점수 개선폭
- `tuning_seed` (int): deterministic 탐색 시드
- `trainer_cooldown_minutes_on_boot` (int): 워커 부팅 후 계산 시작 전 대기분

### Scoring / Gate fixed policy
- Score: `ROI - 0.5 * abs(MDD)`
- Gate PASS 조건:
  - OOS 4주 중 양수 주 >= 3
  - OOS trades >= `tuning_oos_min_trades`
  - Candidate score >= Active score + `tuning_delta_min`

### Legacy/Active key status (중요)

| Key | 상태 | 실제 사용 위치/설명 |
|---|---|---|
| `evolution_enabled` | Active | `web_backend.py` scheduler on/off 제어 |
| `evolution_anchor_time` | Active | `web_backend.py` scheduler 슬롯 계산 기준시각 |
| `evolution_interval_hours` | Active | `web_backend.py` scheduler 주기 |
| `tuning_train_days` | Active | OOS split에서 train 윈도우 길이 |
| `tuning_oos_days` | Active | OOS 윈도우 길이 |
| `tuning_embargo_days` | Active | train/oos 사이 embargo |
| `tuning_trials` | Active | candidate 탐색 횟수 |
| `tuning_oos_min_trades` | Active | OOS gate 최소 거래수 |
| `tuning_delta_min` | Active | Active 대비 점수 개선폭 |
| `tuning_seed` | Active | deterministic seed |
| `tuning_cadence_days` | Partial | `run_tuning_worker.py`에서만 사용 (웹 scheduler에는 미적용) |
| `trainer_cooldown_minutes_on_boot` | Partial | `run_tuning_worker.py`에서만 사용 |
| `evolution_lookback_days` | Legacy | UI/저장만, 현재 OOS 실행 경로에서 미사용 |
| `evolution_trials_per_group` | Legacy | 미사용 함수 `_evaluate_candidates()` 내부에만 잔존 |
| `evolution_min_improve_pct` | Legacy | UI/저장만, OOS gate에 미연결 |
| `evolution_min_trades` | Legacy | UI/저장만, OOS gate는 `tuning_oos_min_trades` 사용 |
| `evolution_max_dd` | Legacy | UI/저장만, OOS score/gate에 미연결 |
| `evolution_require_sharpe` | Legacy | UI/저장만, OOS score/gate에 미연결 |

## 6) Logic Reference (핵심 로직 설명)

### A. Split logic
- 최신 데이터 시점 `T`를 잡고 윈도우 생성:
  - OOS: `T-(oos_days-1) ~ T`
  - Embargo: OOS 시작 직전 `embargo_days`
  - Training: Embargo 직전 `train_days`

### B. Evolution run logic (`run_evolution`)
- 데이터 로드 -> 파라미터 후보 탐색 -> Training 평가 -> Best candidate 선정
- 동일 OOS 구간에서 Candidate vs Active 평가
- Gate PASS 시:
  - staging artifact 기록
  - `_active`로 atomic promote
  - Paper config 업데이트 + pending live 기록
- Gate FAIL 시:
  - candidate archive
  - active 유지

### C. Backtest run logic (`run_backtest`)
- Active 모델 파라미터 로드
- 최신 OOS 구간만 평가
- `last_result.json`, `last_baseline.json` 갱신

### D. Scheduler logic
- 앱 실행 중 주기적으로 now 확인
- `anchor_time + interval_hours` 기반으로 `last_due` 슬롯 계산
- `last_evolution_ts < last_due`일 때만 실행
- 같은 슬롯 중복 실행 방지

### E. Worker logic (on-demand)
- `trainer.lock` 단일 인스턴스 보장
- `next_due_at` 이전이면 clean exit
- due면 tuning cycle 실행 후 state 갱신

## 7) WinError 5 Fix (data_status.json)

### Symptom
`PermissionError: [WinError 5] ... data_status.tmp -> data_status.json`

### Root cause
Windows file lock/transient access race during atomic replace.

### Fix applied
- `_safe_write_json` now:
  - writes to unique tmp filename per attempt
  - flush + fsync
  - retries with backoff on `PermissionError`
- `_write_data_status` now catches write exceptions and logs warning instead of killing update thread.

## 8) Operational Notes

- If backend starts but data update thread fails, check:
  - `results/logs/labs.log`
  - `results/labs/data_status.json`
- If model promotion seems stuck:
  - inspect `models/_staging`, `models/_active`, `models/_archive`
  - restart backend once (recovery logic rechecks model dirs).

## 9) Known Gaps / Next Work

- UI currently exposes both old evolution fields and new OOS fields.
  - Recommend cleanup to reduce confusion.
- Add dedicated API endpoint to return next scheduler due time for UI visibility.
- Add integration test that boots web backend and validates scheduler slot behavior end-to-end.
