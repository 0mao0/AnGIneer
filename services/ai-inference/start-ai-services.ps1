param(
    [switch]$Stop
)

# AnGIneer AI Inference Services Launcher
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$rootDir = if ($PSScriptRoot) { (Get-Item $PSScriptRoot).Parent.Parent.FullName } else { (Get-Location).Path }
$serviceDir = Join-Path $rootDir "services\ai-inference\src\ai_inference"
$logsDir = Join-Path $rootDir "logs"
$embeddingLogPath = Join-Path $logsDir "embedding.log"
$rerankerLogPath = Join-Path $logsDir "reranker.log"
$embeddingPidPath = Join-Path $logsDir "embedding.pid"
$rerankerPidPath = Join-Path $logsDir "reranker.pid"

$embeddingPort = 7997
$rerankerPort = 7998
$embeddingModelPath = $env:BGE_M3_MODEL_PATH
if (-not $embeddingModelPath) { $embeddingModelPath = "D:\AI\AImodles\bge-m3" }
$rerankerModelPath = $env:BGE_RERANKER_MODEL_PATH
if (-not $rerankerModelPath) { $rerankerModelPath = "D:\AI\AImodles\bge-reranker-v2-m3" }

# Recursively kill a process and all its child processes.
function Stop-ProcessTree {
    param([int]$ProcessId)
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) { return }
    $children = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $ProcessId }
    foreach ($child in $children) { Stop-ProcessTree -ProcessId $child.ProcessId }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

# Stop any process occupying the specified port.
function Stop-PortProcess {
    param([string]$Label, [int]$Port)
    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $connections) {
        Write-Host "  ${Label} (port ${Port}): no listeners found." -ForegroundColor DarkGray
        return
    }
    $killedPids = @{}
    foreach ($conn in $connections) {
        $connPid = $conn.OwningProcess
        if ($killedPids.ContainsKey($connPid)) { continue }
        $killedPids[$connPid] = $true
        $proc = Get-Process -Id $connPid -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-ProcessTree -ProcessId $connPid
            Write-Host "  Stopped ${Label} (port ${Port}): PID $connPid" -ForegroundColor Green
        }
    }
}

# Stop the target service process by PID file.
function Stop-ServiceByPidFile {
    param([string]$Label, [string]$PidPath)
    if (-not (Test-Path $PidPath)) { return }
    $pidText = (Get-Content $PidPath -Raw -ErrorAction SilentlyContinue).Trim()
    if ($pidText -match '^\d+$') {
        $existingProcess = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
        if ($existingProcess) {
            Stop-ProcessTree -ProcessId $existingProcess.Id
            Write-Host "  Stopped ${Label} by PID file: PID $pidText" -ForegroundColor Green
        }
    }
    Remove-Item $PidPath -Force -ErrorAction SilentlyContinue
}

# Start a hidden background service process.
function Start-ServiceProcess {
    param(
        [string]$ServiceName,
        [string]$ScriptPath,
        [string]$LogPath,
        [string]$PidPath
    )
    $escapedRootDir = $rootDir.Replace("'", "''")
    $escapedLogPath = $LogPath.Replace("'", "''")
    $startupScript = @"
Set-Location '$escapedRootDir'
python '$ScriptPath' *>> '$escapedLogPath'
"@
    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $startupScript) `
        -WindowStyle Hidden `
        -PassThru
    Set-Content -Path $PidPath -Value $process.Id -Encoding ascii
    return $process
}

# --- Stop mode ---
if ($Stop) {
    Write-Host "Stopping AI Inference services..." -ForegroundColor Yellow
    Stop-ServiceByPidFile -Label "Embedding" -PidPath $embeddingPidPath
    Stop-ServiceByPidFile -Label "Reranker" -PidPath $rerankerPidPath
    Stop-PortProcess -Label "Embedding" -Port $embeddingPort
    Stop-PortProcess -Label "Reranker" -Port $rerankerPort
    Write-Host "AI Inference services stopped." -ForegroundColor Green
    exit 0
}

# --- Start mode ---
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   AI Inference Services" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Check prerequisites
Write-Host "[1/3] Checking prerequisites..." -ForegroundColor Yellow
$pythonOk = $null -ne (Get-Command python -ErrorAction SilentlyContinue)
if (-not $pythonOk) { Write-Error "Python not found!"; exit 1 }
if (-not (Test-Path $embeddingModelPath)) {
    Write-Error "bge-m3 model not found at $embeddingModelPath"
    exit 1
}
if (-not (Test-Path $rerankerModelPath)) {
    Write-Error "bge-reranker-v2-m3 model not found at $rerankerModelPath"
    exit 1
}
Write-Host "  Python OK, models OK" -ForegroundColor DarkGray

# Clean up stale processes
Write-Host "[2/3] Cleaning up stale processes..." -ForegroundColor Yellow
Stop-PortProcess -Label "Embedding" -Port $embeddingPort
Stop-PortProcess -Label "Reranker" -Port $rerankerPort

if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

# Start services
Write-Host "[3/3] Starting services..." -ForegroundColor Yellow
$embeddingScript = Join-Path $serviceDir "semantic_embedding_service.py"
$rerankerScript = Join-Path $serviceDir "semantic_reranker_service.py"

$embProcess = Start-ServiceProcess -ServiceName "Embedding" -ScriptPath $embeddingScript -LogPath $embeddingLogPath -PidPath $embeddingPidPath
$rerProcess = Start-ServiceProcess -ServiceName "Reranker" -ScriptPath $rerankerScript -LogPath $rerankerLogPath -PidPath $rerankerPidPath

Write-Host ""
Write-Host "Services started!" -ForegroundColor Green
Write-Host "  Embedding API: http://localhost:$embeddingPort/v1/embeddings" -ForegroundColor DarkGray
Write-Host "  Reranker API:  http://localhost:$rerankerPort/v1/rerank" -ForegroundColor DarkGray
Write-Host "  Health:        http://localhost:$embeddingPort/health" -ForegroundColor DarkGray
Write-Host "                 http://localhost:$rerankerPort/health" -ForegroundColor DarkGray
Write-Host "  Embedding PID: $($embProcess.Id)" -ForegroundColor DarkGray
Write-Host "  Reranker PID:  $($rerProcess.Id)" -ForegroundColor DarkGray
Write-Host "  Embedding log: $embeddingLogPath" -ForegroundColor DarkGray
Write-Host "  Reranker log:  $rerankerLogPath" -ForegroundColor DarkGray
Write-Host ""
Write-Host "To stop: .\start-ai-services.ps1 -Stop" -ForegroundColor Yellow
