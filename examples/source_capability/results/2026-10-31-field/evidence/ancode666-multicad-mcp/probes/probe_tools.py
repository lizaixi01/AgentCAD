"""Reviewer probes for multiCAD-mcp @360ec77 (run offline in Docker, Linux).

The product is COM-only. pywin32 cannot exist on Linux, so win32shim injects stubs and this
script supplies a small in-memory *fake* COM document (FakeDoc). Every MCP call goes through
the product's real FastMCP server object (src/server.py) via fastmcp's in-memory Client, so the
tool layer, shorthand parser, dispatch, adapter mixins and response building are the product's
own code. What the fake records (entities, coordinates, SaveAs arguments) is read back
independently of the tool's own success flag. Nothing here proves real CAD behaviour.
"""
import asyncio
import json
import os
import sys
import tempfile
import math

sys.path.insert(0, "/out/probes")
import win32shim  # noqa: F401  (installs stubs, imports product)

OUT = tempfile.mkdtemp(prefix="mcm_out_")

# Point the product's configured output directory at a temp dir, leaving everything else
# (in particular the shipped allow_arbitrary_paths=true) as shipped.
from core import config as core_config  # noqa: E402
cfg = core_config.get_config()
cfg.output.directory = OUT


class FakeVariant:
    pass


def pt(v):
    vals = list(getattr(v, "value", v))
    return [float(x) for x in vals]


class FakeEntity:
    def __init__(self, doc, kind, **geo):
        doc._n += 1
        self.Handle = format(0x100 + doc._n, "X")
        self.ObjectName = kind
        self.Layer = "0"
        self.Color = 7
        self.Lineweight = -1
        self.geo = geo
        self._doc = doc

    def Move(self, a, b):
        a, b = pt(a), pt(b)
        d = [b[i] - a[i] for i in range(3)]
        for k, v in self.geo.items():
            if isinstance(v, list) and len(v) == 3:
                self.geo[k] = [v[i] + d[i] for i in range(3)]

    def Rotate(self, c, rad):
        c = pt(c)
        for k, v in self.geo.items():
            if isinstance(v, list) and len(v) == 3:
                x, y = v[0] - c[0], v[1] - c[1]
                self.geo[k] = [c[0] + x * math.cos(rad) - y * math.sin(rad),
                               c[1] + x * math.sin(rad) + y * math.cos(rad), v[2]]

    def ScaleEntity(self, c, f):
        c = pt(c)
        for k, v in self.geo.items():
            if isinstance(v, list) and len(v) == 3:
                self.geo[k] = [c[i] + (v[i] - c[i]) * f for i in range(3)]
        if "radius" in self.geo:
            self.geo["radius"] *= f

    def Delete(self):
        self._doc.entities.pop(self.Handle, None)

    def Update(self):
        pass

    def __getattr__(self, name):  # any other COM property/method
        if name.startswith("_") or name == "geo":
            raise AttributeError(name)
        return 0


class FakeModelSpace:
    def __init__(self, doc):
        self.doc = doc

    def _add(self, e):
        self.doc.entities[e.Handle] = e
        return e

    def AddLine(self, a, b):
        return self._add(FakeEntity(self.doc, "AcDbLine", start=pt(a), end=pt(b)))

    def AddCircle(self, c, r):
        if float(r) <= 0:
            raise Exception("Invalid input (fake COM): radius must be > 0")
        return self._add(FakeEntity(self.doc, "AcDbCircle", center=pt(c), radius=float(r)))

    @property
    def Count(self):
        return len(self.doc.entities)

    def Item(self, i):
        return list(self.doc.entities.values())[i]

    def __iter__(self):
        return iter(list(self.doc.entities.values()))


class FakeLayer:
    def __init__(self, layers, name):
        self.Name, self._layers = name, layers
        self.Color, self.LayerOn, self.Freeze, self.Lock = 7, True, False, False

    def Delete(self):
        if any(e.Layer == self.Name for e in self._layers.doc.entities.values()):
            raise Exception("Object is referenced (fake COM)")
        self._layers.items.pop(self.Name)


class FakeLayers:
    def __init__(self, doc):
        self.doc = doc
        self.items = {"0": FakeLayer(self, "0")}

    def Add(self, name):
        self.items.setdefault(name, FakeLayer(self, name))
        return self.items[name]

    def Item(self, name):
        if name not in self.items:
            raise Exception(f"Key not found (fake COM): {name}")
        return self.items[name]

    @property
    def Count(self):
        return len(self.items)

    def __iter__(self):
        return iter(list(self.items.values()))


class FakeDoc:
    def __init__(self, name="Drawing1.dwg"):
        self.Name = name
        self.entities = {}
        self._n = 0
        self.ModelSpace = FakeModelSpace(self)
        self.Layers = FakeLayers(self)
        self.saveas_calls = []
        self.sent_commands = []
        self.ActiveLayer = self.Layers.items["0"]

    def HandleToObject(self, h):
        if h not in self.entities:
            raise Exception(f"Invalid handle (fake COM): {h}")
        return self.entities[h]

    def SaveAs(self, *args):
        self.saveas_calls.append(list(args))

    def SendCommand(self, s):
        self.sent_commands.append(s)

    def Regen(self, *_):
        pass

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        from unittest.mock import MagicMock
        m = MagicMock(name=f"FakeDoc.{name}")
        setattr(self, name, m)
        return m


class FakeApp:
    def __init__(self, doc):
        self.ActiveDocument = doc
        self.Visible = True
        from unittest.mock import MagicMock
        self.Documents = MagicMock()
        self.Documents.Count = 1
        self.Documents.__iter__ = lambda s: iter([doc])

    def Refresh(self):
        pass

    def Update(self):
        pass


from adapters import AutoCADAdapter  # noqa: E402
from adapters import adapter_manager  # noqa: E402

doc = FakeDoc()
fake_app = FakeApp(doc)
# The adapter keeps application/document thread-locally and reconnects in FastMCP's worker
# thread through win32com.client.GetActiveObject/Dispatch, so route those stubs to the fake.
sys.modules["win32com.client"].GetActiveObject = lambda *a, **k: fake_app
sys.modules["win32com.client"].Dispatch = lambda *a, **k: fake_app
sys.modules["win32com.client"].GetObject = lambda *a, **k: fake_app
adapter = AutoCADAdapter("autocad")
adapter.application = fake_app
adapter.document = doc
reg = adapter_manager.AdapterRegistry.get_instance()
reg._adapter, reg._cad_type = adapter, "autocad"

real_platform = sys.platform
sys.platform = "win32"
try:
    import server  # the product's FastMCP server object with all tools registered
finally:
    sys.platform = real_platform
from fastmcp import Client  # noqa: E402

results = []


def record(pid, item, desc, expected, observed, verdict):
    results.append({"id": pid, "item": item, "probe": desc, "expected": expected,
                    "observed": observed, "verdict": verdict})


async def call(c, tool, arg):
    r = await c.call_tool(tool, arg, raise_on_error=False)
    txt = r.content[0].text if r.content else ""
    try:
        return json.loads(txt)
    except Exception:
        return {"raw": txt, "is_error": r.is_error}


async def main():
    async with Client(server.mcp) as c:
        tools = sorted(t.name for t in await c.list_tools())
        record("P0", "B1", "MCP in-memory list_tools on the product server", "7 tools",
               tools, "pass" if len(tools) == 7 else "fail")

        # P1 ordinary drawing + readback
        r = await call(c, "draw_entities", {"entities": "line|0,0|100,0|red|walls\ncircle|50,40|10|blue"})
        ents = {h: (e.ObjectName, e.geo, e.Layer) for h, e in doc.entities.items()}
        ok = (r.get("created") == 2 and any(v[0] == "AcDbLine" and v[1]["end"] == [100.0, 0.0, 0.0] and v[2] == "walls" for v in ents.values())
              and any(v[0] == "AcDbCircle" and v[1]["radius"] == 10.0 for v in ents.values()))
        record("P1", "F1", "draw line+circle, read fake model back", "2 created with requested geometry/layer",
               {"tool": r, "fake_model": ents}, "pass" if ok else "fail")
        line_h = [h for h, e in doc.entities.items() if e.ObjectName == "AcDbLine"][0]

        # P2 invalid inputs
        r = await call(c, "draw_entities", {"entities": "circle|0,0|-5\ncircle|0,0\nblob|1,1\nline|a,b|1,1"})
        fails = [x.get("success") for x in r.get("results", [])]
        record("P2", "F1/C4", "invalid radius, missing field, unknown type, bad coordinate",
               "all 4 rejected, nothing added", {"tool": r, "entity_count": len(doc.entities)},
               "pass" if fails == [False] * 4 and len(doc.entities) == 2 else "fail")

        # P3 batch with failure: no rollback
        before = len(doc.entities)
        r = await call(c, "draw_entities", {"entities": "line|0,0|1,1\ncircle|0,0|-1\nline|2,2|3,3"})
        record("P3", "C1", "batch with a failing middle op", "documents behaviour (rollback or partial)",
               {"created": r.get("created"), "entities_added": len(doc.entities) - before},
               "observed: partial commit, no rollback")

        # P4 move with one good and one bad handle (defect F2)
        e = doc.entities[line_h]
        start_before = list(e.geo["start"])
        r = await call(c, "manage_entities", {"operations": f"move|{line_h},DEAD|10|5"})
        res = r.get("results", [{}])[0]
        actually_moved = 1 if e.geo["start"] != start_before else 0
        record("P4", "F2", "move [valid, nonexistent] handles by (10,5)",
               "partial failure reported", {"tool": res, "line_start_before": start_before,
                                           "line_start_after": e.geo["start"], "actually_moved": actually_moved},
               "defect reproduced" if res.get("success") is True and res.get("count") == 2 and actually_moved == 1 else "not reproduced")

        # P5 move with only bad handle
        r = await call(c, "manage_entities", {"operations": "move|DEAD|1|1"})
        res = r.get("results", [{}])[0]
        record("P5", "F2/C4", "move nonexistent handle only", "success false",
               res, "pass" if res.get("success") is False else "fail")

        # P6 rotate/scale readback
        r1 = await call(c, "manage_entities", {"operations": f"rotate|{line_h}|90|0|0"})
        rot = list(doc.entities[line_h].geo["start"])
        circ_h = [h for h, x in doc.entities.items() if x.ObjectName == "AcDbCircle"][0]
        r2 = await call(c, "manage_entities", {"operations": f"scale|{circ_h}|2|0|0"})
        rad = doc.entities[circ_h].geo["radius"]
        ok = abs(rot[0] - (-5.0)) < 1e-9 and abs(rot[1] - 10.0) < 1e-9 and rad == 20.0
        record("P6", "F2", "rotate line 90deg about origin; scale circle x2", "start (10,5)->(-5,10); radius 20",
               {"rotate": r1.get("results"), "start_after": rot, "scale": r2.get("results"), "radius_after": rad},
               "pass" if ok else "fail")

        # P7 delete then bad delete
        r = await call(c, "manage_entities", {"operations": f"delete|{circ_h}\ndelete|NOPE"})
        record("P7", "F2/C4", "delete existing, then nonexistent handle", "first true, second false",
               {"tool": [(x.get("success"), x.get("detail") or x.get("error")) for x in r.get("results", [])],
                "circle_still_present": circ_h in doc.entities}, "see observed")

        # P8 layers
        r = await call(c, "manage_layers", {"operations": "create|walls2\ndelete|0\ndelete|missing\nlist"})
        record("P8", "F4/C4", "create layer, delete '0', delete missing, list",
               "create ok; '0' and missing refused", {"results": [(x.get("action"), x.get("success")) for x in r.get("results", [])],
                                                     "fake_layers": sorted(doc.Layers.items)}, "see observed")

        # P9 save by filename (defect C3: reported path vs written path)
        doc.saveas_calls.clear()
        r = await call(c, "manage_files", {"operations": "save|plan.dwg"})
        res = r.get("results", [{}])[0]
        written = doc.saveas_calls[-1] if doc.saveas_calls else None
        record("P9", "C3", "save|plan.dwg (filename into output dir)", "reported path == SaveAs path",
               {"reported": res, "SaveAs_args": written},
               "defect reproduced" if written and res.get("path") != written[0] else "not reproduced")

        # P10 save as dxf / pdf: format only becomes an extension
        for fmt in ("dxf", "pdf"):
            doc.saveas_calls.clear()
            r = await call(c, "manage_files", {"operations": f"save|plan2|{fmt}"})
            res = r.get("results", [{}])[0]
            written = doc.saveas_calls[-1] if doc.saveas_calls else None
            record(f"P10-{fmt}", "C3/F4", f"save|plan2|{fmt}", "a format-specific SaveAs type or plot/export call",
                   {"reported": res, "SaveAs_args": written, "n_args": len(written) if written else None,
                    "reported_path_exists_on_disk": bool(res.get("path")) and os.path.exists(res.get("path", ""))},
                   "defect reproduced" if res.get("success") and written and len(written) == 1 else "not reproduced")

        # P11a relative traversal: only the basename is used
        doc.saveas_calls.clear()
        r = await call(c, "manage_files", {"operations": "save|../../../../tmp/escaped.dwg"})
        res = r.get("results", [{}])[0]
        written = doc.saveas_calls[-1][0] if doc.saveas_calls else None
        inside = bool(written) and os.path.realpath(written).startswith(os.path.realpath(OUT))
        record("P11a", "S1/C3", "save|../../../../tmp/escaped.dwg (relative traversal), shipped config",
               "kept inside output dir; reported path equals written path",
               {"allow_arbitrary_paths": cfg.output.allow_arbitrary_paths, "reported": res, "SaveAs_path": written},
               ("traversal contained; " if inside else "ESCAPED; ") +
               ("reported path mismatch reproduced" if res.get("path") != written else "paths match"))

        # P11b absolute path outside output dir with the SHIPPED config (allow_arbitrary_paths=true)
        doc.saveas_calls.clear()
        r = await call(c, "manage_files", {"operations": "save|/etc/escaped_abs.dwg"})
        res = r.get("results", [{}])[0]
        written = doc.saveas_calls[-1][0] if doc.saveas_calls else None
        record("P11b", "S1", "save|/etc/escaped_abs.dwg with shipped config", "refused (outside output dir)",
               {"allow_arbitrary_paths": cfg.output.allow_arbitrary_paths, "reported": res, "SaveAs_path": written},
               "defect reproduced (write outside output dir accepted by default)" if res.get("success") and written == "/etc/escaped_abs.dwg" else "not reproduced")

        # P12 same absolute path with allow_arbitrary_paths=false
        cfg.output.allow_arbitrary_paths = False
        doc.saveas_calls.clear()
        r = await call(c, "manage_files", {"operations": "save|/etc/escaped_abs2.dwg"})
        res = r.get("results", [{}])[0]
        written = doc.saveas_calls[-1][0] if doc.saveas_calls else None
        inside = bool(written) and os.path.realpath(written).startswith(os.path.realpath(OUT))
        record("P12", "S1/C3", "same absolute path with allow_arbitrary_paths=false",
               "refused, or redirected inside output dir and reported truthfully",
               {"reported": res, "SaveAs_path": written},
               ("contained; " if inside else "ESCAPED; ") +
               ("reported path mismatch reproduced" if res.get("path") != written else "paths match"))
        cfg.output.allow_arbitrary_paths = True

        # P13 unknown action / malformed input
        r = await call(c, "manage_files", {"operations": "explode|x"})
        record("P13", "C4", "unknown file action", "structured error", r, "see observed")

        # P14 undo: fire-and-forget SendCommand
        doc.sent_commands.clear()
        r = await call(c, "manage_session", {"operations": json.dumps([{"action": "undo", "count": 3}])})
        record("P14", "C1", "undo|3", "verified undo", {"tool": r, "sent_commands": doc.sent_commands},
               "observed: command string only, no verification")


asyncio.run(main())

# P15 dashboard API: switch_drawing to a nonexistent drawing; HTTP auth on MCP endpoint
from fastapi.testclient import TestClient  # noqa: E402
import web.api as webapi  # noqa: E402
webapi._cache.update(connected=True)
tc = TestClient(webapi.api_app)
resp = tc.post("/api/cad/switch_drawing", json={"drawing_name": "does_not_exist.dwg"})
record("P15", "C3/S1", "dashboard POST /api/cad/switch_drawing to a nonexistent drawing (no credentials)",
       "success false", {"status": resp.status_code, "body": resp.json(), "active_doc": adapter.document.Name},
       "defect reproduced" if resp.json().get("success") is True else "not reproduced")

app = server.mcp.http_app()
app.mount("/", webapi.api_app)
init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                   "clientInfo": {"name": "probe", "version": "0"}}}
with TestClient(app, base_url="http://127.0.0.1:8888") as h:
    r1 = h.post("/mcp", json=init, headers={"Accept": "application/json, text/event-stream"})
    r2 = h.post("/mcp", json=init, headers={"Accept": "application/json, text/event-stream",
                                            "Host": "evil.example", "Origin": "http://evil.example"})
record("P16", "S1", "HTTP-mode MCP initialize without credentials; then with foreign Host/Origin",
       "401/403 for unauthenticated or foreign origin",
       {"no_auth_status": r1.status_code, "foreign_origin_status": r2.status_code},
       "defect reproduced" if r1.status_code == 200 and r2.status_code == 200 else
       ("partially: no auth" if r1.status_code == 200 else "not reproduced"))

with open("/out/probe_results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
for x in results:
    print(x["id"], x["item"], "|", x["verdict"], "|", json.dumps(x["observed"], default=str)[:400])
