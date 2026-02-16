@echo off
chcp 65001 >nul
cd /d "c:\Users\nak\Desktop\DHR 런처\python\Auto Trading"
echo ==========================================
echo       OOS Pipeline Tests
echo ==========================================
echo.
python test_oos_pipeline.py
echo.
echo [TEST DONE] 창을 닫으려면 아무 키나 누르세요...
pause >nul
