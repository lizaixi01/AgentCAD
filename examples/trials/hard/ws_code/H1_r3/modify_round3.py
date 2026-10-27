"""Add only the central diameter-30 hole and its diameter dimension (round 3)."""
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
BACKUP = ROOT / "part.round3.before.dxf"
STAGED = ROOT / "part.round3.checked.dxf"
REPORT = ROOT / "round3_verification.json"


def near(a, b):
    assert math.isclose(a, b, rel_tol=0, abs_tol=1e-8), (a, b)


def point(a, b):
    assert len(a) == len(b)
    for x, y in zip(a, b):
        near(x, y)


def snapshot(doc):
    # ezdxf synthesizes SEQENDs on reading empty INSERTs. They are not stored
    # in this DXF and receive new handles after HANDSEED advances. Exclude
    # only these unpersisted placeholders from the entity comparison.
    ephemeral = {
        e.seqend.dxf.handle for e in doc.entitydb.values()
        if e.is_alive and e.dxftype() == "INSERT" and not e.attribs
        and e.seqend is not None
    }
    return {
        e.dxf.handle: [(t.code, str(t.value)) for t in TagCollector.dxftags(e)]
        for e in doc.entitydb.values()
        if e.is_alive and e.dxf.handle not in ephemeral
    }


def verify(original, result, circle_handle, dim_handle):
    before, after = snapshot(original), snapshot(result)
    assert before.keys() <= after.keys(), "Existing entities were removed"
    modified = [h for h in before if before[h] != after[h]]
    assert not modified, ("Existing entities changed", modified)
    assert list(original.header.varnames()) == list(result.header.varnames())
    changed_headers = [k for k in original.header.varnames()
                       if original.header[k] != result.header[k]]
    assert changed_headers == ["$HANDSEED"], changed_headers
    assert original.units == result.units == 4
    old_ms = {e.dxf.handle for e in original.modelspace()}
    new_ms = {e.dxf.handle for e in result.modelspace()}
    assert new_ms - old_ms == {circle_handle, dim_handle}
    assert old_ms <= new_ms
    assert len(result.modelspace()) == 17

    outline = result.entitydb["91"]
    ext = bbox.extents([outline])
    center = (ext.extmin + ext.extmax) * 0.5
    point(center, (75, 40, 0))
    point(ext.extmin, (0, 0, 0))
    point(ext.extmax, (150, 80, 0))
    hole = result.entitydb[circle_handle]
    assert hole.dxftype() == "CIRCLE" and hole.dxf.layer == "HOLES"
    point(hole.dxf.center, center)
    near(hole.dxf.radius, 15)
    # Equal edge clearances confirm the new hole is centered on both axes.
    near(hole.dxf.center.x - 15, 60)
    near(150 - hole.dxf.center.x - 15, 60)
    near(hole.dxf.center.y - 15, 25)
    near(80 - hole.dxf.center.y - 15, 25)
    assert len(result.modelspace().query('CIRCLE[layer=="HOLES"]')) == 5
    for h in ("92", "93", "94", "95"):
        near(result.entitydb[h].dxf.radius, 6)
    for h, expected in (("96", 150), ("A5", 80), ("B4", 12),
                        ("C3", 12), ("D2", 12)):
        near(result.entitydb[h].get_measurement(), expected)

    dim = result.entitydb[dim_handle]
    assert dim.dxftype() == "DIMENSION" and dim.dimtype == 3
    assert dim.dxf.layer == "DIM" and dim.dxf.dimstyle == "EZDXF"
    near(dim.get_measurement(), 30)
    point((dim.dxf.defpoint + dim.dxf.defpoint4) * 0.5, center)
    for p in (dim.dxf.defpoint, dim.dxf.defpoint4):
        near((p - center).magnitude, 15)
    assert dim.dxf.text == "<>"
    display = result.blocks[dim.dxf.geometry]
    text = list(display.query("MTEXT"))
    assert len(text) == 1 and text[0].text == "%%c30"
    near(text[0].dxf.char_height, 3.5)
    # The rendered callout stays within the blank central/right-lower region,
    # clear of all four mounting holes, the logo, notes and existing dimensions.
    visible = [e for e in display if e.dxftype() != "POINT"]
    dim_ext = bbox.extents(visible)
    assert 55 < dim_ext.extmin.x < dim_ext.extmax.x < 125
    assert 15 < dim_ext.extmin.y < dim_ext.extmax.y < 55
    text_ext = bbox.extents(text)
    nearest_x = min(max(center.x, text_ext.extmin.x), text_ext.extmax.x)
    nearest_y = min(max(center.y, text_ext.extmin.y), text_ext.extmax.y)
    assert math.hypot(nearest_x - center.x, nearest_y - center.y) > 16
    audit = result.audit()
    assert not audit.errors and not audit.fixes, (audit.errors, audit.fixes)
    return {
        "unchanged_existing_persisted_entities": len(before),
        "changed_existing_entities": modified,
        "changed_header_values": changed_headers,
        "plate_size_mm": [150, 80],
        "new_hole_center_mm": list(hole.dxf.center),
        "new_hole_diameter_mm": hole.dxf.radius * 2,
        "new_diameter_dimension_measurement_mm": dim.get_measurement(),
        "new_diameter_dimension_display": "\u00d830",
        "new_dimension_display_bounds": [list(dim_ext.extmin), list(dim_ext.extmax)],
        "existing_mounting_hole_diameters_mm": [12, 12, 12, 12],
        "hole_count": 5,
        "modelspace_entity_count": len(result.modelspace()),
        "audit_errors": 0,
        "audit_fixes": 0,
    }


def main():
    if BACKUP.exists():
        raise RuntimeError("Round 3 backup already exists; refusing to add a duplicate hole")
    original = ezdxf.readfile(PART)
    assert len(original.modelspace()) == 15
    assert len(original.modelspace().query("CIRCLE")) == 4
    doc = ezdxf.readfile(PART)
    ext = bbox.extents([doc.entitydb["91"]])
    center = (ext.extmin + ext.extmax) * 0.5
    point(center, (75, 40, 0))
    shutil.copy2(PART, BACKUP)
    hole = doc.modelspace().add_circle(center, 15, dxfattribs={"layer": "HOLES"})
    dim = doc.modelspace().add_diameter_dim(
        center=center, radius=15, location=(99, 22),
        dimstyle="EZDXF", override={"dimtoh": 1},
        dxfattribs={"layer": "DIM"},
    )
    dim.render()
    # Keep timestamps, GUIDs and all other metadata; the handle allocation
    # cursor alone must advance because this round creates new entities.
    doc.header["$HANDSEED"] = str(doc.entitydb.handles)
    doc._update_metadata = lambda: None
    doc.saveas(STAGED)
    checked = ezdxf.readfile(STAGED)
    verify(original, checked, hole.dxf.handle, dim.dimension.dxf.handle)
    shutil.copyfile(STAGED, PART)
    final = ezdxf.readfile(PART)
    report = verify(original, final, hole.dxf.handle, dim.dimension.dxf.handle)
    report.update({
        "round": 3,
        "deliverable": PART.name,
        "backup": BACKUP.name,
        "new_hole_handle": hole.dxf.handle,
        "new_dimension_handle": dim.dimension.dxf.handle,
        "existing_content_preserved": True,
        "existing_limitation": "Prior-round customer logo overlap is preserved unchanged.",
        "errors_encountered": [],
        "part_sha256": hashlib.sha256(PART.read_bytes()).hexdigest(),
    })
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
