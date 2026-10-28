<#
.SYNOPSIS
Give one agent its own git worktree, branch, venv and MCP config.

.DESCRIPTION
Creates <Dir>\<Name> on a new branch agent/<Name> from <Base>, then sets up what
git does not carry over: a .venv with this checkout installed editable (sharing the
main .venv would import the main checkout's src/), and a .mcp.json whose paths point
into the worktree. playground/ is per-worktree by construction.

Not isolated by a worktree: AutoCAD (accoreconsole writes the user's registry profile),
so run AutoCAD tasks one at a time, and give each agent its own pytest --basetemp.

.EXAMPLE
scripts\new-worktree.ps1 pdf-export
scripts\new-worktree.ps1 pdf-export -Remove
#>
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Name,
    [string]$Base = "main",
    [string]$Dir = "",
    [switch]$Remove
)
$ErrorActionPreference = "Stop"

$repo = (git -C "$PSScriptRoot\.." rev-parse --show-toplevel).Trim()
if (-not $Dir) { $Dir = Join-Path (Split-Path $repo -Parent) "$(Split-Path $repo -Leaf)-wt" }
$path = Join-Path $Dir $Name
$branch = "agent/$Name"

function Invoke-Checked([string]$what, [scriptblock]$cmd) {
    & $cmd
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

if ($Remove) {
    # Refuses to drop uncommitted work; -d refuses to drop an unmerged branch.
    Invoke-Checked "git worktree remove" { git -C $repo worktree remove $path }
    Invoke-Checked "git branch -d" { git -C $repo branch -d $branch }
    Write-Host "Removed $path and $branch"
    return
}

Invoke-Checked "git worktree add" { git -C $repo worktree add -b $branch $path $Base }

Push-Location $path
try {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Invoke-Checked "uv venv" { uv venv -q .venv }
        Invoke-Checked "uv pip install" { uv pip install -q --python .venv\Scripts\python.exe -e ".[dev]" }
    } else {
        Invoke-Checked "python -m venv" { python -m venv .venv }
        Invoke-Checked "pip install" { .venv\Scripts\python.exe -m pip install -q -e ".[dev]" }
    }
    # .mcp.json is ignored and holds absolute paths; this one points at the worktree's interpreter and playground.
    Invoke-Checked "agentcad mcp-config" { .venv\Scripts\agentcad.exe --root playground mcp-config --write | Out-Null }
} finally {
    Pop-Location
}

Write-Host ""
Write-Host "Worktree: $path"
Write-Host "Branch:   $branch (from $Base)"
Write-Host "Tests:    .venv\Scripts\python -m pytest -p no:cacheprovider --basetemp=<own dir per agent>"
Write-Host "AutoCAD:  shared by all worktrees; run AutoCAD tasks one at a time"
Write-Host "Merge:    git merge $branch   (in $repo)"
Write-Host "Clean up: scripts\new-worktree.ps1 $Name -Remove"
