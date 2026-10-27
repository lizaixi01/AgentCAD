"""Round 5: change the title-block REV and add one revision note only."""
from pathlib import Path
import hashlib
import json
import shutil

import ezdxf
from ezdxf import bbox
from ezdxf.lldxf.tagwriter import TagCollector
from ezdxf.lldxf.tagger import ascii_tags_loader, tag_compiler
from ezdxf.sections.header import HeaderSection

ROOT = Path(__file__).resolve().parent
PART = ROOT / "part.dxf"
BACKUP = ROOT / "part.round5.before.dxf"
STAGED = ROOT / "part.round5.checked.dxf"
REPORT = ROOT / "round5_verification.json"
NOTE = "REV C: 宽度 150，增加中心孔 Ø30"


def read_preserving_header(path):
    # ezdxf 1.4.5 resets TDCREATE in _setup_metadata even on readfile().
    # Load the actual serialized header separately to retain original values.
    with path.open("r", encoding="utf-8") as stream:
        tags = []
        for tag in tag_compiler(ascii_tags_loader(stream)):
            if tag == (0, "ENDSEC"):
                break
            tags.append(tag)
    header = HeaderSection.load(tags)
    doc = ezdxf.readfile(path)
    doc.header = header
    return doc


def snapshot(doc):
    # Ignore reader-created SEQENDs that do not exist in the saved DXF.
    ephemeral = {
        e.seqend.dxf.handle for e in doc.entitydb.values()
        if e.is_alive and e.dxftype() == "INSERT" and not e.attribs
        and e.seqend is not None
    }
    result = {}
    for entity in doc.entitydb.values():
        if not entity.is_alive or entity.dxf.handle in ephemeral:
            continue
        tags = TagCollector.dxftags(entity)
        if entity.dxftype() == "INSERT":
            # INSERT export includes its ATTRIBs and SEQEND, which are each
            # checked separately by entitydb handle. Avoid counting them twice.
            end = next((i for i, tag in enumerate(tags) if i and tag.code == 0), len(tags))
            tags = tags[:end]
        result[entity.dxf.handle] = [(t.code, str(t.value)) for t in tags]
    return result


def overlaps(a, b):
    return (a.extmin.x < b.extmax.x and a.extmax.x > b.extmin.x
            and a.extmin.y < b.extmax.y and a.extmax.y > b.extmin.y)


def verify(before, result, rev_handle, note_handle):
    old, new = snapshot(before), snapshot(result)
    assert set(old) <= set(new), "Existing entity removed"
    assert set(new) - set(old) == {note_handle}, "Unexpected added entities"
    changed = {h for h in old if old[h] != new[h]}
    assert changed == {rev_handle}, ("Unexpected changed entities", changed)
    # Validate that only ATTRIB text (group code 1) changed on the REV entity.
    expected_rev = [(code, "C" if code == 1 else value)
                    for code, value in old[rev_handle]]
    assert new[rev_handle] == expected_rev
    assert result.entitydb[rev_handle].dxf.text == "C"
    assert result.entitydb[rev_handle].dxf.tag == "REV"
    assert list(before.header.varnames()) == list(result.header.varnames())
    header_changes = [k for k in before.header.varnames()
                      if before.header[k] != result.header[k]]
    assert set(header_changes) <= {"$HANDSEED"}, header_changes
    assert before.units == result.units == 4
    assert list(before.layouts.names()) == list(result.layouts.names())
    for layout in before.layouts:
        old_order = [e.dxf.handle for e in layout]
        new_order = [e.dxf.handle for e in result.layouts.get(layout.name)]
        assert new_order == old_order + ([note_handle] if layout.name == "Model" else [])

    note = result.entitydb[note_handle]
    assert note.dxftype() == "TEXT" and note.dxf.text == NOTE
    assert note.dxf.layer == "NOTES" and note.dxf.style == "Standard"
    assert tuple(note.dxf.insert) == (0, -24, 0)
    assert note.dxf.height == 3 and note.dxf.rotation == 0
    bounds = bbox.extents([note])
    assert bounds.extmax.y < 0
    # Include text, dimensions, nested title-block geometry and logo in checks.
    for entity in before.modelspace():
        existing_bounds = bbox.extents([entity])
        if existing_bounds.has_data:
            assert not overlaps(bounds, existing_bounds), ("Note overlaps", entity.dxf.handle)
    # Conservative font-independent envelope for this 23-character single line.
    # 100 mm covers full-width glyphs and provides clearance from the title.
    envelope = bbox.BoundingBox([(0, -25.5, 0), (100, -20, 0)])
    assert bounds.extmin.x >= envelope.extmin.x and bounds.extmax.x <= envelope.extmax.x
    assert bounds.extmin.y >= envelope.extmin.y and bounds.extmax.y <= envelope.extmax.y
    for entity in before.modelspace():
        existing_bounds = bbox.extents([entity])
        if existing_bounds.has_data:
            assert not overlaps(envelope, existing_bounds)

    plate = bbox.extents([result.entitydb["91"]])
    assert tuple(plate.extmin) == (0, 0, 0)
    assert tuple(plate.extmax) == (150, 80, 0)
    assert tuple(result.entitydb["FF"].dxf.center) == (75, 40, 0)
    assert result.entitydb["FF"].dxf.radius * 2 == 30
    assert result.entitydb["96"].get_measurement() == 150
    assert result.entitydb["100"].get_measurement() == 30
    assert [result.entitydb[h].dxf.radius * 2 for h in ("92", "93", "94", "95")] == [10] * 4
    audit = result.audit()
    assert not audit.errors and not audit.fixes, (audit.errors, audit.fixes)
    return {
        "changed_existing_entity_handles": sorted(changed),
        "added_entity_handles": [note_handle],
        "unchanged_persisted_entity_count": len(old) - 1,
        "other_existing_entities_unchanged": True,
        "header_changes": header_changes,
        "revision_note_bounds_mm": [list(bounds.extmin), list(bounds.extmax)],
        "revision_note_no_overlap": True,
        "modelspace_entity_count_before_after": [len(before.modelspace()), len(result.modelspace())],
        "audit_errors": 0,
        "audit_fixes": 0,
    }


def main():
    before = read_preserving_header(PART)
    titles = [e for e in before.modelspace().query("INSERT")
              if e.dxf.name == "TB" and e.has_attrib("REV")]
    assert len(titles) == 1, "Expected a unique TB title block with REV attribute"
    rev = titles[0].get_attrib("REV")
    assert rev.dxf.text == "A", "Unexpected starting revision; do not apply twice"
    assert not any(e.dxf.text == NOTE for e in before.modelspace().query("TEXT"))
    if BACKUP.exists():
        assert BACKUP.read_bytes() == PART.read_bytes(), "Existing backup differs"
    else:
        shutil.copy2(PART, BACKUP)
    doc = read_preserving_header(BACKUP)
    doc.entitydb[rev.dxf.handle].dxf.text = "C"
    note = doc.modelspace().add_text(NOTE, dxfattribs={
        "layer": "NOTES", "style": "Standard", "height": 3.0,
        "insert": (0, -24, 0), "rotation": 0,
    })
    # Preserve existing creation/update dates and ezdxf metadata.
    doc._update_metadata = lambda: None
    doc.header["$HANDSEED"] = str(doc.entitydb.handles)
    doc.saveas(STAGED)
    verify(before, read_preserving_header(STAGED), rev.dxf.handle, note.dxf.handle)
    shutil.copyfile(STAGED, PART)
    result = read_preserving_header(PART)
    checks = verify(before, result, rev.dxf.handle, note.dxf.handle)
    report = {
        "round": 5, "deliverable": PART.name, "backup": BACKUP.name,
        "units": "mm", "title_block": "TB", "revision_before": rev.dxf.text,
        "revision_after": "C", "revision_note": NOTE,
        "revision_note_insert_mm": [0, -24, 0], "revision_note_height_mm": 3,
        "plate_size_mm": [150, 80], "central_hole_diameter_mm": 30,
        "central_hole_center_mm": [75, 40, 0],
        "mounting_hole_diameters_mm": [10, 10, 10, 10],
        **checks, "errors_encountered": [
            "Initial verification double-counted the REV change inside INSERT export; fixed snapshot logic to verify INSERT and its attributes separately.",
            "ezdxf 1.4.5 resets TDCREATE on read; restored the serialized original header and verified its values. Original DXF was not overwritten until checks passed."
        ],
        "limitations": [
            "Existing customer-logo overlap is preserved as required.",
            "Chinese glyph appearance depends on the CAD viewer's existing Standard style fonts (gbenor.shx/gbcbig.shx).",
        ],
        "part_sha256": hashlib.sha256(PART.read_bytes()).hexdigest(),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
