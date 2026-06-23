@echo off
cd /d "%~dp0backend"
call venv\Scripts\activate.bat
echo Starting FastAPI backend on http://localhost:8000
uvicorn app.main:app --reload --port 8000
