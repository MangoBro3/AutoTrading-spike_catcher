
import logging
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger("WatchEngine")

class WatchEngine:
    REGIME_RISK_ON = "RISK_ON"
    REGIME_NEUTRAL = "NEUTRAL"
    REGIME_RISK_OFF = "RISK_OFF"

    def __init__(self, notifier=None):
        self.notifier = notifier
        self.current_regime = self.REGIME_NEUTRAL
        self.watchlist = [] # List of (symbol, score)
        self.last_btc_price = 0.0

    def update_regime(self, btc_df: pd.DataFrame):
        """
        Determines market regime based on BTC trends.
        Logic:
           Price > SMA(20) -> RISK_ON
           Price < SMA(20) -> RISK_OFF (Simplified)
        """
        if btc_df is None or len(btc_df) < 20:
            logger.warning("[WatchEngine] Not enough BTC data for regime check.")
            return self.current_regime

        # Calculate SMA 20
        sma20 = btc_df['close'].rolling(window=20).mean().iloc[-1]
        current_price = btc_df['close'].iloc[-1]
        self.last_btc_price = current_price

        # Determine New Regime
        new_regime = self.REGIME_NEUTRAL
        if current_price > sma20:
            new_regime = self.REGIME_RISK_ON
        else:
            new_regime = self.REGIME_RISK_OFF
        
        # State Change Check
        if new_regime != self.current_regime:
            old_regime = self.current_regime
            self.current_regime = new_regime
            
            msg = f"Market Regime Changed: {old_regime} -> {new_regime} (BTC: {current_price:.0f}, SMA20: {sma20:.0f})"
            logger.info(msg)
            
            if self.notifier:
                self.notifier.emit_event(
                    event_type="RISK",
                    exchange="ALL",
                    title="Regime Change",
                    message=msg,
                    severity="INFO",
                    dedupe_key=f"REGIME_{new_regime}_{datetime.now().strftime('%Y%m%d%H')}",
                    cooldown_min=60
                )
        
        return self.current_regime

    def score_candidates(self, market_data: Dict[str, pd.DataFrame], top_n=3) -> List[tuple]:
        """
        Scores assets based on momentum.
        Market Data: {symbol: OHLCV_DataFrame}
        Logic: (Close - SMA20) / SMA20
        """
        scores = []
        
        for symbol, df in market_data.items():
            # Skip BTC if present (Indicator only)
            if "BTC" in symbol:
                continue
                
            if len(df) < 20:
                continue
                
            close = df['close'].iloc[-1]
            sma20 = df['close'].rolling(window=20).mean().iloc[-1]
            
            if sma20 > 0:
                score = (close - sma20) / sma20
                scores.append((symbol, score))
        
        # Sort desc by score
        scores.sort(key=lambda x: x[1], reverse=True)
        
        # Pick Top N
        self.watchlist = scores[:top_n]
        
        # Notify if new strong candidates found? (Optional for MVP)
        # For strictness, we just return list.
        return self.watchlist

    def get_action_guide(self):
        """
        Returns trading permissions based on Regime.
        """
        if self.current_regime == self.REGIME_RISK_OFF:
            return {'can_enter': False, 'size_mult': 0.0}
        elif self.current_regime == self.REGIME_NEUTRAL:
            return {'can_enter': True, 'size_mult': 0.5}
        else: # RISK_ON
            return {'can_enter': True, 'size_mult': 1.0}
