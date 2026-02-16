
import logging
from datetime import datetime

logger = logging.getLogger("CapitalLedger")

class CapitalLedger:
    def __init__(self, exchange_name: str, initial_seed: float):
        """
        Manages the virtual seed bucket for a specific exchange.
        """
        if initial_seed <= 0:
            raise ValueError(f"Initial seed must be > 0. Got {initial_seed}")
            
        self.exchange_name = exchange_name
        
        # State
        self.baseline_seed = float(initial_seed)
        self.equity = float(initial_seed) # Starts equal to seed
        self.start_ts = datetime.now()
        
        # Cycle Stats
        self.peak_equity = self.equity
        self.max_drawdown = 0.0

    def update(self, current_equity: float):
        """
        Updates the current equity state logic.
        In a real bot, 'current_equity' is calculated as:
        (Cash allocated to bot) + (Value of Bot's Positions).
        
        Note: This module trusts the caller to provide the correct 'Bot Equity'.
        It does not blindly use 'Exchange Total Balance'.
        """
        self.equity = float(current_equity)
        
        # Update Peak & DD
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity
        
        dd = (self.peak_equity - self.equity) / self.peak_equity if self.peak_equity > 0 else 0
        self.max_drawdown = max(self.max_drawdown, dd)

    def get_state(self):
        """
        Returns full accounting state.
        """
        pnl_cycle = self.equity - self.baseline_seed
        roi_pct = (pnl_cycle / self.baseline_seed) * 100 if self.baseline_seed > 0 else 0
        
        return {
            "exchange": self.exchange_name,
            "baseline_seed": self.baseline_seed,
            "equity": self.equity,
            "pnl_cycle": pnl_cycle,
            "roi_pct": round(roi_pct, 2),
            "withdrawable_profit": max(0.0, pnl_cycle),
            "max_drawdown_pct": round(self.max_drawdown * 100, 2),
            "start_ts": self.start_ts.isoformat()
        }

    def can_reset(self, open_positions_count: int, open_orders_count: int) -> bool:
        """
        Reset is ALLOWED ONLY IF:
        1. No open positions (Flat).
        2. No open orders (Safe).
        """
        if open_positions_count > 0:
            logger.warning(f"[{self.exchange_name}] Cannot reset: {open_positions_count} open positions.")
            return False
        if open_orders_count > 0:
            logger.warning(f"[{self.exchange_name}] Cannot reset: {open_orders_count} open orders.")
            return False
        return True

    def reset_seed(self, new_seed: float, open_positions_count: int = 0, open_orders_count: int = 0):
        """
        Archives current cycle and starts a new one with 'new_seed'.
        Strictly enforces can_reset().
        Returns: (True, SummaryDict) or (False, Reason)
        """
        if not self.can_reset(open_positions_count, open_orders_count):
            return False, "Active positions or orders exist."
            
        if new_seed <= 0:
            return False, "New seed must be positive."

        # Archive Old Cycle
        summary = self.get_state()
        summary['event'] = "CYCLE_RESET"
        summary['end_ts'] = datetime.now().isoformat()
        
        # Apply New State
        old_equity = self.equity
        self.baseline_seed = float(new_seed)
        self.equity = float(new_seed) # Reset equity to new seed (assuming funds adjusted)
        self.start_ts = datetime.now()
        self.peak_equity = self.equity
        self.max_drawdown = 0.0
        
        logger.info(f"[{self.exchange_name}] Seed Reset: {summary['baseline_seed']} -> {new_seed}. Cycle PnL: {summary['pnl_cycle']}")
        
        return True, summary
