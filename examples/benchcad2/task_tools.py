"""Input inspection and submission adapters; geometry is made by AgentCAD.

This process knows only the staged workspace, never a reference/case directory.
It deliberately does not import BenchCAD's reference renderer or scorers.
"""
from __future__ import annotations

import io
import json
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from agentcad.mcp_server import build_server
from agentcad.policy import Policy
from mcp.server.fastmcp import Image


def rigid_instances(instances: list[dict]) -> list[dict]:
    """Validate JSON placements without silently repairing a wrong transform."""
    import numpy as np

    if not instances:
        raise ValueError("Supply at least one instance")
    result, counts = [], {}
    for rec in instances:
        pid = rec["part_id"]
        if not isinstance(pid, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", pid):
            raise ValueError("part_id must be an id from bom.json")
        t = np.asarray(rec.get("transform", rec.get("T")), dtype=float)
        if (t.shape != (4, 4) or not np.isfinite(t).all()
                or not np.allclose(t[3], [0, 0, 0, 1], atol=1e-6, rtol=0)
                or not np.allclose(t[:3, :3] @ t[:3, :3].T, np.eye(3), atol=1e-6, rtol=0)
                or abs(np.linalg.det(t[:3, :3]) - 1) > 1e-6):
            raise ValueError(f"{pid}: transform must be a finite proper rigid 4x4 matrix")
        counts[pid] = counts.get(pid, 0) + 1
        result.append({"part_id": pid, "instance_id": rec.get("instance_id", f"{pid}_i{counts[pid]}"),
                       "transform": t.tolist()})
    names = [r["instance_id"] for r in result]
    if len(set(names)) != len(names):
        raise ValueError("instance_id must be unique")
    return result


def preview(shape) -> bytes:
    """A simple independent orthographic preview, not BenchCAD's renderer."""
    import numpy as np
    from PIL import Image as PILImage, ImageDraw

    vertices, triangles = shape.tessellate(0.3)
    v = np.array([p.toTuple() for p in vertices])
    f = np.array(triangles)
    if not len(v) or not len(f):
        raise ValueError("Shape has no triangles")
    v -= (v.min(axis=0) + v.max(axis=0)) / 2
    extent = float(np.ptp(v, axis=0).max())
    size = 480
    canvas = PILImage.new("RGB", (size * 2, size * 2), "white")
    directions = [(-1, -1, 1), (1, 1, 1), (-1, 1, -1), (1, -1, -1)]
    for i, direction in enumerate(directions):
        front = np.array(direction, dtype=float)
        front /= np.linalg.norm(front)
        right = np.cross([0., 0., 1.], front)
        right /= np.linalg.norm(right)
        up = np.cross(front, right)
        xy = np.column_stack([v @ right, -(v @ up)]) * (size * .60 / max(extent, 1e-9)) + size / 2
        depth = (v @ front)[f].mean(axis=1)
        pane = PILImage.new("RGB", (size, size), "white")
        draw = ImageDraw.Draw(pane)
        for k in np.argsort(depth):
            tri = f[k]
            n = np.cross(v[tri[1]] - v[tri[0]], v[tri[2]] - v[tri[0]])
            shade = .45 + .55 * abs(float(n @ front)) / max(float(np.linalg.norm(n)), 1e-12)
            color = tuple(int(c * shade) for c in (110, 195, 192))
            draw.polygon([tuple(p) for p in xy[tri]], fill=color)
        draw.text((8, 8), str(direction), fill="black")
        canvas.paste(pane, ((i % 2) * size, (i // 2) * size))
    out = io.BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


class TaskFiles:
    def __init__(self, root: Path, kind: str):
        self.policy = Policy(root=root, allow_scripts=True)
        self.root, self.kind = self.policy.root, kind
        self._submission_lock = threading.Lock()

    def path(self, value: str, *, exists: bool = True) -> Path:
        # Policy.resolve(must_exist=True) intentionally requires a CAD FILE;
        # this input browser also lists directories, after the same path checks.
        p = self.policy.resolve(value)
        if exists and not p.exists():
            raise FileNotFoundError(value)
        return p

    def part_path(self, pid: str) -> Path:
        # pid has already passed rigid_instances' validation.
        made = self.root / "submission" / "parts" / f"{pid}.step"
        return made if made.exists() else self.path(f"step_files/{pid}.step")

    def submit(self, path: str = "", instances: list[dict] | None = None,
               graph: dict | None = None) -> dict:
        with self._submission_lock:
            return self._submit(path, instances, graph)

    def _submit(self, path: str, instances: list[dict] | None, graph: dict | None) -> dict:
        marker_file = self.root / "answer.json"
        if marker_file.exists():
            return {"submitted": True, **json.loads(marker_file.read_text(encoding="utf-8")),
                    "message": "The first final answer is sealed; the episode has ended."}
        if self.kind == "part":
            answer = self.path(path)
            if answer.suffix.lower() not in (".step", ".stp"):
                raise ValueError("Submit the STEP exported with AgentCAD export_drawing")
        elif self.kind == "assembly":
            rows = rigid_instances(instances or [])
            bom = json.loads(self.path("bom.json").read_text(encoding="utf-8"))
            items = bom if isinstance(bom, list) else bom.get("items", [])
            supplied = [p for p in items if p.get("source") == "step"]
            for part in supplied:
                src = self.path(part["file"])
                dst = self.path(f"submission/parts/{part['part_id']}.step", exists=False)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            for row in rows:
                self.path(f"submission/parts/{row['part_id']}.step")
            answer = self.root / "submission"
            table = answer / "assembly" / "instances.json"
            table.parent.mkdir(parents=True, exist_ok=True)
            table.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        else:
            if not isinstance(graph, dict):
                raise ValueError("Supply the terminal-net graph dict requested by the task")
            # JSON must be finite; do not silently emit NaN/Infinity.
            encoded = json.dumps(graph, indent=2, allow_nan=False)
            answer = self.root / "pred_graph.json"
            answer.write_text(encoded, encoding="utf-8")
        # Runtime tools reject .agentcad/ paths. Seal the first explicit answer
        # there, so later edits to a working STEP cannot change what is scored.
        state = self.root / ".agentcad"
        state.mkdir(exist_ok=True)
        sealed = Path(tempfile.mkdtemp(prefix="benchcad2-submission-", dir=state)) / answer.name
        if answer.is_dir():
            shutil.copytree(answer, sealed)
        else:
            shutil.copy2(answer, sealed)
        marker = {"path": sealed.relative_to(self.root).as_posix(), "kind": self.kind}
        temporary = self.root / "answer.json.tmp"
        temporary.write_text(json.dumps(marker), encoding="utf-8")
        temporary.replace(marker_file)
        self.policy.read_only = True
        return {"submitted": True, **marker, "message": "Final answer recorded. End the task now."}


def server(root: Path, kind: str):
    files = TaskFiles(root, kind)
    # Keep the benchmark's direct tool surface stable even if the caller uses
    # the product's optional discovery profile in its normal sessions.
    mcp = build_server(files.policy, profile="full")

    @mcp.tool()
    def read_workspace(path: str = ".", box: list[int] | None = None) -> list:
        """List a workspace directory or read UTF-8 text/JSON or display a PNG.
        Optional image box [left, top, right, bottom] crops in original pixels;
        for a staged drawing it uses the matching 2x hires master when available.
        For STEP geometry use inspect_step. All paths are workspace-relative.
        """
        from PIL import Image as PILImage

        p = files.path(path)
        if p.is_dir():
            names = sorted(x.relative_to(files.root).as_posix() + ("/" if x.is_dir() else "")
                           for x in p.iterdir() if not x.name.startswith("."))
            return ["\n".join(names[:250])]
        if p.suffix.lower() == ".png":
            im = PILImage.open(p).convert("RGB")
            if box is not None:
                if len(box) != 4 or box[2] <= box[0] or box[3] <= box[1]:
                    raise ValueError("box is [left, top, right, bottom] with positive area")
                master = p.parent / "hires" / p.name
                if master.exists():
                    im = PILImage.open(master).convert("RGB")
                    box = [x * 2 for x in box]
                im = im.crop(box)
            im.thumbnail((2000, 2000))
            b = io.BytesIO()
            im.save(b, format="PNG")
            return [Image(data=b.getvalue(), format="png")]
        if p.suffix.lower() not in (".json", ".md", ".txt"):
            raise ValueError("Read supports directories, PNG, JSON, Markdown and text")
        return [p.read_text(encoding="utf-8")[:40000]]

    @mcp.tool()
    def inspect_step(path: str, show_preview: bool = True, face_limit: int = 60) -> list:
        """Inspect an INPUT or submitted STEP: box, volume, solids and face geometry.
        Optionally display an independent four-view preview in world XYZ.
        """
        import cadquery as cq

        shape = cq.importers.importStep(str(files.path(path))).val()
        b = shape.BoundingBox()
        faces = [{"index": i + 1, "type": f.geomType(), "area": f.Area(),
                  "center": f.Center().toTuple(),
                  "bbox": [f.BoundingBox().xmin, f.BoundingBox().ymin, f.BoundingBox().zmin,
                           f.BoundingBox().xmax, f.BoundingBox().ymax, f.BoundingBox().zmax]}
                 for i, f in enumerate(shape.Faces()[:max(0, min(face_limit, 250))])]
        out = [json.dumps({"bbox": [b.xmin, b.ymin, b.zmin, b.xmax, b.ymax, b.zmax],
                           "volume": shape.Volume(), "solids": len(shape.Solids()),
                           "face_count": len(shape.Faces()), "faces": faces})]
        if show_preview:
            out.append(Image(data=preview(shape), format="png"))
        return out

    @mcp.tool()
    def preview_assembly(instances: list[dict]) -> list:
        """Preview proposed rigid placements (part_id, transform); does not submit.
        Reads modelled submission/parts/<id>.step or supplied step_files/<id>.step.
        """
        import cadquery as cq

        rows = rigid_instances(instances)
        # CadQuery's nested-list Matrix is a gp_GTrsf tagged as "other", even
        # for an exact 90-degree rotation. transformShape requires gp_Trsf and
        # rejects it. The general transform applies the supplied matrix as-is;
        # it changes only this preview, never submitted geometry or placements.
        shapes = [cq.importers.importStep(str(files.part_path(r["part_id"]))).val()
                  .transformGeometry(cq.Matrix(r["transform"])) for r in rows]
        return [Image(data=preview(cq.Compound.makeCompound(shapes)), format="png")]

    @mcp.tool()
    def submit_answer(path: str = "", instances: list[dict] | None = None,
                      graph: dict | None = None) -> dict:
        """Final submission, then end the task. Parts: path to AgentCAD-exported STEP.
        Assemblies: instances [{part_id, instance_id?, transform: rigid 4x4}]; supplied
        parts are copied unchanged; modelled parts must already be exported by
        AgentCAD to submission/parts/<part_id>.step. PCB: graph as requested in TASK.
        No ground-truth score is available during the task.
        """
        return files.submit(path, instances, graph)

    return mcp


if __name__ == "__main__":
    server(Path(sys.argv[1]), sys.argv[2]).run(transport="stdio")
