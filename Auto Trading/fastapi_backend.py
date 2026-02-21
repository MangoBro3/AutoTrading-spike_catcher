import argparse
import json
import os
import sys
import threading
import time
import logging
import logging.config
from datetime import datetime
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
    PHASE_BOOTING_DEGRADED,
    PHASE_RUNNING,
    PHASE_WAITING_OPERATOR,
    PHASE_WAITING_SYNC,
)
from modules.single_instance_lock import SingleInstanceLock


RESULTS_DIR = ROOT_DIR / "results"
LOCK_PATH = RESULTS_DIR / "locks" / "bot.lock"
RUNTIME_STATUS_PATH = RESULTS_DIR / "runtime_status.json"
RUNTIME_STATE_PATH = RESULTS_DIR / "runtime_state.json"
SAFE_START_STATE_PATH = RESULTS_DIR / "safe_start_state.json"
BACKEND_LOG_PATH = RESULTS_DIR / "logs" / "backend.log"


def configure_logging() -> dict:
    BACKEND_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    log_fmt = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
    uvicorn_log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": log_fmt,
            }
        },
        "handlers": {
            "stderr": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "stream": "ext://sys.stderr",
            },
            "file": {
                "class": "logging.FileHandler",
                "formatter": "default",
                "filename": str(BACKEND_LOG_PATH),
                "encoding": "utf-8",
            },
        },
        "root": {
            "handlers": ["stderr", "file"],
            "level": "INFO",
        },
        "loggers": {
            "uvicorn": {"handlers": ["stderr", "file"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["stderr", "file"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["stderr", "file"], "level": "INFO", "propagate": False},
        },
    }
    logging.config.dictConfig(uvicorn_log_config)
    return uvicorn_log_config


class StartRequest(BaseModel):
    mode: str = "PAPER"
    exchange: str = "UPBIT"
    seed: int = 1000000
    force_unlock: bool = False


class ConfirmRequest(BaseModel):
    phrase: str


class ManualRoundtripRequest(BaseModel):
    symbol: str = "KRW-XRP"
    krw_notional: float = 5500
    buy_offset_ticks: int = 1
    hold_seconds: int = 30
    confirm: str = ""


class BackendService:
    def __init__(self):
        self._mtx = threading.Lock()
        self.controller: Optional[RunController] = None
        self.worker: Optional[threading.Thread] = None
        self.last_error: Optional[str] = None
        self.pending = None
        self.lock = SingleInstanceLock(LOCK_PATH)
        self.manual_roundtrip = {"running": False, "stage": "IDLE", "last_result": None, "last_error": None}
        self.safe_start = SafeStartManager(
            state_path=SAFE_START_STATE_PATH,
            runtime_state_path=RUNTIME_STATE_PATH,
            runtime_status_path=RUNTIME_STATUS_PATH,
        )

    def _is_running(self) -> bool:
        return bool(self.worker and self.worker.is_alive() and self.controller and self.controller.running)

    def _json_safe(self, value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, list):
            return [self._json_safe(v) for v in value]
        if isinstance(value, tuple):
            return [self._json_safe(v) for v in value]
        if isinstance(value, dict):
            return {str(k): self._json_safe(v) for k, v in value.items()}
        try:
            return str(value)
        except Exception:
            return f"<{value.__class__.__name__}>"

    def _pending_status(self):
        if not isinstance(self.pending, dict):
            return None
        return {
            "mode": self.pending.get("mode"),
            "exchange": self.pending.get("exchange"),
            "seed": self.pending.get("seed"),
            "expected_phrase": self.pending.get("expected_phrase"),
            "has_controller": self.pending.get("controller") is not None,
        }

    def _read_runtime_status(self):
        try:
            if RUNTIME_STATUS_PATH.exists():
                return json.loads(RUNTIME_STATUS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _build_virtual_capital(self):
        seed = 0.0
        equity = 0.0
        cap = None
        try:
            if self.controller and getattr(self.controller, 'ledger', None):
                ls = self.controller.ledger.get_state() or {}
                seed = float(ls.get('baseline_seed', 0.0) or 0.0)
                equity = float(ls.get('equity', 0.0) or 0.0)
        except Exception:
            pass

        runtime = self._read_runtime_status()
        vc = runtime.get('virtual_capital') if isinstance(runtime, dict) else {}
        if not equity:
            equity = float((vc or {}).get('equity_virtual', 0.0) or runtime.get('equity', 0.0) or 0.0)
        if not seed:
            seed = float((vc or {}).get('allocated', 0.0) or runtime.get('seed_krw', 0.0) or 0.0)
        cap_raw = (vc or {}).get('cap_krw', None)
        try:
            cap = float(cap_raw) if cap_raw is not None else None
        except Exception:
            cap = None

        def _f(v):
            try:
                return float(v) if v is not None else None
            except Exception:
                return None

        total_cap = _f((vc or {}).get('total_cap_krw'))
        upbit_cap = _f((vc or {}).get('upbit_cap_krw'))
        bithumb_cap = _f((vc or {}).get('bithumb_cap_krw'))
        selected_cap = _f((vc or {}).get('selected_cap_krw'))

        next_available = equity if not (cap is not None and cap > 0) else min(equity, cap)
        pnl = equity - seed
        pnl_pct = (pnl / seed * 100.0) if seed > 0 else 0.0
        return {
            'rule': 'next_available_capital = current_virtual_equity',
            'seed_krw': seed,
            'equity_virtual': equity,
            'next_available_capital': max(0.0, next_available),
            'available_for_bot': max(0.0, next_available),
            'pnl_virtual': pnl,
            'pnl_pct_virtual': pnl_pct,
            'cap_krw': cap,
            'total_cap_krw': total_cap,
            'upbit_cap_krw': upbit_cap,
            'bithumb_cap_krw': bithumb_cap,
            'selected_cap_krw': selected_cap if selected_cap is not None else cap,
            'exchange': (vc or {}).get('exchange'),
        }

    def _status_guidance(self, state: dict):
        phase = str((state or {}).get("phase") or "STOPPED").upper()
        details = (state or {}).get("details") or {}
        pending = self._pending_status()
        expected_phrase = (pending or {}).get("expected_phrase")

        why_blocked = None
        next_action = None
        requires_operator_confirm = False

        if phase == PHASE_RUNNING:
            pass
        elif phase == PHASE_WAITING_OPERATOR:
            why_blocked = str(details.get("message") or "Operator confirmation required")
            next_action = "confirm_start"
            requires_operator_confirm = True
        elif phase == PHASE_WAITING_SYNC:
            why_blocked = str(details.get("message") or "Sync check failed")
            next_action = "resolve_sync_and_retry_start"
        elif phase == PHASE_BOOTING_DEGRADED:
            why_blocked = str(details.get("message") or "Booting in degraded mode")
            next_action = "wait_boot_or_check_status"
        else:
            why_blocked = str(details.get("message") or "Stopped")
            next_action = "start"

        return {
            "why_blocked": why_blocked,
            "next_action": next_action,
            "requires_operator_confirm": bool(requires_operator_confirm),
            "expected_phrase": expected_phrase,
        }

    def status(self):
        try:
            state = self.safe_start.read_state()
        except Exception as e:
            state = {"phase": "STOPPED", "details": {"error": f"safe_start_read_failed:{e.__class__.__name__}"}, "ts": None}

        guidance = self._status_guidance(state)
        payload = {
            "ok": True,
            "running": self._is_running(),
            "manual_roundtrip": self.manual_roundtrip,

            "phase": state.get("phase"),
            "safe_start": state,
            "pending": self._pending_status(),
            "virtual_capital": self._build_virtual_capital(),
            "last_error": self.last_error,
            "why_blocked": guidance["why_blocked"],
            "next_action": guidance["next_action"],
            "requires_operator_confirm": guidance["requires_operator_confirm"],
            "expected_phrase": guidance["expected_phrase"],
        }
        return self._json_safe(payload)

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

    def mode(self, req: StartRequest):
        # alias endpoint for unified LIVE/PAPER transition flow
        return self.start(req)

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

    def _tick_size_krw(self, price: float) -> float:
        p = float(price or 0.0)
        if p < 0.1: return 0.0001
        if p < 1: return 0.001
        if p < 10: return 0.01
        if p < 100: return 0.1
        if p < 1000: return 1.0
        if p < 10000: return 5.0
        if p < 100000: return 10.0
        if p < 500000: return 50.0
        if p < 1000000: return 100.0
        if p < 2000000: return 500.0
        return 1000.0

    def _round_tick(self, price: float, tick: float, side: str) -> float:
        u = float(price) / max(1e-12, float(tick))
        n = int(u) if (side == "sell" or abs(u - int(u)) < 1e-12) else int(u) + 1
        return max(float(tick), n * float(tick))

    def _manual_roundtrip_worker(self, req: ManualRoundtripRequest):
        err = None
        result = None
        try:
            c = self.controller
            if c is None:
                raise RuntimeError("controller not running")
            ex = c._resolve_exchange_api(None)
            mode = str(getattr(c, "mode", "PAPER")).upper()
            if mode == "LIVE" and str(req.confirm or "").strip() != "MANUAL ROUNDTRIP LIVE":
                raise RuntimeError("LIVE blocked: confirm required (MANUAL ROUNDTRIP LIVE)")
            symbol = str(req.symbol or "KRW-XRP").upper()
            ccxt_symbol = c._to_ccxt_symbol(symbol)
            t = ex.fetch_ticker(ccxt_symbol) or {}
            px = float(t.get("last") or t.get("close") or 0.0)
            if px <= 0:
                raise RuntimeError("ticker unavailable")
            tick = self._tick_size_krw(px)
            buy_px = self._round_tick(px + int(req.buy_offset_ticks) * tick, tick, "buy")
            buy_qty = max(0.0, float(req.krw_notional) * 0.998 / buy_px)
            self.manual_roundtrip["stage"] = "LIMIT_BUY"
            bo = ex.create_order(ccxt_symbol, "limit", "buy", buy_qty, buy_px)
            bid = bo.get("id")
            if not bid:
                raise RuntimeError("buy order id missing")
            time.sleep(1.0)
            bq = 0.0; bav = 0.0
            for _ in range(50):
                od = ex.fetch_order(bid, ccxt_symbol) or {}
                bq = float(od.get("filled") or 0.0)
                bav = float(od.get("average") or 0.0)
                if str(od.get("status","")).lower() in {"closed","filled"} or bq >= buy_qty - 1e-12:
                    break
                time.sleep(0.5)
            if bq < buy_qty - 1e-12:
                try: ex.cancel_order(bid, ccxt_symbol)
                except Exception: pass
            if bq <= 0:
                raise RuntimeError("buy not filled")
            self.manual_roundtrip["stage"] = "HOLD"
            time.sleep(max(1, int(req.hold_seconds)))
            remaining = bq
            sold = 0.0
            amount = 0.0
            sells = []
            for _ in range(3):
                if remaining <= 1e-12: break
                tx = ex.fetch_ticker(ccxt_symbol) or {}
                spx0 = float(tx.get("last") or tx.get("close") or px)
                stk = self._tick_size_krw(spx0)
                spx = self._round_tick(spx0, stk, "sell")
                so = ex.create_order(ccxt_symbol, "limit", "sell", remaining, spx)
                sid = so.get("id")
                if not sid: break
                sq=0.0; sav=0.0
                for _ in range(40):
                    od = ex.fetch_order(sid, ccxt_symbol) or {}
                    sq = float(od.get("filled") or 0.0)
                    sav = float(od.get("average") or 0.0)
                    if str(od.get("status","")).lower() in {"closed","filled"} or sq >= remaining - 1e-12:
                        break
                    time.sleep(0.5)
                if sq < remaining - 1e-12:
                    try: ex.cancel_order(sid, ccxt_symbol)
                    except Exception: pass
                sold += sq
                amount += sq * (sav if sav>0 else spx)
                remaining = max(0.0, remaining - sq)
                sells.append({"order_id": sid, "filled": sq, "avg": sav if sav>0 else spx})
            result = {"ok": sold>0, "symbol": symbol, "buy": {"order_id": bid, "filled_qty": bq, "avg": bav, "limit_price": buy_px}, "sell": {"orders": sells, "filled_qty": sold, "remaining_qty": remaining}, "hold_seconds": int(req.hold_seconds)}
        except Exception as e:
            err = str(e)
        self.manual_roundtrip.update({"running": False, "stage": "DONE" if err is None else "ERROR", "last_result": result, "last_error": err})

    def start_manual_roundtrip(self, req: ManualRoundtripRequest):
        with self._mtx:
            if self.manual_roundtrip.get("running"):
                return {"ok": False, "error": "manual-roundtrip-running"}
            if not self._is_running() or self.controller is None:
                return {"ok": False, "error": "controller-not-running"}
            self.manual_roundtrip.update({"running": True, "stage": "QUEUED", "last_error": None})
            t = threading.Thread(target=self._manual_roundtrip_worker, args=(req,), daemon=True)
            t.start()
            return {"ok": True, "message": "accepted", "manual_roundtrip": self.manual_roundtrip}

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


class BackendStatusTUI:
    _ANSI_CLEAR_HOME = "\x1b[2J\x1b[H"

    def __init__(self, backend_service: BackendService, interval_sec: float = 1.5):
        self.backend_service = backend_service
        self.interval_sec = max(1.0, float(interval_sec))
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._stdout_is_tty = bool(getattr(sys.stdout, "isatty", lambda: False)())

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_evt.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._stdout_is_tty:
            sys.stdout.write("\n")
            sys.stdout.flush()

    def _safe_json_read(self, path: Path):
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _fmt_ts(self, ts):
        try:
            if ts is None:
                return "-"
            return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return "-"

    def _fetch_open_orders_count(self):
        c = self.backend_service.controller
        if c is None or not getattr(c, "running", False):
            return 0, "-"
        try:
            adapter = getattr(c, "adapter", None)
            if adapter and hasattr(adapter, "get_open_orders"):
                orders = adapter.get_open_orders() or []
                return len(orders), "OK"
            return 0, "N/A"
        except Exception as e:
            return 0, f"ERR:{e.__class__.__name__}"

    def _loop(self):
        while not self._stop_evt.is_set():
            try:
                self._render_once()
            except Exception:
                pass
            self._stop_evt.wait(self.interval_sec)

    def _render_once(self):
        backend = self._safe_json_read(RESULTS_DIR / "backend_status.json")
        runtime = self._safe_json_read(RUNTIME_STATUS_PATH)
        state = self._safe_json_read(RUNTIME_STATE_PATH)
        safe = self.backend_service.safe_start.read_state()

        mode = str((backend.get("controller_mode") or runtime.get("mode") or "PAPER")).upper()
        is_live = mode == "LIVE"
        mode_badge = f"{mode} {'⚠️ LIVE REAL MONEY' if is_live else '🧪 PAPER'}"

        running = bool(self.backend_service._is_running())
        phase = safe.get("phase", "STOPPED")
        lock_exists = bool((backend.get("lock") or {}).get("exists"))
        conn = "CONNECTED" if running else ("WAITING" if phase in {PHASE_BOOTING_DEGRADED, PHASE_WAITING_OPERATOR, PHASE_WAITING_SYNC} else "DISCONNECTED")

        equity = runtime.get("equity")
        pnl_pct = runtime.get("pnl_pct")
        pos_state = state.get("state", "-")
        pos_qty = state.get("position_qty", 0.0)
        pos_symbol = state.get("symbol") or "-"

        open_orders, open_orders_state = self._fetch_open_orders_count()

        last_tick_ts = runtime.get("last_tick_ts")
        age_sec = None
        try:
            if last_tick_ts is not None:
                age_sec = max(0.0, time.time() - float(last_tick_ts))
        except Exception:
            age_sec = None

        last_err = runtime.get("last_error") or self.backend_service.last_error
        if conn == "DISCONNECTED":
            traffic = "🔴 RED"
        elif last_err:
            traffic = "🟡 YELLOW"
        elif age_sec is not None and age_sec > 10:
            traffic = "🟡 YELLOW"
        else:
            traffic = "🟢 GREEN"

        pnl_txt = "-"
        if pnl_pct is not None:
            try:
                pnl_txt = f"{float(pnl_pct) * 100:.2f}%"
            except Exception:
                pnl_txt = "-"

        lines = [
            "=" * 78,
            " SafeBot Backend Status TUI (--tui)",
            "=" * 78,
            f" MODE           : {mode_badge}",
            f" PHASE/CONN     : {phase} / {conn} (lock={'ON' if lock_exists else 'OFF'})",
            f" ACCOUNT        : equity={equity if equity is not None else '-'} KRW | PnL={pnl_txt}",
            f" POSITION       : {pos_state} | {pos_symbol} qty={pos_qty}",
            f" OPEN ORDERS    : {open_orders} ({open_orders_state})",
            f" TRAFFIC LIGHT  : {traffic}",
            f" LAST UPDATE    : runtime={self._fmt_ts(last_tick_ts)} | tui={datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        ]
        if last_err:
            lines.append(f" LAST ERROR     : {last_err}")
        lines.append("=" * 78)

        panel = "\n".join(lines)
        if self._stdout_is_tty:
            sys.stdout.write(self._ANSI_CLEAR_HOME + panel + "\n")
        else:
            sys.stdout.write(panel + "\n")
        sys.stdout.flush()


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


@app.post("/api/v1/control/mode")
def control_mode(req: StartRequest):
    return service.mode(req)


@app.post("/api/v1/control/confirm")
def control_confirm(req: ConfirmRequest):
    return service.confirm_and_run(req)


@app.post("/api/v1/control/stop")
def control_stop():
    return service.stop()


@app.post("/api/v1/manual/roundtrip-test")
def manual_roundtrip_test(req: ManualRoundtripRequest):
    return service.start_manual_roundtrip(req)


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="SafeBot FastAPI backend")
    parser.add_argument("--tui", dest="tui", action="store_true", default=True, help="Enable periodic status panel")
    parser.add_argument("--no-tui", dest="tui", action="store_false", help="Disable periodic status panel")
    parser.add_argument("--tui-interval", type=float, default=1.5, help="TUI refresh interval seconds (default: 1.5)")
    args = parser.parse_args()

    uvicorn_log_config = configure_logging()

    host = os.getenv("BACKEND_HOST", "127.0.0.1")
    port = int(os.getenv("BACKEND_PORT", "8765"))

    tui = None
    if args.tui:
        tui = BackendStatusTUI(service, interval_sec=args.tui_interval)
        tui.start()

    try:
        uvicorn.run(app, host=host, port=port, log_config=uvicorn_log_config)
    finally:
        if tui:
            tui.stop()
