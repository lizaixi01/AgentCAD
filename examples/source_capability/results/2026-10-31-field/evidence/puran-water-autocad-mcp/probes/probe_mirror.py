"""Follow-up probe: ezdxf mirror geometry for CIRCLE, LINE and ARC (saved and reopened)."""
import asyncio, json, os
os.environ["AUTOCAD_MCP_BACKEND"] = "ezdxf"
import ezdxf
from autocad_mcp import server as S

def J(x): return json.loads(x)

async def main():
    await S.drawing(operation="create")
    c = J(await S.entity(operation="create_circle", data={"cx": 0, "cy": 0, "radius": 1}))["payload"]["handle"]
    l = J(await S.entity(operation="create_line", x1=0, y1=0, x2=10, y2=5))["payload"]["handle"]
    a = J(await S.entity(operation="create_arc", data={"cx": 0, "cy": 0, "radius": 5, "start_angle": 0, "end_angle": 90}))["payload"]["handle"]
    out = {}
    for name, h in (("circle", c), ("line", l), ("arc", a)):
        out[name] = J(await S.entity(operation="mirror", entity_id=h, x1=50, y1=-10, x2=50, y2=10))
    p = "/out/probe_artifacts/mirror.dxf"
    await S.drawing(operation="save", data={"path": p})
    by = {e.dxf.handle: e for e in ezdxf.readfile(p).modelspace()}
    mc = by[out["circle"]["payload"]["handle"]]; ml = by[out["line"]["payload"]["handle"]]; ma = by[out["arc"]["payload"]["handle"]]
    obs = {"results": out,
           "circle_center": [round(v, 6) for v in mc.dxf.center], "circle_extrusion": list(mc.dxf.extrusion),
           "circle_wcs_center": [round(v, 6) for v in mc.ocs().to_wcs(mc.dxf.center)],
           "line": [[round(v, 6) for v in ml.dxf.start], [round(v, 6) for v in ml.dxf.end]],
           "arc_center_ocs": [round(v, 6) for v in ma.dxf.center], "arc_extrusion": list(ma.dxf.extrusion),
           "arc_wcs_start_end": [[round(v, 6) for v in ma.start_point], [round(v, 6) for v in ma.end_point]]}
    print(json.dumps(obs, indent=1))
    json.dump(obs, open("/out/probe_mirror_results.json", "w"), indent=1)
asyncio.run(main())


async def readback():
    """entity get on the mirrored circle: does the tool report WCS or raw OCS center?"""
    await S.drawing(operation="create")
    c = J(await S.entity(operation="create_circle", data={"cx": 0, "cy": 0, "radius": 1}))["payload"]["handle"]
    m = J(await S.entity(operation="mirror", entity_id=c, x1=50, y1=-10, x2=50, y2=10))["payload"]["handle"]
    g = J(await S.entity(operation="get", entity_id=m))
    print("entity_get_mirrored_circle", json.dumps(g))
    json.dump({"entity_get_mirrored_circle": g, "true_wcs_center": [100, 0]}, open("/out/probe_mirror_readback.json", "w"), indent=1)
asyncio.run(readback())
