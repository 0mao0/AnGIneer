<#
.SYNOPSIS
    Sync monorepo package changes to standalone worktrees, commit and push the standalone repos.

.DESCRIPTION
    Each standalone repo is a root-layout copy of a source path in this repo
    (default: packages/<pkg>; see $SourcePathOverrides for exceptions like
    services/ai-inference). Sync = make the worktree content match main HEAD for
    that path, using a tree-vs-tree diff:

        git diff split/<pkg> HEAD:<srcPath>

    This works for changes already committed to main (the previous staged-diff
    design silently produced empty patches for committed changes). Per package:
      1. Verify the worktree (.worktrees/angineer-<pkg>, branch split/<pkg>) is
         clean and sits at the split/<pkg> branch tip.
      2. Build a binary-safe patch of all added/modified files, excluding:
         - deletions (--diff-filter=d): files that only exist in the standalone
           repo (.github/, LICENSE, ...) would otherwise be deleted by the patch;
         - protected paths (package.json, CHANGELOG.md, LICENSE): these diverge by
           design (standalone package.json has no "private", rewrites workspace:*
           deps and adds publish metadata; CHANGELOG is standalone-owned). Their
           main-side diff is printed for manual porting instead of being applied.
      3. Apply, commit and push the worktree to its standalone remote.
    The main repo is NOT committed or pushed by this script: commit your code
    changes to main first (uncommitted changes under a target path abort the run).

    Keep this file pure ASCII: Windows PowerShell 5.1 decodes BOM-less UTF-8 as
    the system ANSI codepage, and a Chinese comment ending with an odd number of
    bytes merges the next line into the comment (observed: hashtable literal
    silently skipped, null at runtime). The no-BOM assertion in standalone CI
    covers package.json only, but the ASCII rule keeps this script correct on
    both powershell.exe and pwsh either way.

.PARAMETER Message
    Commit message used in every standalone worktree.
    Defaults to "chore: sync standalone packages".

.PARAMETER DryRun
    Build and validate patches, print diffstats and protected-file diffs, but do
    not apply, commit or push anything.

.PARAMETER Packages
    Package names to sync. Defaults to @('docs-ui', 'aichat-ui', 'smartree',
    'table-ui', 'ai-inference').

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/sync-standalone.ps1 -Message "fix: update preview"

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/sync-standalone.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$Message = '',
    [switch]$DryRun,
    [string[]]$Packages = @('docs-ui', 'aichat-ui', 'smartree', 'table-ui', 'ai-inference')
)

$ErrorActionPreference = 'Stop'

# npm package names are lowercase, GitHub repo names may not be: dir name -> repo name
$RepoNameOverrides = @{ 'smartree' = 'angineer-smartree-ui' }
# packages whose source does not live under packages/<pkg>: dir name -> main-repo path
$SourcePathOverrides = @{ 'ai-inference' = 'services/ai-inference' }
# standalone-owned or diverging files: never auto-overwritten, main-side diff is
# printed for manual porting instead
$ProtectedPaths = @('package.json', 'CHANGELOG.md', 'LICENSE')

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
$Head = (Invoke-Git -Dir $RepoRoot -Args @('rev-parse', 'HEAD')).Trim()

if (-not $Message) {
    $Message = 'chore: sync standalone packages'
}

$patchFiles = @{}

try {
    foreach ($pkg in $Packages) {
        $srcPath = if ($SourcePathOverrides.ContainsKey($pkg)) { $SourcePathOverrides[$pkg] } else { "packages/$pkg" }
        $wt = Join-Path $RepoRoot ".worktrees/angineer-$pkg"
        $splitRef = "split/$pkg"

        if (-not (Test-Path (Join-Path $RepoRoot $srcPath))) {
            Write-Warning "Skip ${pkg}: $srcPath does not exist."
            continue
        }
        if (-not (Test-Path (Join-Path $wt '.git'))) {
            Write-Warning "Skip ${pkg}: worktree $wt not found."
            continue
        }
        Invoke-Git -Dir $RepoRoot -Args @('rev-parse', '--verify', $splitRef) | Out-Null

        $wtBranch = (Invoke-Git -Dir $wt -Args @('branch', '--show-current')).Trim()
        if ($wtBranch -ne $splitRef) {
            throw "Worktree $wt is on branch '$wtBranch', expected $splitRef."
        }
        $wtStatus = & git -C $wt status --porcelain
        if ($LASTEXITCODE -ne 0) { throw "git status failed in $wt" }
        if ($wtStatus) {
            throw "Worktree $wt is dirty. Commit or stash its changes before syncing."
        }
        $wtHead = (Invoke-Git -Dir $wt -Args @('rev-parse', 'HEAD')).Trim()
        $splitTip = (Invoke-Git -Dir $RepoRoot -Args @('rev-parse', $splitRef)).Trim()
        if ($wtHead -ne $splitTip) {
            throw "Worktree $wt HEAD ($wtHead) != $splitRef tip ($splitTip)."
        }

        $dirty = & git -C $RepoRoot status --porcelain -- $srcPath
        if ($LASTEXITCODE -ne 0) { throw "git status failed for $srcPath" }
        if ($dirty) {
            throw "$srcPath has uncommitted changes in main. Commit them first - the sync compares against HEAD."
        }

        # Files to sync = tree diff vs split tip, minus deletions and protected paths.
        $statArgs = @('diff', '--stat', '--diff-filter=d', $splitRef, "${Head}:$srcPath", '--', '.')
        foreach ($p in $ProtectedPaths) { $statArgs += ":(exclude)$p" }
        $syncStat = @(Invoke-Git -Dir $RepoRoot -Args $statArgs)
        $syncFiles = @($syncStat | Where-Object { $_ -match '\|' })
        if ($syncFiles.Count -eq 0) {
            Write-Host "${pkg}: nothing to sync"
            continue
        }

        $patchFile = Join-Path $env:TEMP ("angineer-$pkg-" + [guid]::NewGuid().ToString('N') + '.patch')
        $diffArgs = @('diff', '--binary', '--diff-filter=d', $splitRef, "${Head}:$srcPath", "--output=$patchFile", '--', '.')
        foreach ($p in $ProtectedPaths) { $diffArgs += ":(exclude)$p" }
        Invoke-Git -Dir $RepoRoot -Args $diffArgs | Out-Null

        if ((Get-Item $patchFile).Length -eq 0) {
            Remove-Item $patchFile -Force
            Write-Host "${pkg}: nothing to sync"
            continue
        }
        $patchFiles[$pkg] = $patchFile

        Write-Host "${pkg}: sync contents (deletions and protected paths excluded):"
        $syncStat | ForEach-Object { Write-Host "    $_" }

        $protArgs = @('diff', $splitRef, "${Head}:$srcPath", '--')
        foreach ($p in $ProtectedPaths) { $protArgs += $p }
        $protectedDiff = @(Invoke-Git -Dir $RepoRoot -Args $protArgs)
        if ($protectedDiff) {
            Write-Warning "${pkg}: main-side diff in protected files (NOT applied; port manually into the worktree if needed):"
            $protectedDiff | ForEach-Object { Write-Host "    $_" }
        }

        Invoke-Git -Dir $wt -Args @('apply', '--check', '--binary', $patchFile) | Out-Null
        Write-Host "${pkg}: patch applies cleanly in $wt"
    }

    if ($patchFiles.Count -eq 0) {
        Write-Host 'Nothing to sync: no changes in the target packages.'
        exit 0
    }

    if ($DryRun) {
        Write-Host "DryRun (message would be: $Message): would apply patches, commit and push the worktrees above."
        exit 0
    }

    foreach ($pkg in $patchFiles.Keys) {
        $wt = Join-Path $RepoRoot ".worktrees/angineer-$pkg"
        $patchFile = $patchFiles[$pkg]

        Invoke-Git -Dir $wt -Args @('apply', '--binary', $patchFile) | Out-Null
        Invoke-Git -Dir $wt -Args @('add', '-A') | Out-Null
        Invoke-Git -Dir $wt -Args @('commit', '-m', $Message) | Out-Null
        Write-Host "${pkg}: committed in $wt"

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
    foreach ($f in $patchFiles.Values) {
        if (Test-Path $f) { Remove-Item $f -Force }
    }
}
