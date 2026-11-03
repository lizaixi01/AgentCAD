"""Test Q (release): scripts/release.py builds what the installers download from the latest GitHub release."""
from __future__ import annotations

import importlib.util
import re
import zipfile
from pathlib import Path

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


def test_installers_fetch_the_latest_release_not_main():
    url = "https://github.com/lizaixi01/AgentCAD/releases/latest/download/agentcad.zip"
    for name in ("AgentCAD-Setup.cmd", "AgentCAD-Setup.command"):
        text = (ROOT / "installer" / name).read_text("utf-8")
        assert url in text
        assert not re.search(r"archive/refs/heads", text)
