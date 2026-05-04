[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$rootDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$logsDir = Join-Path $rootDir "logs"
$portContractPath = Join-Path $rootDir "apps/shared/ports.json"
$portContract = Get-Content $portContractPath -Raw | ConvertFrom-Json
$backendPort = $portContract.apiServerPort
$adminPort = $portContract.adminConsolePort
$frontendPort = $portContract.webConsolePort

# Recursively kill a process and all its child processes.
function Stop-ProcessTree {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId
    )

    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) { return }

    $children = Get-CimInstance Win32_Process | Where-Object {
        $_.ParentProcessId -eq $ProcessId
    }
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId $child.ProcessId
    }

    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

# Stop the target service process by PID file and kill the entire process tree.
function Stop-ServiceProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ServiceName,
        [Parameter(Mandatory = $true)]
        [string]$PidPath
    )

    if (-not (Test-Path $PidPath)) {
        Write-Host "${ServiceName}: PID file not found, skipped." -ForegroundColor DarkGray
        return
    }

    $pidText = (Get-Content $PidPath -Raw -ErrorAction SilentlyContinue).Trim()
    if (-not ($pidText -match '^\d+$')) {
        Write-Warning "${ServiceName}: PID file is invalid and has been removed."
        Remove-Item $PidPath -Force -ErrorAction SilentlyContinue
        return
    }

    $targetProcess = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
    if ($targetProcess) {
        Stop-ProcessTree -ProcessId $targetProcess.Id
        Write-Host "${ServiceName}: stopped process tree PID $pidText" -ForegroundColor Green
    } else {
        Write-Host "${ServiceName}: process not found, removing stale PID $pidText" -ForegroundColor DarkYellow
    }

    Remove-Item $PidPath -Force -ErrorAction SilentlyContinue
}

# Stop any process occupying the specified port.
function Stop-PortProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $connections = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if (-not $connections) {
        Write-Host "${Label} (port ${Port}): no listeners found." -ForegroundColor DarkGray
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
            Write-Host "${Label} (port ${Port}): stopped process tree PID $connPid" -ForegroundColor Green
        }
    }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   AnGIneer Stop Services" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Phase 1: Stop by PID files (graceful, kills process trees)
Write-Host "[1/2] Stopping services by PID files..." -ForegroundColor Yellow
if (Test-Path $logsDir) {
    Stop-ServiceProcess -ServiceName "Backend" -PidPath (Join-Path $logsDir "backend.pid")
    Stop-ServiceProcess -ServiceName "Admin" -PidPath (Join-Path $logsDir "admin.pid")
    Stop-ServiceProcess -ServiceName "Embedding" -PidPath (Join-Path $logsDir "embedding.pid")
    Stop-ServiceProcess -ServiceName "Reranker" -PidPath (Join-Path $logsDir "reranker.pid")
} else {
    Write-Host "logs directory not found, skipping PID-based stop." -ForegroundColor DarkGray
}

# Phase 2: Port-based fallback cleanup (catches orphaned processes)
Write-Host "[2/2] Cleaning up orphaned processes by port..." -ForegroundColor Yellow
Stop-PortProcess -Label "Backend" -Port $backendPort
Stop-PortProcess -Label "Admin" -Port $adminPort
Stop-PortProcess -Label "Frontend" -Port $frontendPort
Stop-PortProcess -Label "Embedding" -Port 7997
Stop-PortProcess -Label "Reranker" -Port 7998

Write-Host ""
Write-Host "All services stopped." -ForegroundColor Green
