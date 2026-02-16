import json
from pathlib import Path

from modules.model_manager import ModelManager
from modules.tuning_worker import TuningWorker, run_weekly_tuning_once
from web_backend import _load_data_map, config_to_params, load_settings, load_user_config, ROOT_DIR


def main():
    settings = load_settings()
    raw_dfs = _load_data_map()
    if not raw_dfs:
        print(json.dumps({"ok": False, "error": "no_data"}))
        return

    base_cfg = load_user_config()
    base_params = config_to_params(base_cfg)

    worker = TuningWorker(
        state_path=Path("results/labs/trainer_state.json"),
        lock_path=Path("results/locks/trainer.lock"),
        cooldown_minutes_on_boot=int(settings.get("trainer_cooldown_minutes_on_boot", 15)),
        cadence_days=int(settings.get("tuning_cadence_days", 7)),
    )
    model_mgr = ModelManager(base_dir=ROOT_DIR / "models")

    result = run_weekly_tuning_once(
        worker=worker,
        raw_dfs=raw_dfs,
        base_params=base_params,
        model_manager=model_mgr,
        settings=settings,
        universe=settings.get("watchlist") or [],
    )
    print(json.dumps(result, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
