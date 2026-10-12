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
    'table-ui', 'ai-inference', 'core', 'tree-core', 'docs-core'). 'core' is the short id for
    the angineer-core python package (services/angineer-core, repo angineer-core);
    'tree-core' maps to services/tree-core (repo angineer-tree-core);
    'docs-core' maps to services/docs-core (repo angineer-docs-core).

.PARAMETER AllowVersionDrift
    Proceed even when a python package's HEAD pyproject.toml version is BEHIND
    the newest published version on PyPI (the stale-field case that misleads
    package consumers: repo says 0.1.1 while PyPI serves 0.1.2). Without this
    switch such a sync aborts. Equal version with pending source changes only
    warns ("changed but not released yet").

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/sync-standalone.ps1 -Message "fix: update preview"

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/sync-standalone.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$Message = '',
    [switch]$DryRun,
    [switch]$AllowVersionDrift,
    [string[]]$Packages = @('docs-ui', 'aichat-ui', 'smartree', 'table-ui', 'ai-inference', 'core', 'tree-core', 'docs-core')
)

$ErrorActionPreference = 'Stop'

# npm package names are lowercase, GitHub repo names may not be: dir name -> repo name
$RepoNameOverrides = @{ 'smartree' = 'angineer-smartree-ui' }
# packages whose source does not live under packages/<pkg>: dir name -> main-repo path
$SourcePathOverrides = @{
    'ai-inference' = 'services/ai-inference'
    'core' = 'services/angineer-core'
    'tree-core' = 'services/tree-core'
    'docs-core' = 'services/docs-core'
}
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

# Non-throwing variant: returns stdout lines, or $null when the git command
# exits non-zero (used by the optional version-parity probe, where a missing
# pyproject.toml in the HEAD tree is normal - JS packages).
function Invoke-GitSilent {
    param(
        [Parameter(Mandatory = $true)][string]$Dir,
        [Parameter(Mandatory = $true)][string[]]$Args
    )
    $previousEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    $output = & git -C $Dir @Args 2>$null
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousEap
    if ($exitCode -ne 0) { return $null }
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

        # Version parity guard (python packages only - HEAD tree has no
        # pyproject.toml for JS packages, probe returns $null). Runs only when
        # this sync actually carries source changes, i.e. a release is being
        # prepared. Repo pyproject.version BEHIND the newest published PyPI
        # version is the stale-field trap that misleads package consumers
        # (observed: repo field 0.1.1 while PyPI served 0.1.2) -> abort unless
        # -AllowVersionDrift. Equal version with pending changes warns: the
        # changes will not reach package consumers until bump + tag release.
        $pyLines = Invoke-GitSilent -Dir $RepoRoot -Args @('show', "${Head}:$srcPath/pyproject.toml")
        if ($pyLines) {
            $pyText = ($pyLines -join "`n")
            $mName = [regex]::Match($pyText, '(?m)^name\s*=\s*"([^"]+)"')
            $mVer = [regex]::Match($pyText, '(?m)^version\s*=\s*"([^"]+)"')
            if ($mName.Success -and $mVer.Success) {
                $distName = $mName.Groups[1].Value
                $repoVer = $mVer.Groups[1].Value
                $pypiVer = $null
                try {
                    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                    $meta = Invoke-RestMethod -Uri "https://pypi.org/pypi/$distName/json" -TimeoutSec 20
                    $pypiVer = $meta.info.version
                } catch {
                    Write-Warning "${pkg}: cannot reach pypi.org for $distName - version parity check skipped."
                }
                if ($pypiVer) {
                    $repoV = $null; $pypiV = $null
                    try {
                        $repoV = [Version]$repoVer
                        $pypiV = [Version]$pypiVer
                    } catch {
                        Write-Warning "${pkg}: version strings '$repoVer' / '$pypiVer' not comparable as [Version] - parity check skipped."
                    }
                    if ($repoV -and $pypiV) {
                        if ($repoV -lt $pypiV) {
                            if ($AllowVersionDrift) {
                                Write-Warning "${pkg}: pyproject version $repoVer is BEHIND published $pypiVer (stale field). -AllowVersionDrift given, continuing."
                            } else {
                                throw "${pkg}: pyproject.toml version $repoVer is behind the newest published version $pypiVer of '$distName' on PyPI. The repo version field misleads package consumers. Bump the version in the monorepo (commit to main, then re-run sync), or pass -AllowVersionDrift to proceed anyway."
                            }
                        } elseif ($repoV -eq $pypiV) {
                            Write-Warning "${pkg}: source changes are being synced while pyproject version $repoVer already equals the newest published $pypiVer - these changes will not reach package consumers until a version bump + tag release."
                        } else {
                            Write-Host "${pkg}: version parity OK (repo $repoVer ahead of published $pypiVer)."
                        }
                    }
                }
            }
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

        # list remotes instead of `remote get-url` + $LASTEXITCODE: with
        # $ErrorActionPreference='Stop' a missing remote makes git write to
        # stderr, which PowerShell 5.1 turns into a terminating
        # NativeCommandError before the exit code can be inspected (breaks the
        # first sync of a brand new package).
        $remotes = @(Invoke-Git -Dir $wt -Args @('remote'))
        if ($remotes -notcontains $remoteName) {
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
