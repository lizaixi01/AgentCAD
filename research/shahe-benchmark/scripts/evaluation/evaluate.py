"""Deterministic surface and silhouette comparison; does not estimate rotation.

Usage: python evaluate.py REFERENCE_MESH CANDIDATE_MESH OUTPUT_DIR
Meshes must already share axis orientation. Units may differ. Reference remains
outside the repository; do not expose results to either modeling session.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree
import trimesh


def load_mesh(path):
    obj = trimesh.load(path, force="scene", process=False)
    mesh = obj.to_geometry()
    if not isinstance(mesh, trimesh.Trimesh) or not len(mesh.faces):
        raise ValueError(f"No triangular mesh: {path}")
    if not np.isfinite(mesh.vertices).all() or mesh.area <= 0:
        raise ValueError(f"Invalid coordinates or area: {path}")
    return mesh


def normalized(mesh):
    result = mesh.copy()
    bounds = result.bounds
    extent = bounds[1] - bounds[0]
    scale = float(np.max(extent))
    if scale <= 0:
        raise ValueError("Degenerate bounding box")
    result.vertices = (result.vertices - (bounds[0] + bounds[1]) / 2) / scale
    return result, {"center": ((bounds[0] + bounds[1]) / 2).tolist(), "scale": scale}


def mask(mesh, axes, size=512):
    # Fixed image plane [-0.55, 0.55]; each triangle projects to a filled polygon.
    img = Image.new("1", (size, size), 0)
    draw = ImageDraw.Draw(img)
    points = mesh.vertices[:, axes]
    pixels = (points + 0.55) * ((size - 1) / 1.1)
    pixels[:, 1] = (size - 1) - pixels[:, 1]
    for triangle in mesh.faces:
        draw.polygon([tuple(p) for p in pixels[triangle]], fill=1)
    return np.asarray(img, dtype=bool)


def compare(reference, candidate, outdir, samples=20000, size=512):
    ref_raw = load_mesh(reference)
    cand_raw = load_mesh(candidate)
    ref, r_transform = normalized(ref_raw)
    cand, c_transform = normalized(cand_raw)
    rp, _ = trimesh.sample.sample_surface(ref, samples, seed=41017)
    cp, _ = trimesh.sample.sample_surface(cand, samples, seed=41017)
    d_ref = cKDTree(cp).query(rp, workers=1)[0]
    d_cand = cKDTree(rp).query(cp, workers=1)[0]
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    views = {}
    # Orthographic silhouettes for opposite directions are identical for opaque meshes.
    for name, axes in {"front_back": (0, 2), "left_right": (1, 2), "top": (0, 1)}.items():
        rm, cm = mask(ref, axes, size), mask(cand, axes, size)
        union = np.count_nonzero(rm | cm)
        views[name] = float(np.count_nonzero(rm & cm) / union) if union else None
        diff = np.zeros((size, size, 3), dtype=np.uint8)
        diff[rm & cm] = (220, 220, 220)
        diff[rm & ~cm] = (220, 60, 60)
        diff[cm & ~rm] = (50, 120, 240)
        Image.fromarray(diff).save(outdir / f"{name}.png")
    def quality(m):
        diagnostic = m.copy()
        diagnostic.merge_vertices()
        return {"vertices": len(m.vertices), "faces": len(m.faces), "watertight_after_vertex_merge": bool(diagnostic.is_watertight), "winding_consistent_after_vertex_merge": bool(diagnostic.is_winding_consistent), "bounds": m.bounds.tolist()}
    result = {"normalization": "center each bounding box; divide all axes by its longest extent; no rotation", "transforms": {"first": r_transform, "second": c_transform}, "quality": {"first": quality(ref_raw), "second": quality(cand_raw)}, "surface_samples_each": samples, "seed": 41017, "chamfer_mean_symmetric_unsquared": float((d_ref.mean() + d_cand.mean()) / 2), "silhouette_iou": views, "pixel_size": size, "volume_iou": None, "volume_iou_reason": "not implemented; watertightness alone is insufficient to establish valid volumes"}
    (outdir / "metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference")
    parser.add_argument("candidate")
    parser.add_argument("output")
    args = parser.parse_args()
    compare(args.reference, args.candidate, args.output)
