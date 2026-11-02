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
  `python -m pytest -p no:cacheprovider --basetemp=<a directory of your own>`. Keep that path short
  (e.g. `D:\tmp\<task>`): deep test paths go past Windows' 260-character limit and fail.

## Finishing a task

1. Run the tests that cover what you changed (`python -m pytest ... tests/test_k_pdf.py`). They must
   pass. The full suite (about 13 minutes here) runs in CI on every PR; run it locally only when the
   change reaches across many modules.
2. Stage only the files you changed, by path (`git add -- src/agentcad/plot.py tests/test_k_pdf.py`).
   Never `git add .`, `git add -A` or a whole directory: in a shared checkout that commits another
   agent's unfinished work.
3. Commit, push the branch (`git push -u origin <branch>`) and open a pull request against `main`
   (`gh pr create`). Never push to `main` directly.
4. Merge it as below.
5. After the merge: `scripts\new-worktree.ps1 <task-name> -Remove` removes the worktree and the local
   and remote branch (it refuses while the branch is not in `origin/main`). Update the main checkout with
   `git pull --ff-only` only when its working tree is clean (another agent may be using it).

## Review and merge

The user has handed review and merge to AI. The tests are the gate; review is added where it pays.
A PR is merged when all of these hold:

1. **CI passes on the PR.** GitHub tests the PR merged with the current `main`, so there is no need to
   merge `main` into the branch first. Do that only when GitHub reports a conflict.
2. **GitHub reports the PR mergeable.**
3. **Independent review, when the change needs one.**
   - Needed: more than about 50 changed lines under `src/`; code that guards the user's machine
     (`run_script` checks, file access, the viewer server, the installer); how drawings are written
     to disk (DXF, DWG); anything on the ask-the-user list below.
   - Not needed: docs, tests, write-ups of results, and small fixes (about 50 lines or fewer under
     `src/`) that come with a test.

   A reviewer that did not write the change reads the diff: a fresh subagent or session given only
   the PR (not the author's reasoning), `/code-review`, or `codex review`. It reports correctness
   bugs, missing tests for the change, and files the task did not mean to change; it skips style and
   nits. It does not rerun the full suite (CI did). It posts its verdict on the PR (`gh pr comment`;
   GitHub does not let the author's account approve its own PR). If it finds problems, the author
   fixes them on the same branch and the reviewer checks only the fix commit.

Then the agent that opened the PR, or the session that started that agent, merges with
`gh pr merge <n> --merge`, then cleans up with `-Remove`. Merge commits keep the branch's commit SHAs,
so checkouts that already have them fast-forward. (Not `--delete-branch`: it tries to delete the local
branch, which the task's worktree still has checked out.)

Pull requests run CI on Linux (Python 3.12) and Windows. Every push to `main` runs the full matrix
(adding Linux 3.10 and macOS). If that breaks `main`, fixing it comes before other merges.

Ask the user before merging a PR that:

- removes or rewrites recorded trial results or measurements that the README or docs cite;
- adds Autodesk sample drawings or files derived from them (not ours to redistribute; see `.gitignore`);
- touches the license, credentials, GitHub settings or CI;
- needs a force push or a history rewrite.
