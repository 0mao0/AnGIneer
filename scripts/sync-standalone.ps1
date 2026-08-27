<#
.SYNOPSIS
    Sync monorepo package changes to standalone worktrees, commit and push both repos.

.DESCRIPTION
    For each package (default: docs-ui, aichat-ui):
      1. Stages changes under packages/<pkg> in the main repo.
      2. Generates a binary-safe patch with paths relative to the package dir.
      3. Applies and commits the patch in the standalone worktree
         (.worktrees/angineer-<pkg>, branch split/<pkg>).
      4. Commits the main repo (only the package paths) and pushes origin main.
      5. Pushes the worktree branch to the standalone remote
         (angineer-<pkg>, github.com/0mao0/angineer-<pkg>).

    Requirements:
      - Run from the AnGIneer repo on the main branch.
      - Standalone worktrees must be clean (no uncommitted changes).

.PARAMETER Message
    Commit message used for the main repo and every standalone worktree.
    Defaults to "chore: sync standalone packages".

.PARAMETER DryRun
    Stage changes and validate patches, but do not commit or push anything.
    Note: changes remain staged in main afterwards; run "git reset" to undo.

.PARAMETER Packages
    Package names to sync. Defaults to @('docs-ui', 'aichat-ui').

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/sync-standalone.ps1 -Message "fix: update preview"

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/sync-standalone.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$Message = '',
    [switch]$DryRun,
    [string[]]$Packages = @('docs-ui', 'aichat-ui', 'smartree', 'table-ui')
)

$ErrorActionPreference = 'Stop'

# npm 包名必须小写，GitHub 仓库名可能含大写；目录名 -> 仓库名
$RepoNameOverrides = @{ 'smartree' = 'angineer-smartree-ui' }

function Invoke-Git {
    param(
        [Parameter(Mandatory = $true)][string]$Dir,
        [Parameter(Mandatory = $true)][string[]]$Args
    )
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $output = & git -C $Dir @Args 2>&1
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousEap
    if ($exitCode -ne 0) {
        throw "git $($Args -join ' ') failed (exit $exitCode): $output"
    }
    return $output
}

$RepoRoot = (Invoke-Git -Dir '.' -Args @('rev-parse', '--show-toplevel')).Trim()
$CurrentBranch = (Invoke-Git -Dir $RepoRoot -Args @('branch', '--show-current')).Trim()
if ($CurrentBranch -ne 'main') {
    throw "This script must run on the main branch (current: $CurrentBranch)."
}

$changedPackages = @()
$patchFiles = @()

try {
    foreach ($pkg in $Packages) {
        $mainPath = "packages/$pkg"
        $wt = Join-Path $RepoRoot ".worktrees/angineer-$pkg"

        if (-not (Test-Path (Join-Path $RepoRoot $mainPath))) {
            Write-Warning "Skip ${pkg}: $mainPath does not exist."
            continue
        }
        if (-not (Test-Path (Join-Path $wt '.git'))) {
            Write-Warning "Skip ${pkg}: worktree $wt not found."
            continue
        }

        $wtStatus = & git -C $wt status --porcelain
        if ($LASTEXITCODE -ne 0) { throw "git status failed in $wt" }
        if ($wtStatus) {
            throw "Worktree $wt is dirty. Commit or stash its changes before syncing."
        }

        Invoke-Git -Dir $RepoRoot -Args @('add', '-A', '--', $mainPath) | Out-Null

        $patchFile = Join-Path $env:TEMP ("angineer-$pkg-" + [guid]::NewGuid().ToString('N') + '.patch')
        Invoke-Git -Dir $RepoRoot -Args @(
            'diff', '--cached', '--binary',
            "--relative=$mainPath",
            "--output=$patchFile",
            'HEAD', '--', $mainPath
        ) | Out-Null

        if ((Get-Item $patchFile).Length -eq 0) {
            Remove-Item $patchFile -Force
            Write-Host "${pkg}: no changes"
            continue
        }

        $patchFiles += $patchFile
        $changedPackages += $pkg
        Write-Host "${pkg}: changes detected"
    }

    if ($changedPackages.Count -eq 0) {
        Write-Host 'Nothing to sync: no changes in the target packages.'
        exit 0
    }

    if (-not $Message) {
        $Message = 'chore: sync standalone packages'
    }
    Write-Host "Commit message: $Message"

    foreach ($pkg in $changedPackages) {
        $wt = Join-Path $RepoRoot ".worktrees/angineer-$pkg"
        $patchFile = $patchFiles | Where-Object { $_ -like "*angineer-$pkg-*" } | Select-Object -First 1
        Invoke-Git -Dir $wt -Args @('apply', '--check', '--binary', $patchFile) | Out-Null
        Write-Host "${pkg}: patch applies cleanly in $wt"
    }

    if ($DryRun) {
        Write-Host 'DryRun: would commit main + worktrees, push origin main and standalone remotes.'
        Write-Host 'Changes are currently staged in main (run "git reset" to undo the staging).'
        exit 0
    }

    foreach ($pkg in $changedPackages) {
        $wt = Join-Path $RepoRoot ".worktrees/angineer-$pkg"
        $patchFile = $patchFiles | Where-Object { $_ -like "*angineer-$pkg-*" } | Select-Object -First 1

        Invoke-Git -Dir $wt -Args @('apply', '--binary', $patchFile) | Out-Null
        Invoke-Git -Dir $wt -Args @('add', '-A') | Out-Null
        Invoke-Git -Dir $wt -Args @('commit', '-m', $Message) | Out-Null
        Write-Host "${pkg}: committed in $wt"
    }

    $commitPaths = $changedPackages | ForEach-Object { "packages/$_" }
    Invoke-Git -Dir $RepoRoot -Args @('commit', '-m', $Message, '--', $commitPaths) | Out-Null
    Write-Host 'main: committed'

    Invoke-Git -Dir $RepoRoot -Args @('push', 'origin', 'main') | Out-Null
    Write-Host 'main: pushed to origin'

    foreach ($pkg in $changedPackages) {
        $wt = Join-Path $RepoRoot ".worktrees/angineer-$pkg"
        $remoteName = "angineer-$pkg"
        $repoName = if ($RepoNameOverrides.ContainsKey($pkg)) { $RepoNameOverrides[$pkg] } else { "angineer-$pkg" }
        $remoteUrl = "git@github.com:0mao0/$repoName.git"

        $existing = & git -C $wt remote get-url $remoteName 2>$null
        if ($LASTEXITCODE -ne 0) {
            Invoke-Git -Dir $wt -Args @('remote', 'add', $remoteName, $remoteUrl) | Out-Null
            Write-Host "${pkg}: added remote $remoteName -> $remoteUrl"
        }

        Invoke-Git -Dir $wt -Args @('push', '-u', $remoteName, 'HEAD:main') | Out-Null
        Write-Host "${pkg}: pushed $remoteName main"
    }

    Write-Host 'Done. All packages synced and pushed.'
}
finally {
    foreach ($f in $patchFiles) {
        if (Test-Path $f) { Remove-Item $f -Force }
    }
}
