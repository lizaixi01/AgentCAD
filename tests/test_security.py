"""Execution safety: sandboxed paths, overwrite protection, read-only, op allow-list, budgets, locking."""
from __future__ import annotations

from agentcad.policy import Policy
from agentcad.service import Runtime
from conftest import ok


def test_path_traversal_and_absolute_paths_refused(rt, ws):
    for p in ("../x.dxf", "..\\..\\x.dxf", "C:/Windows/x.dxf", "/etc/x.dxf", "sub/../../x.dxf"):
        r = rt.create_drawing(p)
        assert not r["ok"] and r["error"]["code"] == "PATH_OUTSIDE_WORKSPACE", (p, r)
    assert rt.create_drawing(".agentcad/x.dxf")["error"]["code"] == "PATH_RESERVED"
    assert rt.create_drawing("notes.txt")["error"]["code"] == "BAD_EXTENSION"
    assert rt.extract_requirements("../secret.txt")["error"]["code"] == "PATH_OUTSIDE_WORKSPACE"


def test_overwrite_protection(rt, ws, blank):
    before = (ws / blank).read_bytes()
    r = rt.create_drawing(blank)
    assert r["error"]["code"] == "FILE_EXISTS" and (ws / blank).read_bytes() == before
    ok(rt.create_drawing(blank, overwrite=True))
    assert ok(rt.list_checkpoints(blank))["checkpoints"]  # the replaced file was checkpointed
    assert rt.export_drawing(blank, blank)["error"]["code"] in ("SAME_FILE", "FILE_EXISTS")


def test_read_only_mode(ws):
    Runtime(Policy(root=ws)).create_drawing("a.dxf")
    ro = Runtime(Policy(root=ws, read_only=True))
    assert ok(ro.read_drawing("a.dxf"))
    assert ok(ro.validate_drawing("a.dxf"))
    for r in (ro.apply_operations("a.dxf", [{"op": "add_point", "location": [0, 0]}]),
              ro.create_drawing("b.dxf"), ro.rollback("a.dxf"), ro.export_drawing("a.dxf", "c.dxf")):
        assert r["error"]["code"] == "READ_ONLY" and r["error"]["category"] == "policy"
    assert ok(ro.apply_operations("a.dxf", [{"op": "add_point", "location": [0, 0]}], dry_run=True))["dry_run"]


def test_allowed_operation_scope(ws):
    rt = Runtime(Policy(root=ws, allowed_ops=frozenset({"add_line"})))
    ok(rt.create_drawing("a.dxf"))
    ok(rt.apply_operations("a.dxf", [{"op": "add_line", "start": [0, 0], "end": [1, 1]}]))
    e = rt.apply_operations("a.dxf", [{"op": "add_line", "start": [0, 0], "end": [2, 2]},
                                      {"op": "delete", "target": {"all": True}}])["error"]
    assert e["code"] == "OP_NOT_ALLOWED" and e["op_index"] == 1
    assert len(ok(rt.read_drawing("a.dxf"))["tags"]) == 0 and ok(rt.read_drawing("a.dxf"))["entity_count"] == 1


def test_budgets(ws):
    rt = Runtime(Policy(root=ws, max_ops_per_batch=5, max_entities=10))
    ok(rt.create_drawing("a.dxf"))
    e = rt.apply_operations("a.dxf", [{"op": "add_point", "location": [i, 0]} for i in range(6)])["error"]
    assert e["code"] == "BUDGET_EXCEEDED"
    ok(rt.apply_operations("a.dxf", [{"op": "add_point", "location": [i, 0]} for i in range(5)]))
    e = rt.apply_operations("a.dxf", [{"op": "add_point", "location": [0, 1]},
                                      {"op": "array_rect", "target": "$0", "rows": 1, "cols": 10, "col_spacing": 1}])["error"]
    assert e["code"] == "BUDGET_EXCEEDED"
    assert ok(rt.read_drawing("a.dxf"))["entity_count"] == 5


def test_concurrent_writer_lock(rt, ws, blank):
    from agentcad.store import DrawingStore
    store = DrawingStore(rt.policy, (ws / blank).resolve())
    (store.dir / "lock").write_text("other")
    e = rt.apply_operations(blank, [{"op": "add_point", "location": [0, 0]}])["error"]
    assert e["code"] == "DRAWING_LOCKED" and e["retryable"] is True
    (store.dir / "lock").unlink()
    ok(rt.apply_operations(blank, [{"op": "add_point", "location": [0, 0]}]))


def test_no_shell_or_arbitrary_execution_surface():
    """Operations are a closed registry; nothing maps agent input to system commands. The one exception is the
    opt-in run_script tool: off by default, statically checked, run in a separate process without a shell."""
    from agentcad.ops import REGISTRY
    import agentcad
    from pathlib import Path
    pkg = Path(agentcad.__file__).parent
    launchers = {pkg / "backends" / "autocad.py", pkg / "backends" / "freecad.py", pkg / "scripting.py",
                 pkg / "install.py"}
    for f in pkg.rglob("*.py"):
        text = f.read_text("utf-8")
        assert "os.system" not in text and "eval(" not in text, f
        if f != pkg / "_script_runner.py":
            assert "exec(" not in text, f
        if f not in launchers:
            assert "subprocess" not in text, f
    # process launchers: fixed executables, no shell
    backend = (pkg / "backends" / "autocad.py").read_text("utf-8")
    assert "shell=False" in backend and "shell=True" not in backend and "Popen(args" in backend
    fc = (pkg / "backends" / "freecad.py").read_text("utf-8")
    assert "shell=False" in fc and "shell=True" not in fc and "timeout=TIMEOUT" in fc
    scripting = (pkg / "scripting.py").read_text("utf-8")
    assert "shell=False" in scripting and "shell=True" not in scripting and "timeout=timeout" in scripting
    # install.py runs only the user's own 'claude mcp' CLI, from 'agentcad setup'; no tool reaches it
    inst = (pkg / "install.py").read_text("utf-8")
    assert "shell=False" in inst and "shell=True" not in inst
    for f in ("service.py", "mcp_server.py", "http_api.py"):
        assert "install import" not in (pkg / f).read_text("utf-8").replace("install import ensure_workspace", ""), f
    assert "check_script(code)" in (pkg / "service.py").read_text("utf-8")
    assert Policy(root=Path.cwd()).allow_scripts in (False,) or __import__("os").environ.get("AGENTCAD_ALLOW_SCRIPTS")
    assert all(callable(d.fn) for d in REGISTRY.values())
