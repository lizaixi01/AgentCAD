"""Render a STEP file the way BenchCAD renders its Vision2Code inputs: the same 2x2 composite of four diagonal views,
the same camera positions, framing and colors. Copied into each workspace of the code arm.

    python render.py submission.step preview.png
"""
import os
import sys
from pathlib import Path

# BENCHCAD_SRC: the folder holding BenchCAD-main, as for prepare.py and score.py
sys.path.insert(0, str(Path(os.environ.get("BENCHCAD_SRC", r"D:\Projects\bench-src")) / "BenchCAD-main"))
from benchcad_core.scoring.views import composite_for_step  # noqa: E402

out = Path(sys.argv[2])
out.unlink(missing_ok=True)  # composite_for_step keeps an output newer than the STEP
composite_for_step(Path(sys.argv[1]), out)
print(f"wrote {out}")
