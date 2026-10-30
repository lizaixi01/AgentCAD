import os
import subprocess
import sys
import time

import pytest

from agentcad.errors import AgentCADError
from agentcad.locking import drawing_lock


def test_old_but_live_process_lock_cannot_be_stolen_and_crash_releases_it(rt, ws, blank):
    _, store = rt._drawing(blank)
    code = """import sys
from pathlib import Path
from agentcad.locking import drawing_lock
with drawing_lock(Path(sys.argv[1])):
    print('locked', flush=True)
    sys.stdin.read()
"""
    child = subprocess.Popen([sys.executable, "-c", code, str(store.dir)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "locked"
        old = time.time() - 3600
        os.utime(store.dir / "write.lock", (old, old))
        before = (ws / blank).read_bytes()
        result = rt.apply_operations(blank, [{"op": "add_line", "start": [0, 0], "end": [10, 0]}])
        assert result["error"]["code"] == "DRAWING_LOCKED"
        assert (ws / blank).read_bytes() == before
        child.kill()
        child.wait(timeout=10)
        # No timestamp, PID polling or manual deletion is needed after a crash.
        # On Windows Popen can name the venv launcher; its actual Python child
        # briefly outlives kill+wait. The lock must remain held until that writer exits.
        deadline = time.monotonic() + 5
        while True:
            result = rt.apply_operations(blank, [{"op": "add_line", "start": [0, 0], "end": [10, 0]}])
            if result['ok'] or result['error']['code'] != 'DRAWING_LOCKED' or time.monotonic() >= deadline:
                break
            time.sleep(.02)
        assert result["ok"], result
    finally:
        if child.poll() is None:
            child.kill()
        child.communicate(timeout=10)


def test_two_runtime_handles_cannot_overlap_even_in_one_process(tmp_path):
    with drawing_lock(tmp_path):
        with pytest.raises(AgentCADError) as error:
            with drawing_lock(tmp_path):
                pytest.fail("overlapping writer")
        assert error.value.code == "DRAWING_LOCKED"
    with drawing_lock(tmp_path):
        pass


def test_legacy_marker_is_not_stolen_on_age_alone(tmp_path):
    marker = tmp_path / "lock"
    marker.write_text("old runtime")
    os.utime(marker, (0, 0))
    with pytest.raises(AgentCADError):
        with drawing_lock(tmp_path):
            pytest.fail("legacy writer was bypassed")
    assert marker.read_text() == "old runtime"


def test_recover_preserves_legacy_markers_even_when_the_recorded_process_exited(rt, ws, blank):
    _, store = rt._drawing(blank)
    marker = store.dir / "lock"  # older runtimes wrote their PID into it
    line = [{"op": "add_line", "start": [0, 0], "end": [10, 0]}]
    gone = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    before = (ws / blank).read_bytes()
    for content in ("old runtime", str(os.getpid()), gone.stdout.strip()):
        marker.write_text(content)
        assert "manually deleting" in rt.apply_operations(blank, line)["error"]["hint"]
        assert rt.recover(blank)["error"]["code"] == "DRAWING_LOCKED"
        assert marker.read_text() == content
        assert (ws / blank).read_bytes() == before
    marker.unlink()  # explicit offline migration, never performed by recover
    recovered = rt.recover(blank)
    assert recovered['ok'] and not recovered['recovered']
    assert not marker.exists()
    assert rt.apply_operations(blank, line)["ok"]


def test_recover_does_not_read_or_unlink_legacy_markers(rt, blank, monkeypatch):
    from pathlib import Path
    _, store = rt._drawing(blank)
    marker = store.dir / "lock"
    marker.write_text("12345")

    original_read, original_unlink = Path.read_text, Path.unlink
    def guarded_read(path, *args, **kwargs):
        assert path != marker, 'PID reads cannot establish ownership'
        return original_read(path, *args, **kwargs)
    def guarded_unlink(path, *args, **kwargs):
        assert path != marker, 'legacy marker must remain untouched'
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', guarded_read)
    monkeypatch.setattr(Path, 'unlink', guarded_unlink)
    assert rt.recover(blank)["error"]["code"] == "DRAWING_LOCKED"
    assert original_read(marker) == '12345'
