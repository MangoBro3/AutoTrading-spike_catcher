# Task C 증거 수집 (항목 3/4/5)

기준 경로(절대): `/mnt/f/SafeBot/openclaw-news-workspace/python`
작성 시각(KST): 2026-02-19 02:24 이후 수집

---

## 3) run_id별 입력 매핑표 (경로 존재 확인)

- run_id 소스: `backtest/config/run_matrix.py`
- 관례 경로(conventional): `Auto Trading/results/runs/<run_id>/run_summary.json`
- 실제 매핑 상태 증거: `backtest/out_at_continuous/<run_id>/summary.json`의 `input_mapping_status`
- 참고: 현재 `backtest/config/autotrading_run_summary_map.json` 파일은 **없음(ENOENT)**

| run_id | expected input path (conventional) | path exists | input_mapping_status (증거) |
|---|---|---:|---|
| R0_DEF | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runs/R0_DEF/run_summary.json` | ❌ | `run_id_path_missing:R0_DEF|default_from_cli_reused` |
| R0_AGG | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runs/R0_AGG/run_summary.json` | ❌ | `run_id_path_missing:R0_AGG|default_from_cli_reused` |
| R0_HYB | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runs/R0_HYB/run_summary.json` | ❌ | `run_id_path_missing:R0_HYB|default_from_cli_reused` |
| R1_SCOUT_ON | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runs/R1_SCOUT_ON/run_summary.json` | ❌ | `run_id_path_missing:R1_SCOUT_ON|default_from_cli_reused` |
| R1_SCOUT_OFF | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runs/R1_SCOUT_OFF/run_summary.json` | ❌ | `run_id_path_missing:R1_SCOUT_OFF|default_from_cli_reused` |
| R1_ATR_IGN_ON | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runs/R1_ATR_IGN_ON/run_summary.json` | ❌ | `run_id_path_missing:R1_ATR_IGN_ON|default_from_cli_reused` |
| R1_ATR_IGN_OFF | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runs/R1_ATR_IGN_OFF/run_summary.json` | ❌ | `run_id_path_missing:R1_ATR_IGN_OFF|default_from_cli_reused` |
| R1_RATE_ON | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runs/R1_RATE_ON/run_summary.json` | ❌ | `run_id_path_missing:R1_RATE_ON|default_from_cli_reused` |
| R1_RATE_OFF | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runs/R1_RATE_OFF/run_summary.json` | ❌ | `run_id_path_missing:R1_RATE_OFF|default_from_cli_reused` |
| R2_MULTI | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runs/R2_MULTI/run_summary.json` | ❌ | `run_id_path_missing:R2_MULTI|default_from_cli_reused` |
| R2_SIMPLE | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runs/R2_SIMPLE/run_summary.json` | ❌ | `run_id_path_missing:R2_SIMPLE|default_from_cli_reused` |
| R3_FEE_X2 | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runs/R3_FEE_X2/run_summary.json` | ❌ | `run_id_path_missing:R3_FEE_X2|default_from_cli_reused` |
| R3_SLIP_X2 | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runs/R3_SLIP_X2/run_summary.json` | ❌ | `run_id_path_missing:R3_SLIP_X2|default_from_cli_reused` |
| R3_BOTH_X2 | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runs/R3_BOTH_X2/run_summary.json` | ❌ | `run_id_path_missing:R3_BOTH_X2|default_from_cli_reused` |
| R4_KILL | `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/runs/R4_KILL/run_summary.json` | ❌ | `run_id_path_missing:R4_KILL|default_from_cli_reused` |

---

## 4) 공통값 재사용 차단 코드 위치 3개 (file:line)

아래 3개는 `run_id` 미매핑/누락 시 다른 run의 값을 조용히 재사용하지 않도록 막는 핵심 지점:

1. `backtest/core/autotrading_adapter.py:192-194`  
   - (docstring) *"...missing ... instead of silently reusing another run summary."*

2. `backtest/core/autotrading_adapter.py:327-329`  
   - `run_summary_map`가 있을 때 `run_id` 미존재 시 즉시 `None` 반환:  
   - `return None, f"run_id_unmapped:{run_id}|{run_summary_map_status}"`

3. `backtest/core/autotrading_adapter.py:350-363`  
   - `ctx is None`이면 재사용 대신 중립값/요약불가 상태로 처리:  
   - `guard_mapping_status = "guards_unavailable_no_summary"`  
   - `schema_status = "summary_unavailable"`  
   - `returns_mapping_source = "summary_unavailable"`

---

## 5) fail-fast 발동 로그 원문 1개 (타임스탬프 포함)

로그 파일: `/mnt/f/SafeBot/openclaw-news-workspace/python/Auto Trading/results/logs/launcher.log`

원문:

```text
2026-02-04 13:49:10,293 [ERROR] Init Failed
Traceback (most recent call last):
  File "C:\Users\nak\Desktop\DHR 런처\python\Auto Trading\launcher.py", line 73, in start_trading_thread
    notifier = TelegramNotifier(token=None, chat_id=None) # Will load env inside
TypeError: TelegramNotifier.__init__() got an unexpected keyword argument 'token'
```

- 타임스탬프 포함 에러 로그이며, 초기화 단계에서 즉시 중단(실패 즉시 종료)된 사례로 수집.
