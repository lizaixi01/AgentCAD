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
        result = rt.apply_operations(blank, [{"op": "add_line", "start": [0, 0], "end": [10, 0]}])
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
