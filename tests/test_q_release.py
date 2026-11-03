"""Test Q (release): scripts/release.py builds what the installers download from the latest GitHub release."""
from __future__ import annotations

import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", ROOT / "scripts" / "release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_build_makes_the_package_and_both_installers(tmp_path: Path):
    files = {f.name: f for f in release.build("HEAD", tmp_path)}
    assert set(files) == {"agentcad.zip", "AgentCAD-Setup.cmd", "AgentCAD-Setup-mac.zip"}

    # the package: what uv builds AgentCAD from, one top folder, no examples/ or research/ (the whole repo is 100+ MB)
    names = zipfile.ZipFile(files["agentcad.zip"]).namelist()
    assert {"agentcad/pyproject.toml", "agentcad/README.md", "agentcad/src/agentcad/cli.py"} <= set(names)
    assert all(n.startswith("agentcad/") for n in names)
    assert not any(n.startswith(("agentcad/examples/", "agentcad/research/")) for n in names)
    assert files["agentcad.zip"].stat().st_size < 10_000_000

    # cmd.exe misreads labels and goto in a .cmd with LF line endings
    cmd = files["AgentCAD-Setup.cmd"].read_bytes()
    assert b"\r\n" in cmd and b"\n" not in cmd.replace(b"\r\n", b"")

    # the mac installer: executable inside the zip, so it still runs after Finder unpacks it
    info = zipfile.ZipFile(files["AgentCAD-Setup-mac.zip"]).getinfo("AgentCAD-Setup.command")
    assert info.external_attr >> 16 & 0o111


@pytest.mark.parametrize("statuses, allow_pending, ok", [
    ({"agentcad/main-health": "success", "agentcad/macos": "success"}, False, True),
    ({"agentcad/main-health": "success", "agentcad/macos": "pending"}, False, False),
    ({"agentcad/main-health": "success", "agentcad/macos": "pending"}, True, True),   # macOS had no runner
    ({"agentcad/main-health": "success"}, True, True),
    ({"agentcad/main-health": "success", "agentcad/macos": "failure"}, True, False),
    ({}, True, False),  # main's run has not finished: Linux / Windows may still fail
    ({"agentcad/main-health": "pending", "agentcad/macos": "pending"}, True, False),
    ({"agentcad/main-health": "failure", "agentcad/macos": "success"}, True, False),
])
def test_ci_gate(statuses, allow_pending, ok):
    assert (release.ci_problem(statuses, allow_pending) is None) == ok


class Done:
    def __init__(self, returncode=0, stdout=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, "boom"


def fake_git(monkeypatch, *, in_main=True, statuses=None, exists=False):
    """release.run with git and gh answered here; returns the commands that would publish."""
    published = []

    def run(*cmd, check=True):
        if cmd[:2] == ("git", "rev-parse"):
            return Done(stdout="a" * 40)
        if cmd[:2] == ("git", "merge-base"):
            return Done(0 if in_main else 1)
        if cmd[:2] == ("gh", "api"):
            return Done(stdout=json.dumps({"statuses": [{"context": k, "state": v}
                                                        for k, v in (statuses or {}).items()]}))
        if cmd[:3] == ("gh", "release", "view"):
            return Done(0 if exists else 1)
        if cmd[:3] == ("gh", "release", "create"):
            published.append(cmd)
            return Done(stdout="https://github.com/x/releases/tag/v9")
        return Done()

    monkeypatch.setattr(release, "run", run)
    monkeypatch.setattr(release, "build", lambda sha, out: [])
    return published


GREEN = {"agentcad/main-health": "success", "agentcad/macos": "success"}


@pytest.mark.parametrize("kwargs, message", [
    ({"in_main": False, "statuses": GREEN}, "not in origin/main"),
    ({"statuses": {}}, "not reported yet"),
    ({"statuses": {**GREEN, "agentcad/macos": "failure"}}, "macOS CI on main failed"),
    ({"statuses": GREEN, "exists": True}, "exists already"),
])
def test_release_refuses(monkeypatch, tmp_path, kwargs, message):
    published = fake_git(monkeypatch, **kwargs)
    monkeypatch.setattr(sys, "argv", ["release.py", "v9", "--allow-pending", "--out", str(tmp_path)])
    with pytest.raises(SystemExit) as e:
        release.main()
    assert message in str(e.value) and not published


def test_release_publishes_a_green_commit_as_latest(monkeypatch, tmp_path):
    published = fake_git(monkeypatch, statuses=GREEN)
    monkeypatch.setattr(sys, "argv", ["release.py", "v9", "--out", str(tmp_path)])
    release.main()
    (cmd,) = published
    assert cmd[3] == "v9" and "--latest" in cmd and cmd[cmd.index("--target") + 1] == "a" * 40


def test_installers_fetch_the_latest_release_not_main():
    url = "https://github.com/lizaixi01/AgentCAD/releases/latest/download/agentcad.zip"
    for name in ("AgentCAD-Setup.cmd", "AgentCAD-Setup.command"):
        text = (ROOT / "installer" / name).read_text("utf-8")
        assert url in text
        assert not re.search(r"archive/refs/heads", text)
