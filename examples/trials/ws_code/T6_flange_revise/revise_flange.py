"""Revise the supplied flange using ezdxf only; verify and call get_diff."""
import json
import math
import shutil
import sys
from pathlib import Path

import ezdxf
from ezdxf.math import Vec3

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "flange.dxf"
BEFORE = ROOT / "flange_before.dxf"
TOL = 1e-8


def close(a, b):
    return abs(a - b) < TOL


def state(entity):
    # JSON roundtrip converts Vec3 and other DXF values to comparable data.
    attrs = entity.dxf.all_existing_dxf_attribs().copy()
    if entity.dxftype() == "MTEXT":
        attrs["content"] = entity.text
    return json.loads(json.dumps(attrs, default=lambda v: list(v)))


def rendered_text(doc, dim):
    return [e.text if e.dxftype() == "MTEXT" else e.dxf.text
            for e in doc.blocks[dim.dxf.geometry]
            if e.dxftype() in ("TEXT", "MTEXT")]


def get_diff(before_path, after_path):
    """Local semantic DXF diff; no external get_diff tool is exposed here."""
    before = ezdxf.readfile(before_path)
    after = ezdxf.readfile(after_path)
    old = {e.dxf.handle: e for e in before.modelspace()}
    new = {e.dxf.handle: e for e in after.modelspace()}
    changed = []
    for handle in sorted(old.keys() & new.keys()):
        a, b = state(old[handle]), state(new[handle])
        fields = {k: {"before": a.get(k), "after": b.get(k)}
                  for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k)}
        if fields:
            item = {"handle": handle, "type": new[handle].dxftype(), "fields": fields}
            if new[handle].dxftype() == "DIMENSION":
                item["rendered_text_before"] = rendered_text(before, old[handle])
                item["rendered_text_after"] = rendered_text(after, new[handle])
            changed.append(item)
    added = [{"type": new[h].dxftype(), "attributes": state(new[h])}
             for h in sorted(new.keys() - old.keys())]
    removed = [{"type": old[h].dxftype(), "attributes": state(old[h])}
               for h in sorted(old.keys() - new.keys())]
    old_blocks = {b.name for b in before.blocks}
    new_blocks = {b.name for b in after.blocks}
    return {"method": "local Python get_diff using ezdxf",
            "before": before_path.name, "after": after_path.name,
            "modelspace": {"modified_count": len(changed), "added_count": len(added),
                           "removed_count": len(removed), "modified": changed,
                           "added": added, "removed": removed},
            "dimension_blocks_removed": sorted(old_blocks - new_blocks),
            "dimension_blocks_added": sorted(new_blocks - old_blocks)}


def rerender(doc, dimension):
    old_block = dimension.dxf.geometry
    dimension.override().render()
    # Remove obsolete dimension graphics, including stale annotation text.
    assert not any(e.is_alive and
                   ((e.dxftype() == "DIMENSION" and e.dxf.get("geometry") == old_block) or
                    (e.dxftype() == "INSERT" and e.dxf.name == old_block))
                   for e in doc.entitydb.values())
    # ezdxf safe=True rejects all anonymous *D blocks, even when unreferenced.
    doc.blocks.delete_block(old_block, safe=False)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    original = ezdxf.readfile(BEFORE if BEFORE.exists() else SOURCE)
    assert original.units == 4, "Expected millimetres"
    msp = original.modelspace()
    holes = list(msp.query('CIRCLE[layer=="HOLES"]'))
    pitch, = [e for e in msp.query('CIRCLE[layer=="CENTER"]')
              if close(e.dxf.radius, 55)]
    assert len(holes) == 6 and all(close(e.dxf.radius, 6) for e in holes)
    assert all(close(e.dxf.center.magnitude, 55) for e in holes)
    hole_dim, = [d for d in msp.query("DIMENSION") if d.dxf.text == "6\u00d7\u00d812"]
    pitch_dim, = [d for d in msp.query("DIMENSION") if close(d.get_measurement(), 110)]
    expected_modified = {e.dxf.handle for e in holes} | {
        pitch.dxf.handle, hole_dim.dxf.handle, pitch_dim.dxf.handle}
    untouched = {e.dxf.handle: state(e) for e in msp
                 if e.dxf.handle not in expected_modified}
    untouched_blocks = {d.dxf.geometry: [state(e) for e in original.blocks[d.dxf.geometry]]
                        for d in msp.query("DIMENSION")
                        if d not in (hole_dim, pitch_dim)}
    if not BEFORE.exists():
        shutil.copy2(SOURCE, BEFORE)

    pitch.dxf.radius = 57.5
    # Reuse six original circles, preserving their layer and entity properties.
    for index in range(8):
        circle = holes[index] if index < 6 else holes[0].copy()
        angle = math.radians(90 + 45 * index)
        x, y = 57.5 * math.cos(angle), 57.5 * math.sin(angle)
        circle.dxf.center = (0 if abs(x) < TOL else x, 0 if abs(y) < TOL else y, 0)
        circle.dxf.radius = 6
        if index >= 6:
            msp.add_entity(circle)

    # Move the actual diameter definition onto the relocated top hole.
    hole_dim.translate(0, 2.5, 0)
    hole_dim.dxf.text = "8\u00d7\u00d812"
    hole_dim.dxf.actual_measurement = 12
    rerender(original, hole_dim)

    # Update both diameter endpoints, cached measurement, and displayed graphics.
    for field in ("defpoint", "defpoint4"):
        pitch_dim.dxf.set(field, Vec3(pitch_dim.dxf.get(field)) * (115 / 110))
    pitch_dim.dxf.actual_measurement = 115
    pitch_dim.dxf.text = "<>"
    rerender(original, pitch_dim)
    original.saveas(SOURCE)

    # Validate the saved file, not just the in-memory model.
    result = ezdxf.readfile(SOURCE)
    audit = result.audit()
    assert not audit.errors and not audit.fixes
    assert result.units == 4 and result.dxfversion == original.dxfversion
    final_holes = list(result.modelspace().query('CIRCLE[layer=="HOLES"]'))
    assert len(final_holes) == 8
    assert all(close(c.dxf.radius, 6) and close(c.dxf.center.magnitude, 57.5)
               and close(c.dxf.center.z, 0) for c in final_holes)
    angles = sorted(math.degrees(math.atan2(c.dxf.center.y, c.dxf.center.x)) % 360
                    for c in final_holes)
    gaps = [(angles[(i + 1) % 8] - angles[i]) % 360 for i in range(8)]
    assert all(close(gap, 45) for gap in gaps)
    assert final_holes[0].dxf.center.isclose(Vec3(0, 57.5, 0), abs_tol=TOL)
    assert close(result.entitydb[pitch.dxf.handle].dxf.radius * 2, 115)
    hd, pd = result.entitydb[hole_dim.dxf.handle], result.entitydb[pitch_dim.dxf.handle]
    assert hd.dxf.text == "8\u00d7\u00d812" and close(hd.get_measurement(), 12)
    assert rendered_text(result, hd) == ["8\u00d7%%c12"]
    for field in ("defpoint", "defpoint4"):
        assert close((Vec3(hd.dxf.get(field)) - Vec3(0, 57.5, 0)).magnitude, 6)
        assert close(Vec3(pd.dxf.get(field)).magnitude, 57.5)
    assert close(pd.get_measurement(), 115) and close(pd.dxf.actual_measurement, 115)
    assert pd.dxf.text == "<>" and rendered_text(result, pd) == ["%%c115"]
    for handle, expected in untouched.items():
        assert state(result.entitydb[handle]) == expected, handle
    for name, expected in untouched_blocks.items():
        assert [state(e) for e in result.blocks[name]] == expected, name
    assert sorted(c.dxf.radius * 2 for c in result.modelspace().query('CIRCLE[layer=="OUTLINE"]')) == [60, 150]
    for block in result.blocks:
        for e in block:
            if e.dxftype() == "MTEXT":
                assert "110" not in e.text and "6\u00d7" not in e.text

    diff = get_diff(BEFORE, SOURCE)
    assert diff["modelspace"]["modified_count"] == 9
    assert diff["modelspace"]["added_count"] == 2
    assert diff["modelspace"]["removed_count"] == 0
    (ROOT / "flange_diff.json").write_text(json.dumps(diff, ensure_ascii=False, indent=2), encoding="utf-8")
    checks = {"status": "PASS", "units": "mm", "hole_count": 8, "hole_diameter": 12,
              "pitch_diameter": 115, "angular_spacing_deg": gaps,
              "first_hole_center": list(final_holes[0].dxf.center),
              "hole_centers": [list(c.dxf.center) for c in final_holes],
              "hole_annotation": hd.dxf.text, "pitch_measurement": pd.get_measurement(),
              "pitch_rendered_text": rendered_text(result, pd),
              "outer_diameter": 150, "bore_diameter": 60,
              "audit_errors": len(audit.errors), "audit_fixes": len(audit.fixes),
              "unchanged_entity_count": len(untouched)}
    (ROOT / "flange_verification.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    print("get_diff: 9 modelspace entities modified, 2 circles added, 0 removed; 2 dimension graphics blocks regenerated.")


if __name__ == "__main__":
    main()
