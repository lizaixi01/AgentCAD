"""Independent numeric transcriptions; sources and scope in docs/standard-tables.md."""
import ezdxf
import pytest

from agentcad import stdlib as library
from conftest import ok


def test_all_supported_fastener_rows_against_published_dimensions():
    sizes = ['M3', 'M4', 'M5', 'M6', 'M8', 'M10', 'M12', 'M14', 'M16', 'M20', 'M24']
    # ISO 4032:2012 tables 1/2: P, s, m(max). JFE ISO 4017 datasheet: k(nominal).
    expected = [(.5,5.5,2.4,2), (.7,7,3.2,2.8), (.8,8,4.7,3.5), (1,10,5.2,4),
                (1.25,13,6.8,5.3), (1.5,16,8.4,6.4), (1.75,18,10.8,7.5),
                (2,21,12.8,8.8), (2,24,14.8,10), (2.5,30,18,12.5), (3,36,21.5,15)]
    assert set(library.PITCH) == set(sizes)
    assert [(library.PITCH[s], library.HEX_S[s], library.NUT_M[s], library.BOLT_K[s]) for s in sizes] == expected
    # WASI DIN 125A / similar ISO 7089: nominal d1,d2,h.
    assert [library.WASHER[s] for s in sizes] == [
        (3.2,7,.5),(4.3,9,.8),(5.3,10,1),(6.4,12,1.6),(8.4,16,1.6),(10.5,20,2),
        (13,24,2.5),(15,28,2.5),(17,30,3),(21,37,3),(25,44,4)]
    # WASI BPL2005: dk, k(max), s; paired columns split explicitly.
    assert [library.SHCS[s] for s in sizes] == [
        (5.5,3,2.5),(7,4,3),(8.5,5,4),(10,6,5),(13,8,6),(16,10,8),
        (18,12,10),(21,14,12),(24,16,14),(30,20,17),(36,24,19)]


def test_all_bearing_envelopes_against_timken_table_1():
    # Timken E10857-GB, printed p2/PDF p4. Only d,D,B, not internal geometry.
    bore = [10,12,15,17,20,25,30,35,40,45,50]
    outer = [[26,28,32,35,42,47,55,62,68,75,80],
             [30,32,35,40,47,52,62,72,80,85,90],
             [35,37,42,47,52,62,72,80,90,100,110]]
    width = [[8,8,9,10,12,12,13,14,15,16,16],
             [9,10,11,12,14,15,16,17,18,19,20],
             [11,12,13,14,15,17,19,21,23,25,27]]
    expected = {str(series+i): (bore[i], outer[row][i], width[row][i])
                for row, series in enumerate((6000,6200,6300)) for i in range(11)}
    assert library.BEARINGS == expected


def test_hole_references_and_explicit_recommendation_boundaries():
    sizes = ['M3','M4','M5','M6','M8','M10','M12','M14','M16','M20','M24']
    # NBK clearance table / ISO 273 note (2015-06-18), three clearance series.
    assert [library.CLEARANCE[s] for s in sizes] == [
        (3.2,3.4,3.6),(4.3,4.5,4.8),(5.3,5.5,5.8),(6.4,6.6,7),
        (8.4,9,10),(10.5,11,12),(13,13.5,14.5),(15,15.5,16.5),
        (17,17.5,18.5),(21,22,24),(25,26,28)]
    # EXACT GS52 through M12; Thurmer larger sizes. These are recommendations.
    assert [library.TAP_DRILL[s] for s in sizes] == [2.5,3.3,4.2,5,6.8,8.5,10.2,12,14,17.5,21]
    # Ifanger p32 omits M14. Never manufacture a source row for that legacy value.
    assert [library.COUNTERBORE[s][0] for s in sizes if s != 'M14'] == [6.5,8,10,11,15,18,20,26,33,40]
    # Supplier depth row, without washer; not a normative DIN verification.
    assert [library.COUNTERBORE[s][1] for s in sizes] == [3.4,4.4,5.4,6.4,8.6,10.6,12.6,14.6,16.6,20.6,24.8]
    assert library.hole_dims('M14', 'counterbore')['reference_status'] == 'unverified_counterbore'
    assert 'DIN' not in library.hole_dims('M14', 'counterbore')['standard']


def test_public_lookup_refuses_missing_rows_and_reports_scope(rt):
    for item in [*library.PARTS, *library.HOLE_KINDS]:
        result = ok(rt.standard_library(item))
        assert result['provenance']['reference']
        assert 'not full standards' in result['provenance']['scope']
        assert rt.standard_library(item, 'M7')['error']['code'] == 'INVALID_SIZE'
    row = ok(rt.standard_library('counterbore', 'M14'))['rows']['M14']
    assert row['reference_status'] == 'unverified_counterbore'
    assert ok(rt.standard_library('tapped', 'M12'))['rows']['M12']['diameter'] == 10.2


def test_reference_dimensions_convert_to_saved_inch_geometry(rt, ws):
    ok(rt.create_drawing('inch.dxf', units='in'))
    result = ok(rt.apply_operations('inch.dxf', [
        {'op':'add_standard_hole', 'size':'M12', 'kind':'tapped', 'centers':[[0,0]], 'tag':'pilot'},
        {'op':'add_standard_hole', 'size':'M14', 'kind':'counterbore', 'centers':[[2,0]], 'tag':'cb'},
        {'op':'add_standard_part', 'part':'washer', 'size':'M24', 'view':'top', 'insert':[4,0]}]))
    assert result['results'][1]['dims']['reference_status'] == 'unverified_counterbore'
    doc = ezdxf.readfile(ws / 'inch.dxf')
    pilot = [e for e in doc.modelspace().query('CIRCLE') if e.dxf.center.x == 0]
    assert len(pilot) == 1 and pilot[0].dxf.radius * 2 == pytest.approx(10.2 / 25.4)
    washer = list(doc.modelspace().query('INSERT'))[-1]
    assert washer.dxf.xscale == pytest.approx(1 / 25.4)
    assert sorted(e.dxf.radius * 2 for e in doc.blocks[washer.dxf.name].query('CIRCLE')) == [25,44]
