import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from .oos_tuner import run_tuning_cycle
from .utils_json import safe_json_dump


class TuningWorker:
    def __init__(
        self,
        state_path="results/labs/trainer_state.json",
        lock_path="results/locks/trainer.lock",
        cooldown_minutes_on_boot=15,
        cadence_days=7,
    ):
        self.state_path = Path(state_path)
        self.lock_path = Path(lock_path)
        self.cooldown_minutes_on_boot = int(cooldown_minutes_on_boot)
        self.cadence_days = int(cadence_days)

    def _load_state(self):
        if not self.state_path.exists():
            return {
                "last_run_at": None,
                "next_due_at": None,
                "last_success_at": None,
                "active_model_id": None,
            }
        import json
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return {
                "last_run_at": None,
                "next_due_at": None,
                "last_success_at": None,
                "active_model_id": None,
            }

    def _save_state(self, state):
        safe_json_dump(state, self.state_path)

    def _acquire_lock(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            os.close(fd)
            return True
        except FileExistsError:
            return False

    def _release_lock(self):
        try:
            self.lock_path.unlink(missing_ok=True)
        except Exception:
            pass

    @staticmethod
    def _parse_dt(value):
        if not value:
            return None
        try:
            from datetime import datetime as _dt
            return _dt.fromisoformat(value)
        except Exception:
            return None

    def _next_due(self, now):
        return now + timedelta(days=self.cadence_days)

    def run_if_due(self, run_fn, sleep_fn=time.sleep):
        """
        run_fn: callable with no args, should return dict containing optional active_model_id.
        """
        if not self._acquire_lock():
            return {"ok": False, "skipped": "locked"}

        try:
            now = datetime.now()
            state = self._load_state()
            due = self._parse_dt(state.get("next_due_at"))
            if due is not None and now < due:
                return {"ok": True, "skipped": "not_due", "next_due_at": due.isoformat()}

            cooldown_sec = max(0, int(self.cooldown_minutes_on_boot) * 60)
            if cooldown_sec > 0:
                sleep_fn(cooldown_sec)

            result = run_fn()

            done = datetime.now()
            state["last_run_at"] = done.isoformat()
            state["next_due_at"] = self._next_due(done).isoformat()
            if bool(result.get("gate_pass", False)):
                state["last_success_at"] = done.isoformat()
            if result.get("active_model_id"):
                state["active_model_id"] = result.get("active_model_id")
            self._save_state(state)

            return {"ok": True, "result": result, "state": state}
        finally:
            self._release_lock()


def run_weekly_tuning_once(
    worker: TuningWorker,
    raw_dfs,
    base_params,
    model_manager,
    settings,
    universe,
):
    def _runner():
        cycle = run_tuning_cycle(
            raw_dfs=raw_dfs,
            base_params=base_params,
            model_manager=model_manager,
            strategy_name=str(settings.get("strategy_name", "default")),
            global_seed=int(settings.get("tuning_seed", 42)),
            universe=universe,
            train_days=int(settings.get("tuning_train_days", 180)),
            oos_days=int(settings.get("tuning_oos_days", 28)),
            embargo_days=int(settings.get("tuning_embargo_days", 2)),
            n_trials=int(settings.get("tuning_trials", 30)),
            oos_min_trades=int(settings.get("tuning_oos_min_trades", 20)),
            mdd_cap=float(settings.get("tuning_mdd_cap", -0.15)),
            delta_min=float(settings.get("tuning_delta_min", 0.0)),
        )
        cycle["active_model_id"] = model_manager.active_model_id()
        return cycle

    return worker.run_if_due(_runner)
