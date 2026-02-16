
import pandas as pd
import numpy as np
import lightgbm as lgb
import os
import joblib
from datetime import datetime, timedelta

class MLEngine:
    def __init__(self, model_path="ml_model.pkl"):
        self.model_path = model_path
        self.model = None
        self.feature_cols = [
            'rsi', 'vol_spike', 'atr_ratio', 'breakout_strength', 
            'close_loc', 'turnover_log', 'is_bear', 'btc_ret'
        ]
        
    def load_model(self):
        if os.path.exists(self.model_path):
            self.model = joblib.load(self.model_path)
            return True
        return False

    def save_model(self):
        if self.model:
            joblib.dump(self.model, self.model_path)

    def extract_features(self, df, btc_df=None):
        """
        Extract ML features from a single symbol DF.
        Assumes 'rsi', 'vol_spike' etc exist or calculation needed.
        """
        df = df.copy()
        
        # Ensure base columns
        if 'rsi' not in df.columns: df['rsi'] = 50
        if 'vol_spike' not in df.columns: 
            # Simple vol spike: Vol / MA(Vol)
            df['vol_ma'] = df['volume'].rolling(20).mean()
            df['vol_spike'] = df['volume'] / (df['vol_ma'] + 1e-9)
            
        if 'atr' not in df.columns: df['atr'] = df['high'] - df['low'] # Simple proxy if missing
        
        # 1. ATR Ratio (Volatility relative to price)
        df['atr_ratio'] = df['atr'] / df['close']
        
        # 2. Breakout Strength (Close vs 20d High)
        df['high_20'] = df['high'].rolling(20).max()
        df['breakout_strength'] = df['close'] / (df['high_20'] + 1e-9)
        
        # 3. Close Location in Range (0..1)
        df['close_loc'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-9)
        
        # 4. Turnover Log
        df['turnover_log'] = np.log1p(df.get('turnover', df['close']*df['volume']))
        
        # 5. BTC Context
        if btc_df is not None:
            # Map BTC data by index (datetime)
            common_idx = df.index.intersection(btc_df.index)
            # Create a Series for mapping
            # This is slow if done per symbol in loop. Better to join?
            # For inference (single day), it's fast. For training (bulk), join is better.
            
            # Simple Join for Bulk
            # Assuming df index is valid datetime
            pass # We handle this in prepare_dataset
        
        # Fill NaNs
        df = df.fillna(0) # Simple fill
        
        return df

    def prepare_dataset(self, data_map, params, btc_df=None):
        """
        Create X, y from all symbols.
        Target: Forward Return (5 days) or Risk-Adjusted Return.
        """
        X_list = []
        y_list = []
        
        print("Feature Engineering...")
        
        # BTC Regime Pre-calc
        if btc_df is not None:
            btc_df['btc_ret'] = btc_df['close'].pct_change(20) # 20d trend
            btc_df['is_bear'] = btc_df['close'] < btc_df['close'].rolling(60).mean()
            btc_map = btc_df[['btc_ret', 'is_bear']].to_dict('index')
        else:
            btc_map = {}
        
        for sym, df in data_map.items():
            if df.empty or len(df) < 60: continue
            
            # Feature extraction
            df_feat = self.extract_features(df)
            
            # Map BTC features
            if btc_map:
                # Iterate rows is slow. Vectorize map?
                # df_feat['btc_ret'] = df_feat.index.map(...)
                # Let's loop efficiently or use merge
                 # Reindex BTC to DF
                 btc_re = btc_df[['btc_ret', 'is_bear']].reindex(df_feat.index).fillna(0)
                 df_feat['btc_ret'] = btc_re['btc_ret']
                 df_feat['is_bear'] = btc_re['is_bear'].astype(int)
            else:
                 df_feat['btc_ret'] = 0
                 df_feat['is_bear'] = 0
            
            # Target Generation (Future 5d Return)
            # We want to predict if entry is good.
            # But entry happens only on Signal.
            # So training data should be filtered by "Is there a Signal?"
            # Or train on all days? Training on all days learns general price action.
            # But we only care about ranking SIGNALS.
            # Training on ALL days creates class imbalance (most days are noise).
            # Training only on Signal days is better for Ranking.
            
            # Let's filter by Signal (A or B)
            # We need strat logic involved or just train on Vol Spike days?
            # Let's train on top 30% volatility days?
            # Simple: Train on ALL days but weight them?
            # Decision: Train on "Potential Candidates" (e.g. Vol Spike > 1.5)
            
            mask = df_feat['vol_spike'] > 1.5
            subset = df_feat[mask].copy()
            
            if subset.empty: continue
            
            # Label: 5-Day Forward Return
            # Shift -5
            subset['target'] = subset['close'].shift(-5) / subset['close'] - 1.0
            subset = subset.dropna()
            
            if subset.empty: continue
            
            X_list.append(subset[self.feature_cols])
            y_list.append(subset['target'])
            
        if not X_list:
            return None, None
            
        X = pd.concat(X_list)
        y = pd.concat(y_list)
        
        # Classification (Good Trade > 5%) or Regression?
        # Ranking needs Regression score.
        # But data is noisy. 
        # Clip outliers
        y = np.clip(y, -0.5, 1.0)
        
        return X, y

    def train(self, data_map, params, btc_df=None):
        X, y = self.prepare_dataset(data_map, params, btc_df)
        if X is None:
            print("No training data found.")
            return
            
        print(f"Training LightGBM on {len(X)} samples...")
        
        # LGBM Regressor
        model = lgb.LGBMRegressor(
            n_estimators=100,
            learning_rate=0.05,
            num_leaves=31,
            random_state=42,
            n_jobs=-1
        )
        
        model.fit(X, y)
        self.model = model
        self.save_model()
        
        # Feature Importance
        imp = pd.DataFrame({
            'feature': self.feature_cols,
            'importance': model.feature_importances_
        }).sort_values('importance', ascending=False)
        
        print("Training Complete.")
        return imp

    def predict(self, row_candidates):
        """
        Rank candidates. 
        row_candidates: List of dicts (from daily_debug or screener)
        Must contain feature keys.
        """
        if not self.model: return [0.0] * len(row_candidates)
        if not row_candidates: return []
        
        # Convert list to DataFrame
        df_pred = pd.DataFrame(row_candidates)
        
        # Ensure cols
        for c in self.feature_cols:
            if c not in df_pred.columns:
                df_pred[c] = 0.0 # Missing feature
                
        preds = self.model.predict(df_pred[self.feature_cols])
        return preds
