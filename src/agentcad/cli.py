"""``agentcad`` command-line interface. Every command prints one JSON envelope
on stdout. Exit codes: 0 ok, 1 validation failed, 2 input/spec/geometry
error, 3 file error, 4 policy refusal, 5 internal error, 6 optional dependency missing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .errors import AgentCADError
from .policy import Policy
from .service import Runtime

REPO_URL = "https://github.com/lizaixi01/AgentCAD"
EXIT = {"validation": 1, "input": 2, "spec": 2, "geometry": 2, "file": 3, "policy": 4, "internal": 5, "dependency": 6}


def _json_arg(value: str | None, file: str | None, what: str) -> Any:
    if file:
        try:
            return json.loads(Path(file).read_text("utf-8"))
        except (OSError, ValueError) as exc:
            _die(f"cannot read {what} file {file}: {exc}")
    if value:
        try:
            return json.loads(value)
        except ValueError as exc:
            _die(f"invalid {what} JSON: {exc}")
    return None


def _die(msg: str) -> None:
    print(json.dumps({"ok": False, "error": {"code": "CLI_USAGE", "category": "input", "message": msg}}))
    sys.exit(2)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="agentcad", description="Headless agent-native CAD runtime: 2D drawings (DXF) "
                                 "and 3D parts (FreeCAD). New here? Run 'agentcad setup', then 'agentcad doctor'.")
    ap.add_argument("--root", help="Workspace root (default: $AGENTCAD_ROOT, else the current folder; 'mcp', 'setup' "
                                   "and 'doctor' use ~/AgentCAD instead of the current folder); all paths must be "
                                   "inside it")
    ap.add_argument("--read-only", action="store_true", help="Refuse every modification")
    ap.add_argument("--allow-scripts", action="store_true", help="Enable the 'script' command (agent-written ezdxf "
                                                                 "scripts; CadQuery / FreeCAD scripts for 3D parts)")
    ap.add_argument("--compact", action="store_true", help="Single-line JSON output")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("create", help="Create an empty drawing")
    s.add_argument("path"); s.add_argument("--units", default="mm"); s.add_argument("--template", default="mechanical")
    s.add_argument("--dxf-version", default="R2010"); s.add_argument("--overwrite", action="store_true")
    s.add_argument("--annotation-scale", type=float, default=1.0, help="Plot scale 1:N for dimension/linetype sizes")

    s = sub.add_parser("inspect", help="Drawing summary: units, extents, layers, counts, tags, metadata")
    s.add_argument("path")

    s = sub.add_parser("measure", help="Exact DXF entity or 3D plane/distance measurements")
    s.add_argument("path")
    s.add_argument("--target", required=True, help="JSON entity selector, planar_levels or face_distance target")

    s = sub.add_parser("image", help="Inspect/magnify a workspace image; JSON contains a base64 PNG")
    s.add_argument("path"); s.add_argument("--region", help="JSON [left,top,right,bottom] in source pixels")
    s.add_argument("--max-size", type=int, default=1536)
    s.add_argument("--rotate", type=int, choices=(0, 90, 180, 270), default=0, help="Clockwise degrees after cropping")
    s.add_argument("--dimensions", help="JSON linear-dimension anchors; [] shows source-coordinate guides")
    s.add_argument("--dimensions-file", help="JSON file with linear-dimension anchors")

    s = sub.add_parser("entities", help="List entities (filtered, paginated)")
    s.add_argument("path"); s.add_argument("--type"); s.add_argument("--layer"); s.add_argument("--tag")
    s.add_argument("--tag-prefix"); s.add_argument("--ids", help="Comma-separated handles")
    s.add_argument("--limit", type=int, default=200); s.add_argument("--offset", type=int, default=0)
    s.add_argument("--brief", action="store_true")
    s.add_argument("--layout", help="Model (default), a paper layout name, or * for all")

    s = sub.add_parser("apply", help="Apply an operation batch atomically")
    s.add_argument("path"); s.add_argument("--ops"); s.add_argument("--ops-file")
    s.add_argument("--requirements-file"); s.add_argument("--dry-run", action="store_true")
    s.add_argument("--strict", action="store_true", help="Do not save if post-validation fails")
    s.add_argument("--label")

    s = sub.add_parser("script", help="Run an ezdxf script on a drawing, or a CadQuery / FreeCAD script that builds a "
                                      "3D part's solid, as one transaction (needs --allow-scripts)")
    s.add_argument("path"); s.add_argument("--file", required=True, help="Python file; a drawing is `doc`, a part's "
                                                                         "script sets `result`")
    s.add_argument("--requirements-file"); s.add_argument("--dry-run", action="store_true")
    s.add_argument("--strict", action="store_true"); s.add_argument("--label")
    s.add_argument("--language", choices=["ezdxf", "cadquery", "freecad"],
                   help="Default: ezdxf for .dxf, cadquery for .FCStd")
    s.add_argument("--keep-features", action="store_true", help="3D part: rebuild the Body's features on the new solid")

    s = sub.add_parser("validate", help="Independent validation of the file on disk")
    s.add_argument("path"); s.add_argument("--requirements-file"); s.add_argument("--requirements")
    s.add_argument("--bounds", help="x0,y0,x1,y1"); s.add_argument("--tolerance", type=float, default=1e-6)
    s.add_argument("--no-stored-spec", action="store_true"); s.add_argument("--contour-layers")
    s.add_argument("--layout", help="Validate this paper-space layout instead of model space")
    s.add_argument("--detail", action="store_true", help="Full report (every requirement, circle and dimension)")

    s = sub.add_parser("draw", help="Generate a drawing from a part spec / plan")
    s.add_argument("--spec", required=True, help="Spec JSON file"); s.add_argument("--output", required=True)
    s.add_argument("--overwrite", action="store_true"); s.add_argument("--dxf-version", default="R2010")

    s = sub.add_parser("revise", help="Revise a spec-made drawing with spec changes (reconciled in place)")
    s.add_argument("path"); s.add_argument("--spec", required=True, help="Changes JSON file")
    s.add_argument("--dry-run", action="store_true")

    s = sub.add_parser("constraints", help="Check (or --enforce) geometric constraints")
    s.add_argument("path"); s.add_argument("--file", required=True); s.add_argument("--enforce", action="store_true")
    s.add_argument("--tolerance", type=float, default=1e-6)

    s = sub.add_parser("extract", help="Extract a structured spec (with sources) from a PDF/TXT/MD document")
    s.add_argument("document"); s.add_argument("--facts-file"); s.add_argument("--overrides-file")

    s = sub.add_parser("from-doc", help="Document -> spec -> drawing -> verification against the document")
    s.add_argument("document"); s.add_argument("--output", required=True); s.add_argument("--facts-file")
    s.add_argument("--overrides-file"); s.add_argument("--overwrite", action="store_true")

    s = sub.add_parser("diff", help="Structured diff against a checkpoint or another drawing")
    s.add_argument("path"); s.add_argument("--against", default="previous")
    s.add_argument("--detail", action="store_true", help="Full geometry of added/deleted entities")

    s = sub.add_parser("rollback", help="Restore a checkpoint (default latest)")
    s.add_argument("path"); s.add_argument("--checkpoint")

    s = sub.add_parser("history", help="Show the operation journal (one line per record)"); s.add_argument("path")
    s.add_argument("--detail", action="store_true", help="Full records")
    s.add_argument("--seq", type=int, action="append", help="Full record with this sequence number (repeatable)")

    for name, hlp in (("checkpoints", "List checkpoints"), ("recover", "Recover from a crash / corrupted file")):
        s = sub.add_parser(name, help=hlp); s.add_argument("path")

    s = sub.add_parser("export", help="Export to dxf (other version, incl. R12) / svg / json / pdf / dwg")
    s.add_argument("path"); s.add_argument("output"); s.add_argument("--format", default=None)
    s.add_argument("--dxf-version"); s.add_argument("--overwrite", action="store_true")
    s.add_argument("--layout", help="pdf: 'Model', a paper layout, or '*' (default: paper layouts with content)")
    s.add_argument("--paper", help="pdf: A0-A4 or auto"); s.add_argument("--scale", type=float,
                                                                         help="pdf: paper mm per drawing unit")
    s.add_argument("--orientation", default="auto"); s.add_argument("--monochrome", action="store_true")

    s = sub.add_parser("import", help="Import a DWG as DXF (optional AutoCAD backend)")
    s.add_argument("source"); s.add_argument("output"); s.add_argument("--overwrite", action="store_true")
    s = sub.add_parser("live", help="Work with a running AutoCAD: status | open | reload | pull | zoom | command")
    s.add_argument("action", choices=["status", "open", "reload", "pull", "zoom", "command"])
    s.add_argument("path", nargs="?"); s.add_argument("--start", action="store_true", help="open: launch AutoCAD")
    s.add_argument("--discard", action="store_true", help="reload: drop unsaved edits made in AutoCAD")
    s.add_argument("--id", action="append", dest="ids", help="zoom: entity id or tag:<name> (repeatable)")
    s.add_argument("--command", help="command: the command line to send"); s.add_argument("--label")
    s.add_argument("--force", action="store_true", help="pull: even if the file changed since AutoCAD opened it")
    s = sub.add_parser("library", help="Industry libraries: index, an item's dimensions, or a drawing's parts list")
    s.add_argument("item", nargs="?"); s.add_argument("--size"); s.add_argument("--drawing")

    s = sub.add_parser("acad-audit", help="Run AutoCAD's AUDIT on a drawing (optional AutoCAD backend)")
    s.add_argument("path")

    s = sub.add_parser("ops", help="Operation index; --op/--category/--detail for JSON schemas"); s.add_argument("--category"); s.add_argument("--op", action="append", help="Full schema of this op (repeatable)"); s.add_argument("--detail", action="store_true")
    sub.add_parser("mcp", help="Run the MCP server on stdio (workspace: --root, $AGENTCAD_ROOT or ~/AgentCAD)")
    s = sub.add_parser("setup", help="Connect AgentCAD to Claude Code, Codex, Claude Desktop or Cursor",
                       description="Writes the MCP config of the chosen apps (keeping their other servers), creates "
                                   "the workspace folder, looks for FreeCAD and AutoCAD and prints what to do next. "
                                   "Safe to run again.")
    s.add_argument("--client", action="append", choices=("claude-code", "codex", "claude-desktop", "cursor", "all"),
                   help="App to configure (repeatable; 'all' = all four). Default: ask, or every app found when "
                        "--yes is given or input is not a terminal")
    s.add_argument("--root", dest="setup_root", metavar="FOLDER",
                   help="Workspace folder for drawings (default: $AGENTCAD_ROOT, else ~/AgentCAD)")
    s.add_argument("--freecad", metavar="PATH", help="FreeCAD 1.1 install folder (or its bin folder / python), if "
                                                     "it is not found automatically")
    s.add_argument("--launcher", choices=("auto", "uvx", "pipx", "python"), default="auto",
                   help="How the app starts the server: uvx or pipx (fetch AgentCAD from GitHub) or this Python. "
                        "auto: uvx (else pipx) when this copy runs from a uvx/pipx cache, else this Python")
    s.add_argument("--from", dest="source", metavar="SPEC", help="uvx/pipx package source (default: where this "
                                                                 "copy came from, else git+" + REPO_URL + ")")
    s.add_argument("--name", default="agentcad", help="Server name in the configs")
    s.add_argument("--dry-run", action="store_true", help="Show what would change; write nothing")
    s.add_argument("-y", "--yes", action="store_true", help="Do not ask; configure every app found")
    s.add_argument("--json", action="store_true", help="Print the result as JSON")
    s = sub.add_parser("doctor", help="Check Python, AgentCAD, FreeCAD, AutoCAD, Pillow and each app's MCP config",
                       description="Each check says ok, missing or skip, with a one-line fix.")
    s.add_argument("--root", dest="setup_root", metavar="FOLDER", help="Workspace folder to check")
    s.add_argument("--json", action="store_true", help="Print the result as JSON")
    s = sub.add_parser("mcp-config", help="Print (or --write) an MCP client config for this interpreter and --root")
    s.add_argument("--client", choices=("claude", "codex"), default="claude")
    s.add_argument("--name", default="agentcad", help="Server name in the config")
    s.add_argument("--write", nargs="?", const="", metavar="PATH",
                   help="Write it: claude merges into PATH (default ./.mcp.json), keeping other servers; "
                        "codex appends to PATH (default ~/.codex/config.toml)")
    s = sub.add_parser("serve", help="Run the HTTP JSON API"); s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s = sub.add_parser("viewer", help="Live web viewer of the root's drawings and parts (read-only)")
    s.add_argument("--host", default="127.0.0.1"); s.add_argument("--port", type=int, default=8770)
    s.add_argument("--allow-remote", action="store_true",
                   help="Allow a non-loopback --host and any Host header (the page has no authentication)")
    return ap


def _setup_or_doctor(a: argparse.Namespace) -> tuple[dict[str, Any], int]:
    from . import install
    root = a.setup_root or a.root
    if a.cmd == "doctor":
        r = install.doctor(root)
        print(json.dumps(r, ensure_ascii=False, indent=1) if a.json else install.render_doctor(r))
        return {"ok": True}, 0 if r["ok"] else 1
    clients = [c for c in (a.client or []) if c != "all"]
    if a.client and "all" in a.client:
        clients = list(install.CLIENTS)
    if not a.client:
        detected = install.detect_clients()
        if a.yes or a.json or not sys.stdin.isatty():
            clients = [c for c in install.CLIENTS if detected[c]]
        else:
            clients = install.ask_clients(detected)
    try:
        res = install.setup(list(dict.fromkeys(clients)), root, launcher=a.launcher, source=a.source,
                            freecad=a.freecad, dry_run=a.dry_run, read_only=a.read_only,
                            allow_scripts=a.allow_scripts, name=a.name)
    except AgentCADError as exc:
        return {"ok": False, "error": exc.to_dict()}, EXIT.get(exc.category, 5)
    print(json.dumps(res.to_dict(), ensure_ascii=False, indent=1) if a.json else install.render_setup(res))
    return {"ok": True}, 0 if res.ok else 1


def run(argv: list[str] | None = None) -> tuple[dict[str, Any], int]:
    a = build_parser().parse_args(argv)
    if a.cmd in ("setup", "doctor"):
        return _setup_or_doctor(a)
    if a.cmd == "mcp" and not a.root:
        from .install import ensure_workspace
        a.root = str(ensure_workspace())  # never the folder the client happens to start in
    policy = Policy(**({"root": Path(a.root)} if a.root else {}))
    if a.read_only:
        policy.read_only = True
    if a.allow_scripts:
        policy.allow_scripts = True
    if a.cmd == "mcp":
        from .mcp_server import serve_stdio
        serve_stdio(policy)
        return {"ok": True}, 0
    if a.cmd == "serve":
        from .http_api import serve
        from .errors import AgentCADError
        try:
            serve(policy, a.host, a.port)
        except AgentCADError as exc:
            return {"ok": False, "error": exc.to_dict()}, EXIT.get(exc.category, 5)
        return {"ok": True}, 0
    if a.cmd == "viewer":
        from .errors import AgentCADError
        from .viewer import Viewer
        try:
            Viewer(policy, a.host, a.port, allow_remote=a.allow_remote).serve()
        except AgentCADError as exc:
            return {"ok": False, "error": exc.to_dict()}, EXIT.get(exc.category, 5)
        except OSError as exc:
            return {"ok": False, "error": {"code": "PORT_IN_USE", "category": "input",
                                           "message": f"Cannot listen on {a.host}:{a.port}: {exc}",
                                           "hint": "Pass another --port"}}, 2
        return {"ok": True}, 0
    if a.cmd == "mcp-config":
        from .errors import AgentCADError
        from .mcp_config import mcp_config
        try:
            return mcp_config(policy, a.client, a.name, a.write), 0
        except AgentCADError as exc:
            return {"ok": False, "error": exc.to_dict()}, EXIT.get(exc.category, 5)
    rt = Runtime(policy)
    c = a.cmd
    if c == "create":
        r = rt.create_drawing(a.path, a.units, a.template, a.dxf_version, a.overwrite, a.annotation_scale)
    elif c == "inspect":
        r = rt.read_drawing(a.path)
    elif c == "image":
        r = rt.inspect_image(a.path, _json_arg(a.region, None, "region"), a.max_size, a.rotate,
                             _json_arg(a.dimensions, a.dimensions_file, "dimensions"))
    elif c == "measure":
        r = rt.measure_entities(a.path, _json_arg(a.target, None, "target"))
    elif c == "entities":
        flt = {k: v for k, v in (("type", a.type), ("layer", a.layer), ("tag", a.tag), ("tag_prefix", a.tag_prefix)) if v}
        r = rt.inspect_entities(a.path, filter=flt or None, ids=a.ids.split(",") if a.ids else None,
                                limit=a.limit, offset=a.offset, detail=not a.brief, layout=a.layout)
    elif c == "script":
        try:
            code = Path(a.file).read_text(encoding="utf-8")
        except OSError as exc:
            _die(f"cannot read script {a.file}: {exc}")
        r = rt.run_script(a.path, code, label=a.label, dry_run=a.dry_run, strict=a.strict,
                          requirements=_json_arg(None, a.requirements_file, "requirements"), language=a.language,
                          keep_features=a.keep_features)
    elif c == "apply":
        ops = _json_arg(a.ops, a.ops_file, "operations")
        if ops is None:
            _die("give --ops or --ops-file")
        if isinstance(ops, dict) and "operations" in ops:
            ops = ops["operations"]
        r = rt.apply_operations(a.path, ops, dry_run=a.dry_run, strict=a.strict, label=a.label,
                                requirements=_json_arg(None, a.requirements_file, "requirements"))
    elif c == "validate":
        bounds = None
        if a.bounds:
            v = [float(x) for x in a.bounds.split(",")]
            bounds = [[v[0], v[1]], [v[2], v[3]]]
        r = rt.validate_drawing(a.path, requirements=_json_arg(a.requirements, a.requirements_file, "requirements"),
                                use_stored_spec=not a.no_stored_spec, bounds=bounds, tolerance=a.tolerance,
                                contour_layers=a.contour_layers.split(",") if a.contour_layers else None,
                                layout=a.layout, detail=a.detail)
    elif c == "draw":
        r = rt.draw_from_spec(_json_arg(None, a.spec, "spec"), a.output, overwrite=a.overwrite, dxf_version=a.dxf_version)
    elif c == "revise":
        r = rt.revise_drawing(a.path, _json_arg(None, a.spec, "changes"), dry_run=a.dry_run)
    elif c == "constraints":
        cs = _json_arg(None, a.file, "constraints")
        if isinstance(cs, dict):
            cs = cs.get("constraints", [])
        r = rt.apply_constraints(a.path, cs, mode="enforce" if a.enforce else "check", tolerance=a.tolerance)
    elif c == "extract":
        r = rt.extract_requirements(a.document, _json_arg(None, a.facts_file, "facts"),
                                    _json_arg(None, a.overrides_file, "overrides"))
    elif c == "from-doc":
        r = rt.revise_from_document(a.document, a.output, _json_arg(None, a.facts_file, "facts"),
                                    _json_arg(None, a.overrides_file, "overrides"), overwrite=a.overwrite)
    elif c == "diff":
        r = rt.get_diff(a.path, a.against, a.detail)
    elif c == "rollback":
        r = rt.rollback(a.path, a.checkpoint)
    elif c == "checkpoints":
        r = rt.list_checkpoints(a.path)
    elif c == "history":
        r = rt.history(a.path, detail=a.detail, seq=a.seq)
    elif c == "recover":
        r = rt.recover(a.path)
    elif c == "export":
        fmt = a.format or Path(a.output).suffix.lstrip(".") or "dxf"
        r = rt.export_drawing(a.path, a.output, fmt, a.dxf_version, a.overwrite, a.layout, a.paper, a.scale,
                              a.orientation, a.monochrome)
    elif c == "import":
        r = rt.import_drawing(a.source, a.output, a.overwrite)
    elif c == "live":
        r = rt.autocad_live(a.action, a.path, start=a.start, discard=a.discard, ids=a.ids, command=a.command,
                            label=a.label, force=a.force)
    elif c == "library":
        r = rt.standard_library(a.item, a.size, a.drawing)
    elif c == "acad-audit":
        r = rt.autocad_audit(a.path)
    elif c == "ops":
        r = rt.list_operations(a.category, a.op, a.detail)
    else:  # pragma: no cover
        _die(f"unknown command {c}")
    if not r["ok"]:
        code = EXIT.get(r["error"]["category"], 5)
    elif (c == "validate" and not r["validation"]["passed"]) or (c == "acad-audit" and not r["passed"]):
        code = 1
    else:
        code = 0
    return r, code


def main(argv: list[str] | None = None) -> None:
    compact = "--compact" in (argv or sys.argv[1:])
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    r, code = run(argv)
    if r != {"ok": True}:
        print(json.dumps(r, ensure_ascii=False, indent=None if compact else 1, default=str))
    sys.exit(code)


if __name__ == "__main__":
    main()
