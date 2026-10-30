import asyncio
import contextlib
import math
import threading

import ezdxf
import pytest

from agentcad.policy import Policy
from agentcad.service import Runtime
from agentcad.worker import CADWorker


@pytest.fixture
def rt(tmp_path):
    return Runtime(Policy(root=tmp_path))


def test_stale_preview_and_revision_survive_process_equivalent_reopen(rt):
    assert rt.create_drawing("a.dxf")["ok"]
    rt.apply_operations("a.dxf", [{"op": "add_line", "start": [0, 0], "end": [10, 0]}])
    line = rt.inspect_entities("a.dxf")["entities"][0]["id"]
    ops = [{"op": "move", "target": line, "delta": [1, 0]}]
    preview = rt.apply_operations("a.dxf", ops, dry_run=True)["preview"]
    doc = ezdxf.readfile(rt.policy.root / "a.dxf")
    doc.entitydb[line].dxf.color = 5
    doc.saveas(rt.policy.root / "a.dxf")
    fresh_rt = Runtime(rt.policy)
    refused = fresh_rt.apply_operations(
        "a.dxf", ops, expected_revision=preview["revision"], preconditions=preview["preconditions"]
    )
    assert refused["error"]["code"] == "STALE_REVISION"
    assert refused["error"]["entities"] == [line]
    assert fresh_rt.inspect_entities("a.dxf")["entities"][0]["start"][:2] == [0, 0]
    rev = fresh_rt.read_drawing("a.dxf")["status"]["revision"]
    assert fresh_rt.apply_operations("a.dxf", ops, expected_revision=rev)["revision"] == rev + 1
    before = (rt.policy.root / "a.dxf").read_bytes()
    assert fresh_rt.apply_operations("a.dxf", ops, expected_revision=rev)["error"]["code"] == "STALE_REVISION"
    assert (rt.policy.root / "a.dxf").read_bytes() == before
    assert fresh_rt.read_drawing("a.dxf")["status"]["revision"] == rev + 1


def test_analytic_bulges_hatch_nesting_and_styles(rt):
    rt.create_drawing("a.dxf")
    ops = [
        {
            "op": "add_polyline",
            "points": [[0, 0], [10, 0], [10, 10, 1], [0, 10]],
            "closed": True,
            "tag": "outline",
        },
        {
            "op": "add_hatch",
            "points": [[0, 0], [20, 0], [20, 20], [0, 20]],
            "holes": [[[5, 5], [15, 5], [15, 15], [5, 15]], [[8, 8], [12, 8], [12, 12], [8, 12]]],
            "tag": "h",
        },
    ]
    assert rt.apply_operations("a.dxf", ops)["ok"]
    area = rt.measure_entities("a.dxf", "tag:outline")["measurements"][0]
    assert area["area"] == pytest.approx(100 + 25 * math.pi / 2)
    for style, expected in [("normal", 316), ("outer", 300), ("ignore", 400)]:
        assert rt.apply_operations("a.dxf", [{"op": "edit_hatch", "target": "tag:h", "style": style}])["ok"]
        assert rt.measure_entities("a.dxf", "tag:h")["measurements"][0]["area"] == pytest.approx(expected)


def test_cancel_does_not_overlap_workers():
    async def run():
        worker = CADWorker()
        entered, release = threading.Event(), threading.Event()
        trace = []

        def held():
            entered.set()
            release.wait(5)
            trace.append("A")

        try:
            first = asyncio.create_task(worker.run(held))
            assert await asyncio.to_thread(entered.wait, 5)
            first.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await first
            second = asyncio.create_task(worker.run(lambda: trace.append("B")))
            await asyncio.sleep(0.05)
            assert trace == []
            release.set()
            await second
            assert trace == ["A", "B"]
        finally:
            release.set()
            worker.close()

    asyncio.run(run())


def test_attribute_fingerprint_refuses_stale_block_edit(rt):
    from agentcad.guards import fingerprint

    rt.create_drawing("attributes.dxf")
    assert rt.apply_operations(
        "attributes.dxf",
        [
            {
                "op": "define_block",
                "name": "PART",
                "entities": [{"op": "add_circle", "center": [0, 0], "radius": 1}],
                "attributes": [{"tag": "MASS", "insert": [0, 0]}],
            },
            {"op": "insert_block", "name": "PART", "insert": [0, 0], "attributes": {"MASS": "10"}},
        ],
    )["ok"]
    path = rt.policy.root / "attributes.dxf"
    doc = ezdxf.readfile(path)
    block = doc.modelspace().query("INSERT")[0]
    guard = {"entities": {block.dxf.handle: fingerprint(block)}}
    block.get_attrib("MASS").dxf.text = "20"
    doc.saveas(path)
    before = path.read_bytes()
    result = rt.apply_operations(
        "attributes.dxf", [{"op": "move", "target": block.dxf.handle, "delta": [1, 0]}], preconditions=guard
    )
    assert result["error"]["code"] == "STALE_REVISION"
    assert path.read_bytes() == before


def test_block_from_entities_retains_sources_and_uses_base_point(rt):
    rt.create_drawing("blocks.dxf")
    result = rt.apply_operations(
        "blocks.dxf",
        [
            {"op": "add_line", "start": [10, 20], "end": [15, 20], "tag": "source"},
            {"op": "block_from_entities", "name": "PART", "target": "tag:source", "base_point": [10, 20]},
            {"op": "insert_block", "name": "PART", "insert": [100, 200]},
        ],
    )
    assert result["ok"], result
    doc = ezdxf.readfile(rt.policy.root / "blocks.dxf")
    assert len(doc.modelspace().query("LINE")) == 1
    line = list(doc.modelspace().query("INSERT")[0].virtual_entities())[0]
    assert tuple(line.dxf.start) == (100, 200, 0)
    assert tuple(line.dxf.end) == (105, 200, 0)


def test_duplicate_removal_preserves_styles_records_and_large_delete_policy(rt):
    rt.create_drawing("duplicates.dxf")
    path = rt.policy.root / "duplicates.dxf"
    doc = ezdxf.readfile(path)
    for width in (1, 2):
        doc.modelspace().add_lwpolyline([(0, 0), (10, 0)], dxfattribs={"const_width": width})
    for _ in range(53):
        doc.modelspace().add_line((0, 10), (10, 10))
    doc.saveas(path)
    before = path.read_bytes()
    denied = rt.apply_operations("duplicates.dxf", [{"op": "remove_duplicates"}])
    assert denied["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert path.read_bytes() == before
    result = rt.apply_operations("duplicates.dxf", [{"op": "remove_duplicates", "confirm_large": True}])
    assert result["ok"], result
    doc = ezdxf.readfile(path)
    assert len(doc.modelspace().query("LINE")) == 1
    assert len(doc.modelspace().query("LWPOLYLINE")) == 2


def test_bom_exports_saved_attributes_safely_and_preserves_identifier_strings(rt):
    import csv
    from zipfile import ZipFile
    from xml.etree import ElementTree as ET
    from agentcad.tabular import value

    assert value("00042") == "00042"
    assert value("1234567890123456") == "1234567890123456"
    rt.create_drawing("bom.dxf")
    assert rt.apply_operations(
        "bom.dxf",
        [
            {
                "op": "define_block",
                "name": "PART",
                "entities": [{"op": "add_circle", "center": [0, 0], "radius": 1}],
                "attributes": [{"tag": t, "insert": [0, 0]} for t in ("DESIGNATION", "MASS", "MATERIAL")],
            },
            {
                "op": "insert_block",
                "name": "PART",
                "insert": [0, 0],
                "attributes": {"DESIGNATION": "=1+1", "MASS": "-12.5", "MATERIAL": "@NOW()"},
            },
        ],
    )["ok"]
    for fmt in ("csv", "xlsx"):
        assert rt.export_drawing("bom.dxf", "bom." + fmt, fmt, table="bom")["ok"]
    with (rt.policy.root / "bom.csv").open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["designation"] == "'=1+1" and rows[0]["mass"] == "-12.5"
    with ZipFile(rt.policy.root / "bom.xlsx") as z:
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    assert sheet.find(".//s:f", ns) is None
    cells = {e.attrib["r"]: e for e in sheet.findall(".//s:c", ns)}
    assert cells["C2"].attrib["t"] == "inlineStr"
    assert cells["F2"].attrib["t"] == "n"


def test_delivery_refuses_source_mutation_without_manifest(rt, monkeypatch):
    rt.create_drawing("source.dxf")
    rt.apply_operations("source.dxf", [{"op": "add_line", "start": [0, 0], "end": [1, 0]}])
    real_export = rt.export_drawing

    def changed(*args, **kwargs):
        result = real_export(*args, **kwargs)
        path = rt.policy.root / "source.dxf"
        doc = ezdxf.readfile(path)
        doc.modelspace().query("LINE")[0].dxf.color = 3
        doc.saveas(path)
        return result

    monkeypatch.setattr(rt, "export_drawing", changed)
    result = rt.deliver_drawing("source.dxf", "bundle", formats=["dxf"])
    assert result["error"]["code"] == "STALE_REVISION"
    assert not (rt.policy.root / "bundle" / "manifest.json").exists()
