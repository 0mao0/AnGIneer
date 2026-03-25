# AnGIneer Startup Script (Simplified)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$rootDir = if ($PSScriptRoot) { $PSScriptRoot } else { (Get-Location).Path }
$portContractPath = Join-Path $rootDir "apps/shared/ports.json"
$portContract = Get-Content $portContractPath -Raw | ConvertFrom-Json

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

# 1. 检查基础环境
Write-Host "[1/3] Cheking Node.js & Python..." -ForegroundColor Yellow
$nodeVer = node --version 2>$null
if (-not $nodeVer) { Write-Error "Node.js not found!"; exit 1 }
$pythonVer = python --version 2>$null
if (-not $pythonVer) { Write-Error "Python not found!"; exit 1 }

# 2. 安装依赖 (仅在 node_modules 不存在时强制安装，否则手动更新)
if (-not (Test-Path "node_modules")) {
    Write-Host "[2/3] Install dependencies (first time)..." -ForegroundColor Yellow
    pnpm install
} else {
    Write-Host "[2/3] Skipping dependencies installation (node_modules exists)..." -ForegroundColor Green
}

# 3. 启动所有服务
Write-Host "[3/3] Starting Backend, Admin and Frontend..." -ForegroundColor Yellow
Write-Host "      Backend:  $backendUrl" -ForegroundColor Green
Write-Host "      Admin:    $adminUrl" -ForegroundColor Green
Write-Host "      Frontend: $frontendUrl" -ForegroundColor Green

# 后端 (独立窗口)
Start-Process cmd -ArgumentList "/k cd /d `"$rootDir`" && title AnGIneer Backend && pnpm dev:backend"

# Admin (独立窗口)
Start-Process cmd -ArgumentList "/k cd /d `"$rootDir`" && title AnGIneer Admin && pnpm dev:admin"

# 等待后端启动
Write-Host ""
Write-Host "waiting for backend to start (10 seconds)..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

# Frontend (当前窗口)
pnpm dev:frontend
