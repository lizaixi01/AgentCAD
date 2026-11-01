"""Synthetic smoke test independent of any protected reference model."""
import tempfile
from pathlib import Path
import trimesh
from evaluate import compare

with tempfile.TemporaryDirectory() as tmp:
    p = Path(tmp)
    box = trimesh.creation.box(extents=[2, 1, 1])
    box.export(p / "a.stl")
    box.export(p / "b.stl")
    shifted = trimesh.creation.box(extents=[2, 1, 0.4])
    shifted.export(p / "c.stl")
    same = compare(p / "a.stl", p / "b.stl", p / "same", samples=1000, size=128)
    different = compare(p / "a.stl", p / "c.stl", p / "different", samples=1000, size=128)
    assert all(v == 1 for v in same["silhouette_iou"].values())
    assert different["silhouette_iou"]["front_back"] < 1
    assert same["chamfer_mean_symmetric_unsquared"] < different["chamfer_mean_symmetric_unsquared"]
    print("Synthetic evaluation smoke test passed")
