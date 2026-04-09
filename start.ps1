param(
    [switch]$TailLogs
)

# AnGIneer Startup Script (Simplified)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$rootDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$portContractPath = Join-Path $rootDir "apps/shared/ports.json"
$portContract = Get-Content $portContractPath -Raw | ConvertFrom-Json
$logsDir = Join-Path $rootDir "logs"
$backendLogPath = Join-Path $logsDir "backend.log"
$adminLogPath = Join-Path $logsDir "admin.log"
$backendPidPath = Join-Path $logsDir "backend.pid"
$adminPidPath = Join-Path $logsDir "admin.pid"

# Stop stale hidden service processes and clean leftover PID files.
function Stop-ServiceProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ServiceName,
        [Parameter(Mandatory = $true)]
        [string]$PidPath
    )

    if (-not (Test-Path $PidPath)) {
        return
    }

    $pidText = (Get-Content $PidPath -Raw -ErrorAction SilentlyContinue).Trim()
    if ($pidText -match '^\d+$') {
        $existingProcess = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
        if ($existingProcess) {
            Write-Host "Stopping stale $ServiceName process: PID $pidText" -ForegroundColor DarkYellow
            Stop-Process -Id $existingProcess.Id -Force -ErrorAction SilentlyContinue
        }
    }

    Remove-Item $PidPath -Force -ErrorAction SilentlyContinue
}

# Stop any process occupying the specified port (for Frontend cleanup).
function Stop-PortProcess {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if (-not $connections) {
        return
    }

    foreach ($conn in $connections) {
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        if ($proc) {
            Write-Host "Stopping stale process on port $Port : PID $($proc.Id)" -ForegroundColor DarkYellow
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
        }
    }
}

# Start a hidden background service process and store PID/logs under logs.
function Start-ServiceProcess {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ServiceName,
        [Parameter(Mandatory = $true)]
        [string]$ServiceCommand,
        [Parameter(Mandatory = $true)]
        [string]$LogPath,
        [Parameter(Mandatory = $true)]
        [string]$PidPath
    )

    Stop-ServiceProcess -ServiceName $ServiceName -PidPath $PidPath

    $escapedRootDir = $rootDir.Replace("'", "''")
    $escapedLogPath = $LogPath.Replace("'", "''")
    $startupBanner = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] starting: $ServiceCommand"
    $startupScript = @"
Set-Location '$escapedRootDir'
'$startupBanner' | Out-File -FilePath '$escapedLogPath' -Encoding utf8 -Append
$ServiceCommand *>> '$escapedLogPath'
"@

    $process = Start-Process `
        -FilePath "powershell.exe" `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $startupScript) `
        -WindowStyle Hidden `
        -PassThru

    Set-Content -Path $PidPath -Value $process.Id -Encoding ascii
    return $process
}

# Follow current service logs in a separate terminal when needed.
function Watch-ServiceLogs {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$LogPaths
    )

    $existingLogs = @($LogPaths | Where-Object { Test-Path $_ })
    if (-not $existingLogs.Count) {
        Write-Warning "No log files found. Run .\start.ps1 first."
        return
    }

    Write-Host "Following logs..." -ForegroundColor Cyan
    $existingLogs | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
    Get-Content -Path $existingLogs -Tail 30 -Wait
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   AnGIneer Simplified Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

$hostName = $portContract.localHost
$backendPort = $portContract.apiServerPort
$adminPort = $portContract.adminConsolePort
$frontendPort = $portContract.webConsolePort
$backendUrl = "http://${hostName}:${backendPort}"
$adminUrl = "http://${hostName}:${adminPort}"
$frontendUrl = "http://${hostName}:${frontendPort}"

# 1. Check prerequisites
Write-Host "[1/3] Cheking Node.js & Python..." -ForegroundColor Yellow
$nodeVer = node --version 2>$null
if (-not $nodeVer) { Write-Error "Node.js not found!"; exit 1 }
$pythonVer = python --version 2>$null
if (-not $pythonVer) { Write-Error "Python not found!"; exit 1 }

# 2. Install dependencies only on first run
if (-not (Test-Path "node_modules")) {
    Write-Host "[2/3] Install dependencies (first time)..." -ForegroundColor Yellow
    pnpm install
} else {
    Write-Host "[2/3] Skipping dependencies installation (node_modules exists)..." -ForegroundColor Green
}

if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

if ($TailLogs) {
    Watch-ServiceLogs -LogPaths @($backendLogPath, $adminLogPath)
    exit 0
}

# 3. Start services
Write-Host "[3/3] Starting Backend, Admin and Frontend..." -ForegroundColor Yellow
Write-Host "      Backend:  $backendUrl" -ForegroundColor Green
Write-Host "      Admin:    $adminUrl" -ForegroundColor Green
Write-Host "      Frontend: $frontendUrl" -ForegroundColor Green

# Backend (hidden background process, no popup window)
$backendProcess = Start-ServiceProcess -ServiceName "Backend" -ServiceCommand "pnpm dev:backend" -LogPath $backendLogPath -PidPath $backendPidPath

# Admin (hidden background process, no popup window)
$adminProcess = Start-ServiceProcess -ServiceName "Admin" -ServiceCommand "pnpm dev:admin" -LogPath $adminLogPath -PidPath $adminPidPath

Write-Host "      Backend log:  $backendLogPath" -ForegroundColor DarkGray
Write-Host "      Admin log:    $adminLogPath" -ForegroundColor DarkGray
Write-Host "      Backend PID:  $($backendProcess.Id)" -ForegroundColor DarkGray
Write-Host "      Admin PID:    $($adminProcess.Id)" -ForegroundColor DarkGray

# Wait for backend startup
Write-Host ""
Write-Host "waiting for backend to start (10 seconds)..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

# Clean up any stale Frontend processes on the expected port
Stop-PortProcess -Port $frontendPort

# Frontend (current window)
pnpm dev:frontend
