# backtest

Hybrid Spec v1.2 검증용 백테스트 스캐폴드.

## 포함 파일
- `splits/splits_v1.json`: 기간/킬존 정의
- `config/run_matrix.py`: R0~R4 런 매트릭스
- `core/evaluator.py`: Go/No-Go 판정
- `core/report_writer.py`: 필수 산출물 writer
- `core/runner.py`: 현재 mock 기반 실행기(실엔진 연동 전)
- `../run_backtest.py`: CLI 엔트리

## 실행
```bash
cd /mnt/f/SafeBot/openclaw-news-workspace/python
. .venv/bin/activate
python run_backtest.py
```

## 출력
- `backtest/out/<RUN_ID>/...` 필수 산출물
- `backtest/out/runner_summary.json`

> NOTE: `core/runner.py`의 `simulate_run`은 임시 mock 구현이며,
> 다음 단계에서 실제 데이터/엔진 인터페이스로 교체해야 함.
