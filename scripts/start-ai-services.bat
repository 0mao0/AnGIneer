@echo off
chcp 65001 >nul 2>&1
title AI Services - bge-m3 + bge-reranker-v2-m3

echo ============================================================
echo   AI Embedding & Reranker Services Launcher
echo   bge-m3 (Embedding, port 7997)
echo   bge-reranker-v2-m3 (Reranker, port 7998)
echo ============================================================
echo.

:: 检查 Python
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.10+.
    pause
    exit /b 1
)

:: 检查模型目录
if not exist "D:\AI\AImodles\bge-m3" (
    echo [ERROR] bge-m3 model not found at D:\AI\AImodles\bge-m3
    echo Please download first.
    pause
    exit /b 1
)

if not exist "D:\AI\AImodles\bge-reranker-v2-m3" (
    echo [ERROR] bge-reranker-v2-m3 model not found at D:\AI\AImodles\bge-reranker-v2-m3
    echo Please download first.
    pause
    exit /b 1
)

:: 检查依赖
python -c "import sentence_transformers, fastapi, uvicorn" >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing dependencies...
    pip install sentence-transformers fastapi uvicorn
)

echo [1/2] Starting bge-m3 Embedding Service on port 7997...
start "bge-m3 Embedding" cmd /c "python D:\AI\AnGIneer\scripts\embedding_server.py"

echo [2/2] Starting bge-reranker-v2-m3 Reranker Service on port 7998...
start "bge-reranker Reranker" cmd /c "python D:\AI\AnGIneer\scripts\reranker_server.py"

echo.
echo ============================================================
echo   Services started!
echo   - Embedding API: http://localhost:7997/v1/embeddings
echo   - Reranker API:  http://localhost:7998/v1/rerank
echo   - Health Check:   http://localhost:7997/health
echo                     http://localhost:7998/health
echo ============================================================
echo.
echo Press any key to STOP both services...
pause >nul

echo Stopping services...
taskkill /fi "WINDOWTITLE eq bge-m3 Embedding*" /f >nul 2>&1
taskkill /fi "WINDOWTITLE eq bge-reranker Reranker*" /f >nul 2>&1
echo Services stopped.
