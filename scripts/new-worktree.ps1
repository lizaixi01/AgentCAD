<#
.SYNOPSIS
Give one agent its own git worktree, branch, venv and MCP config.

.DESCRIPTION
Creates <Dir>\<Name> on a new branch agent/<Name> from origin/main (fetched first), then sets up
what git does not carry over: a .venv with this checkout installed editable (sharing the main .venv
would import the main checkout's src/), and a .mcp.json whose paths point into the worktree.
playground/ is per-worktree by construction. If setup fails, the worktree and branch are removed.

-Here sets up .venv and .mcp.json in the current checkout instead, e.g. a worktree the Claude Code
desktop app made under .claude/worktrees/.

-Remove deletes the worktree and its branch, but only once the branch is merged into origin/main.

Not isolated by a worktree: AutoCAD (accoreconsole writes the user's registry profile),
so run AutoCAD tasks one at a time, and give each agent its own pytest --basetemp.

.EXAMPLE
scripts\new-worktree.ps1 pdf-export
scripts\new-worktree.ps1 -Here
scripts\new-worktree.ps1 pdf-export -Remove
#>
param(
    [Parameter(Position = 0)][string]$Name = "",
    [string]$Base = "origin/main",
    [string]$Dir = "",
    [switch]$Here,
    [switch]$Remove
)
$ErrorActionPreference = "Stop"

function Invoke-Checked([string]$what, [scriptblock]$cmd) {
    # Native tools write progress to stderr; under Stop that would throw when stderr is redirected.
    $ErrorActionPreference = "Continue"
    & $cmd
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

function Initialize-Checkout([string]$path) {
    Push-Location $path
    try {
        if (Get-Command uv -ErrorAction SilentlyContinue) {
            Invoke-Checked "uv venv" { uv venv -q .venv }
            Invoke-Checked "uv pip install" { uv pip install -q --python .venv\Scripts\python.exe -e ".[dev]" }
        } else {
            Invoke-Checked "python -m venv" { python -m venv .venv }
            Invoke-Checked "pip install" { .venv\Scripts\python.exe -m pip install -q -e ".[dev]" }
        }
        # .mcp.json is ignored and holds absolute paths; this one points at this checkout's interpreter and playground.
        Invoke-Checked "agentcad mcp-config" { .venv\Scripts\agentcad.exe --root playground mcp-config --write | Out-Null }
    } finally {
        Pop-Location
    }
}

if ($Here) {
    $top = (git rev-parse --show-toplevel).Trim()
    Initialize-Checkout $top
    Write-Host "Set up .venv and .mcp.json in $top"
    return
}
if (-not $Name) { throw "Give a task name, or -Here" }

# The main checkout, also when this runs inside a worktree (its toplevel would nest new worktrees under it).
$common = (git -C $PSScriptRoot rev-parse --path-format=absolute --git-common-dir).Trim()
$repo = Split-Path $common -Parent
if (-not $Dir) { $Dir = Join-Path (Split-Path $repo -Parent) "$(Split-Path $repo -Leaf)-wt" }
$path = Join-Path $Dir $Name
$branch = "agent/$Name"

Invoke-Checked "git fetch" { git -C $repo fetch -q origin }

if ($Remove) {
    # Check before deleting anything, so a refusal leaves the worktree and branches as they were.
    $ErrorActionPreference = "Continue"
    git -C $repo show-ref -q --verify "refs/heads/$branch"; $local = $LASTEXITCODE -eq 0
    git -C $repo show-ref -q --verify "refs/remotes/origin/$branch"; $remote = $LASTEXITCODE -eq 0
    foreach ($ref in @($(if ($local) { $branch }), $(if ($remote) { "origin/$branch" })) | Where-Object { $_ }) {
        git -C $repo merge-base --is-ancestor $ref origin/main
        if ($LASTEXITCODE -ne 0) { throw "$ref is not merged into origin/main; nothing removed" }
    }
    if (Test-Path $path) {
        Invoke-Checked "git worktree remove" { git -C $repo worktree remove $path }
    } else {
        Invoke-Checked "git worktree prune" { git -C $repo worktree prune }
    }
    # -D: merged into origin/main, which local main may not have pulled yet.
    if ($local) { Invoke-Checked "git branch -D" { git -C $repo branch -q -D $branch } }
    if ($remote) { Invoke-Checked "git push --delete" { git -C $repo push -q origin --delete $branch } }
    Write-Host "Removed $path and $branch (local: $local, origin: $remote)"
    return
}

# --no-track: the branch must not get origin/main as its upstream.
Invoke-Checked "git worktree add" { git -C $repo worktree add --quiet --no-track -b $branch $path $Base }
try {
    Initialize-Checkout $path
} catch {
    Write-Warning "Setup failed; removing $path and $branch"
    $ErrorActionPreference = "Continue"
    git -C $repo worktree remove --force $path 2>$null
    git -C $repo branch -q -D $branch 2>$null
    throw
}

Write-Host ""
Write-Host "Worktree: $path"
Write-Host "Branch:   $branch (from $Base)"
Write-Host "Tests:    .venv\Scripts\python -m pytest -p no:cacheprovider --basetemp=<own dir per agent>"
Write-Host "AutoCAD:  shared by all worktrees; run AutoCAD tasks one at a time"
Write-Host "Finish:   commit by path, git push -u origin $branch, gh pr create (see AGENTS.md)"
Write-Host "Clean up: scripts\new-worktree.ps1 $Name -Remove   (after the PR is merged)"
