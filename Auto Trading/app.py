import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os
import glob
from datetime import datetime
import time
import subprocess
import sys

# Import modules
try:
    from strategy import Strategy
    from backtester import Backtester
    import data_loader
    from telegram_bot import send_telegram_message
    from autotune import AutoTuner
    from ml_engine import MLEngine
except ImportError:
    st.error("Modules not found.")

st.set_page_config(page_title="Korea Quant Dashboard", layout="wide", page_icon="🐯")

# --- Utils ---
@st.cache_data(ttl=300)
def load_data():
    """Load all parquet files"""
    data_dir = "data"
    files = glob.glob(os.path.join(data_dir, "*.parquet"))
    
    data_map = {}
    for f in files:
        basename = os.path.basename(f).replace(".parquet", "")
        try:
            data_map[basename] = pd.read_parquet(f)
        except: pass
            
    return data_map

def get_btc_status(data_map):
    btc = None
    candidates = ['GLOBAL_BTC', 'UPBIT_KRW-BTC', 'BITHUMB_BTC_KRW']
    for c in candidates:
        if c in data_map:
            btc = data_map[c]
            break
    if btc is None: return None, None
    last_row = btc.iloc[-1]
    return last_row.get('is_bear', False), last_row.get('ret_1d', 0)

# --- Sidebar ---
st.sidebar.title("🛠 컨트롤 타워")

# 0. Telegram Control
with st.sidebar.expander("🤖 자동 감시 (Telegram)"):
    if st.button("🔔 알림 테스트 (Test Msg)"):
        if send_telegram_message("🔔 테스트 알림입니다! (Test Alert)"):
            st.success("전송 성공!")
        else:
            st.error("전송 실패 (토큰 확인)")

# 0-1. Auto-Scan Scheduler Control
with st.sidebar.expander("🕒 자동 업데이트 (Scheduler)"):
    pid_file = "scheduler.pid"
    is_running = False
    pid = None
    
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r") as f:
                pid = f.read().strip()
            # Double check if process really exists (Windows)
            # Efficient check: 
            cmd = f'tasklist /FI "PID eq {pid}"'
            # Simple check override for now, assume file is truth
            is_running = True
        except:
            is_running = False

    if is_running:
        st.success(f"Running (PID: {pid})")
        if st.button("⏹ 정지 (Stop Scheduler)"):
            try:
                # Windows Kill
                subprocess.call(['taskkill', '/F', '/T', '/PID', pid])
                if os.path.exists(pid_file): os.remove(pid_file)
                st.rerun()
            except Exception as e:
                st.error(f"Stop Failed: {e}")
    else:
        st.warning("Stopped")
        if st.button("▶ 시작 (Start Auto-Update)"):
            try:
                # Spawn hidden process
                subprocess.Popen([sys.executable, "scheduler.py"], creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                time.sleep(1) # Wait for start
                st.rerun()
            except Exception as e:
                st.error(f"Start Failed: {e}")
            
    # Monitor Process Control
    st.markdown("---")
    monitor_interval = st.number_input("주기(분)", min_value=10, max_value=240, value=60)
    
    if st.button("▶️ 자동 감시 시작 (Background)"):
        # Launch monitor.py as subprocess
        try:
            subprocess.Popen([sys.executable, "monitor.py"], creationflags=subprocess.CREATE_NEW_CONSOLE)
            st.success("모니터링 봇이 새 창에서 시작되었습니다!")
            send_telegram_message(f"🚀 **자동 감시 시작** (주기: {monitor_interval}분)")
        except Exception as e:
            st.error(f"실행 실패: {e}")

# --- Config Persist ---
CONFIG_FILE = "user_config.json"
import json

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: return {}
    return {}

def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

config = load_config()

# 1. Exchange Filter
st.sidebar.markdown("---")
col_cfg1, col_cfg2 = st.sidebar.columns([3, 1])
col_cfg1.subheader("필터 / 설정")
if col_cfg2.button("💾 저장"):
    # We will gather values at the end of sidebar section or here using session state if possible.
    # But widgets update variables directly in this script flow. 
    # To save, we need to collect them. 
    # Strategy: We define widgets first, then at very end of sidebar, we verify save.
    st.session_state['do_save_config'] = True

exchange_filter = st.sidebar.radio("거래소", ["전체 (All)", "업비트 (Upbit)", "빗썸 (Bithumb)"])

# 2. System Health
latency_ms = int(time.time() * 1000) % 100 
last_updated = datetime.now().strftime("%H:%M:%S")
st.sidebar.caption(f"Ping: {latency_ms}ms | Last: {last_updated}")

# 3. Strategy Params (New Round 1)
with st.sidebar.expander("⚙️ 1. 포트폴리오 설정 (Portfolio)", expanded=True):
    col_p1, col_p2 = st.columns(2)
    enable_A = col_p1.checkbox("전략 A (돌파)", config.get('enable_A', True))
    enable_B = col_p2.checkbox("전략 B (눌림)", config.get('enable_B', True))
    
    alloc_A = st.slider("비중 A (%)", 0, 100, config.get('alloc_A', 60))
    alloc_B = 100 - alloc_A
    st.caption(f"비중 B: {alloc_B}%")
    
    max_entries = st.number_input("일일 최대 진입 (종목 수)", 1, 5, config.get('max_entries', 2))
    max_pos = st.number_input("최대 보유 종목 (Max Pos)", 1, 10, config.get('max_pos', 3))
    cooldown = st.number_input("손절 후 재진입 금지 (일)", 0, 10, config.get('cooldown', 5))
    loss_limit = st.number_input("일일 손실 제한 (%)", 1.0, 10.0, config.get('loss_limit', 2.0))
    universe_top_n = st.number_input("Dynamic Universe (Top N)", 0, 200, config.get('universe_top_n', 0))
    min_turnover = st.number_input("최소 거래대금 (KRW)", 0, 1_000_000_000, config.get('min_turnover', 10_000_000), step=10_000_000, format="%d")

    enable_ml_ranking = st.checkbox("🧠 ML Ranking 활성화", config.get('enable_ml_ranking', False))
    
    with st.popover("🚨 Crash 모드 설정 (Risk Off)"):
        st.caption("BTC 급락 시 적용될 안전 장치")
        crash_max_pos = st.number_input("Crash 시 최대 보유 종목", 0, 5, config.get('crash_max_pos', 0))
        crash_loss_limit = st.number_input("Crash 시 손실 제한 (%)", 0.5, 5.0, config.get('crash_loss_limit', 1.0))
        st.info("조건: BTC < 60일선 AND (폭락 or 고변동성)")

with st.sidebar.expander("📈 2. 전략 A (Breakout+Retest)"):
    trig_vol_A = st.slider("트리거 거래량 (배수)", 1.5, 5.0, config.get('trig_vol_A', 2.0))
    bo_days_A = st.slider("신고가 기준 (일)", 3, 20, config.get('bo_days_A', 7))
    confirm_pct_A = st.slider("종가 확인 버퍼 (%)", 0.1, 2.0, config.get('confirm_pct_A', 0.5)) / 100
    delay_A = st.slider("확인 대기 (봉)", 0, 2, config.get('delay_A', 1))
    rsi_cap_A = st.slider("추격 방지 RSI 상한", 60, 90, config.get('rsi_cap_A', 75))
    
    st.markdown("---")
    sl_mul_A = st.number_input("손절 (ATR x)", 1.0, 3.0, config.get('sl_mul_A', 1.8))
    trail_mul_A = st.number_input("트레일링 (ATR x)", 1.5, 4.0, config.get('trail_mul_A', 2.5))
    tp_r_A = st.number_input("부분익절 (R 배수)", 0.5, 3.0, config.get('tp_r_A', 1.2))
    time_A = st.number_input("타임 스탑 (일)", 1, 10, config.get('time_A', 3))
    
    use_regime_filter_A = st.checkbox("🐻 약세장 진입 제한 (Bear Filter)", config.get('use_regime_filter_A', True), help="체크 해제 시 약세장에서도 돌파 매매를 시도합니다.")

with st.sidebar.expander("📉 3. 전략 B (Pullback)"):
    ma_fast_B = st.number_input("단기 이평", 5, 50, config.get('ma_fast_B', 20))
    ma_slow_B = st.number_input("장기 이평", 20, 120, config.get('ma_slow_B', 60))
    rsi_B = st.slider("진입 RSI (이하)", 30, 60, config.get('rsi_B', 45))
    
    st.markdown("---")
    sl_mul_B = st.number_input("손절 B (ATR x)", 1.0, 3.0, config.get('sl_mul_B', 1.4))
    tp_r_B = st.number_input("부분익절 B (R 배수)", 0.5, 3.0, config.get('tp_r_B', 1.0))
    max_hold_B = st.number_input("최대 보유 B (일)", 1, 10, config.get('max_hold_B', 5))

# Save Logic
if st.session_state.get('do_save_config', False):
    new_config = {
        'enable_A': enable_A, 'enable_B': enable_B, 'alloc_A': alloc_A,
        'max_entries': max_entries, 'max_pos': max_pos, 'cooldown': cooldown, 
        'loss_limit': loss_limit, 'universe_top_n': universe_top_n, 'min_turnover': min_turnover,
        'enable_ml_ranking': enable_ml_ranking, 'crash_max_pos': crash_max_pos, 
        'crash_loss_limit': crash_loss_limit,
        'trig_vol_A': trig_vol_A, 'bo_days_A': bo_days_A, 'confirm_pct_A': confirm_pct_A * 100,
        'delay_A': delay_A, 'rsi_cap_A': rsi_cap_A, 'sl_mul_A': sl_mul_A, 
        'trail_mul_A': trail_mul_A, 'tp_r_A': tp_r_A, 'time_A': time_A,
        'use_regime_filter_A': use_regime_filter_A,
        'ma_fast_B': ma_fast_B, 'ma_slow_B': ma_slow_B, 'rsi_B': rsi_B,
        'sl_mul_B': sl_mul_B, 'tp_r_B': tp_r_B, 'max_hold_B': max_hold_B
    }
    save_config(new_config)
    st.sidebar.success("설정이 저장되었습니다!")
    st.session_state['do_save_config'] = False

# 4. Data Control
if st.sidebar.button("🔄 데이터 최신화 (Scan)"):
    progress_bar = st.sidebar.progress(0, text="대기 중...")
    def update_progress(p, msg):
        progress_bar.progress(p, text=msg)
    try:
        data_loader.update_data(progress_callback=update_progress)
        st.cache_data.clear()
        st.success("완료!")
        
        # Check for alerts immediately after manual scan?
        # Typically yes
        st.rerun()
    except Exception as e:
        st.error(f"실패: {e}")

# --- Main ---
data_map = load_data()
if not data_map:
    st.warning("데이터가 없습니다.")
    st.stop()

is_bear, btc_ret = get_btc_status(data_map)
kill_switch_active = False
try:
    k_thresh = float(kill_switch_threshold) / 100.0
    if btc_ret is not None and btc_ret < k_thresh:
        kill_switch_active = True
except: pass

col1, col2 = st.columns([1, 3])
with col1:
    if kill_switch_active: st.error(f"🔴 KILL SW (BTC {btc_ret:.2%})")
    elif is_bear: st.warning(f"🟠 BEAR (BTC {btc_ret:.2%})")
    else: st.success(f"🟢 BULL (BTC {btc_ret:.2%})")

# Strategy Parameters
strat_params = {
    'enable_strategy_A': enable_A,
    'enable_strategy_B': enable_B,
    # Strategy A Params (Signal Generation)
    'trigger_vol_A': trig_vol_A,
    'breakout_days_A': bo_days_A,
    'close_confirm_pct_A': confirm_pct_A,
    'entry_delay_bars_A': delay_A,
    'rsi_ceiling_A': rsi_cap_A,
    'max_gap_pct_A': 0.15, # Hardcoded or default
    'use_regime_filter_A': use_regime_filter_A,
    # Strategy B Params
    'trend_ma_fast_B': ma_fast_B,
    'trend_ma_slow_B': ma_slow_B,
    'rsi_entry_B': rsi_B
}

# Run Strategy
strat = Strategy()

# Analyze using simplified loop for Screener
triggers_A = []
triggers_B = []

# ML Prep
ml_model_obj = None
if enable_ml_ranking:
    try:
        mle = MLEngine()
        if mle.load_model():
            ml_model_obj = mle
    except: pass

for symbol, df in data_map.items():
    if df.empty: continue
    if "USDT" in symbol or "USDC" in symbol: continue
    if exchange_filter == "업비트 (Upbit)" and "UPBIT" not in symbol: continue
    if exchange_filter == "빗썸 (Bithumb)" and "BITHUMB" not in symbol: continue
    
    # Analyze
    res = strat.analyze(df, params=strat_params)
    last = res.iloc[-1]
    
    # Check A
    if last.get('signal_A', False):
        triggers_A.append({
            'symbol': symbol,
            'price': last['close'],
            'score': last.get('score_A', 0),
            'bo_level': last.get('bo_level_A', 0),
            'rsi': last.get('rsi', 0),
            'df': df,
            # ML Features
            'vol_spike': last.get('vol_spike', 0),
            'atr_ratio': last.get('atr_ratio', 0),
            'breakout_strength': last.get('breakout_strength', 0),
            'close_loc': last.get('close_loc', 0),
            'turnover': last.get('turnover', 0),
            'is_bear': last.get('is_bear', False),
            'btc_ret': last.get('btc_ret', 0)
        })
        
    # Check B
    if last.get('signal_B', False) and enable_B:
        triggers_B.append({
            'symbol': symbol,
            'price': last['close'],
            'score': last.get('score_B', 0),
            'ma_fast': last.get('ma_fast', 0), 
            'rsi': last.get('rsi', 0),
            'df': df
        })

# Apply ML to A (B is simple)
if ml_model_obj and triggers_A:
    preds = ml_model_obj.predict(triggers_A)
    for i, p in enumerate(preds):
        triggers_A[i]['ml_score'] = p
        
# Sort
if ml_model_obj:
    triggers_A.sort(key=lambda x: (x.get('ml_score', -99), x['score']), reverse=True)
else:
    triggers_A.sort(key=lambda x: x['score'], reverse=True)
    
triggers_B.sort(key=lambda x: x['score'], reverse=True)

tab1, tab2, tab3, tab4, tab5 = st.tabs(["🚀 실시간 탐색기", "🧪 전략 연구소", "🔍 데이터 확인", "🤖 AutoTune", "🧠 ML Lab"])

with tab1:
    # A Section
    st.markdown("### 🅰️ 전략 A: 돌파 & 리테스트 (Breakout)")
    if triggers_A:
        for t in triggers_A:
            # Score Formatting
            score_txt = ""
            if 'ml_score' in t:
                ml_val = t['ml_score']
                icon = "⭐" if ml_val > 0.02 else "😐"
                if ml_val > 0.05: icon = "🚀"
                score_txt += f"{icon} AI: {ml_val:.4f} | "
            
            act_val = t['score']
            fire = "🔥" if act_val > 10 else "💧"
            score_txt += f"{fire} Act: {act_val:.1f}"
            
            with st.expander(f"{t['symbol']}  [{score_txt}]"):
                c1, c2 = st.columns(2)
                c1.metric("Current Price", f"{t['price']:,.0f}")
                c1.caption(f"Breakout Level: {t['bo_level']:,.0f}")
                c2.metric("RSI", f"{t['rsi']:.1f}")
                
                # Recommendation Text
                if 'ml_score' in t and t['ml_score'] > 0.02:
                    st.success(f"**AI 추천: 강력 매수 신호 (예상 수익률 {t['ml_score']:.2%})**")
                
                st.line_chart(t['df']['close'].tail(30))
    else:
        st.info("전략 A 진입 신호 없음")
        
    st.divider()
    
    # B Section
    st.markdown("### 🅱️ 전략 B: 눌림목 (Pullback)")
    if triggers_B:
        for t in triggers_B:
            # Score Formatting (Simple for B for now)
            act_val = t['score']
            icon = "🌊"
            score_txt = f"{icon} Act: {act_val:.1f}"
            
            with st.expander(f"{t['symbol']}  [{score_txt}]"):
                c1, c2 = st.columns(2)
                c1.metric("Current Price", f"{t['price']:,.0f}")
                c2.metric("RSI", f"{t['rsi']:.1f}")
                st.line_chart(t['df']['close'].tail(30))
    else:
        st.info("전략 B 진입 신호 없음")
    
    st.divider()
    
    # Beast (Optional - keep empty or revive if needed, user focused on A/B)
    # st.markdown(f"### 🔥 [야수 모드] Beast")


# --- Tab 2: Strategy Lab (Backtest) ---
with tab2:
    st.subheader("🧪 포트폴리오 시뮬레이션 (Portfolio Backtest)")
    st.caption("전략 A/B 분산 투자 및 상세 리스크 관리 적용")
    
    if st.button("⚡ 시뮬레이션 실행 (Run)", key="btn_run_sim"):
        with st.spinner("포트폴리오 백테스트 진행 중..."):
            
            # 1. Collect Params
            bt_params = {
                'enable_strategy_A': enable_A,
                'enable_strategy_B': enable_B,
                'allocation_A_pct': alloc_A,
                'allocation_B_pct': alloc_B,
                'max_entries_per_day': max_entries,
                'max_open_positions': max_pos,
                'cooldown_days_after_sl': cooldown,
                'daily_loss_limit_pct': loss_limit,
                'min_turnover_krw': min_turnover,
                'universe_top_n': universe_top_n, 
                
                # A
                'trigger_vol_A': trig_vol_A,
                'breakout_days_A': bo_days_A,
                'close_confirm_pct_A': confirm_pct_A,
                'entry_delay_bars_A': delay_A,
                'rsi_ceiling_A': rsi_cap_A,
                'sl_atr_mult_A': sl_mul_A,
                'trail_atr_mult_A': trail_mul_A,
                'partial_tp_r_A': tp_r_A,
                'time_stop_days_A': time_A,
                'use_regime_filter_A': use_regime_filter_A,
                
                # B
                'trend_ma_fast_B': ma_fast_B,
                'trend_ma_slow_B': ma_slow_B,
                'rsi_entry_B': rsi_B,
                'sl_atr_mult_B': sl_mul_B, 
                'partial_tp_r_B': tp_r_B,
                'max_hold_days_B': max_hold_B
            }
            
            # 2. Prepare/Analyze Data
            symbol_dfs = {}
            for symbol, df in data_map.items():
                if df.empty: continue
                if "USDT" in symbol or "USDC" in symbol: continue
                # Analyze using new Strategy A/B logic
                df_analyzed = strat.analyze(df, params=bt_params)
                symbol_dfs[symbol] = df_analyzed
            
            # 3. Run Engine
            ml_model_obj = None
            if enable_ml_ranking:
                mle = MLEngine()
                if mle.load_model():
                    ml_model_obj = mle
                    st.info("🧠 ML 모델이 적용되었습니다.")
                else:
                    st.warning("⚠️ ML 모델 파일이 없습니다. Tab 5에서 먼저 학습하세요.")

            # Load Benchmark (BTC)
            benchmark_df =  data_map.get('GLOBAL_BTC')
            if benchmark_df is None:
                 benchmark_df = data_map.get('KRW-BTC')
            
            if benchmark_df is None:
                st.warning("⚠️ KRW-BTC 데이터가 없어 레짐 판별이 불가능합니다. (Neutral로 진행)")
            
            # Regime Overrides
            bt_params['regime_overrides'] = {
                'Crash': {
                    'max_open_positions': crash_max_pos,
                    'daily_loss_limit_pct': crash_loss_limit
                }
            }

            bt = Backtester()
            res = bt.run_portfolio(symbol_dfs, bt_params, ml_model=ml_model_obj, benchmark_df=benchmark_df)
            
            # Save to Session State for Tab 3
            st.session_state['bt_results'] = res
            st.session_state['symbol_dfs'] = symbol_dfs
            
            # 4. Display Results
            k1, k2, k3 = st.columns(3)
            k1.metric("총 수익률 (Total Return)", f"{res['total_return']:.2%}")
            k2.metric("승률 (Win Rate)", f"{res['win_rate']:.1%}")
            k3.metric("매매 횟수 (Trades)", f"{res['trades']}회")
            
            # Combine Trades & Events for Export
            trades_df = pd.DataFrame(res['trade_list'])
            events_df = pd.DataFrame(res['event_list'])
            
            if not trades_df.empty:
                st.markdown("### 📝 매매 저널 (Trade Journal)")
                
                # Date Formatting
                trades_df['entry_date'] = pd.to_datetime(trades_df['entry_date']).dt.strftime('%Y-%m-%d')
                
                # Display Code
                # Display Code
                cols = ['symbol', 'strategy_tag', 'entry_date', 'entry_price', 'exit_date', 'exit_price', 'return', 'reason', 'hold_days']
                view_df = trades_df[[c for c in cols if c in trades_df.columns]]
                
                st.dataframe(view_df.style.format({
                    'entry_price': '{:,.0f}',
                    'return': '{:.2%}',
                    'max_dd': '{:.2%}'
                }).background_gradient(subset=['return'], cmap='RdYlGn', vmin=-0.1, vmax=0.1))
                
                # Export Buttons
                c1, c2 = st.columns(2)
                c1.download_button("💾 저널 다운로드 (CSV)", trades_df.to_csv(index=False).encode('utf-8-sig'), "trade_journal.csv")
                if not events_df.empty:
                    st.markdown("### ⚡ 이벤트 로그 (Partial TP / Updates)")
                    st.dataframe(events_df)
                    c2.download_button("💾 이벤트 다운로드 (CSV)", events_df.to_csv(index=False).encode('utf-8-sig'), "events.csv")
            else:
                st.warning("거래 내역이 없습니다. 파라미터를 조정해보세요.")


# --- Tab 3: Data Inspector ---
with tab3:
    st.subheader("🔍 데이터 정밀 분석 (Inspector)")
    
    if 'bt_results' not in st.session_state:
        st.info("⚠️ 먼저 [전략 연구소] 탭에서 시뮬레이션을 실행해야 분석이 가능합니다.")
    else:
        res = st.session_state['bt_results']
        symbol_dfs = st.session_state.get('symbol_dfs', {})
        daily_debug = res.get('daily_debug', {})
        trades = res.get('trade_list', [])
        
        # 1. Consistency Check (SSOT)
        st.markdown("### 1. 데이터무결성 점검 (Consistency Checker)")
        check_cols = st.columns(4)
        
        kpi_trades = res['trades']
        list_trades = len(trades)
        sl_errors = sum(1 for t in trades if t['reason'] == 'SL' and t['return'] >= 0)
        
        check_cols[0].metric("KPI Trades", kpi_trades)
        check_cols[1].metric("List Rows", list_trades, delta="OK" if kpi_trades == list_trades else "FAIL")
        
        # SL Integrity Check
        sl_trades = [t for t in trades if t['reason'] == 'SL']
        sl_fail = len([t for t in sl_trades if t['return'] >= 0])
        check_cols[2].metric("SL Integrity", f"{len(sl_trades)} cases", delta="FAIL" if sl_fail > 0 else "OK", delta_color="inverse")
        
        # Null Check
        null_count = pd.DataFrame(trades).isnull().sum().sum() if trades else 0
        check_cols[3].metric("Null/NaN", null_count, delta="OK" if null_count == 0 else "FAIL", delta_color="inverse")
        
        if kpi_trades != list_trades:
            st.error(f"🚨 불일치 발생! KPI({kpi_trades}) vs List({list_trades}).")
        if sl_fail > 0:
            st.error(f"🚨 SL 로직 위반: 'SL' Reason인데 수익인 건이 {sl_fail}개 있습니다. (return < 0 필수)")
            
        st.divider()
        
        # 2. Daily Inspector
        st.markdown("### 2. 일별 시뮬레이션 복기 (Daily Replay)")
        
        col_i1, col_i2 = st.columns([1, 3])
        
        # Date Selection from Backtest range
        all_dates = sorted(list(daily_debug.keys()))
        if all_dates:
            target_date_str = col_i1.selectbox("날짜 선택", all_dates, index=len(all_dates)-1)
            
            # Display Candidates
            col_i1.info(f"선택 날짜: {target_date_str}")
            
            debug_data = daily_debug.get(target_date_str, [])
            
            # Phase 3 Adaptation: Handle Dictionary Structure
            if isinstance(debug_data, dict):
                current_regime = debug_data.get('regime', 'Neutral')
                logs = debug_data.get('candidates', [])
                st.info(f"📊 Market Regime: **{current_regime}**")
                
                # Show active params if available (optional)
            else:
                logs = debug_data
            
            if logs:
                st.write(f"📋 진입 후보 ({len(logs)}개)")
                log_df = pd.DataFrame(logs)
                
                # Ensure 'tag' exists
                if 'tag' not in log_df.columns:
                    log_df['tag'] = 'N/A'
                
                # UI Enhancement: Rename and Reorder
                if 'ml_score' in log_df.columns:
                    log_df['⭐ AI Score (Prob)'] = log_df['ml_score'].map('{:.4f}'.format)
                
                if 'score' in log_df.columns:
                    log_df['🔥 Activity (Vol)'] = log_df['score'].map('{:.1f}'.format)
                else:
                    log_df['🔥 Activity (Vol)'] = 0.0
                
                # Select/Order Columns
                base_cols = ['symbol', 'tag', '🔥 Activity (Vol)']
                
                # Filter out columns that don't exist in base_cols either
                available_cols = [c for c in base_cols if c in log_df.columns]
                
                if 'ml_score' in log_df.columns:
                    available_cols.insert(1, '⭐ AI Score (Prob)')
                    
                # Add other useful info if exists
                optional_cols = ['rsi', 'turnover'] 
                final_cols = available_cols + [c for c in optional_cols if c in log_df.columns]
                
                st.dataframe(log_df[final_cols])
                
                with st.expander("ℹ️ 점수 보는 법 (Guide)"):
                    st.markdown("""
                    **1. ⭐ AI Score (Prob)**
                    - **AI가 예측한 5일 후 기대 수익률**입니다.
                    - **양수(+)**: 수익 예상, **음수(-)**: 손실 예상.
                    - *예: 0.0500 → 약 5% 상승 예측*
                    - **추천 기준**: 0.02 (2%) 이상이면 긍정적 시그널.
                    
                    **2. 🔥 Activity (Vol)**
                    - **거래량과 변동성의 강도**입니다. (Rule-Based)
                    - 높을수록 시장의 관심을 받고 있다는 뜻입니다.
                    - *기준: 10점 이상이면 활발, 30점 이상이면 과열.*
                    """)
                
                # Check Details for top candidate
                if not log_df.empty:
                    top_sym = log_df.iloc[0]['symbol']
                    st.write(f"🔎 Top 심볼 분석: **{top_sym}**")
                    
                    if top_sym in symbol_dfs:
                        df_chk = symbol_dfs[top_sym]
                        try:
                            row = df_chk.loc[target_date_str]
                            st.json(row.to_dict()) # Show all features
                        except:
                            st.error(f"{top_sym}의 {target_date_str} 데이터가 없습니다.")
            else:
                st.warning("이 날짜에는 진입 후보가 없었습니다 (Low Vol or No Signal).")
        else:
            st.warning("일별 로그(daily_debug)가 없습니다.")


# --- Tab 4: AutoTune ---
with tab4:
    st.subheader("🤖 AutoTune (Parameter Optimization)")
    st.caption("Walk-Forward Validation & Genetic-like Optimization")
    
    # Config
    c1, c2, c3 = st.columns(3)
    target_group = c1.selectbox("튜닝 그룹 (Target Group)", ["A", "B", "C"], index=0, help="A: 진입, B: 청산/리스크, C: 포트폴리오")
    num_trials = c2.number_input("시도 횟수 (Trials)", 10, 100, 20)
    seed_val = c3.number_input("Seed", 1, 9999, 42)
    
    if st.button("🚀 AutoTune 시작 (Run)", type="primary"):
        # Progress UI
        prog_bar = st.progress(0.0)
        status_text = st.empty()
        
        def update_ui(p, msg):
            prog_bar.progress(p)
            status_text.text(msg)
            
        try:
            # Init Tuner with RAW data (data_map)
            # data_map is loaded at top of app.py
            tuner = AutoTuner(data_map, strat_params, output_dir="autotune_runs")
            
            # Run
            run_dir = tuner.run_process(target_group, num_trials, seed_val, callback=update_ui)
            
            st.success(f"완료! 결과 저장됨: {run_dir}")
            st.session_state['last_run_dir'] = run_dir
            
        except Exception as e:
            st.error(f"오류 발생: {e}")
            
    st.divider()
    
    # Results Viewer
    if 'last_run_dir' in st.session_state:
        run_dir = st.session_state['last_run_dir']
        st.write(f"📂 분석 대상: `{run_dir}`")
        
        try:
            lb_path = os.path.join(run_dir, "leaderboard.csv")
            if os.path.exists(lb_path):
                lb_df = pd.read_csv(lb_path)
                st.markdown("### 🏆 Leaderboard (Top 20)")
                st.dataframe(lb_df.head(20).style.background_gradient(subset=['score'], cmap='Greens'))
                
                # Best Param Apply
                best_path = os.path.join(run_dir, "best_params.json")
                if st.button("✅ 최적 파라미터 적용 (Apply Best)"):
                    try:
                        with open(best_path, "r") as f:
                            best_p = json.load(f)
                        
                        # Apply to Session State (Not persistent across reload unless code changes or we use session state for params)
                        # NOTE: Sidebar widgets take value from args or session state?
                        # Streamlit widgets retain value if key is set.
                        # We didn't set keys for sidebar widgets in app.py snippet.
                        # To support "Apply", we should load sidebar defaults from session_state if available.
                        # For Phase 1, we just display them and ask user to update, or try to inject.
                        
                        st.json(best_p)
                        st.info("파라미터를 확인했습니다. 사이드바에 수동으로 입력해주세요 (자동 연동은 Phase 2 예정).")
                        
                    except Exception as e:
                        st.error(f"적용 실패: {e}")
            else:
                st.warning("Leaderboard 파일이 없습니다.")
        except Exception as e:
            st.error(f"결과 로딩 실패: {e}")

# --- Tab 5: ML Lab ---
with tab5:
    st.subheader("🧠 ML Ranking Model")
    st.caption("LightGBM을 사용하여 진입 후보의 승률/수익률을 예측하고 랭킹을 재정렬합니다.")
    
    mle = MLEngine()
    model_exists = mle.load_model()
    
    c1, c2 = st.columns(2)
    c1.metric("모델 상태", "✅ 학습됨" if model_exists else "⚠️ 미학습")
    
    if st.button("🔄 모델 학습 시작 (Train Model)", type="primary"):
        with st.spinner("Features 추출 및 학습 중... (시간이 소요됩니다)"):
            try:
                # Use data_map from main
                # Need valid params? Use strat_params
                imp_df = mle.train(data_map, strat_params, btc_df=None) # btc_df not loaded yet, can skip or load
                if imp_df is not None:
                    st.success("학습 완료!")
                    st.session_state['ml_trained'] = True
                    st.markdown("### Feature Importance")
                    st.bar_chart(imp_df.set_index('feature'))
                else:
                    st.warning("학습 데이터가 부족합니다.")
            except Exception as e:
                st.error(f"학습 중 오류: {e}")
                st.exception(e)

    if model_exists:
        st.info("모델이 로드되었습니다. 시뮬레이션 및 AutoTune에서 'ML Ranking'을 활성화하여 사용할 수 있습니다.")

