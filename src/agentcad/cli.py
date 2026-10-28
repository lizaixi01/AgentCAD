"""``agentcad`` command-line interface. Every command prints one JSON envelope
on stdout. Exit codes: 0 ok, 1 validation failed, 2 input/spec/geometry
error, 3 file error, 4 policy refusal, 5 internal error, 6 optional dependency missing."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .policy import Policy
from .service import Runtime

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
    ap = argparse.ArgumentParser(prog="agentcad", description="Headless agent-native 2D CAD runtime (DXF)")
    ap.add_argument("--root", help="Workspace root (default: $AGENTCAD_ROOT or cwd); all paths must be inside it")
    ap.add_argument("--read-only", action="store_true", help="Refuse every modification")
    ap.add_argument("--allow-scripts", action="store_true", help="Enable the 'script' command (agent-written ezdxf scripts)")
    ap.add_argument("--compact", action="store_true", help="Single-line JSON output")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("create", help="Create an empty drawing")
    s.add_argument("path"); s.add_argument("--units", default="mm"); s.add_argument("--template", default="mechanical")
    s.add_argument("--dxf-version", default="R2010"); s.add_argument("--overwrite", action="store_true")
    s.add_argument("--annotation-scale", type=float, default=1.0, help="Plot scale 1:N for dimension/linetype sizes")

    s = sub.add_parser("inspect", help="Drawing summary: units, extents, layers, counts, tags, metadata")
    s.add_argument("path")

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

    s = sub.add_parser("script", help="Run an ezdxf script on a drawing as one transaction (needs --allow-scripts)")
    s.add_argument("path"); s.add_argument("--file", required=True, help="Python file; the drawing is `doc`")
    s.add_argument("--requirements-file"); s.add_argument("--dry-run", action="store_true")
    s.add_argument("--strict", action="store_true"); s.add_argument("--label")

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

    s = sub.add_parser("export", help="Export to dxf (other version, incl. R12) / svg / json")
    s.add_argument("path"); s.add_argument("output"); s.add_argument("--format", default=None)
    s.add_argument("--dxf-version"); s.add_argument("--overwrite", action="store_true")

    s = sub.add_parser("import", help="Import a DWG as DXF (optional AutoCAD backend)")
    s.add_argument("source"); s.add_argument("output"); s.add_argument("--overwrite", action="store_true")
    s = sub.add_parser("acad-audit", help="Run AutoCAD's AUDIT on a drawing (optional AutoCAD backend)")
    s.add_argument("path")

    s = sub.add_parser("ops", help="Operation index; --op/--category/--detail for JSON schemas"); s.add_argument("--category"); s.add_argument("--op", action="append", help="Full schema of this op (repeatable)"); s.add_argument("--detail", action="store_true")
    sub.add_parser("mcp", help="Run the MCP server on stdio")
    s = sub.add_parser("mcp-config", help="Print (or --write) an MCP client config for this interpreter and --root")
    s.add_argument("--client", choices=("claude", "codex"), default="claude")
    s.add_argument("--name", default="agentcad", help="Server name in the config")
    s.add_argument("--write", nargs="?", const="", metavar="PATH",
                   help="Write it: claude merges into PATH (default ./.mcp.json), keeping other servers; "
                        "codex appends to PATH (default ~/.codex/config.toml)")
    s = sub.add_parser("serve", help="Run the HTTP JSON API"); s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    return ap


def run(argv: list[str] | None = None) -> tuple[dict[str, Any], int]:
    a = build_parser().parse_args(argv)
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
        serve(policy, a.host, a.port)
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
                          requirements=_json_arg(None, a.requirements_file, "requirements"))
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
        r = rt.export_drawing(a.path, a.output, fmt, a.dxf_version, a.overwrite)
    elif c == "import":
        r = rt.import_drawing(a.source, a.output, a.overwrite)
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
