import numpy as np
from collections import deque

class RiskCalculator:
    def __init__(self, window_sec=60):
        self.window_sec = window_sec
        self.tick_history = deque() # (timestamp, price)
        self.raw_microvol_history = deque(maxlen=200) # Winsorize용 히스토리

    def add_tick(self, timestamp, price):
        self.tick_history.append((timestamp, price))
        # 윈도우 지난 틱 제거
        while self.tick_history and self.tick_history[0][0] < timestamp - self.window_sec:
            self.tick_history.popleft()

    def get_microvol_clean(self, current_spread_bp, spread_threshold_bp=30):
        """
        노이즈 억제된 초단기 변동성 계산
        """
        if len(self.tick_history) < 10: # Min-Ticks Gate
            return 0.0

        prices = np.array([p for t, p in self.tick_history])
        log_ret = np.diff(np.log(prices))
        if len(log_ret) == 0: return 0.0
        
        raw_vol = np.std(log_ret)
        
        # (A) Winsorize: 분포의 상위 99% 컷 (히스토리 기반)
        self.raw_microvol_history.append(raw_vol)
        if len(self.raw_microvol_history) > 10:
            p99 = np.percentile(self.raw_microvol_history, 99)
            raw_vol = min(raw_vol, p99)

        # (B) Spread Gate: 스프레드가 넓으면 신뢰도 하락 (패널티)
        spread_factor = 1.0
        if current_spread_bp > spread_threshold_bp:
            # 예: 스프레드 60bp면 factor 0.5 (30/60)
            spread_factor = max(0.3, spread_threshold_bp / (current_spread_bp + 1e-9))
        
        return raw_vol * spread_factor

    def get_risk_unit(self, atr14, atr3, current_high, current_low, current_price, microvol_clean):
        """
        V2.1 혼합형 Risk Unit
        microvol_clean은 비율이므로 가격을 곱해 단위 맞춤
        """
        range_vol = (current_high - current_low) * 0.5 # K_range (예: 0.5)
        micro_vol_scaled = microvol_clean * current_price * 2.0 # 스케일링 팩터
        
        # 가장 보수적(큰) 변동성 채택
        risk_unit = max(atr14, atr3, range_vol, micro_vol_scaled)
        return risk_unit
