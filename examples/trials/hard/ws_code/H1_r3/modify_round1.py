"""Round 1: widen only the installation plate and its associated annotations.

Run with the supplied Python interpreter. No third-party packages except ezdxf.
The immutable backup is the reference for this round; the script refuses to
repeat the operation on an already modified drawing.
"""
from pathlib import Path
import hashlib
import json
import math
import shutil

import ezdxf
from ezdxf import bbox
from ezdxf.lldxf.tagwriter import TagCollector


ROOT = Path(__file__).resolve().parent
PART = ROOT / "part.dxf"
BACKUP = ROOT / "part.round1.before.dxf"
STAGED = ROOT / "part.round1.checked.dxf"
REPORT = ROOT / "round1_verification.json"


def fingerprint(entity):
    return [(tag.code, str(tag.value)) for tag in TagCollector.dxftags(entity)]


def snapshot(doc):
    return {e.dxf.handle: fingerprint(e) for e in doc.entitydb.values() if e.is_alive}


def near(actual, expected):
    assert math.isclose(actual, expected, abs_tol=1e-8), (actual, expected)


def point(actual, expected):
    for a, b in zip(actual, expected):
        near(a, b)


def check(original, changed, allowed):
    assert changed.units == original.units == 4
    before, after = snapshot(original), snapshot(changed)
    assert before.keys() == after.keys(), "Entity handles were added or removed"
    differences = {h for h in before if before[h] != after[h]}
    assert differences == allowed, ("Unexpected entity changes", differences ^ allowed)
    assert len(changed.modelspace()) == len(original.modelspace()) == 15

    outline = changed.entitydb["91"]
    expected_points = [
        (5, 0), (145, 0), (150, 5), (150, 75),
        (145, 80), (5, 80), (0, 75), (0, 5),
    ]
    assert outline.closed
    old_points = list(original.entitydb["91"].get_points())
    for index, (actual, expected) in enumerate(zip(outline.get_points(), expected_points)):
        point(actual[:2], expected)
        point(actual[2:], old_points[index][2:])  # widths and arc bulges unchanged
    bounds = bbox.extents([outline])
    near(bounds.extmin.x, 0)
    near(bounds.extmin.y, 0)
    near(bounds.extmax.x, 150)
    near(bounds.extmax.y, 80)
    # The round corners remain quarter circles of radius 5.
    for index in (1, 3, 5, 7):
        p = outline.get_points()[index]
        q = outline.get_points()[(index + 1) % 8]
        radius = math.hypot(q[0] - p[0], q[1] - p[1]) * (1 + p[4] ** 2) / (4 * p[4])
        near(radius, 5)

    centers = {"92": (12, 12, 0), "93": (138, 12, 0),
               "94": (12, 68, 0), "95": (138, 68, 0)}
    for handle, center in centers.items():
        hole = changed.entitydb[handle]
        point(hole.dxf.center, center)
        near(hole.dxf.radius, 5)
    for handle in ("93", "95"):
        near(150 - changed.entitydb[handle].dxf.center.x, 12)

    width = changed.entitydb["96"]
    near(width.get_measurement(), 150)
    point(width.dxf.defpoint2, (0, 5, 0))
    point(width.dxf.defpoint3, (150, 5, 0))
    point(width.dxf.text_midpoint, (75, -12.625, 0))
    assert width.dxf.text == "<>"
    assert changed.entitydb["A1"].text == "150"
    point(changed.entitydb["9B"].dxf.start, (150, 4.375, 0))
    point(changed.entitydb["9B"].dxf.end, (150, -16.25, 0))
    point(changed.entitydb["9E"].dxf.insert, (150, -15, 0))
    point(changed.entitydb["A0"].dxf.end, (147.5, -15, 0))
    point(changed.entitydb["A1"].dxf.insert, (75, -12.625, 0))
    point(changed.entitydb["A4"].dxf.location, (150, 5, 0))

    diameter = changed.entitydb["D2"]
    near(diameter.get_measurement(), 10)
    point((diameter.dxf.defpoint + diameter.dxf.defpoint4) / 2, (138, 68, 0))
    assert changed.entitydb["DD"].text == "4X %%c10"
    audit = changed.audit()
    assert not audit.errors and not audit.fixes, (audit.errors, audit.fixes)
    return sorted(differences), len(before) - len(differences)


def main():
    doc = ezdxf.readfile(PART)
    near(doc.entitydb["96"].get_measurement(), 120)
    assert doc.entitydb["A1"].text == "120"
    if BACKUP.exists():
        assert BACKUP.read_bytes() == PART.read_bytes(), "Existing backup differs; refusing to overwrite it"
    else:
        shutil.copy2(PART, BACKUP)
    original = ezdxf.readfile(BACKUP)

    # Stretch just the four vertices defining the right end. Preserve bulges.
    outline = doc.entitydb["91"]
    points = [list(p) for p in outline.get_points()]
    for index in (1, 2, 3, 4):
        points[index][0] += 30
    outline.set_points(points)
    for handle in ("93", "95"):
        hole = doc.entitydb[handle]
        hole.dxf.center = hole.dxf.center + (30, 0, 0)

    # Update both the semantic dimension and its existing display block, keeping
    # all entity handles, styles, arrow sizes, and unrelated blocks intact.
    width = doc.entitydb["96"]
    width.dxf.defpoint3 = (150, 5, 0)
    width.dxf.text_midpoint = (75, -12.625, 0)
    doc.entitydb["9B"].translate(30, 0, 0)
    doc.entitydb["9E"].dxf.insert = (150, -15, 0)
    doc.entitydb["A0"].dxf.end = (147.5, -15, 0)
    doc.entitydb["A1"].dxf.insert = (75, -12.625, 0)
    doc.entitydb["A1"].text = "150"
    doc.entitydb["A4"].dxf.location = (150, 5, 0)

    # The existing diameter callout belongs to the upper-right hole. Translate
    # its defining points and display block together so it still identifies it.
    diameter = doc.entitydb["D2"]
    diameter_block_handles = {e.dxf.handle for e in doc.blocks[diameter.dxf.geometry]}
    diameter.translate(30, 0, 0)
    allowed = {"91", "93", "95", "96", "9B", "9E", "A0", "A1", "A4", "D2"} | diameter_block_handles

    # ezdxf normally rewrites timestamps, GUIDs, and HANDSEED during export.
    # This edit creates no entities; preserve these original document values as
    # well. Keeping HANDSEED also keeps the same transient empty-INSERT SEQEND
    # handles on reload, making the complete entity comparison deterministic.
    doc._update_metadata = lambda: None
    doc.saveas(STAGED)
    reread = ezdxf.readfile(STAGED)
    differences, unchanged = check(original, reread, allowed)
    # Replace the deliverable only after the serialized result passes all checks.
    shutil.copyfile(STAGED, PART)
    final = ezdxf.readfile(PART)
    check(original, final, allowed)
    report = {
        "round": 1,
        "deliverable": PART.name,
        "original_backup": BACKUP.name,
        "units": "mm",
        "plate_width": 150,
        "plate_height": 80,
        "corner_radius": 5,
        "hole_diameter": 10,
        "hole_centers": [[12, 12], [138, 12], [12, 68], [138, 68]],
        "right_hole_center_to_right_edge": [12, 12],
        "width_dimension_measurement_and_display": 150,
        "diameter_callout_moved_with_upper_right_hole": True,
        "changed_entity_handles": differences,
        "unchanged_entity_count": unchanged,
        "modelspace_entity_count": 15,
        "audit_errors": 0,
        "audit_fixes": 0,
        "unrelated_content_preserved": "All other entity DXF tags, including title attributes, technical notes, logo, layers and other dimensions, compare equal to the backup.",
        "layout_limitation": "The widened plate overlaps the original customer logo region x=135..155, y=60..75. Logo intentionally remains in its original position as requested.",
        "part_sha256": hashlib.sha256(PART.read_bytes()).hexdigest(),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
