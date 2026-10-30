# Local dev backend watchdog: keep docs-api / aichat-api / sop-api alive.
# Loop: probe /health per service; after 2 consecutive failures kill the stale
# process tree and relaunch python services/<name>/main.py hidden, with startup
# grace + exponential backoff so a crash loop cannot hammer the machine.
# Stop monitoring: pnpm backend:watch:stop (creates stop flag; services survive).
# ASCII-only on purpose: Chinese text in .ps1 without BOM breaks PowerShell 5.1 parsing.
param([switch]$Stop)

$ErrorActionPreference = 'Continue'
$rootDir = if ($PSScriptRoot) { Split-Path -Parent $PSScriptRoot } else { (Get-Location).Path }
$logsDir = Join-Path $rootDir 'logs'
if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }
$logPath  = Join-Path $logsDir 'dev-watchdog.log'
$lockPath = Join-Path $logsDir 'dev-watchdog.lock'
$flagPath = Join-Path $logsDir 'dev-watchdog.stop'

function Write-WD([string]$msg) {
    $line = "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg"
    Write-Host $line
    Add-Content -Path $logPath -Value $line -Encoding utf8
}

if ($Stop) {
    Set-Content -Path $flagPath -Value 'stop' -Encoding ascii
    Write-WD 'stop flag set - running watchdog will exit on its next tick (services are NOT killed)'
    exit 0
}

$portContract = Get-Content (Join-Path $rootDir 'apps/shared/ports.json') -Raw | ConvertFrom-Json
$services = @(
    @{ Name = 'docs-api';   Port = [int]$portContract.docsApiPort;   Grace = 240 },
    @{ Name = 'aichat-api'; Port = [int]$portContract.aichatApiPort; Grace = 180 },
    @{ Name = 'sop-api';    Port = [int]$portContract.sopApiPort;    Grace = 60  }
)
$interval   = 15    # seconds between probe rounds
$failsToAct = 2     # consecutive failures before a restart

# single-instance guard: one watchdog only; stale lock (dead pid) is reclaimed.
if (Test-Path $lockPath) {
    $oldPid = (Get-Content $lockPath -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ($oldPid -and (Get-Process -Id ([int]$oldPid) -ErrorAction SilentlyContinue)) {
        Write-WD "another watchdog alive (pid=$oldPid) -> exit"
        exit 0
    }
    Write-WD "stale lock (pid=$oldPid gone) -> reclaim"
}
Set-Content -Path $lockPath -Value $PID -Encoding ascii
# A leftover stop flag from a previous -Stop would make this run quit instantly.
Remove-Item $flagPath -Force -ErrorAction SilentlyContinue

function Stop-ProcessTree([int]$ProcessId) {
    $process = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if (-not $process) { return }
    $children = Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq $ProcessId }
    foreach ($child in $children) { Stop-ProcessTree -ProcessId $child.ProcessId }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Stop-ServiceProcesses($svc) {
    $pattern = 'services[\\/]' + [regex]::Escape($svc.Name) + '[\\/]main\.py'
    $targets = @{}
    $procs = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match $pattern })
    foreach ($p in $procs) { $targets[$p.ProcessId] = $true }
    # uvicorn --reload can leave the listening socket on a dead parent: only kill
    # port owners whose command line belongs to THIS service, never foreign ones.
    foreach ($conn in @(Get-NetTCPConnection -LocalPort $svc.Port -State Listen -ErrorAction SilentlyContinue)) {
        $ownPid = $conn.OwningProcess
        $owner = @(Get-CimInstance Win32_Process -Filter "ProcessId=$ownPid" -ErrorAction SilentlyContinue)
        if ($owner -and $owner[0].CommandLine -match $pattern) { $targets[$ownPid] = $true }
        else { Write-WD "$($svc.Name): port $($svc.Port) held by foreign pid=$ownPid - NOT killing it" }
    }
    foreach ($procId in $targets.Keys) {
        Write-WD "$($svc.Name): killing stale pid=$procId"
        Stop-ProcessTree -ProcessId $procId
    }
}

function Test-ServiceHealth($svc) {
    try {
        # 127.0.0.1 not localhost: localhost can add a seconds-long stall on this box.
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$($svc.Port)/health" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        return $resp.StatusCode -eq 200
    } catch { return $false }
}

function Start-ServiceBackend($svc) {
    $scriptPath = Join-Path $rootDir "services\$($svc.Name)\main.py"
    $outLog = Join-Path $logsDir "$($svc.Name)-watch.out.log"
    $errLog = Join-Path $logsDir "$($svc.Name)-watch.err.log"
    $proc = Start-Process -FilePath 'python' -ArgumentList "`"$scriptPath`"" `
        -WorkingDirectory $rootDir -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput $outLog -RedirectStandardError $errLog
    Write-WD "$($svc.Name): started pid=$($proc.Id), stderr -> $errLog"
}

Write-WD "watchdog start (pid=$PID, interval=${interval}s, failsToAct=$failsToAct, services=$($services.Name -join ','))"
$state = @{}
foreach ($svc in $services) {
    $state[$svc.Name] = @{ Fails = 0; Restarts = 0; CooldownUntil = (Get-Date) }
}

while ($true) {
    if (Test-Path $flagPath) {
        Write-WD 'stop flag found -> watchdog exit (services keep running)'
        Remove-Item $flagPath -Force -ErrorAction SilentlyContinue
        Remove-Item $lockPath -Force -ErrorAction SilentlyContinue
        break
    }
    $now = Get-Date
    foreach ($svc in $services) {
        $st = $state[$svc.Name]
        if ($now -lt $st.CooldownUntil) { continue }   # startup grace / crash-loop backoff
        if (Test-ServiceHealth $svc) {
            if ($st.Fails -gt 0) { Write-WD "$($svc.Name): recovered after $($st.Fails) failed probe(s)" }
            elseif ($st.Restarts -gt 0) { Write-WD "$($svc.Name): healthy after restart, backoff reset" }
            $st.Fails = 0
            $st.Restarts = 0
            continue
        }
        $st.Fails++
        Write-WD "$($svc.Name): probe failed ($($st.Fails)/$failsToAct)"
        if ($st.Fails -lt $failsToAct) { continue }
        Write-WD "$($svc.Name): restarting (attempt $($st.Restarts + 1))"
        try {
            Stop-ServiceProcesses $svc
            Start-Sleep -Seconds 2
            Start-ServiceBackend $svc
        } catch { Write-WD "$($svc.Name): restart step failed: $($_.Exception.Message)" }
        $st.Restarts++
        $st.Fails = 0
        $backoff = [Math]::Min(60 * [Math]::Pow(2, [Math]::Min($st.Restarts, 4)), 600)
        $st.CooldownUntil = $now.AddSeconds([Math]::Max($svc.Grace, $backoff))
    }
    Start-Sleep -Seconds $interval
}
Write-WD 'watchdog stopped'
