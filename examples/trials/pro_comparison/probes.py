"""Deterministic MCP probes for batch failure, restart recovery and workspace boundaries."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import ezdxf
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[3]


def unpack(result) -> dict:
    raw = result.model_dump(mode="json", by_alias=True, exclude_none=True)
    body = raw.get("structuredContent")
    if body is None:
        for item in raw.get("content", []):
            if item.get("type") == "text":
                try:
                    body = json.loads(item.get("text", ""))
                except ValueError:
                    body = item.get("text")
                break
    return {"is_error": raw.get("isError", False), "body": body}


def geometry(path: Path) -> list:
    doc = ezdxf.readfile(path)
    return sorted([
        [round(e.dxf.start.x, 4), round(e.dxf.start.y, 4), round(e.dxf.end.x, 4), round(e.dxf.end.y, 4)]
        for e in doc.modelspace().query("LINE")
    ])


@asynccontextmanager
async def session(arm: str, ws: Path, pro: Path, log: Path):
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if arm == "A":
        command = REPO / ".venv" / "Scripts" / "python.exe"
        args = ["-m", "agentcad.mcp_server"]
        env.update(AGENTCAD_ROOT=str(ws), AGENTCAD_ALLOW_SCRIPTS="0", AGENTCAD_READ_ONLY="0", AGENTCAD_ALLOWED_OPS="")
    else:
        command = pro / ".venv" / "Scripts" / "autocad-mcp.exe"
        args = []
        env.update(AUTOCAD_MCP_BACKEND="ezdxf", ALLOWED_PATHS=str(ws), EZDXF_UNDO_DEPTH="5",
                   DISCOVERY_MODE="off", TOOL_PROFILE="full", TOOL_PACKS="all", ENABLE_3D="false")
    params = StdioServerParameters(command=str(command), args=args, env=env, cwd=str(ws))
    with log.open("w", encoding="utf-8") as err:
        async with stdio_client(params, errlog=err) as (read, write):
            async with ClientSession(read, write) as client:
                await asyncio.wait_for(client.initialize(), 90)
                yield client


async def call(client: ClientSession, name: str, args: dict) -> dict:
    return unpack(await asyncio.wait_for(client.call_tool(name, arguments=args), 180))


async def case(out: Path, pro: Path, name: str, arm: str, fixture: Path, handle: str) -> dict:
    ws = out / name
    ws.mkdir()
    path = ws / "part.dxf"
    shutil.copyfile(fixture, path)
    before = geometry(path)
    initial_bytes = path.read_bytes()
    details: dict = {"before": before}

    if name == "agentcad_batch":
        async with session(arm, ws, pro, ws / "server1.log") as c:
            details["batch"] = await call(c, "apply_operations", {
                "path": "part.dxf", "operations": [
                    {"op": "move", "target": handle, "delta": [3, 0]},
                    {"op": "delete", "target": "FFFFFFFE"},
                ],
            })
        details["drawing_bytes_unchanged"] = path.read_bytes() == initial_bytes

    elif name.startswith("pro_batch"):
        mode = "rollback" if name.endswith("rollback") else "stop"
        async with session(arm, ws, pro, ws / "server1.log") as c:
            details["open"] = await call(c, "drawing_open", {"path": str(path)})
            details["batch"] = await call(c, "cad_batch", {
                "steps": [
                    {"tool": "entity_move", "args": {"handle": handle, "dx": 3, "dy": 0}},
                    {"tool": "entity_delete", "args": {"handle": "FFFFFFFE"}},
                ],
                "on_error": mode, "verbose": True,
            })
            details["save"] = await call(c, "drawing_save", {})

    elif name == "agentcad_restart":
        async with session(arm, ws, pro, ws / "server1.log") as c:
            details["move"] = await call(c, "apply_operations", {
                "path": "part.dxf", "operations": [{"op": "move", "target": handle, "delta": [3, 0]}],
            })
        details["after_move"] = geometry(path)
        async with session(arm, ws, pro, ws / "server2.log") as c:
            details["history"] = await call(c, "history", {"path": "part.dxf"})
            details["undo"] = await call(c, "rollback", {"path": "part.dxf"})

    elif name == "pro_restart":
        async with session(arm, ws, pro, ws / "server1.log") as c:
            details["open1"] = await call(c, "drawing_open", {"path": str(path)})
            details["move"] = await call(c, "entity_move", {"handle": handle, "dx": 3, "dy": 0})
            details["save1"] = await call(c, "drawing_save", {})
        details["after_move"] = geometry(path)
        async with session(arm, ws, pro, ws / "server2.log") as c:
            details["open2"] = await call(c, "drawing_open", {"path": str(path)})
            details["undo"] = await call(c, "drawing_undo", {})
            details["save2"] = await call(c, "drawing_save", {})

    elif name.endswith("_scope"):
        async with session(arm, ws, pro, ws / "server1.log") as c:
            if arm == "A":
                details["outside_access"] = await call(c, "read_drawing", {"path": str(fixture)})
            else:
                details["outside_access"] = await call(c, "drawing_open", {"path": str(fixture)})

    details["after"] = geometry(path)
    details["geometry_restored"] = details["after"] == before
    return details


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--pro", type=Path, required=True)
    args = parser.parse_args()
    out, pro = args.out.resolve(), args.pro.resolve()
    out.mkdir(parents=True, exist_ok=False)
    fixture = out / "fixture.dxf"
    doc = ezdxf.new("R2010")
    entity = doc.modelspace().add_line((0, 0), (10, 0))
    handle = entity.dxf.handle
    doc.saveas(fixture)
    results = {}
    for name, arm in (
        ("agentcad_batch", "A"), ("pro_batch_stop", "B"), ("pro_batch_rollback", "B"),
        ("agentcad_restart", "A"), ("pro_restart", "B"), ("agentcad_scope", "A"), ("pro_scope", "B"),
    ):
        try:
            results[name] = await case(out, pro, name, arm, fixture, handle)
        except Exception as exc:
            results[name] = {"infrastructure_error": type(exc).__name__ + ": " + str(exc)}
        temporary = out / "results.json.tmp"
        temporary.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, out / "results.json")
        print(json.dumps({"case": name, "geometry_restored": results[name].get("geometry_restored"),
                          "infrastructure_error": results[name].get("infrastructure_error")}, ensure_ascii=False),
              flush=True)


if __name__ == "__main__":
    asyncio.run(main())
