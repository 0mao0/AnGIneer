param(
    [switch]$TailLogs
)

# AnGIneer Startup Script
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$rootDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$portContractPath = Join-Path $rootDir "apps/shared/ports.json"
$portContract = Get-Content $portContractPath -Raw | ConvertFrom-Json
$logsDir = Join-Path $rootDir "logs"
$backendLogPath = Join-Path $logsDir "backend.log"
$adminLogPath = Join-Path $logsDir "admin.log"
$backendPidPath = Join-Path $logsDir "backend.pid"
$adminPidPath = Join-Path $logsDir "admin.pid"

$hostName = $portContract.localHost
$backendPort = $portContract.apiServerPort
$adminPort = $portContract.adminConsolePort
$frontendPort = $portContract.webConsolePort
$backendUrl = "http://${hostName}:${backendPort}"
$adminUrl = "http://${hostName}:${adminPort}"
$frontendUrl = "http://${hostName}:${frontendPort}"

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

    if (-not (Test-Path $PidPath)) { return }

    $pidText = (Get-Content $PidPath -Raw -ErrorAction SilentlyContinue).Trim()
    if ($pidText -match '^\d+$') {
        $existingProcess = Get-Process -Id ([int]$pidText) -ErrorAction SilentlyContinue
        if ($existingProcess) {
            Write-Host "Stopping stale $ServiceName process tree: PID $pidText" -ForegroundColor DarkYellow
            Stop-ProcessTree -ProcessId $existingProcess.Id
        }
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
    if (-not $connections) { return }

    $killedPids = @{}
    foreach ($conn in $connections) {
        $connPid = $conn.OwningProcess
        if ($killedPids.ContainsKey($connPid)) { continue }
        $killedPids[$connPid] = $true
        $proc = Get-Process -Id $connPid -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-ProcessTree -ProcessId $connPid
            Write-Host "Stopped stale process on port ${Port} (${Label}): PID $connPid" -ForegroundColor DarkYellow
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

# Check if the backend is responding on its health endpoint.
function Test-BackendHealth {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $attempts = 0

    while ((Get-Date) -lt $deadline) {
        $attempts++
        try {
            $response = Invoke-WebRequest -Uri $Url -Method GET -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
            if ($response.StatusCode -eq 200) {
                Write-Host "  Backend health check passed (attempt $attempts)" -ForegroundColor Green
                return $true
            }
        } catch {
            # Expected during startup - backend not ready yet
        }
        Write-Host "  Waiting for backend... (attempt $attempts)" -ForegroundColor DarkGray
        Start-Sleep -Seconds 2
    }

    return $false
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
Write-Host "   AnGIneer Startup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# 1. Check prerequisites
Write-Host "[1/4] Checking Node.js & Python..." -ForegroundColor Yellow
$nodeVer = node --version 2>$null
if (-not $nodeVer) { Write-Error "Node.js not found!"; exit 1 }
$pythonVer = python --version 2>$null
if (-not $pythonVer) { Write-Error "Python not found!"; exit 1 }
Write-Host "  Node.js $nodeVer, $pythonVer" -ForegroundColor DarkGray

# 2. Install dependencies only on first run
if (-not (Test-Path "node_modules")) {
    Write-Host "[2/4] Installing dependencies (first time)..." -ForegroundColor Yellow
    pnpm install
} else {
    Write-Host "[2/4] Skipping dependencies (node_modules exists)" -ForegroundColor Green
}

if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir | Out-Null
}

if ($TailLogs) {
    Watch-ServiceLogs -LogPaths @($backendLogPath, $adminLogPath)
    exit 0
}

# 3. Clean up stale processes on ALL service ports before starting
Write-Host "[3/4] Cleaning up stale processes..." -ForegroundColor Yellow
Stop-PortProcess -Label "Backend" -Port $backendPort
Stop-PortProcess -Label "Admin" -Port $adminPort
Stop-PortProcess -Label "Frontend" -Port $frontendPort

# 4. Start services
Write-Host "[4/4] Starting services..." -ForegroundColor Yellow
Write-Host "      Backend:  $backendUrl" -ForegroundColor Green
Write-Host "      Admin:    $adminUrl" -ForegroundColor Green
Write-Host "      Frontend: $frontendUrl" -ForegroundColor Green

$backendProcess = Start-ServiceProcess -ServiceName "Backend" -ServiceCommand "pnpm dev:backend" -LogPath $backendLogPath -PidPath $backendPidPath
$adminProcess = Start-ServiceProcess -ServiceName "Admin" -ServiceCommand "pnpm dev:admin" -LogPath $adminLogPath -PidPath $adminPidPath

Write-Host "      Backend log:  $backendLogPath" -ForegroundColor DarkGray
Write-Host "      Admin log:    $adminLogPath" -ForegroundColor DarkGray
Write-Host "      Backend PID:  $($backendProcess.Id)" -ForegroundColor DarkGray
Write-Host "      Admin PID:    $($adminProcess.Id)" -ForegroundColor DarkGray

# 5. Health check: verify backend is actually responding
Write-Host ""
Write-Host "Waiting for backend to start..." -ForegroundColor Yellow
$backendHealthy = Test-BackendHealth -Url $backendUrl -TimeoutSeconds 30

if (-not $backendHealthy) {
    Write-Host ""
    Write-Host "WARNING: Backend did not respond within 30 seconds!" -ForegroundColor Red
    Write-Host "  Check the log for errors: $backendLogPath" -ForegroundColor Red
    Write-Host "  Last 20 lines:" -ForegroundColor Red
    if (Test-Path $backendLogPath) {
        Get-Content $backendLogPath -Tail 20 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkRed }
    }
    Write-Host ""
    Write-Host "Press any key to continue starting Frontend anyway, or Ctrl+C to abort..." -ForegroundColor Yellow
    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
}

# 6. Start Frontend in current window
Write-Host ""
Write-Host "Starting Frontend..." -ForegroundColor Yellow
pnpm dev:frontend
