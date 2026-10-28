# Working on AgentCAD

Several agents (Claude Code, Codex) often work on this repo at the same time. These rules keep their
changes apart.

## One task, one worktree

Never edit in the main checkout (`D:\Projects\AgentCAD`) while another agent may be working there. Do
each task in its own worktree on its own branch:

- A Claude Code desktop session started with a worktree already has one (`.claude/worktrees/`).
- Otherwise: `scripts\new-worktree.ps1 <task-name>` creates `..\AgentCAD-wt\<task-name>` on branch
  `agent/<task-name>` from `main`.

Each worktree needs what git does not carry over (the script does both):

- its own `.venv` with the checkout installed editable. A shared editable venv imports the main
  checkout's `src/`, so tests would run code you did not change.
- its own `.mcp.json` (`.venv\Scripts\agentcad --root playground mcp-config --write`), so the MCP
  server runs the worktree's code against the worktree's `playground/`.

Not isolated by a worktree:

- AutoCAD (accoreconsole, the PNG renderer, DWG and AUDIT) writes the user's registry profile. Run
  AutoCAD tasks one at a time.
- pytest's default temp dir is blocked on this machine. Run
  `python -m pytest -p no:cacheprovider --basetemp=<a directory of your own>`.

## Finishing a task

1. Run the tests in the worktree. They must pass.
2. Stage only the files you changed, by path (`git add -- src/agentcad/plot.py tests/test_k_pdf.py`).
   Never `git add .`, `git add -A` or a whole directory: in a shared checkout that commits another
   agent's unfinished work.
3. Commit, push the branch (`git push -u origin <branch>`) and open a pull request against `main`
   (`gh pr create`). Do not push to `main` and do not merge your own PR; the user merges.
4. After the merge: `scripts\new-worktree.ps1 <task-name> -Remove`.
