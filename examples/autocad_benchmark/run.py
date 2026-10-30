"""Run the pinned U-C4N v8 matrix through AgentCAD's public MCP interface.

No AgentCAD modules are imported by the adapter. The upstream task definitions,
result contract, runner and scoring are reused; rival code performs no credited
AgentCAD work.
Fixture creation and independent file readback belong to the evaluator; all CAD
work being credited belongs to the real server. Partial gates receive zero.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

import ezdxf
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pypdf import PdfReader

PIN = "58a05ddfc34a9832c626e82cd88ecdce8e16a62a"
REPO = Path(__file__).resolve().parents[2]


def git(path: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def strict_result(task_id, passed, metrics=None, message="", *, partial=False):
    from benchmarks.adapters.base import TaskResult
    return TaskResult(task_id, "pass" if passed else ("partial" if partial else "fail"),
                      100.0 if passed else 0.0, message=message, metrics=metrics or {})


def grade_roundtrip(before, after, reopened, *, parity_unchanged, bores_moved):
    """Require every original measurement, including independently expected values."""
    for report, distance, failed in [(before, math.hypot(45, 25), []),
                                     (after, math.hypot(48, 25), ["R3"]),
                                     (reopened, math.hypot(48, 25), ["R3"])]:
        rows = {r["id"]: r for r in report["constraints"]}
        if set(rows) != {"R1", "R2", "R3"} or report["failed"] != failed:
            return False
        if any(abs(rows[key]["actual"] - value) > 1e-6
               for key, value in {"R1": 20, "R2": 90, "R3": distance}.items()):
            return False
        count = report["count"]
        if len(count) != 1 or count[0]["id"] != "R4" or count[0]["status"] != "pass" or count[0]["actual"] != 4:
            return False
    return parity_unchanged and bores_moved == 1


class AgentCADAdapter:
    name = "agentcad"

    def __init__(self, python: Path):
        self.python = python
        info = subprocess.check_output([str(python), "-I", "-c",
            "import agentcad,json,sys,importlib.metadata as m; "
            "print(json.dumps({'module':agentcad.__file__,'python':sys.version,"
            "'dependencies':{k:m.version(k) for k in ['mcp','ezdxf','pypdf']}}))"], text=True)
        self.server_environment = json.loads(info)
        expected = REPO / "src" / "agentcad" / "__init__.py"
        if Path(self.server_environment["module"]).resolve() != expected.resolve():
            raise RuntimeError("--python must have this worktree installed editable (see scripts/new-worktree.ps1)")
        self.product_sha = git(REPO, "rev-parse", "HEAD")
        self.product_dirty = bool(git(REPO, "status", "--porcelain", "--untracked-files=no"))
        self.source_hashes = {str(p.relative_to(REPO)).replace("\\", "/"): digest(p)
                              for p in sorted((REPO / "src" / "agentcad").rglob("*.py"))}
        self.session = None
        self.current_task = "setup"
        self.calls = 0
        self.completed = []

    def log(self, kind: str, **data):
        with (self.artifact_dir / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": kind, "task": self.current_task,
                                     "time": time.time(), **data}, ensure_ascii=False) + "\n")

    @asynccontextmanager
    async def connect(self):
        env = {**os.environ, "AGENTCAD_ROOT": str(self.workspace), "AGENTCAD_VIEWER": "0",
               "AGENTCAD_LIVE_SYNC": "0", "AGENTCAD_ALLOW_SCRIPTS": "0",
               "AGENTCAD_READ_ONLY": "0", "AGENTCAD_ALLOWED_OPS": "",
               "AGENTCAD_MAX_ENTITIES": "200000", "AGENTCAD_MAX_OPS": "5000",
               "PYTHONUTF8": "1"}
        params = StdioServerParameters(command=str(self.python), args=["-I", "-m", "agentcad.mcp_server"],
                                       cwd=str(REPO), env=env)
        with (self.artifact_dir / "server.stderr.log").open("a", encoding="utf-8") as stderr:
            async with stdio_client(params, errlog=stderr) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    yield session

    async def setup(self, artifact_dir):
        self.artifact_dir = artifact_dir
        self.workspace = artifact_dir / "workspace"
        self.workspace.mkdir()
        async with self.connect() as self.session:
            response = await self.session.list_tools()
            self.tools = {tool.name: tool.model_dump(by_alias=True, mode="json", exclude_none=True)
                          for tool in response.tools}
            write_json(artifact_dir / "tools.json", {"tools": list(self.tools.values())})
            self.catalog = await self.call("list_operations", detail=True)
            self.compact = await self.call("list_operations")
            self.library = await self.call("standard_library")
        self.session = None

    async def cleanup(self):
        self.current_task = "finished"

    def metadata(self):
        return {"backend": "ezdxf", "interface": "MCP stdio (official SDK)",
                "python": str(self.python), "product_sha": self.product_sha,
                "product_dirty": self.product_dirty, "source_sha256": self.source_hashes,
                "scripts_enabled": False, "live_autocad": False,
                "server_environment": self.server_environment,
                "partial_score_policy": "0; only every original gate earns 100",
                "server_lifecycle": "fresh MCP process per task; extra fresh reader where required",
                "mcp_calls": self.calls}

    async def call(self, name, *, allow_error=False, **arguments):
        self.calls += 1
        response = await self.session.call_tool(name, arguments)
        data = response.structuredContent
        if data is None:
            texts = [c.text for c in response.content if c.type == "text"]
            try:
                data = json.loads("\n".join(texts))
            except ValueError:
                data = {"ok": False, "protocol_error": "\n".join(texts)}
        self.log("call", seq=self.calls, tool=name, arguments=arguments, response=data,
                 is_error=response.isError)
        if (response.isError or data.get("ok") is False) and not allow_error:
            raise RuntimeError(f"{name}: {data}")
        return data

    async def apply(self, operations, **kwargs):
        return await self.call("apply_operations", path=self.path, operations=operations, **kwargs)

    async def inspect(self, **kwargs):
        return await self.call("inspect_entities", path=self.path, **kwargs)

    async def validate(self, path=None, **kwargs):
        return (await self.call("validate_drawing", path=path or self.path, detail=True, **kwargs))["validation"]

    def read(self, path=None):
        return ezdxf.readfile(self.workspace / (path or self.path))

    async def run_task(self, task):
        from benchmarks.adapters.base import TaskResult
        self.current_task = task.task_id
        self.path = task.task_id + ".dxf"
        self.log("task_start")
        print(f"START {task.task_id}", flush=True)
        handler = getattr(self, "task_" + task.task_id, None)
        if handler is None:
            result = TaskResult(task.task_id, "unsupported", 0, GAP_REASONS[task.task_id],
                                metrics={"evidence": "setup tools.json; full operations and library in events.jsonl",
                                         "probe": "documented public catalog capability assessment; no CAD execution"})
        else:
            async with self.connect() as self.session:
                if task.task_id not in {"token_budget", "tool_discovery", "cancel_safety"}:
                    await self.call("create_drawing", path=self.path, units="mm")
                result = await handler()
            self.session = None
        self.completed.append(result.to_dict())
        write_json(self.artifact_dir / "progress.json", self.completed)
        self.log("task_end", result=result.to_dict())
        print(f"END {task.task_id}: {result.status} ({result.score})", flush=True)
        # Keep actual files, protocol catalog and full transcript hashable in the report.
        files = [self.workspace / self.path]
        result.artifacts.extend(str(p) for p in files if p.is_file())
        return result

    async def task_core_geometry(self):
        await self.apply([{"op": "add_line", "start": [0, 0], "end": [3, 4], "tag": "line"},
                          {"op": "add_circle", "center": [10, 10], "radius": 2}])
        line = (await self.inspect(ids=["tag:line"]))["entities"][0]
        msp = self.read().modelspace()
        saved_lines = list(msp.query("LINE"))
        circles = list(msp.query("CIRCLE"))
        passed = (line["length"] == 5 and len(saved_lines) == len(circles) == 1
                  and abs((saved_lines[0].dxf.end - saved_lines[0].dxf.start).magnitude - 5) < 1e-6
                  and circles[0].dxf.radius == 2 and tuple(circles[0].dxf.center)[:2] == (10, 10))
        return strict_result("core_geometry", passed, {"line_length": line["length"]})

    async def task_modify_query(self):
        await self.apply([{"op": "add_line", "start": [0, 0], "end": [10, 0], "tag": "line"}])
        await self.apply([{"op": "move", "target": "tag:line", "delta": [5, 2]}])
        line = (await self.inspect(ids=["tag:line"]))["entities"][0]
        saved = self.read().modelspace().query("LINE")[0]
        return strict_result("modify_query", line["start"][:2] == [5, 2] and tuple(saved.dxf.start)[:2] == (5, 2),
                             {"start": line["start"]})

    async def task_layers_linetypes(self):
        await self.apply([{"op": "create_layer", "name": "GEOMETRY"},
                          {"op": "create_layer", "name": "CENTERLINE", "linetype": "CENTER"}])
        doc = self.read()
        return strict_result("layers_linetypes", "GEOMETRY" in doc.layers and "CENTER" in doc.linetypes,
                             {"center_linetype": doc.layers.get("CENTERLINE").dxf.linetype})

    async def task_dimensions(self):
        await self.apply([{"op": "add_linear_dim", "p1": [0, 0], "p2": [50, 0], "base": [25, 10], "layer": "DIM"}])
        dims = self.read().modelspace().query("DIMENSION")
        return strict_result("dimensions", len(dims) == 1 and bool(dims[0].dxf.geometry)
                             and abs(dims[0].get_measurement() - 50) < 1e-6,
                             {"entity_type": dims[0].dxftype(), "render_block": dims[0].dxf.geometry})

    async def task_table_mleader(self):
        await self.apply([{"op": "add_table", "insert": [0, 20], "rows": [["ITEM", "QTY"], ["A", "1"]],
                           "col_widths": [20, 20], "tag": "table"},
                          {"op": "add_leader", "points": [[0, 0], [10, 10]], "text": "NOTE"}])
        msp = self.read().modelspace()
        texts = {e.dxf.text for e in msp.query("TEXT MTEXT")}
        passed = {"ITEM", "QTY", "A", "1", "NOTE"} <= texts and len(msp.query("LEADER")) == 1
        return strict_result("table_mleader", passed,
                             {"representations": ["composite grid + TEXT", "LEADER + MTEXT"],
                              "native_table_mleader": False},
                             "The pinned reference also accepts composite representations; native TABLE/MLEADER is not claimed.")

    async def task_transactions(self):
        await self.apply([{"op": "add_circle", "center": [0, 0], "radius": 1}])
        await self.call("rollback", path=self.path)
        count = len(self.read().modelspace())
        return strict_result("transactions", count == 0, {"entity_count_after_rollback": count})

    async def task_quality_refiner(self):
        await self.apply([{"op": "add_line", "start": [0, 0], "end": [10, 0]},
                          {"op": "add_line", "start": [0, 0], "end": [10, 0]}])
        report = await self.validate()
        duplicates = [i for i in report["issues"] if i["code"] == "DUPLICATE_ENTITY"]
        return strict_result("quality_refiner", False, {"duplicate_findings": duplicates},
                             "Duplicate detection exists; no public automatic quality-scoring/refiner loop.", partial=True)

    async def task_dxf_roundtrip(self):
        await self.apply([{"op": "add_line", "start": [0, 0], "end": [10, 10]}])
        output = "roundtrip-export.dxf"
        await self.call("export_drawing", path=self.path, output=output, format="dxf")
        async with self.connect() as fresh:
            response = await fresh.call_tool("read_drawing", {"path": output})
            data = response.structuredContent or json.loads(response.content[0].text)
            self.log("fresh_read", response=data)
        count = len(self.read(output).modelspace())
        return strict_result("dxf_roundtrip", data.get("ok") and count == 1,
                             {"entity_count": count, "fresh_process": True})

    async def task_auditable_delivery(self):
        applied = await self.apply([{"op": "add_line", "start": [0, 0], "end": [10, 0]}])
        await self.call("export_drawing", path=self.path, output="delivery.dxf", format="dxf")
        report = await self.validate("delivery.dxf")
        return strict_result("auditable_delivery", False,
                             {"committed_sha256": applied.get("sha256"), "export_readable": report.get("readable")},
                             "Commit hashes and independent validation exist; no native hashed delivery manifest.", partial=True)

    async def task_tool_discovery(self):
        from benchmarks.adapters.base import TaskResult
        schema = self.tools["list_operations"]["inputSchema"]["properties"]
        return TaskResult("tool_discovery", "unsupported", 0,
                          "Operation index/name/category lookup exists; no command-name search or ranked top-3 results.",
                          metrics={"discovery_parameters": sorted(schema),
                                   "queries": ["FILLET", "BPOLY", "QSELECT", "WBLOCK", "OVERKILL", "CHSPACE"]})

    async def task_token_budget(self):
        wire = json.dumps({"tools": list(self.tools.values())}, ensure_ascii=False, separators=(",", ":"))
        tokens = max(1, int(round(len(wire) / 4.19)))
        return strict_result("token_budget", tokens < 2000,
                             {"discovery_tokens": tokens, "catalog_chars": len(wire), "advertised_tools": len(self.tools),
                              "ceiling": 2000, "tokenizer": "ratio/v1 (estimate)",
                              "instructions_included": False},
                             "Same upstream JSON-schema ratio estimator; no opt-in hidden-tool search mode exists.")

    async def task_hatch_islands(self):
        await self.apply([{"op": "add_hatch", "points": [[0, 0], [20, 0], [20, 20], [0, 20]],
                           "holes": [[[5, 5], [15, 5], [15, 15], [5, 15]]], "pattern": "ANSI31"}])
        inspected = (await self.inspect(filter={"type": "HATCH"}))["entities"][0]
        hatch = self.read().modelspace().query("HATCH")[0]
        return strict_result("hatch_islands", False, {"saved_paths": len(hatch.paths),
                             "inspection_fields": sorted(inspected), "hatch_style": hatch.dxf.hatch_style},
                             "Both loops persist. No public filled-area measurement or hatch-style=ignore edit, so the 300/400 gate is incomplete.", partial=True)

    async def task_selection_filter(self):
        await self.apply([{"op": "add_circle", "center": [5, 5], "radius": 1},
                          {"op": "add_circle", "center": [10, 5], "radius": 3},
                          {"op": "add_circle", "center": [18, 18], "radius": 0.5},
                          {"op": "add_circle", "center": [40, 40], "radius": 1, "layer": "TEXT"}])
        crossing = await self.inspect(window=[[0, 0], [10, 10]])
        by_layer = await self.inspect(filter={"type": "CIRCLE", "layer": "TEXT"})
        return strict_result("selection_filter", False,
                             {"crossing": crossing["total"], "by_layer": by_layer["total"],
                              "expected_window_crossing_bbox_polygon": [1, 2, 3, 1]},
                             "Crossing and property filtering work; fully-contained window and polygon selectors are absent.", partial=True)

    async def task_measure_from_handle(self):
        await self.apply([{"op": "add_line", "start": [0, 0], "end": [10, 0]},
                          {"op": "add_line", "start": [10, 0], "end": [10, 10]},
                          {"op": "add_line", "start": [0, 10], "end": [0, 0]},
                          {"op": "add_arc", "center": [5, 10], "radius": 5, "start_angle": 0, "end_angle": 180}])
        await self.apply([{"op": "join", "target": {"all": True}, "tag": "boundary"}])
        info = (await self.inspect(ids=["tag:boundary"]))["entities"][0]
        return strict_result("measure_from_handle", False, {"boundary": info, "expected_area": 100 + math.pi * 25 / 2},
                             "Join preserves the curved boundary, but inspection has no analytic area measurement by handle.", partial=True)

    async def task_page_setup_truth(self):
        await self.apply([{"op": "create_layout", "name": "BenchmarkSheet", "paper": "custom", "width": 432, "height": 279},
                          {"op": "add_line", "start": [20, 20], "end": [100, 100], "layout": "BenchmarkSheet"}])
        await self.call("export_drawing", path=self.path, output="ansi-b.pdf", format="pdf", layout="BenchmarkSheet")
        page = PdfReader(self.workspace / "ansi-b.pdf").pages[0]
        size = [float(page.mediabox.width) * 25.4 / 72, float(page.mediabox.height) * 25.4 / 72]
        changed = await self.apply([{"op": "create_layout", "name": "BenchmarkSheet", "paper": "A3"}], allow_error=True)
        return strict_result("page_setup_truth", False, {"ansi_b_mediabox_mm": size, "change_to_a3": changed},
                             "ANSI B output can be created. Native layout operations cannot change an existing page setup to A3 or report a known CTB.", partial=True)

    async def task_requirements_roundtrip(self):
        await self.call("draw_from_spec", output=self.path, overwrite=True,
                        spec={"kind": "plate", "units": "mm", "width": 120, "height": 80,
                              "material": "steel", "thickness": 10, "dimensions": "none", "center_marks": False,
                              "holes": [{"pattern": "single", "tag": tag, "center": [x, y], "diameter": diameter}
                                        for tag, x, y, diameter in [("bore", 60, 40, 20), ("c1", 15, 15, 8),
                                                                   ("c2", 105, 15, 8), ("c3", 105, 65, 8),
                                                                   ("c4", 15, 65, 8)]]})
        constraints = [{"id": "R1", "type": "diameter", "a": "tag:bore", "value": 20},
                       {"id": "R2", "type": "distance", "a": "tag:c1@center", "b": "tag:c2@center", "value": 90},
                       {"id": "R3", "type": "distance", "a": "tag:c1@center", "b": "tag:bore@center", "value": math.hypot(45, 25)}]
        count_req = [{"id": "R4", "type": "hole_count", "diameter": 8, "count": 4}]

        async def measure(session):
            previous = self.session
            self.session = session
            try:
                cr = await self.call("apply_constraints", path=self.path, constraints=constraints, mode="check")
                vr = await self.validate(requirements=count_req)
                rows = cr["constraints"]
                failed = [r["id"] for r in rows if not r["satisfied"]]
                failed += [r["id"] for r in vr["requirements"] if r["status"] != "pass"]
                return {"failed": sorted(failed), "constraints": rows, "count": vr["requirements"]}
            finally:
                self.session = previous

        before = await measure(self.session)
        doc = self.read()
        from ezdxf import bbox
        parity_before = (len(doc.modelspace()), tuple(bbox.extents(doc.modelspace())))
        bores = [c for c in doc.modelspace().query("CIRCLE") if c.dxf.radius == 10]
        bores[0].dxf.center = (63, 40, 0)
        doc.saveas(self.workspace / self.path)
        saved = self.read()
        parity_after = (len(saved.modelspace()), tuple(bbox.extents(saved.modelspace())))
        after = await measure(self.session)
        async with self.connect() as fresh:
            reopened = await measure(fresh)
        passed = grade_roundtrip(before, after, reopened, parity_unchanged=parity_before == parity_after,
                                 bores_moved=len(bores))
        return strict_result("requirements_roundtrip", passed,
                             {"document": before, "artifact": after, "fresh_process": reopened,
                              "moved_mm": 3, "equivalent_contract": "native check-only constraints R1-R3 + geometry count R4"})

    async def task_cancel_safety(self):
        from benchmarks.adapters.base import TaskResult
        return TaskResult("cancel_safety", "not_run", 0,
                          "No equivalent deterministic held-worker/event-trace fixture for the public MCP interface. Cancellation safety is unmeasured, not a product failure.")

    async def task_qa_large_drawing(self):
        # Same raw fixture staging as the reference; evaluation only calls the public validator.
        doc = ezdxf.new("R2010", setup=True, units=4)
        doc.layers.add("GEOMETRY")
        doc.layers.add("CONSTRUCTION")
        msp = doc.modelspace()
        construction = {}
        for index in range(1, 10001):
            layer = "CONSTRUCTION" if index == 5001 else "GEOMETRY"
            e = msp.add_line((0, index * 10), (100, index * 10), dxfattribs={"layer": layer})
            if index == 5001:
                construction["at_5001"] = e.dxf.handle
        construction["after_10000"] = msp.add_line((-300, 0), (-200, 0), dxfattribs={"layer": "CONSTRUCTION"}).dxf.handle
        construction["paper"] = doc.layouts.get("Layout1").add_line((0, 0), (50, 0), dxfattribs={"layer": "CONSTRUCTION"}).dxf.handle
        a = msp.add_line((500, -50), (600, -50), dxfattribs={"layer": "GEOMETRY"})
        b = msp.add_line((600, -50), (500, -50), dxfattribs={"layer": "GEOMETRY"})
        doc.saveas(self.workspace / self.path)
        report = await self.validate()
        paper = await self.validate(layout="Layout1")
        found = {h for report_ in [report, paper] for issue in report_["issues"] for h in issue.get("entities", [])}
        missing = [name for name, h in construction.items() if h not in found]
        dup_found = any({a.dxf.handle, b.dxf.handle} <= set(i.get("entities", [])) for i in report["issues"])
        return strict_result("qa_large_drawing", not missing and dup_found,
                             {"construction": construction, "missing_construction": missing, "duplicate_found": dup_found,
                              "issue_codes": sorted({i["code"] for i in report["issues"] + paper["issues"]})},
                             "Full model and paper validation called separately; all reference construction findings and the duplicate are required.")

    async def task_export_safety(self):
        results = {}
        for fmt in ["csv", "xlsx"]:
            results[fmt] = await self.call("export_drawing", path=self.path, output=f"export.{fmt}", format=fmt, allow_error=True)
        from benchmarks.adapters.base import TaskResult
        return TaskResult("export_safety", "unsupported", 0, "CSV and XLSX exports are both refused (UNSUPPORTED_FORMAT).",
                          metrics={"refusals": results})

    async def task_stale_preview(self):
        await self.apply([{"op": "add_line", "start": [0, 0], "end": [10, 0], "tag": "line"}])
        ops = [{"op": "move", "target": "tag:line", "delta": [5, 0]}]
        preview = await self.apply(ops, dry_run=True)
        doc = self.read()
        doc.modelspace().query("LINE")[0].dxf.color = 5
        doc.saveas(self.workspace / self.path)
        applied = await self.apply(ops, allow_error=True)
        line = self.read().modelspace().query("LINE")[0]
        moved = tuple(line.dxf.start)[:2] != (0, 0)
        return strict_result("stale_preview", False, {"preview_keys": sorted(preview), "apply": applied,
                             "moved_over_stale_preview": moved, "expected_revision_parameter": False},
                             "Dry run returns no reusable fingerprint/revision token; unguarded apply moves the externally edited line.")

    async def task_revision_guarded_edit(self):
        from benchmarks.adapters.base import TaskResult
        props = self.tools["apply_operations"]["inputSchema"]["properties"]
        return TaskResult("revision_guarded_edit", "unsupported", 0,
                          "apply_operations has no expected_revision or fingerprint precondition input; journal sequence is not an optimistic concurrency guard.",
                          metrics={"apply_parameters": sorted(props)})

    async def task_foreign_edit_verified(self):
        doc = ezdxf.new("R2010", units=4)
        msp = doc.modelspace()
        msp.add_lwpolyline([(0, 0), (100, 0), (100, 60), (0, 60)], close=True)
        holes = [("H1", 20, 20, 5), ("H2", 80, 20, 5), ("H3", 80, 40, 4.5), ("H4", 20, 40, 5)]
        for _, x, y, radius in holes:
            msp.add_circle((x, y), radius)
        msp.add_text("PLATE 100 x 60", height=2.5).set_placement((5, 52))
        doc.saveas(self.workspace / self.path)
        original = self.workspace / "foreign-original.dxf"
        doc.saveas(original)
        reqs = [{"id": name, "type": "hole", "center": [x, y], "diameter": 10} for name, x, y, _ in holes]
        reqs += [{"id": "N", "type": "hole_count", "count": 4}]
        before = await self.validate(requirements=reqs)
        selected = (await self.inspect(filter={"type": "CIRCLE"}))["entities"]
        pitch_handles = {tuple(e["center"][:2]): e["id"] for e in selected}
        pitch = await self.call("apply_constraints", path=self.path, mode="check", constraints=[
            {"id": "P", "type": "distance", "a": pitch_handles[(20, 20)] + "@center",
             "b": pitch_handles[(80, 20)] + "@center", "value": 60}])
        fail = [r for r in before["requirements"] if r["status"] == "fail"]
        handle = fail[0]["entities"][0] if len(fail) == 1 else None
        if handle:
            await self.apply([{"op": "modify", "target": handle, "set": {"radius": 5}}])
        after = await self.validate(requirements=reqs)
        pitch_after = await self.call("apply_constraints", path=self.path, mode="check", constraints=[
            {"id": "P", "type": "distance", "a": pitch_handles[(20, 20)] + "@center",
             "b": pitch_handles[(80, 20)] + "@center", "value": 60}])
        before_entities = {e.dxf.handle: e.dxfattribs() for e in ezdxf.readfile(original).modelspace()}
        after_entities = {e.dxf.handle: e.dxfattribs() for e in self.read().modelspace()}
        changed = [h for h in before_entities.keys() & after_entities if before_entities[h] != after_entities[h]]
        return strict_result("foreign_edit_verified", False, {"before_failed": [r["id"] for r in fail],
                             "after_failed": [r["id"] for r in after["requirements"] if r["status"] != "pass"],
                             "pitch_before": pitch["constraints"], "pitch_after": pitch_after["constraints"],
                             "changed": changed, "added": sorted(after_entities.keys() - before_entities),
                             "removed": sorted(before_entities.keys() - after_entities), "fingerprint_guard": False},
                             "Native diameter/count checks and one-entity repair work; original gate also requires fingerprint-guarded repair. No full credit.", partial=True)

    async def task_damaged_dxf_refusal(self):
        await self.apply([{"op": "add_line", "start": [0, 0], "end": [10, 0]}])
        before = digest(self.workspace / self.path)
        doc = ezdxf.new("R2010", units=4)
        for index in range(50):
            doc.modelspace().add_line((0, index), (10, index))
        intact = self.workspace / "intact.dxf"
        doc.saveas(intact)
        data = intact.read_bytes()
        (self.workspace / "truncated.dxf").write_bytes(data[:len(data) // 2])
        (self.workspace / "not-a-drawing.dxf").write_bytes(b"this is not a drawing\n" * 8)
        cases = {}
        for name in ["truncated.dxf", "not-a-drawing.dxf"]:
            response = await self.call("read_drawing", path=name, allow_error=True)
            err = response.get("error", {})
            cases[name] = {"refused": not response.get("ok"), "error": err,
                           "named": "DXF" in json.dumps(err).upper()}
        kept = before == digest(self.workspace / self.path) and len(self.read().modelspace()) == 1
        return strict_result("damaged_dxf_refusal", kept and all(c["refused"] and c["named"] for c in cases.values()),
                             {"cases": cases, "document_kept": kept, "identity": "file path + exact bytes; server is stateless"})

    async def task_dimension_binding(self):
        # Identical four geometric/annotation traps to the pinned reference.
        doc = ezdxf.new("R2010", setup=True, units=4)
        msp = doc.modelspace()
        handles = {}
        for name, x, width, kwargs in [("D1", 0, 42, {}), ("D2", 100, 40, {"text": "42"}),
                                       ("D3", 200, 21, {"override": {"dimlfac": 2}})]:
            msp.add_line((x, 0), (x, 20))
            msp.add_line((x + width, 0), (x + width, 20))
            dim = msp.add_linear_dim(base=(x, 30), p1=(x, 0), p2=(x + width, 0), dimstyle="Standard", **kwargs)
            dim.render()
            handles[name] = dim.dimension.dxf.handle
        msp.add_circle((350, 10), 20)
        dim = msp.add_diameter_dim(center=(350, 10), radius=20, angle=0, dimstyle="Standard")
        dim.render()
        handles["D4"] = dim.dimension.dxf.handle
        doc.saveas(self.workspace / self.path)
        report = await self.validate()
        inspected = await self.inspect(filter={"type": "DIMENSION"})
        mismatches = [i for i in report["issues"] if i["code"] == "DIMENSION_TEXT_MISMATCH"]
        flagged = {h for i in mismatches for h in i.get("entities", [])}
        # Requirement-to-physical-feature binding is also required; inspection
        # measurements alone cannot establish that contract.
        passed = False
        return strict_result("dimension_binding", passed,
                             {"handles": handles, "mismatches": mismatches, "accepted": report["passed"],
                              "both_lies_flagged": flagged == {handles["D2"], handles["D3"]},
                              "dimension_measurements": inspected["entities"],
                              "missing_dimension_requirement_handle_binding": True},
                             "Gate requires both the text override and DIMLFAC to be flagged against physical geometry.")


GAP_REASONS = {
    "preflight": "No native ready/spec_hash requirements preflight contract (drawing from a spec is a different contract).",
    "pid_roundtrip": "P&ID symbols/lines exist, but no spec-to-graph reader with dangling/confidence checks, line list and instrument index.",
    "mech_assembly": "Standard parts/title blocks exist, but no mechanical part/view engine, linked BOM/balloon critique and >=90 finalize score.",
    "arch_roundtrip": "No architectural wall/opening/room engine, room-area recognition or door/window/room schedule contract.",
    "takeoff_roundtrip": "No plant-scale inference or pipe/cable takeoff engine (RMST lengths, panels, allowance and service readback).",
    "understand_foreign": "Summary/validation exist, but no inferred-units versus INSUNITS warning, distant-cluster or P&ID service classifier.",
    "pid_file_roundtrip": "No P&ID graph/line-number/instrument-index reader to prove their semantic roundtrip across processes.",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True, help="New or empty directory (never overwrites evidence)")
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--task", action="append")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args()
    upstream = args.upstream.resolve()
    if git(upstream, "rev-parse", "HEAD") != PIN or git(upstream, "status", "--porcelain", "--untracked-files=no"):
        parser.error(f"upstream must be a clean checkout of {PIN}")
    if args.out.exists() and any(args.out.iterdir()):
        parser.error("--out must be new or empty; use a new directory to retry")
    args.out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(upstream))
    from benchmarks.run_competitors import run_tasks, _summary
    from benchmarks.tasks_v8 import TASKS_V8, TASKS_V2
    tasks = [t for t in TASKS_V8 if not args.task or t.task_id in args.task]
    if args.task and set(args.task) - {t.task_id for t in tasks}:
        parser.error("unknown task id")
    adapter = AgentCADAdapter(args.python.resolve())
    report = asyncio.run(run_tasks(adapter, tasks, args.out / "artifacts", timeout=args.timeout, matrix="v8"))
    # Upstream's manifest names its own repository. Explicitly identify the measured
    # product and retain the upstream manifest under evaluator instead of relabelling it.
    evaluator = report["manifest"]
    report["git_sha"] = adapter.product_sha
    report["manifest"] = {"server_sha": adapter.product_sha, "dirty": adapter.product_dirty,
                          "source_sha256": adapter.source_hashes, "evaluator": evaluator,
                          "adapter_sha256": digest(Path(__file__)),
                          "dependencies": {name: importlib.metadata.version(name) for name in ["mcp", "ezdxf", "pypdf"]}}
    from benchmarks.adapters.base import TaskResult
    v2ids = {t.task_id for t in TASKS_V2}
    v2results = [TaskResult(**r) for r in report["results"] if r["task_id"] in v2ids]
    report["v2_summary"] = _summary(TASKS_V2, v2results)
    report["fixed_matrix_full_pass_percent"] = round(report["summary"]["passed"] / len(tasks) * 100, 2)
    report["evidence_boundary"] = "Local independent adapter; not an upstream-certified leaderboard submission. Partial gates score 0."
    for result in report["results"]:
        for artifact in result["artifacts"]:
            artifact.pop("path", None)
    write_json(args.out / "report.json", report)
    print(json.dumps({"summary": report["summary"], "v2_summary": report["v2_summary"]}, indent=2))


if __name__ == "__main__":
    main()
