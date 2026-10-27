"""Experiment A2: which parts of ezdxf's R12 export make AutoCAD AUDIT complain?
Builds variants of the R12 file with table entries removed and imports each."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import ezdxf

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from acad import WORK, run_lisp  # noqa: E402

ROOT = HERE.parents[1]
SRC = ROOT / "examples/output/A_mounting_plate_100x60_R12.dxf"


def variant(name: str, drop_ltypes=(), keep_styles=None, keep_dimstyles=None) -> Path:
    doc = ezdxf.readfile(SRC)
    for n in drop_ltypes:
        if n in doc.linetypes:
            doc.linetypes.remove(n)
    if keep_styles is not None:
        for s in [s.dxf.name for s in doc.styles]:
            if s.upper() not in keep_styles:
                doc.styles.remove(s)
    if keep_dimstyles is not None:
        for s in [s.dxf.name for s in doc.dimstyles]:
            if s.upper() not in keep_dimstyles:
                doc.dimstyles.remove(s)
    out = WORK / "r12_variants" / f"{name}.dxf"
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.saveas(out)
    return out


def errors(p: Path) -> tuple[str, list[str]]:
    r = run_lisp("r12_" + p.stem, '(command "_.DXFIN" "%DIR%/in.dxf")\n(out "done" 1)', files={"in.dxf": p})
    seg = r.log[r.log.find("DXFIN"):]
    total = [l.strip() for l in seg.splitlines() if "共发现" in l]
    kinds = sorted({l.strip() for l in seg.splitlines() if "重复" in l or "无效" in l})
    return (total[0] if total else "?"), kinds


if __name__ == "__main__":
    used_dim = {"STANDARD", "AGENTCAD"}
    rows = {}
    for name, kw in {
        "orig": {},
        "no_byltypes": {"drop_ltypes": ("BYBLOCK", "BYLAYER")},
        "std_style_only": {"keep_styles": {"STANDARD"}},
        "no_byltypes_std_style": {"drop_ltypes": ("BYBLOCK", "BYLAYER"), "keep_styles": {"STANDARD"}},
        "no_byltypes_std_style_dims": {"drop_ltypes": ("BYBLOCK", "BYLAYER"), "keep_styles": {"STANDARD"},
                                       "keep_dimstyles": used_dim},
    }.items():
        p = variant(name, **kw)
        rows[name] = errors(p)
        print(name, rows[name])
    (HERE / "results").mkdir(exist_ok=True)
    (HERE / "results" / "exp_r12_bisect.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), "utf-8")
