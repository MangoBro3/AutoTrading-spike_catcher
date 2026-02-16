import json
import os
from datetime import datetime

class BudgetManager:
    def __init__(self, exchange_name, budget_krw=100000, reserve_krw=5000):
        self.exchange = exchange_name
        self.budget_krw = budget_krw
        self.reserve_krw = reserve_krw
        
        # 봇 전용 가상 원장 (Bot Ledger)
        self.bot_cash = budget_krw  # 봇이 가용 가능한 KRW
        self.bot_assets = {}        # {symbol: qty} 봇이 매수한 코인 수량
        
        # 기존 자산 스냅샷 (Baseline)
        self.baseline_snapshot = {} # {currency: total_qty}
        self.is_initialized = False

    def initialize_baseline(self, current_balances):
        """
        봇 시작 시점의 계좌 잔고를 스냅샷으로 저장.
        이 시점 이후 늘어난 수량만 봇이 건드릴 수 있음.
        """
        if self.is_initialized:
            return
        
        self.baseline_snapshot = current_balances.copy()
        self.is_initialized = True
        print(f"[{self.exchange}] Baseline Initialized: {self.baseline_snapshot}")
        
        # Save baseline to file for persistency check (Optional but good)
        try:
             with open(f"live_runs/baseline_{self.exchange}.json", "w") as f:
                 json.dump(self.baseline_snapshot, f)
        except Exception as e:
            print(f"Failed to save baseline: {e}")

    def can_buy(self, required_krw, current_real_krw):
        """
        매수 가능 여부 확인
        1. 봇 가상 원장에 돈이 있는가?
        2. 실제 계좌에 돈이 있는가? (수수료용 Reserve 제외)
        """
        if required_krw > (self.bot_cash - self.reserve_krw):
            return False, f"BOT_BUDGET_EXCEEDED (Req:{required_krw:.0f} > BotCash:{self.bot_cash:.0f})"
        
        if required_krw > (current_real_krw - self.reserve_krw):
            return False, f"REAL_BALANCE_INSUFFICIENT (Req:{required_krw:.0f} > Real:{current_real_krw:.0f})"
            
        return True, "OK"

    def can_sell(self, symbol, qty_to_sell, current_real_qty):
        """
        매도 가능 여부 확인 (기존 보유분 보호)
        bot_owned_qty = max(0, current_real_qty - baseline_qty)
        """
        baseline_qty = self.baseline_snapshot.get(symbol, 0.0)
        bot_owned_real = max(0.0, current_real_qty - baseline_qty)
        
        # 가상 원장상 수량과 교차 검증 (더 보수적인 쪽 따름)
        bot_owned_virtual = self.bot_assets.get(symbol, 0.0)
        
        # We take the MIN of Real-Baseline and Virtual. 
        # If Virtual is higher but Real is lower (maybe manual sell?), we stick to Real.
        # If Real is higher (manual buy?) but Virtual is lower, we stick to Virtual (don't touch manual buy).
        available_qty = min(bot_owned_real, bot_owned_virtual)
        
        if qty_to_sell > available_qty * 1.0001: # Small buffer for float errors
            return False, f"PROTECTED_ASSET (Req:{qty_to_sell} > Avail:{available_qty})"
            
        return True, "OK"

    def update_on_trade(self, side, symbol, price, qty, fee):
        """체결 시 가상 원장 업데이트"""
        amount = price * qty
        if side == 'buy':
            self.bot_cash -= (amount + fee)
            self.bot_assets[symbol] = self.bot_assets.get(symbol, 0.0) + qty
        elif side == 'sell':
            self.bot_cash += (amount - fee)
            current_qty = self.bot_assets.get(symbol, 0.0)
            self.bot_assets[symbol] = max(0.0, current_qty - qty)
