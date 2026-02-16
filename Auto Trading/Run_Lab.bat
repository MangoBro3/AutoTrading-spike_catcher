@echo off
chcp 65001
cd /d "c:\Users\nak\Desktop\DHR 런처\python\Auto Trading"
echo ==========================================
echo       Auto Trading Lab (Training/Backtest)
echo ==========================================
echo.
echo [INFO] 브라우저가 열리면 'AutoTune' 탭에서 최적화를 진행하세요.
echo [INFO] 최적화가 끝나면 'best_params.json'이 저장되고, 
echo        봇(Run_Bot_V2)이 자동으로 이를 불러와 매매합니다.
echo.
python -m streamlit run app.py
pause
