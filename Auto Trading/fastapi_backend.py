import os
import sys
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

# Align cwd/import behavior with legacy backend
AUTO_DIR = Path(__file__).resolve().parent
ROOT_DIR = AUTO_DIR.parent
sys.path.append(str(AUTO_DIR))
os.chdir(str(ROOT_DIR))

from modules.adapter_upbit import UpbitAdapter
from modules.adapter_bithumb import BithumbAdapter
from modules.capital_ledger import CapitalLedger
from modules.watch_engine import WatchEngine
from modules.run_controller import RunController
from modules.notifier_telegram import TelegramNotifier
from modules.safe_start import (
    SafeStartManager,
    PHASE_RUNNING,
    PHASE_WAITING_OPERATOR,
)
from modules.single_instance_lock import SingleInstanceLock


RESULTS_DIR = ROOT_DIR / "results"
LOCK_PATH = RESULTS_DIR / "locks" / "bot.lock"
RUNTIME_STATUS_PATH = RESULTS_DIR / "runtime_status.json"
RUNTIME_STATE_PATH = RESULTS_DIR / "runtime_state.json"
SAFE_START_STATE_PATH = RESULTS_DIR / "safe_start_state.json"


class StartRequest(BaseModel):
    mode: str = "PAPER"
    exchange: str = "UPBIT"
    seed: int = 1000000
    force_unlock: bool = False


class ConfirmRequest(BaseModel):
    phrase: str


class BackendService:
    def __init__(self):
        self._mtx = threading.Lock()
        self.controller: Optional[RunController] = None
        self.worker: Optional[threading.Thread] = None
        self.last_error: Optional[str] = None
        self.pending = None
        self.lock = SingleInstanceLock(LOCK_PATH)
        self.safe_start = SafeStartManager(
            state_path=SAFE_START_STATE_PATH,
            runtime_state_path=RUNTIME_STATE_PATH,
            runtime_status_path=RUNTIME_STATUS_PATH,
        )

    def _is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive() and self.controller and self.controller.running)

    def status(self):
        state = self.safe_start.read_state()
        return {
            "ok": True,
            "running": self._is_running(),
            "phase": state.get("phase"),
            "safe_start": state,
            "pending": self.pending,
            "last_error": self.last_error,
        }

    def start(self, req: StartRequest):
        with self._mtx:
            if self._is_running():
                return {"ok": False, "error": "already-running"}

            mode = str(req.mode or "PAPER").upper()
            exchange = str(req.exchange or "UPBIT").upper()
            seed = int(req.seed)

            ok, lock_msg = self.lock.acquire(mode=mode, exchange=exchange, force=bool(req.force_unlock))
            if not ok:
                return {"ok": False, "error": "lock-failed", "detail": lock_msg}

            self.safe_start.begin_boot()

            try:
                if exchange == "UPBIT":
                    adapter = UpbitAdapter(use_env=True)
                elif exchange == "BITHUMB":
                    key = os.getenv("BITHUMB_KEY")
                    secret = os.getenv("BITHUMB_SECRET")
                    if not key or not secret:
                        self.lock.release()
                        self.safe_start.mark_stopped("Missing BITHUMB credentials")
                        return {"ok": False, "error": "missing-bithumb-credentials"}
                    adapter = BithumbAdapter(key, secret)
                else:
                    self.lock.release()
                    self.safe_start.mark_stopped(f"Unsupported exchange: {exchange}")
                    return {"ok": False, "error": "unsupported-exchange"}

                notifier = TelegramNotifier()
                ledger = CapitalLedger(exchange_name=exchange, initial_seed=seed)
                watch = WatchEngine(notifier)
                controller = RunController(adapter, ledger, watch, notifier, mode=mode)

                sync_result = self.safe_start.sync_check()
                if not sync_result.ok:
                    self.pending = {
                        "mode": mode,
                        "exchange": exchange,
                        "seed": seed,
                        "controller": controller,
                    }
                    self.controller = None
                    self.worker = None
                    return {
                        "ok": False,
                        "error": "sync-check-failed",
                        "phase": sync_result.phase,
                        "details": sync_result.details,
                    }

                self.pending = {
                    "mode": mode,
                    "exchange": exchange,
                    "seed": seed,
                    "controller": controller,
                    "expected_phrase": f"CONFIRM START {exchange} {mode} SEED={seed}",
                }
                return {
                    "ok": True,
                    "phase": PHASE_WAITING_OPERATOR,
                    "requires_operator_confirm": True,
                    "expected_phrase": self.pending["expected_phrase"],
                }
            except Exception as e:
                self.last_error = str(e)
                self.lock.release()
                self.safe_start.mark_stopped(f"start-failed: {e}")
                return {"ok": False, "error": "start-exception", "detail": str(e)}

    def confirm_and_run(self, req: ConfirmRequest):
        with self._mtx:
            state = self.safe_start.read_state()
            if state.get("phase") != PHASE_WAITING_OPERATOR:
                return {"ok": False, "error": "not-waiting-operator", "phase": state.get("phase")}

            if not self.pending:
                return {"ok": False, "error": "no-pending-start"}

            expected = self.pending.get("expected_phrase")
            if str(req.phrase or "").strip() != expected:
                return {"ok": False, "error": "bad-confirm-phrase", "expected_phrase": expected}

            controller = self.pending.get("controller")
            if controller is None:
                return {"ok": False, "error": "pending-controller-missing"}

            worker = threading.Thread(target=controller.run, daemon=True)
            worker.start()

            self.controller = controller
            self.worker = worker
            self.pending = None
            self.safe_start.mark_running()
            return {"ok": True, "phase": PHASE_RUNNING}

    def stop(self):
        with self._mtx:
            if self.controller is not None:
                try:
                    self.controller.stop()
                except Exception as e:
                    self.last_error = str(e)
            if self.worker is not None and self.worker.is_alive():
                self.worker.join(timeout=5)

            self.controller = None
            self.worker = None
            self.pending = None
            self.lock.release()
            self.safe_start.mark_stopped("Stopped by operator")
            return {"ok": True}


service = BackendService()
app = FastAPI(title="SafeBot Backend API", version="0.1.0")


@app.get("/api/v1/health")
def health():
    return {"ok": True}


@app.get("/api/v1/status")
def status():
    return service.status()


@app.post("/api/v1/control/start")
def control_start(req: StartRequest):
    return service.start(req)


@app.post("/api/v1/control/confirm")
def control_confirm(req: ConfirmRequest):
    return service.confirm_and_run(req)


@app.post("/api/v1/control/stop")
def control_stop():
    return service.stop()


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("BACKEND_HOST", "127.0.0.1")
    port = int(os.getenv("BACKEND_PORT", "8765"))
    uvicorn.run(app, host=host, port=port)
