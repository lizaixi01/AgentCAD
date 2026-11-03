"""Publish a release: what the double-click installers, and the desktop icon's daily update, install.
    python scripts/release.py v0.2.0                # origin/main, once its CI on main has passed
    python scripts/release.py v0.2.0 --dry-run      # build the files only, publish nothing
The installers fetch releases/latest/download/agentcad.zip, so a merge to main reaches nobody until a release.
Roll back: gh release edit <an older tag> --latest (one made by this script: it carries agentcad.zip). The next
daily update, or the next run of the installer, then installs that release again.

Each release carries agentcad.zip (pyproject.toml, README.md and src/ under agentcad/, about 2 MB instead of the
whole repository) and the two installers, which the README links as releases/latest/download/<name>.
"""
from __future__ import annotations

import argparse
import io
import json
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

REPO = "lizaixi01/AgentCAD"
PACKAGE = ["pyproject.toml", "README.md", "src"]
NOTES = """Install: download **AgentCAD-Setup.cmd** (Windows) or **AgentCAD-Setup-mac.zip** (macOS / Linux, unpack it, then \
open AgentCAD-Setup.command) and double-click it. The files are not code-signed yet: on Windows click **More info**, \
then **Run anyway**; on macOS right-click the file and choose **Open**. Details: \
[docs/install.md](https://github.com/lizaixi01/AgentCAD/blob/main/docs/install.md).

Code: {sha}."""


def run(*cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", check=check)


def fail(message: str) -> None:
    sys.exit(f"release: {message}")


def ci_state(sha: str) -> str:
    """The combined status the 'main health' job posts on a main commit: success, pending or failure."""
    res = run("gh", "api", f"repos/{REPO}/commits/{sha}/status", "--jq", ".state", check=False)
    if res.returncode:
        fail(f"cannot read CI status of {sha[:7]}: {res.stderr.strip()}")
    return res.stdout.strip()


def build(sha: str, out: Path) -> list[Path]:
    """agentcad.zip, AgentCAD-Setup.cmd and AgentCAD-Setup-mac.zip from commit sha. git archive applies the
    .gitattributes line endings (CRLF for .cmd, LF for .command)."""
    package = out / "agentcad.zip"
    run("git", "archive", "--format=zip", "--prefix=agentcad/", "-o", str(package), sha, "--", *PACKAGE)
    raw = subprocess.run(["git", "archive", "--format=tar", sha, "installer"], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
        cmd = tar.extractfile("installer/AgentCAD-Setup.cmd").read()
        command = tar.extractfile("installer/AgentCAD-Setup.command").read()
    windows = out / "AgentCAD-Setup.cmd"
    windows.write_bytes(cmd)
    mac = out / "AgentCAD-Setup-mac.zip"
    with zipfile.ZipFile(mac, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("AgentCAD-Setup.command", date_time=(2026, 1, 1, 0, 0, 0))
        info.external_attr = 0o100755 << 16  # a regular file, executable: macOS opens it with a double-click
        info.create_system = 3  # unix, so unzip and Finder read the mode
        z.writestr(info, command, zipfile.ZIP_DEFLATED)
    return [package, windows, mac]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tag", help="the new release's tag, e.g. v0.2.0")
    ap.add_argument("--ref", default="origin/main", help="commit to release (default origin/main); must be in main")
    ap.add_argument("--allow-pending", action="store_true",
                    help="release while main's CI is still pending (macOS without a runner); never after a failure")
    ap.add_argument("--dry-run", action="store_true", help="build the files and print where; publish nothing")
    ap.add_argument("--out", type=Path, help="folder for the built files (default: a temporary one)")
    args = ap.parse_args()

    run("git", "fetch", "--quiet", "origin", "main")
    sha = run("git", "rev-parse", "--verify", f"{args.ref}^{{commit}}").stdout.strip()
    if run("git", "merge-base", "--is-ancestor", sha, "origin/main", check=False).returncode:
        fail(f"{args.ref} ({sha[:7]}) is not in origin/main: release only what has been merged")
    state = ci_state(sha)
    if state == "failure" or (state != "success" and not args.allow_pending):
        fail(f"CI on {sha[:7]} is '{state}', not 'success'. Wait for it"
             + ("" if state == "failure" else ", or pass --allow-pending (macOS without a runner)"))
    if not args.dry_run and run("gh", "release", "view", args.tag, "--repo", REPO, check=False).returncode == 0:
        fail(f"release {args.tag} exists already")

    out = args.out or Path(tempfile.mkdtemp(prefix="agentcad-release-"))
    out.mkdir(parents=True, exist_ok=True)
    files = build(sha, out)
    sizes = {f.name: f.stat().st_size for f in files}
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "sha": sha, "folder": str(out), "files": sizes}, indent=2))
        return
    res = run("gh", "release", "create", args.tag, "--repo", REPO, "--target", sha, "--latest",
              "--title", f"AgentCAD {args.tag}", "--notes", NOTES.format(sha=sha), "--generate-notes",
              *map(str, files), check=False)
    if res.returncode:
        fail(res.stderr.strip())
    print(json.dumps({"ok": True, "tag": args.tag, "sha": sha, "url": res.stdout.strip(), "files": sizes,
                      "roll_back": "gh release edit <an older tag made by this script> --latest"}, indent=2))


if __name__ == "__main__":
    main()
