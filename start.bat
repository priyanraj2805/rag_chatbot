@echo off
title DotStark RAG Chatbot

echo.
echo  =============================================
echo   DotStark RAG Chatbot - Starting...
echo  =============================================
echo.

REM ── Start Backend in its own window ──────────────────────────────────
echo  [1/2] Starting Backend (FastAPI on port 8000)...
start "RAG Backend :8000" cmd /k "cd /d %~dp0backend && venv\Scripts\activate.bat && uvicorn app.main:app --port 8000 --reload"

REM ── Wait 5 seconds for backend to boot before starting frontend ───────
echo  Waiting for backend to boot...
timeout /t 5 /nobreak >nul

REM ── Start Frontend in its own window ─────────────────────────────────
echo  [2/2] Starting Frontend (React on port 5173)...
start "RAG Frontend :5173" cmd /k "cd /d %~dp0frontend && npm run dev"

REM ── Open browser after a short delay ─────────────────────────────────
echo  Opening browser...
timeout /t 4 /nobreak >nul
start http://localhost:5173

echo.
echo  =============================================
echo   Both servers are starting in separate windows.
echo   App will open at: http://localhost:5173
echo   API docs at:      http://localhost:8000/docs
echo  =============================================
echo.
echo  To STOP everything: close the two black terminal windows.
echo.
pause
