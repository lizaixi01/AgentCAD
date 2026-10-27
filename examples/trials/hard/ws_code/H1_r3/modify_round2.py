"""Round 2: change four mounting holes from diameter 10 to 12 mm only.

Uses ezdxf, preserves handles and the existing dimension display block, and
checks the serialized drawing before replacing part.dxf.
"""
from pathlib import Path
import hashlib
import json
import math
import shutil

import ezdxf
from ezdxf.lldxf.tagwriter import TagCollector

ROOT = Path(__file__).resolve().parent
PART = ROOT / "part.dxf"
BACKUP = ROOT / "part.round2.before.dxf"
STAGED = ROOT / "part.round2.checked.dxf"
REPORT = ROOT / "round2_verification.json"
HOLES = ("92", "93", "94", "95")


def fingerprint(entity):
    return [(t.code, str(t.value)) for t in TagCollector.dxftags(entity)]


def snapshot(doc):
    return {e.dxf.handle: fingerprint(e) for e in doc.entitydb.values() if e.is_alive}


def near(a, b):
    assert math.isclose(a, b, rel_tol=0, abs_tol=1e-9), (a, b)


def point(a, b):
    assert len(a) == len(b)
    for x, y in zip(a, b):
        near(x, y)


def changes_for(original):
    dim = original.entitydb["D2"]
    center = (dim.dxf.defpoint + dim.dxf.defpoint4) / 2
    unit = (dim.dxf.defpoint - center).normalize()
    # Text and the horizontal leader stay in place. Extend the diameter span
    # by 1 mm at each end and keep the original arrow sizes and rotations.
    return {
        **{h: {"radius": 6.0} for h in HOLES},
        "D2": {"defpoint": center + unit * 6,
               "defpoint4": center - unit * 6},
        "D6": {"insert": original.entitydb["D6"].dxf.insert - unit},
        "D8": {"insert": original.entitydb["D8"].dxf.insert + unit},
        "DA": {"start": original.entitydb["DA"].dxf.start - unit,
               "end": original.entitydb["DA"].dxf.end + unit},
        "DB": {"start": original.entitydb["DB"].dxf.start - unit},
        "DD": {"text": "4X %%c12"},
        "DF": {"location": center - unit * 6},
    }


def apply_changes(doc, changes):
    for handle, attrs in changes.items():
        for name, value in attrs.items():
            if name == "text" and doc.entitydb[handle].dxftype() == "MTEXT":
                doc.entitydb[handle].text = value
            else:
                setattr(doc.entitydb[handle].dxf, name, value)


def verify(original, result, expected, changes):
    before, after = snapshot(original), snapshot(result)
    assert before.keys() == after.keys(), "Entity handles added or removed"
    changed = {h for h in before if before[h] != after[h]}
    assert changed == set(changes), ("Unexpected changes", changed ^ set(changes))
    assert after == snapshot(expected), "DXF tags differ from the exact intended edits"
    assert list(original.header.varnames()) == list(result.header.varnames())
    for key in original.header.varnames():
        assert original.header[key] == result.header[key], ("Header changed", key)
    assert original.units == result.units == 4
    assert len(original.modelspace()) == len(result.modelspace()) == 15
    assert {e.dxf.handle for e in result.modelspace().query('CIRCLE[layer=="HOLES"]')} == set(HOLES)
    for h in HOLES:
        point(result.entitydb[h].dxf.center, original.entitydb[h].dxf.center)
        near(result.entitydb[h].dxf.radius, 6)
    dim = result.entitydb["D2"]
    center = result.entitydb["95"].dxf.center
    point((dim.dxf.defpoint + dim.dxf.defpoint4) / 2, center)
    for p in (dim.dxf.defpoint, dim.dxf.defpoint4):
        near((p - center).magnitude, 6)
    near(dim.get_measurement(), 12)
    assert dim.dxf.text == "4X <>"
    assert result.entitydb["DD"].text == "4X %%c12"
    point(result.entitydb["D6"].dxf.insert, dim.dxf.defpoint4)
    point(result.entitydb["D8"].dxf.insert, dim.dxf.defpoint)
    point(result.entitydb["DF"].dxf.location, dim.dxf.defpoint4)
    point(result.entitydb["DE"].dxf.location, center)
    unit = (dim.dxf.defpoint - center).normalize()
    line = result.entitydb["DA"]
    point(line.dxf.start, dim.dxf.defpoint4 - unit * 2.5)
    point(line.dxf.end, dim.dxf.defpoint - unit * 2.5)
    point(result.entitydb["DB"].dxf.start, line.dxf.start)
    point(result.entitydb["DB"].dxf.end, result.entitydb["DC"].dxf.start)
    for h, measurement in (("96", 150), ("A5", 80), ("B4", 12), ("C3", 12)):
        near(result.entitydb[h].get_measurement(), measurement)
    audit = result.audit()
    assert not audit.errors and not audit.fixes, (audit.errors, audit.fixes)
    return sorted(changed), len(before) - len(changed)


def main():
    doc = ezdxf.readfile(PART)
    for h in HOLES:
        near(doc.entitydb[h].dxf.radius, 5)
    near(doc.entitydb["D2"].get_measurement(), 10)
    assert doc.entitydb["DD"].text == "4X %%c10"
    if BACKUP.exists():
        assert BACKUP.read_bytes() == PART.read_bytes(), "Existing round-2 backup differs"
    else:
        shutil.copy2(PART, BACKUP)
    original = ezdxf.readfile(BACKUP)
    expected = ezdxf.readfile(BACKUP)
    changes = changes_for(original)
    apply_changes(expected, changes)
    apply_changes(doc, changes)
    # No entity creation: preserve the original GUIDs, timestamps and HANDSEED.
    doc._update_metadata = lambda: None
    doc.saveas(STAGED)
    checked = ezdxf.readfile(STAGED)
    differences, unchanged = verify(original, checked, expected, changes)
    shutil.copyfile(STAGED, PART)
    final = ezdxf.readfile(PART)
    verify(original, final, expected, changes)
    report = {
        "round": 2,
        "deliverable": PART.name,
        "backup": BACKUP.name,
        "units": "mm",
        "hole_count": 4,
        "hole_diameters": [final.entitydb[h].dxf.radius * 2 for h in HOLES],
        "hole_centers": [list(final.entitydb[h].dxf.center) for h in HOLES],
        "diameter_dimension_measurement": final.entitydb["D2"].get_measurement(),
        "diameter_display": "4X Ø12",
        "changed_entity_handles": differences,
        "unchanged_entity_count": unchanged,
        "all_other_entity_tags_and_header_values_unchanged": True,
        "modelspace_entity_count": len(final.modelspace()),
        "audit_errors": 0,
        "audit_fixes": 0,
        "existing_limitation": "The prior-round customer logo overlap is preserved; no unrelated layout edits were made.",
        "inspection_error_resolved": "Initial get_acad_dstyle({}) inspection passed an invalid dict; replaced with the public override() accessor. No drawing was changed by that failed read-only inspection.",
        "part_sha256": hashlib.sha256(PART.read_bytes()).hexdigest(),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
