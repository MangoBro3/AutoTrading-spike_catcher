import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

import sys
sys.path.append(str(Path(__file__).resolve().parent))

from modules.model_manager import ModelManager
from modules.oos_tuner import (
    build_split_windows,
    evaluate_oos_gate,
    find_best_candidate,
)
from modules.tuning_worker import TuningWorker


def _make_df(days=260, seed=7):
    rng = np.random.default_rng(seed)
    dates = pd.date_range(end=pd.Timestamp("2026-02-01"), periods=days, freq="D")
    close = 10000 + np.cumsum(rng.normal(0, 80, size=days))
    open_ = close * (1 + rng.normal(0, 0.001, size=days))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0.002, 0.001, size=days)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0.002, 0.001, size=days)))
    vol = np.abs(rng.normal(1000, 150, size=days))
    df = pd.DataFrame(
        {
            "datetime": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": vol,
        }
    )
    df["vol_ma20"] = df["volume"].rolling(window=20).mean()
    df["vol_spike"] = (df["volume"] / (df["vol_ma20"] + 1e-9)).fillna(1.0)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - df["close"].shift(1)).abs(),
            (df["low"] - df["close"].shift(1)).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr"] = tr.rolling(window=14).mean().fillna(0.0)
    return df


class TestOOSPipeline(unittest.TestCase):
    def test_split_policy(self):
        t = pd.Timestamp("2026-02-01")
        w = build_split_windows(t, train_days=180, oos_days=28, embargo_days=2)
        self.assertEqual(w["oos_end"], pd.Timestamp("2026-02-01"))
        self.assertEqual(w["oos_start"], pd.Timestamp("2026-01-05"))
        self.assertEqual(w["embargo_start"], pd.Timestamp("2026-01-03"))
        self.assertEqual(w["embargo_end"], pd.Timestamp("2026-01-04"))
        self.assertEqual(w["train_end"], pd.Timestamp("2026-01-02"))
        self.assertEqual(w["train_start"], pd.Timestamp("2025-07-07"))

    def test_determinism(self):
        raw = {"UPBIT_KRW-ETH": _make_df(days=280, seed=11)}
        base_params = {
            "enable_strategy_A": True,
            "enable_strategy_B": True,
            "trigger_vol_A": 2.0,
            "breakout_days_A": 7,
            "close_confirm_pct_A": 0.005,
            "rsi_ceiling_A": 75,
            "entry_delay_bars_A": 1,
            "trend_ma_fast_B": 20,
            "trend_ma_slow_B": 60,
            "rsi_entry_B": 45,
            "allocation_A_pct": 60,
            "allocation_B_pct": 40,
            "max_entries_per_day": 2,
            "max_open_positions": 3,
            "cooldown_days_after_sl": 5,
            "daily_loss_limit_pct": 2.0,
            "min_turnover_krw": 1_000_000,
            "universe_top_n": 0,
            "sl_atr_mult_A": 1.8,
            "trail_atr_mult_A": 2.5,
            "partial_tp_r_A": 1.2,
            "time_stop_days_A": 3,
            "sl_atr_mult_B": 1.4,
            "partial_tp_r_B": 1.0,
            "max_hold_days_B": 5,
        }
        w = build_split_windows(pd.Timestamp("2026-02-01"), train_days=180, oos_days=28, embargo_days=2)
        a, _ = find_best_candidate(
            raw,
            base_params,
            w["train_start"],
            w["train_end"],
            n_trials=4,
            seed=42,
        )
        b, _ = find_best_candidate(
            raw,
            base_params,
            w["train_start"],
            w["train_end"],
            n_trials=4,
            seed=42,
        )
        self.assertEqual(a["params"], b["params"])
        self.assertAlmostEqual(a["metrics"]["score"], b["metrics"]["score"], places=10)

    def test_gate_failures(self):
        oos_start = pd.Timestamp("2026-01-05")

        low_trade_gate = evaluate_oos_gate(
            candidate_metrics={"score": 0.10, "trades": 5},
            candidate_res={"trade_list": []},
            active_metrics={"score": 0.09},
            oos_start=oos_start,
            min_trades=20,
            delta_min=0.0,
        )
        self.assertFalse(low_trade_gate["pass"])
        self.assertTrue(any("min_trades_fail" in r for r in low_trade_gate["reasons"]))

        weak_weekly_gate = evaluate_oos_gate(
            candidate_metrics={"score": 0.20, "trades": 40},
            candidate_res={
                "trade_list": [
                    {"exit_date": oos_start + timedelta(days=1), "return": 0.02},
                    {"exit_date": oos_start + timedelta(days=8), "return": -0.03},
                    {"exit_date": oos_start + timedelta(days=15), "return": -0.01},
                    {"exit_date": oos_start + timedelta(days=22), "return": 0.01},
                ]
            },
            active_metrics={"score": 0.10},
            oos_start=oos_start,
            min_trades=20,
            delta_min=0.0,
        )
        self.assertFalse(weak_weekly_gate["pass"])
        self.assertTrue(any("weekly_robustness_fail" in r for r in weak_weekly_gate["reasons"]))

    def test_atomic_promotion_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "models"
            mm = ModelManager(base_dir=base)

            mm.write_staging_artifacts(
                run_id="seed_active",
                best_params={"p": 1},
                run_summary={"ok": True},
                model_meta={"model_id": "seed_active"},
            )
            mm.promote("seed_active")

            mm.write_staging_artifacts(
                run_id="next_run",
                best_params={"p": 2},
                run_summary={"ok": True},
                model_meta={"model_id": "next_run"},
            )

            with self.assertRaises(RuntimeError):
                mm.promote("next_run", fail_step="after_old")

            # Re-initialize -> recover path should restore a valid active model
            mm2 = ModelManager(base_dir=base)
            self.assertTrue(mm2.active_dir.exists())
            active_file = mm2.active_dir / "best_params.json"
            self.assertTrue(active_file.exists())
            active = json.loads(active_file.read_text(encoding="utf-8"))
            self.assertIn("p", active)

    def test_worker_scheduling_not_due(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "trainer_state.json"
            lock_path = Path(tmp) / "trainer.lock"
            future = datetime.now() + timedelta(days=3)
            state_path.write_text(
                json.dumps(
                    {
                        "last_run_at": None,
                        "next_due_at": future.isoformat(),
                        "last_success_at": None,
                        "active_model_id": None,
                    }
                ),
                encoding="utf-8",
            )

            worker = TuningWorker(
                state_path=state_path,
                lock_path=lock_path,
                cooldown_minutes_on_boot=0,
                cadence_days=7,
            )
            called = {"n": 0}

            def _runner():
                called["n"] += 1
                return {"gate_pass": False}

            res = worker.run_if_due(_runner)
            self.assertEqual(called["n"], 0)
            self.assertEqual(res.get("skipped"), "not_due")


if __name__ == "__main__":
    unittest.main()
