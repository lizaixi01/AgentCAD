"""The flange batch for the launch video: check each row of the H3 parameter table, build apply_batch jobs
for the valid ones (English and Chinese labels) and list the rejected rows with the reason."""
import json
import math
import sys

ROWS = """FL-101,150,60,110,6,12,Q235
FL-102,180,75,135,8,14,Q235
FL-103,120,40,90,4,11,45钢
FL-104,200,90,160,8,18,Q345
FL-105,160,60,120,6,14,Q235
FL-106,100,30,70,4,9,304不锈钢
FL-107,220,110,180,12,14,Q235
FL-108,140,50,105,6,11,45钢
FL-109,130,60,118,6,14,Q235
FL-110,250,120,200,16,18,Q345
FL-111,90,40,66,16,14,Q235
FL-112,170,80,130,8,13,304不锈钢"""
EN = {"Q235": "Q235", "Q345": "Q345", "45钢": "C45 steel", "304不锈钢": "304 stainless"}


def g(v):
    return int(v) if float(v).is_integer() else v


def build(lang):
    jobs, rejected = [], []
    for line in ROWS.splitlines():
        no, od, b, p, n, d, mat = line.split(",")
        od, b, p, d, n = float(od), float(b), float(p), float(d), int(n)
        r = p / 2
        why = []
        if r + d / 2 >= od / 2:
            why.append({"en": f"bolt holes reach r = {r + d / 2:g} mm, past the outer radius {od / 2:g} mm",
                        "zh": f"螺栓孔外缘到 r = {r + d / 2:g} mm，超出外圆半径 {od / 2:g} mm"})
        if r - d / 2 <= b / 2:
            why.append({"en": "bolt holes cut into the bore", "zh": "螺栓孔碰到中心孔"})
        chord = 2 * r * math.sin(math.pi / n)
        if chord <= d:
            why.append({"en": f"{n} × Ø{d:g} holes overlap: centres only {chord:.1f} mm apart",
                        "zh": f"{n} 个 Ø{d:g} 孔相互重叠：孔心距只有 {chord:.1f} mm"})
        if why:
            rejected.append({"no": no, "why": [w[lang] for w in why]})
            continue
        e = od / 2 + 8
        text = f"{no}  Material {EN[mat]}" if lang == "en" else f"{no}  材料 {mat}"
        ops = [
            {"op": "add_circle", "center": [0, 0], "diameter": g(od), "layer": "OUTLINE", "tag": "od"},
            {"op": "add_circle", "center": [0, 0], "diameter": g(b), "layer": "OUTLINE", "tag": "bore"},
            {"op": "add_circle", "center": [0, 0], "diameter": g(p), "layer": "CENTER", "linetype": "CENTER", "tag": "pcd"},
            {"op": "add_circle", "center": [0, g(r)], "diameter": g(d), "layer": "HOLES", "tag": "h1"},
            {"op": "array_polar", "target": "tag:h1", "center": [0, 0], "count": n, "total_angle": 360},
            {"op": "add_line", "start": [-g(e), 0], "end": [g(e), 0], "layer": "CENTER", "linetype": "CENTER"},
            {"op": "add_line", "start": [0, -g(e)], "end": [0, g(e)], "layer": "CENTER", "linetype": "CENTER"},
            {"op": "add_diameter_dim", "target": "tag:od", "angle": 20, "outside": True, "layer": "DIM"},
            {"op": "add_diameter_dim", "target": "tag:pcd", "angle": -35, "outside": True, "layer": "DIM"},
            {"op": "add_diameter_dim", "target": "tag:bore", "angle": 135, "layer": "DIM"},
            {"op": "add_diameter_dim", "target": "tag:h1", "angle": 60, "text": f"{n}×<>", "layer": "DIM"},
            {"op": "add_text", "text": text, "insert": [-g(od / 2), -g(od / 2 + 24)], "height": 5, "layer": "TEXT"},
        ]
        folder = "flanges" if lang == "en" else "flanges_zh"
        jobs.append({"path": f"{folder}/{no}.dxf", "create": {"units": "mm", "template": "mechanical"},
                     "label": f"{no} from the parameter table", "operations": ops,
                     "requirements": [{"type": "hole_count", "diameter": g(d), "count": n}]})
    return jobs, rejected


if __name__ == "__main__":
    lang = sys.argv[1]
    jobs, rejected = build(lang)
    json.dump({"jobs": jobs, "rejected": rejected}, open(f"frames/v2/batch_{lang}.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(rejected, ensure_ascii=False))
    print(json.dumps(jobs, ensure_ascii=False, separators=(",", ":")))
