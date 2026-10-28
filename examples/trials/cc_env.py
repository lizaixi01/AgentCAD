"""Run a trial script with the Claude desktop app's session variables removed.

Inside a Claude desktop session, CLAUDE_* / ANTHROPIC_* variables tell a child `claude` to use the app's host
auth, which a standalone headless run does not have; without them it uses its own `claude auth login`.

    python examples/trials/cc_env.py examples/trials/hard/run_hard.py --agent claude ...
"""
from __future__ import annotations

import os
import subprocess
import sys

env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "ANTHROPIC"))}
env["PYTHONIOENCODING"] = "utf-8"
sys.exit(subprocess.run([sys.executable, *sys.argv[1:]], env=env, shell=False).returncode)
