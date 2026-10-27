"""AutoCAD AUDIT of every H1 final drawing and H3 flange, and PNG renders of the H1 finals (run from PowerShell).

    python examples/trials/hard/acad_hard.py <A workspaces> <B workspaces>
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
sys.path.insert(0, str(HERE.parent))
from agentcad.backends import autocad  # noqa: E402
from render_png import render  # noqa: E402


def main() -> None:
    roots = {"A": Path(sys.argv[1]), "B": Path(sys.argv[2])}
    jobs = Path(tempfile.mkdtemp(prefix="acadhard"))
    out = {}
    for arm, root in roots.items():
        for rep in (1, 2, 3):
            f = HERE / "snapshots" / arm / f"H1_r{rep}" / "round5.dxf"
            if f.is_file():
                a = autocad.audit_dxf(f, jobs)
                out[f"{arm}/H1_r{rep}"] = a.get("audit_errors")
                png = render(f, HERE / "png" / arm)
                if png:
                    png.replace(png.with_name(f"H1_r{rep}.png"))
            errs = {}
            for f in sorted((root / f"H3_r{rep}").glob("FL-*.dxf")):
                errs[f.stem] = autocad.audit_dxf(f, jobs).get("audit_errors")
            out[f"{arm}/H3_r{rep}"] = errs
            print(arm, rep, out.get(f"{arm}/H1_r{rep}"), errs, flush=True)
    (HERE / "acad_hard.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
