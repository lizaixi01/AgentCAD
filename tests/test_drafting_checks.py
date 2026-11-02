"""Drafting-practice warnings from the 2026-11-02 rerun (examples/trials): values right, drawing still wrong.
T1 drew three diameter lines through the flange center, T6 kept Ø150 and Ø60 on one line, T3 left out the edges
of the shaft's shoulders. Each is a warning with a hint; add_diameter_dim(outside=true) gives the way out."""
import pytest

from agentcad.policy import Policy
from agentcad.service import Runtime

FLANGE = [{"op": "add_circle", "center": [0, 0], "diameter": 150, "layer": "OUTLINE"},
          {"op": "add_circle", "center": [0, 0], "diameter": 60, "layer": "OUTLINE"},
          {"op": "add_circle", "center": [0, 0], "diameter": 110, "layer": "CENTER", "linetype": "CENTER"},
          {"op": "add_circle", "center": [0, 55], "diameter": 12, "layer": "HOLES"},
          {"op": "array_polar", "target": "$3", "center": [0, 0], "count": 6}]


@pytest.fixture
def rt(tmp_path):
    return Runtime(Policy(root=str(tmp_path)))


def codes(r):
    """The drafting warnings among a result's issues."""
    return [i["code"] for i in r["validation"]["issues"]
            if i["code"] in ("DIMENSION_OVERLAP", "DIMENSION_LINES_CROSS", "TURNED_EDGE_MISSING")]


def draw(rt, name, ops):
    r = rt.apply_operations(name, ops, create={"units": "mm"})
    assert r["ok"], r
    return r


def test_three_diameter_lines_through_one_center_are_flagged(rt):
    r = draw(rt, "t1.dxf", FLANGE + [
        {"op": "add_diameter_dim", "target": "$0", "angle": 45, "layer": "DIM"},
        {"op": "add_diameter_dim", "target": "$2", "angle": 120, "layer": "DIM"},
        {"op": "add_diameter_dim", "target": "$1", "angle": 240, "layer": "DIM"}])
    cross = [i for i in r["validation"]["issues"] if i["code"] == "DIMENSION_LINES_CROSS"]
    assert len(cross) == 1 and len(cross[0]["entities"]) == 3 and r["validation"]["passed"]
    assert "outside=true" in cross[0]["details"]["hint"]


def test_two_concentric_diameters_may_share_the_center(rt):
    r = draw(rt, "two.dxf", FLANGE + [
        {"op": "add_diameter_dim", "target": "$0", "angle": 45, "layer": "DIM"},
        {"op": "add_diameter_dim", "target": "$1", "angle": 120, "layer": "DIM"}])
    assert codes(r) == []


def test_an_outside_diameter_draws_no_line_through_the_center(rt):
    import ezdxf
    r = draw(rt, "out.dxf", FLANGE + [
        {"op": "add_diameter_dim", "target": "$0", "angle": 45, "layer": "DIM"},
        {"op": "add_diameter_dim", "target": "$2", "angle": 120, "layer": "DIM"},
        {"op": "add_diameter_dim", "target": "$1", "angle": 240, "outside": True, "layer": "DIM"}])
    assert r["validation"]["issues"] == []  # no display or measurement issue either: it still reads Ø60
    v = rt.validate_drawing("out.dxf", requirements=[{"type": "dimension", "kind": "diameter", "value": 60}])
    assert v["validation"]["passed"]
    d = ezdxf.readfile(rt.policy.root / "out.dxf").modelspace().query("DIMENSION")[2]
    lines = [(g.dxf.start.vec2.magnitude, g.dxf.end.vec2.magnitude) for g in d.get_geometry_block()
             if g.dxftype() == "LINE"]
    leader = [ln for ln in lines if max(ln) > 5]  # the rest is the center mark
    assert len(leader) == 1 and min(leader[0]) >= 30 - 1e-6  # from the circle outward


def test_collinear_diameters_are_drawn_over_one_another(rt):
    """T6's input: Ø150 at 30 degrees and Ø60 at 210 degrees lie on one line."""
    r = draw(rt, "t6.dxf", FLANGE + [
        {"op": "add_diameter_dim", "target": "$0", "angle": 30, "layer": "DIM"},
        {"op": "add_diameter_dim", "target": "$1", "angle": 210, "layer": "DIM"}])
    over = [i for i in r["validation"]["issues"] if i["code"] == "DIMENSION_OVERLAP"]
    assert len(over) == 1 and "on top of each other" in over[0]["message"]


def test_linear_dimensions_overlap_but_chains_do_not(rt):
    base = [{"op": "add_rectangle", "corner": [0, 0], "width": 200, "height": 40, "layer": "OUTLINE"}]
    chain = [{"op": "add_linear_dim", "p1": [0, 0], "p2": [50, 0], "offset": -12, "layer": "DIM"},
             {"op": "add_linear_dim", "p1": [50, 0], "p2": [130, 0], "offset": -12, "layer": "DIM"},
             {"op": "add_linear_dim", "p1": [0, 0], "p2": [200, 0], "offset": -24, "layer": "DIM"}]
    assert codes(draw(rt, "chain.dxf", base + chain)) == []
    r = draw(rt, "clash.dxf", base + [chain[0], {**chain[1], "p1": [20, 0]}])
    assert "DIMENSION_OVERLAP" in codes(r)


def test_a_pile_of_overlapping_dimensions_is_one_warning(rt):
    """draw_mechanical_assembly with 50 steps of 1.1 gave 144 pairs: one warning, so delivery still scores."""
    steps = [{"op": "add_linear_dim", "p1": [i, 0], "p2": [i + 1, 0], "offset": -10, "layer": "DIM"}
             for i in range(10)]
    r = draw(rt, "pile.dxf", [{"op": "add_polyline", "points": [[i, 0] for i in range(11)], "layer": "OUTLINE"},
                              *steps])
    over = [i for i in r["validation"]["issues"] if i["code"] == "DIMENSION_OVERLAP"]
    assert len(over) == 1 and len(over[0]["entities"]) == 10 and over[0]["message"].startswith("10 dimensions")


SHAFT = [{"op": "add_polyline", "closed": True, "layer": "OUTLINE", "points": [
    [0, -13], [2, -15], [50, -15], [50, -20], [130, -20], [130, -15], [198, -15], [200, -13],
    [200, 13], [198, 15], [130, 15], [130, 20], [50, 20], [50, 15], [2, 15], [0, 13]]},
    {"op": "add_line", "start": [-8, 0], "end": [208, 0], "layer": "CENTER", "linetype": "CENTER"},
    {"op": "add_linear_dim", "p1": [25, -15], "p2": [25, 15], "orientation": "vertical", "offset": 0,
     "text": "%%c<>", "layer": "DIM"}]
CHAMFERS = [{"op": "add_line", "start": [x, -15], "end": [x, 15], "layer": "OUTLINE"} for x in (2, 198)]
SHOULDERS = [{"op": "add_line", "start": [x, -15], "end": [x, 15], "layer": "OUTLINE"} for x in (50, 130)]


def test_a_shaft_needs_the_edge_of_each_shoulder_and_chamfer(rt):
    r = draw(rt, "t3.dxf", SHAFT + CHAMFERS)
    miss = [i for i in r["validation"]["issues"] if i["code"] == "TURNED_EDGE_MISSING"]
    assert len(miss) == 1 and r["validation"]["passed"]
    assert miss[0]["details"]["lines"] == [[[50.0, -15.0], [50.0, 15.0]], [[130.0, -15.0], [130.0, 15.0]]]
    r = draw(rt, "t3b.dxf", SHAFT + SHOULDERS)  # chamfer edges missing instead
    lines = [i for i in r["validation"]["issues"] if i["code"] == "TURNED_EDGE_MISSING"][0]["details"]["lines"]
    assert [p[0][0] for p in lines] == [2.0, 198.0]
    assert "TURNED_EDGE_MISSING" not in codes(draw(rt, "t3c.dxf", SHAFT + CHAMFERS + SHOULDERS))


def test_a_stepped_plate_without_diameters_is_left_alone(rt):
    """The same outline with plain (not Ø) dimensions may be a flat plate: no line across."""
    plate = SHAFT[:2] + [{**SHAFT[2], "text": "<>"}]
    assert "TURNED_EDGE_MISSING" not in codes(draw(rt, "plate.dxf", plate + CHAMFERS))


@pytest.mark.parametrize("angle", [0, 90, 180, 270])
def test_an_outside_diameter_at_an_axis_angle_is_clean(rt, angle):
    """Its center mark has an arm along the dimension line; that arm is not the dimension line (review of #82)."""
    r = draw(rt, f"axis{angle}.dxf", FLANGE + [
        {"op": "add_diameter_dim", "target": "$0", "angle": 45, "layer": "DIM"},
        {"op": "add_diameter_dim", "target": "$2", "angle": 120, "layer": "DIM"},
        {"op": "add_diameter_dim", "target": "$1", "angle": angle, "outside": True, "layer": "DIM"}])
    assert codes(r) == []


def test_an_outside_diameter_clears_the_circle_at_any_annotation_scale(rt):
    import ezdxf
    for th in (None, 3.5):
        name = f"s{th}.dxf"
        draw(rt, name, [{"op": "set_annotation_scale", "scale": 50},
                        {"op": "add_circle", "center": [0, 0], "diameter": 3000, "layer": "OUTLINE"},
                        {"op": "add_diameter_dim", "target": "$1", "angle": 30, "outside": True, "layer": "DIM",
                         **({"text_height": th} if th else {})}])
        d = ezdxf.readfile(rt.policy.root / name).modelspace().query("DIMENSION")[0]
        t = next(g for g in d.get_geometry_block() if g.dxftype() == "MTEXT")
        assert t.dxf.insert.vec2.magnitude - 1500 > 2 * t.dxf.char_height


def test_three_diameters_away_from_the_origin_are_one_crossing(rt):
    """Grouped by distance: a rounded key split (29.75, 127.75) into three cells and missed it (review of #82)."""
    c = [29.75, 127.75]
    circles = [{"op": "add_circle", "center": c, "diameter": d, "layer": "OUTLINE"} for d in (150, 110, 60)]
    r = draw(rt, "off.dxf", circles + [{"op": "add_diameter_dim", "target": f"${i}", "angle": a, "layer": "DIM"}
                                       for i, a in enumerate((330, 30, 120))])
    assert codes(r) == ["DIMENSION_LINES_CROSS"]


def test_a_center_line_in_pieces_is_one_axis(rt):
    pieces = [{"op": "add_line", "start": [a, 0], "end": [b, 0], "layer": "CENTER", "linetype": "CENTER"}
              for a, b in ((-8, 60), (70, 140), (150, 208))]
    r = draw(rt, "pieces.dxf", [SHAFT[0], *pieces, SHAFT[2], *CHAMFERS])
    assert codes(r) == ["TURNED_EDGE_MISSING"]


def test_a_tiny_center_line_does_not_break_validation(rt):
    r = draw(rt, "tiny.dxf", SHAFT + CHAMFERS + SHOULDERS +
             [{"op": "add_line", "start": [10, 0], "end": [10.000001, 0], "layer": "CENTER"}])
    assert codes(r) == []


def test_a_bore_diameter_does_not_make_a_plate_turned(rt):
    """A Ø dimension between the hidden lines of a bore, not between points of the outline (review of #82)."""
    bore = [{"op": "add_line", "start": [0, y], "end": [200, y], "layer": "HIDDEN"} for y in (-5, 5)]
    plate = [SHAFT[0], SHAFT[1], *bore,
             {"op": "add_linear_dim", "p1": [25, -5], "p2": [25, 5], "orientation": "vertical", "offset": 0,
              "text": "%%c<>", "layer": "DIM"}]
    assert "TURNED_EDGE_MISSING" not in codes(draw(rt, "bore.dxf", plate + CHAMFERS))


def test_a_grid_of_crossing_dimensions_is_one_warning(rt):
    """An imported sheet of crossing lines: one warning, found without comparing every crossing with every other
    (400 such dimensions took 184 s; review of #82)."""
    import time
    grid = [{"op": "add_linear_dim", "p1": [0, 10 * i], "p2": [300, 10 * i], "offset": 0, "layer": "DIM"}
            for i in range(30)]
    grid += [{"op": "add_linear_dim", "p1": [10 * i + 5, 0], "p2": [10 * i + 5, 300], "orientation": "vertical",
             "offset": 0, "layer": "DIM"} for i in range(30)]
    t0 = time.time()
    r = draw(rt, "grid.dxf", grid)
    cross = [i for i in r["validation"]["issues"] if i["code"] == "DIMENSION_LINES_CROSS"]
    assert len(cross) == 1 and "places" in cross[0]["message"] and time.time() - t0 < 30


def test_a_center_line_either_side_of_horizontal_is_one_axis(rt):
    """(-8, 0)-(100, -1e-9) and (100, 0)-(208, 1e-9): 359.9999 and 0.0000 degrees, one line."""
    pieces = [{"op": "add_line", "start": [-8, 0], "end": [100, -1e-9], "layer": "CENTER"},
              {"op": "add_line", "start": [100, 0], "end": [208, 1e-9], "layer": "CENTER"}]
    r = draw(rt, "wrap.dxf", [SHAFT[0], *pieces, SHAFT[2], *CHAMFERS])
    assert codes(r) == ["TURNED_EDGE_MISSING"]
