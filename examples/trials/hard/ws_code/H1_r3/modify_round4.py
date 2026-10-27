"""Undo only the verified round-2 hole edits, retaining rounds 1 and 3."""
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
BACKUP = ROOT / "part.round4.before.dxf"
STAGED = ROOT / "part.round4.checked.dxf"
REPORT = ROOT / "round4_verification.json"
RESTORE = {
    "92": ("radius",), "93": ("radius",),
    "94": ("radius",), "95": ("radius",),
    "D2": ("defpoint", "defpoint4"),
    "D6": ("insert",), "D8": ("insert",),
    "DA": ("start", "end"), "DB": ("start",),
    "DD": ("text",), "DF": ("location",),
}


def snapshot(doc):
    # Empty INSERT SEQENDs are synthesized on reading and are not serialized.
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


def near(a, b):
    assert math.isclose(a, b, rel_tol=0, abs_tol=1e-8), (a, b)


def point(a, b):
    assert len(a) == len(b)
    for x, y in zip(a, b):
        near(x, y)


def verify(before, result, source, expected):
    old, new, restored = snapshot(before), snapshot(result), snapshot(source)
    assert old.keys() == new.keys(), "Entity handles added or removed"
    changed = {h for h in old if old[h] != new[h]}
    assert changed == set(RESTORE), ("Unexpected edits", changed ^ set(RESTORE))
    assert new == snapshot(expected), "Unexpected entity tag changes"
    for h in RESTORE:
        assert new[h] == restored[h], ("Incomplete round-2 restoration", h)
    assert list(before.header.varnames()) == list(result.header.varnames())
    for key in before.header.varnames():
        assert before.header[key] == result.header[key], ("Header changed", key)
    assert before.units == result.units == 4
    assert len(result.modelspace()) == len(before.modelspace()) == 17
    centers = ((12, 12, 0), (138, 12, 0), (12, 68, 0), (138, 68, 0))
    for h, center in zip(("92", "93", "94", "95"), centers):
        point(result.entitydb[h].dxf.center, center)
        near(result.entitydb[h].dxf.radius, 5)
    dim = result.entitydb["D2"]
    near(dim.get_measurement(), 10)
    point((dim.dxf.defpoint + dim.dxf.defpoint4) / 2, centers[-1])
    assert dim.dxf.text == "4X <>"
    assert result.entitydb["DD"].text == "4X %%c10"
    point(result.entitydb["D6"].dxf.insert, dim.dxf.defpoint4)
    point(result.entitydb["D8"].dxf.insert, dim.dxf.defpoint)
    point(result.entitydb["DF"].dxf.location, dim.dxf.defpoint4)
    bounds = bbox.extents([result.entitydb["91"]])
    point(bounds.extmin, (0, 0, 0))
    point(bounds.extmax, (150, 80, 0))
    assert result.entitydb["91"].closed
    for h, value in (("96", 150), ("A5", 80), ("B4", 12), ("C3", 12)):
        near(result.entitydb[h].get_measurement(), value)
    assert result.entitydb["A1"].text == "150"
    point(result.entitydb["FF"].dxf.center, (75, 40, 0))
    near(result.entitydb["FF"].dxf.radius, 15)
    central_dim = result.entitydb["100"]
    near(central_dim.get_measurement(), 30)
    assert [e.text for e in result.blocks[central_dim.dxf.geometry].query("MTEXT")] == ["%%c30"]
    assert len(result.modelspace().query("CIRCLE")) == 5
    audit = result.audit()
    assert not audit.errors and not audit.fixes, (audit.errors, audit.fixes)
    return sorted(changed), len(old) - len(changed)


def main():
    source = ezdxf.readfile(ROOT / "part.round2.before.dxf")
    round2 = ezdxf.readfile(ROOT / "part.round2.checked.dxf")
    before = ezdxf.readfile(PART)
    src, r2, current = map(snapshot, (source, round2, before))
    assert src.keys() == r2.keys()
    assert {h for h in src if src[h] != r2[h]} == set(RESTORE)
    for h in RESTORE:
        assert current[h] == r2[h], ("Target changed since round 2", h)
    if BACKUP.exists():
        assert BACKUP.read_bytes() == PART.read_bytes(), "Existing round-4 backup differs"
    else:
        shutil.copy2(PART, BACKUP)
    doc = ezdxf.readfile(BACKUP)
    expected = ezdxf.readfile(BACKUP)
    # Restore only the fields changed in round 2 from the actual prior DXF.
    for target in (doc, expected):
        for h, names in RESTORE.items():
            for name in names:
                if h == "DD" and name == "text":
                    target.entitydb[h].text = source.entitydb[h].text
                else:
                    setattr(target.entitydb[h].dxf, name, getattr(source.entitydb[h].dxf, name))
    doc._update_metadata = lambda: None
    doc.saveas(STAGED)
    verify(before, ezdxf.readfile(STAGED), source, expected)
    shutil.copyfile(STAGED, PART)
    final = ezdxf.readfile(PART)
    changed, unchanged = verify(before, final, source, expected)
    report = {
        "round": 4,
        "deliverable": PART.name,
        "backup": BACKUP.name,
        "restoration_reference": "part.round2.before.dxf",
        "units": "mm",
        "mounting_hole_diameters_mm": [final.entitydb[h].dxf.radius * 2 for h in ("92", "93", "94", "95")],
        "mounting_hole_centers_mm": [list(p) for p in centers_from(final)],
        "diameter_dimension_measurement_mm": final.entitydb["D2"].get_measurement(),
        "diameter_dimension_display": "4X \u00d810",
        "plate_size_mm": [150, 80],
        "central_hole_center_mm": list(final.entitydb["FF"].dxf.center),
        "central_hole_diameter_and_dimension_mm": [30, final.entitydb["100"].get_measurement()],
        "changed_entity_handles": changed,
        "unchanged_persisted_entity_count": unchanged,
        "other_entity_tags_and_all_header_values_unchanged": True,
        "round1_and_round3_changes_preserved": True,
        "modelspace_entity_count": len(final.modelspace()),
        "audit_errors": 0,
        "audit_fixes": 0,
        "errors_encountered": [],
        "existing_limitation": "Prior-round customer logo overlap is preserved unchanged.",
        "part_sha256": hashlib.sha256(PART.read_bytes()).hexdigest(),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


def centers_from(doc):
    return [doc.entitydb[h].dxf.center for h in ("92", "93", "94", "95")]


if __name__ == "__main__":
    main()
