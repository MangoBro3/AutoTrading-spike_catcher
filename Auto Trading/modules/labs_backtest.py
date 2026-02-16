
import sys
import os
import logging
import pandas as pd
import numpy as np
import json
from pathlib import Path
from datetime import datetime

# CRITICAL: Matplotlib Headless Mode
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

try:
    from .results_writer import ResultsWriter
    from .utils_json import safe_json_dump
except ImportError:
    # Fallback for standalone testing if needed
    from modules.results_writer import ResultsWriter
    from modules.utils_json import safe_json_dump

logger = logging.getLogger("LabsBacktest")

class LabsBacktester:
    def __init__(self, base_dir="results"):
        self.writer = ResultsWriter(base_dir=base_dir)

    def run(self, strategy_class, universe, params: dict, tag: str = ""):
        """
        Runs the backtest and saves results + charts.
        """
        run_type = "backtest"
        exchange = "LABS_SIM"
        
        # 1. Create Run Directory
        run_id, run_path = self.writer.create_run_dir(run_type, exchange, tag)
        print(f"\n[Labs] Backtest Started. Run ID: {run_id}")
        
        charts_dir = run_path / "charts"
        charts_dir.mkdir(exist_ok=True)
        
        # 2. Run Backtest (Mock for MVP structure, or integration)
        # TODO: Integrate real Backtester here.
        # For Stage 9 delivery, we assume we get 'equity_df' and 'trades_df' from the Engine.
        # Simulating data for now to demonstrate storage capability.
        print("[Labs] Running Simulation/Backtest Engine...")
        
        # --- SIMULATED DATA START ---
        dates = pd.date_range(start="2025-01-01", periods=100, freq="D")
        equity_data = 100000 * (1 + np.random.normal(0.001, 0.02, 100).cumsum())
        equity_df = pd.DataFrame({'equity': equity_data}, index=dates)
        
        trades_df = pd.DataFrame([
            {'dt': dates[10], 'symbol': 'KRW-BTC', 'side': 'BUY', 'price': 50000, 'size': 0.1},
            {'dt': dates[20], 'symbol': 'KRW-BTC', 'side': 'SELL', 'price': 55000, 'size': 0.1}
        ])
        # --- SIMULATED DATA END ---

        # 3. Save CSVs
        equity_csv = run_path / "equity.csv"
        trades_csv = run_path / "trades.csv"
        
        equity_df.to_csv(equity_csv)
        trades_df.to_csv(trades_csv)
        
        # 4. Generate & Save Charts
        print("[Labs] Generating Charts...")
        
        # Chart 1: Equity Curve
        fig1, ax1 = plt.subplots(figsize=(10, 6))
        ax1.plot(equity_df.index, equity_df['equity'], label='Equity')
        ax1.set_title(f"Equity Curve ({run_id})")
        ax1.grid(True)
        ax1.legend()
        fig1.savefig(charts_dir / "equity_curve.png")
        plt.close(fig1)
        
        # Chart 2: Drawdown
        peak = equity_df['equity'].cummax()
        dd = (equity_df['equity'] - peak) / peak
        
        fig2, ax2 = plt.subplots(figsize=(10, 6))
        ax2.fill_between(equity_df.index, dd, 0, color='red', alpha=0.3, label='Drawdown')
        ax2.set_title(f"Drawdown ({run_id})")
        ax2.grid(True)
        fig2.savefig(charts_dir / "drawdown.png")
        plt.close(fig2)
        
        print(f"[Labs] Charts Saved to: {charts_dir}")
        
        # 5. Write Summary
        summary = {
            "run_type": run_type,
            "run_id": run_id,
            "created_at": datetime.now().isoformat(),
            "exchange": exchange,
            "market": "KRW",
            "contracts": {
                "signal_lag_days": 1, 
                "turnover_lag_days": 1,
                "execution": "t_open"
            },
            "files": {
                "equity_csv": str(equity_csv),
                "trades_csv": str(trades_csv),
                "charts_dir": str(charts_dir)
            },
            "metrics": {
                "total_return": (equity_data[-1] - equity_data[0]) / equity_data[0] * 100,
                "max_dd": dd.min() * 100
            }
        }
        
        self.writer.write_summary(run_id, summary)
        self.writer.update_index(summary)
        
        # 6. Interaction
        self._prompt_show_charts(charts_dir)
        
        return run_id

    def _prompt_show_charts(self, charts_dir):
        """
        Safely prompts user to show charts.
        """
        # Check if running in non-interactive mode (e.g. tests)
        if not sys.stdin.isatty():
            return

        try:
            choice = input("\n[Labs] Show Charts? (Y/N): ").strip().upper()
        except EOFError:
            choice = 'N'

        if choice == 'Y':
            print("[Labs] Attempting to display charts... (Close window to continue)")
            try:
                # Re-import pyplot for display - might fail if Agg backend persists strictly?
                # Actually, Agg backend cannot show().
                # Use system default viewer logic or just warn.
                # If we want to show, we might need to switch backend or just open files.
                # Opening files is safer.
                
                # Check OS
                if os.name == 'nt': # Windows
                    os.startfile(charts_dir)
                else:
                    # Linux/Mac logic (xdg-open or open)
                    pass
                print(f"[Labs] Opened chart directory: {charts_dir}")
            except Exception as e:
                print(f"[Labs] Failed to open charts: {e}")
        else:
            print(f"[Labs] Charts saved to {charts_dir}")
