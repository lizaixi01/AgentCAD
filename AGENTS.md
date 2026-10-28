# Working on AgentCAD

Several agents (Claude Code, Codex) often work on this repo at the same time. These rules keep their
changes apart.

## One task, one worktree

Never edit in the main checkout (`D:\Projects\AgentCAD`) while another agent may be working there. Do
each task in its own worktree on its own branch:

- A Claude Code desktop session started with a worktree already has one (`.claude/worktrees/`). Run
  `scripts\new-worktree.ps1 -Here` in it once to set up the two items below.
- Otherwise: `scripts\new-worktree.ps1 <task-name>` creates `..\AgentCAD-wt\<task-name>` on branch
  `agent/<task-name>` from a freshly fetched `origin/main` (the local `main` may lag behind).

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
   (`gh pr create`). Never push to `main` directly.
4. Get the PR reviewed and merged as below.
5. After the merge: `scripts\new-worktree.ps1 <task-name> -Remove` (it refuses while the branch is not
   in `origin/main`). Update the main checkout with
   `git pull --ff-only` only when its working tree is clean (another agent may be using it).

## Review and merge

The user has handed review and merge to AI. A PR is merged when all of these hold:

1. **Independent review.** A reviewer that did not write the change reads the diff: a fresh subagent
   or session given only the PR (not the author's reasoning), `/code-review`, or `codex review`. It
   checks correctness, that tests cover the change, and that the diff holds only files the task meant
   to change. It posts its verdict on the PR (`gh pr comment`; GitHub does not let the author's
   account approve its own PR).
2. **Tests pass** on the PR branch, brought up to date with `main`, in a worktree.
3. **GitHub reports the PR mergeable.**

Then the agent that opened the PR, or the session that started that agent, merges with
`gh pr merge <n> --merge --delete-branch`. Merge commits keep the branch's commit SHAs, so checkouts
that already have them fast-forward. If the review finds problems, the author
fixes them on the same branch and the PR is reviewed again.

Ask the user before merging a PR that:

- removes or rewrites recorded trial results or measurements that the README or docs cite;
- adds Autodesk sample drawings or files derived from them (not ours to redistribute; see `.gitignore`);
- touches the license, credentials, GitHub settings or CI;
- needs a force push or a history rewrite.
