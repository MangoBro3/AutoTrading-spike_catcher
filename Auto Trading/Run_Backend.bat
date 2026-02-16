@echo off
chcp 65001 >nul
cd /d "c:\Users\nak\Desktop\DHR 런처\python\Auto Trading"
echo ==========================================
echo       DHR Web Backend
echo ==========================================
echo.
python web_backend.py
echo.
echo [BACKEND STOPPED] 창을 닫으려면 아무 키나 누르세요...
pause >nul
