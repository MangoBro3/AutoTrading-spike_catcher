import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import precision_recall_curve, auc
import matplotlib.pyplot as plt
import numpy as np
import joblib
import os
import logging

# Config
DATA_FILE = "data/processed/train_dataset.parquet"
MODEL_FILE = "data/model.pkl"
RESULTS_FILE = "data/eval_results.txt"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def train_and_eval():
    if not os.path.exists(DATA_FILE):
        logging.error("Train dataset not found.")
        return

    df = pd.read_parquet(DATA_FILE)
    df = df.sort_values('date').reset_index(drop=True)
    
    
    # Features
    exclude_cols = [
        'date', 'market', 'target', 'is_pump_event', 
        'candle_date_time_kst', 'candle_date_time_utc', 'timestamp',
        'opening_price', 'high_price', 'low_price', 'trade_price', 
        'candle_acc_trade_volume', 'candle_acc_trade_price'
    ]
    features = [c for c in df.columns if c not in exclude_cols]
    
    X = df[features]

    y = df['target']
    
    logging.info(f"Training on {len(X)} samples. Features: {len(features)}")
    
    # Split: Last 20% as Test (simple time split)
    split_idx = int(len(df) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]

    # Identifiers

    date_col = 'date'
    if 'date' not in df.columns:
        if 'candle_date_time_kst' in df.columns:
            date_col = 'candle_date_time_kst'
        elif 'candle_date_time_utc' in df.columns:
            date_col = 'candle_date_time_utc'
    
    test_dates = df[date_col].iloc[split_idx:]
    test_markets = df['market'].iloc[split_idx:]

    
    # LGBM
    model = lgb.LGBMClassifier(
        n_estimators=500,
        learning_rate=0.05,
        num_leaves=31,
        random_state=42,
        class_weight='balanced',
        n_jobs=-1,
        verbose=-1
    )
    
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        eval_metric='binary_logloss',
        callbacks=[lgb.early_stopping(stopping_rounds=50)]
    )
    
    # Eval
    y_pred = model.predict_proba(X_test)[:, 1]
    
    # Precision-Recall AUC
    precision, recall, _ = precision_recall_curve(y_test, y_pred)
    pr_auc = auc(recall, precision)
    logging.info(f"PR AUC: {pr_auc:.4f}")
    
    # Precision@K Logic
    # Group by Date, Rank score, Check if top K are hits.
    
    eval_df = pd.DataFrame({
        'date': test_dates,
        'market': test_markets,
        'label': y_test,
        'score': y_pred
    })
    
    # For each day in test set
    daily_groups = eval_df.groupby('date')
    
    k_values = [5, 10, 20]
    precisions = {k: [] for k in k_values}
    
    for date, group in daily_groups:
        # Sort by score desc
        group = group.sort_values('score', ascending=False)
        
        for k in k_values:
            top_k = group.head(k)
            if len(top_k) > 0:
                hits = top_k['label'].sum()
                p_k = hits / len(top_k)
                precisions[k].append(p_k)
    
    results_txt = "=== Precision@K Evaluation ===\n"
    for k in k_values:
        avg_pK = np.mean(precisions[k])
        log_msg = f"Average Precision@{k}: {avg_pK:.4f}"
        logging.info(log_msg)
        results_txt += log_msg + "\n"
        
    # Feature Importance
    importance = pd.DataFrame({
        'feature': features,
        'importance': model.feature_importances_
    }).sort_values('importance', ascending=False)
    
    results_txt += "\n=== Top 10 Features ===\n"
    results_txt += str(importance.head(10))
    
    # Save
    joblib.dump(model, MODEL_FILE)
    with open(RESULTS_FILE, 'w') as f:
        f.write(results_txt)
        
    logging.info(f"Model saved to {MODEL_FILE}")
    print(results_txt)

if __name__ == "__main__":
    train_and_eval()
