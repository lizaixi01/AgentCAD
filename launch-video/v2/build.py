"""Collect the real captures into v2/assets/<lang>/ and write v2/data_<lang>.js for film.html.

Everything shown comes from the AgentCAD runs of 2026-11-03 in D:/Projects/AgentCAD/playground: drawings exported
by AgentCAD (PNG), drawings as the live viewer serves them (SVG), AutoCAD 2027's own plot, live-viewer and
setup-wizard screenshots. Text strings for both languages live here and in narration.json.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from PIL import Image

HERE = Path(__file__).parent
FILM = HERE.parent
REPO = FILM.parent
PLAY = Path("D:/Projects/AgentCAD/playground")
LIVE = FILM / "frames" / "live"
V2 = FILM / "frames" / "v2"
VOICE = "en"   # the voice both films are cut to

FLANGES = ["FL-101", "FL-102", "FL-103", "FL-104", "FL-105", "FL-106", "FL-107", "FL-108", "FL-110", "FL-112"]
TABLE = [r.split(",") for r in """FL-101,150,60,110,6,12
FL-102,180,75,135,8,14
FL-103,120,40,90,4,11
FL-104,200,90,160,8,18
FL-105,160,60,120,6,14
FL-106,100,30,70,4,9
FL-107,220,110,180,12,14
FL-108,140,50,105,6,11
FL-109,130,60,118,6,14
FL-110,250,120,200,16,18
FL-111,90,40,66,16,14
FL-112,170,80,130,8,13""".splitlines()]

TEXT = {
    "en": {
        "font_display": "'Newsreader', Georgia, serif", "font_body": "'Inter', 'Segoe UI', sans-serif",
        "open": ["For four decades, CAD has been built for a hand on a mouse.", "The next engineer at the keyboard is an agent.",
                 "Agents don't need a mouse.<br>They need a runtime."],
        "tagline": "The CAD runtime built for AI agents.",
        "script_title": "edit_drawing.py", "why_head": "A throwaway script", "why_fail": ["No undo", "No checks", "No memory"],
        "pillars": [["Operations", "71 typed CAD operations, run as transactions"], ["Undo", "A checkpoint before every edit, a journal on disk"],
                    ["A second pair of eyes", "An independent checker re-reads every saved file"], ["Sight", "It renders what it drew, like the plotted sheet"]],
        "agent": "Claude Code", "connected": "connected to AgentCAD",
        "p_plan": "Draw a two-bedroom apartment, 12 × 9 m: living and dining, two bedrooms, a bath and a kitchen. Doors, windows, dimensions and room areas.",
        "t_plan": ["draw_arch_plan · 5 walls · 10 doors and windows · 5 rooms", "✓ saved · 0 errors · 0 warnings"],
        "measured": "measured from the walls",
        "p_edit": "Make the master bedroom 1 m deeper.",
        "t_edit": ["bedroom wall → 3.5 m · bedroom door → 1.5 m", "✓ one transaction · 0 errors"],
        "rooms_before_after": [["Master bedroom", "18.66", "22.98"], ["Bedroom", "18.66", "14.34"]],
        "new_session": "New session · no memory of the last one",
        "p_undo": "Someone changed this plan in an earlier session. Undo that last change.",
        "t_undo": ["history", "read_engineering", "rollback → cp-0002"],
        "r_undo": "Undone: the master bedroom 1 m deeper. Both bedrooms are 18.66 m² again.",
        "feed": "Live viewer · what happened",
        "table_head": ["Part", "OD", "Bore", "PCD", "n", "Ø"], "reject": "rejected",
        "why_109": "bolt holes reach r 66, past the rim (r 65)", "why_111": "16 × Ø14 overlap: centres 12.9 mm apart",
        "batch_stat": ["10 drawings", "3.1 s", "10 / 10 checks passed"],
        "dwg_window": "AutoCAD 2027 · two_bed_apartment.dwg", "audit": ["AUDIT", "0 errors found, 0 fixed", "87 entities seen by AutoCAD"],
        "bench_head": "Same agent. Same model. Only the tools change.",
        "stats": [["4.1", "min", "vs 12.9", "five-round revision, vs the same agent writing code"],
                  ["1.9×", "", "faster", "than AutoCAD MCP Pro, with AutoCAD open"],
                  ["3/3", "", "vs 0/3", "undo across sessions, vs AutoCAD MCP Pro"]],
        "board_head": "Source-capability review · 9 CAD MCP servers", "v8": "U-C4N AutoCAD MCP benchmark v8 · 31 / 31",
        "foot": "Our own timed trials (2–3 runs per task) and AI reviews we requested, pinned sources, 2026-10-31. Not an official ranking. Reports, logs and where it did not win: docs/benchmarks.md",
        "install_head": "Open source. Installs in about a minute.", "install_sub": "Claude Code · Codex · any MCP app",
        "close": "Your agent can already write code.<br>Now it can draft.",
        "end": ["The CAD runtime built for AI agents", "Open source · MIT", "github.com/lizaixi01/AgentCAD"],
    },
    "zh": {
        "font_display": "'Noto Serif SC', 'Newsreader', serif", "font_body": "'Noto Sans SC', 'Inter', sans-serif",
        "open": ["四十年来，CAD 一直为握着鼠标的手而设计。", "下一位坐在键盘前的工程师，是 Agent。", "Agent 不需要鼠标。<br>它需要一个运行时。"],
        "tagline": "为 AI Agent 打造的 CAD 运行时",
        "script_title": "edit_drawing.py", "why_head": "用完就扔的脚本", "why_fail": ["不能撤销", "没人检查", "不留记录"],
        "pillars": [["CAD 操作", "71 个带类型的操作，按事务执行"], ["撤销", "每次修改前存检查点，日志写在磁盘上"],
                    ["第二双眼睛", "独立检查器重新读取每一个保存的文件"], ["看得见", "像打印图纸一样，渲染出自己画的东西"]],
        "agent": "Claude Code", "connected": "已连接 AgentCAD",
        "p_plan": "画一套 12 × 9 米的两居室：客餐厅、两间卧室、卫生间和厨房，带门窗、尺寸和房间面积。",
        "t_plan": ["draw_arch_plan · 5 道墙 · 10 处门窗 · 5 个房间", "✓ 已保存 · 0 错误 · 0 警告"],
        "measured": "根据墙体实测",
        "p_edit": "主卧加深 1 米。",
        "t_edit": ["隔墙 → 3.5 米 · 次卧门 → 1.5 米", "✓ 一个事务 · 0 错误"],
        "rooms_before_after": [["主卧", "18.66", "22.98"], ["次卧", "18.66", "14.34"]],
        "new_session": "全新会话 · 不记得上一次",
        "p_undo": "之前有人改过这张平面图，帮我把最后那次修改撤销掉。",
        "t_undo": ["history", "read_engineering", "rollback → cp-0002"],
        "r_undo": "已撤销：主卧加深 1 米。主卧和次卧都恢复为 18.66 m²。",
        "feed": "实时查看器 · 动态",
        "table_head": ["零件号", "外径", "中心孔", "节圆", "孔数", "孔径"], "reject": "不出图",
        "why_109": "螺栓孔外缘 r 66，超出外圆 r 65", "why_111": "16 个 Ø14 孔重叠：孔心距 12.9 mm",
        "batch_stat": ["10 张图纸", "3.1 秒", "10 / 10 项检查通过"],
        "dwg_window": "AutoCAD 2027 · 两居室平面图.dwg", "audit": ["AUDIT", "共发现 0 个错误，已修复 0 个", "AutoCAD 读到 65 个实体"],
        "bench_head": "同一个 Agent，同一个模型，只换工具。",
        "stats": [["4.1", "分钟", "对比 12.9", "五轮改图，对比同一 Agent 自己写代码"],
                  ["1.9×", "", "更快", "对比 AutoCAD MCP Pro（AutoCAD 同时打开）"],
                  ["3/3", "", "对比 0/3", "跨会话撤销，对比 AutoCAD MCP Pro"]],
        "board_head": "源码能力评审 · 9 个 CAD MCP 服务", "v8": "U-C4N AutoCAD MCP 基准 v8 · 31 / 31",
        "foot": "数据来自我们自己的计时试验（每题 2–3 次）和我们委托的 AI 评审，源码版本固定，2026-10-31。非官方排名。报告、日志以及没赢的地方：docs/benchmarks.md",
        "install_head": "开源，大约一分钟装好。", "install_sub": "Claude Code · Codex · 任何 MCP 应用",        "close": "你的 Agent 已经会写代码。<br>现在，它也会画图了。",
        "end": ["The CAD runtime built for AI agents", "开源 · MIT", "github.com/lizaixi01/AgentCAD"],
    },
}
BOARD = [["AgentCAD", 100], ["AutoCAD MCP Pro", 93], ["LokmenoWer/best-cad-mcp", 41], ["beiming183-cloud/AutoCAD-MCP", 33],
         ["varavista/autocad-mcp", 31], ["puran-water/autocad-mcp", 24], ["AnCode666/multiCAD-mcp", 18],
         ["zh19980811/Easy-MCP-AutoCad", 14], ["daobataotie/CAD-MCP", 13]]


def svg_lines(svg: str, keep_text: bool, drop_fills: bool = False) -> str:
    """The viewer's SVG with the drawing's own colours kept as classes. Fill-only classes are text and arrowheads:
    their paths get data-fill so film.html fades them in instead of drawing them. The viewer sets Chinese text as
    boxes, so the Chinese film drops black text (keep_text=False); drop_fills removes all of them (bare linework)."""
    svg = re.sub(r'<rect fill="#ffffff"[^>]*/>', "", svg)
    svg = re.sub(r'width="[^"]*mm" height="[^"]*mm" ', "", svg, count=1)
    fills = {m.group(1): m.group(2) for m in re.finditer(r"\.(C\d+) \{stroke: none;[^}]*fill: (#[0-9a-f]{6})", svg)}
    for cls, colour in fills.items():
        if drop_fills or (not keep_text and colour == "#000000"):
            svg = re.sub(rf'<path [^>]*class="{cls}" />', "", svg)
        else:
            svg = svg.replace(f'class="{cls}"', f'class="{cls}" data-fill="1"')
    return svg


def light_on_clear(src: Path, dst: Path) -> None:
    """A plotted PNG (dark ink on white paper) as light ink on a transparent background, hues kept: the
    lightness is inverted and becomes the alpha, so the film's background shows through the paper."""
    import colorsys

    import numpy as np
    rgb = np.asarray(Image.open(src).convert("RGB")).astype(float) / 255
    mx, mn = rgb.max(-1), rgb.min(-1)
    light = (mx + mn) / 2
    alpha = 1 - light                                     # white paper -> clear, black ink -> opaque
    sat = np.where(mx - mn > 1e-6, (mx - mn) / (1 - np.abs(2 * light - 1) + 1e-6), 0)
    ink = np.stack([np.full_like(light, .93), np.full_like(light, .95), np.full_like(light, .97)], -1)
    coloured = sat > .25                                  # dimension green, centre-line red: keep their hue
    if coloured.any():
        rgb_c = rgb[coloured]
        alpha[coloured] = np.clip(mx[coloured] * 1.0, 0, 1)
        ink[coloured] = np.clip(rgb_c / (rgb_c.max(-1, keepdims=True) + 1e-6), 0, 1) * .95 + .05
    out = np.dstack([ink, np.clip(alpha * 1.15, 0, 1)])
    Image.fromarray((out * 255).astype("uint8"), "RGBA").save(dst)


def main() -> None:
    durs = json.loads((HERE / "voice" / "durations.json").read_text(encoding="utf-8"))
    lines = json.loads((HERE / "narration.json").read_text(encoding="utf-8"))["lines"]
    for lang in ("en", "zh"):
        out = HERE / "assets" / lang
        out.mkdir(parents=True, exist_ok=True)
        copy = {
            "plan1.png": PLAY / "launch_video" / ("apartment_v1.png" if lang == "en" else "plan_zh.png"),
            "plan2.png": PLAY / "launch_video" / ("apartment_v2.png" if lang == "en" else "plan_zh_v2.png"),
            "acad.png": V2 / "acad" / f"acad__plan_{lang}.png",
            "wiz1.png": LIVE / ("wiz_1.png" if lang == "en" else "zh_wiz_1.png"),
            "wiz2.png": LIVE / ("wiz_2.png" if lang == "en" else "zh_wiz_2.png"),
            "wiz3.png": LIVE / ("wiz_3.png" if lang == "en" else "zh_wiz_3.png"),
        }
        for name, src in copy.items():
            if name.startswith("plan"):
                light_on_clear(src, out / name)
            else:
                shutil.copyfile(src, out / name)
        # the viewer's "what happened" feed and version list after the new-session undo
        Image.open(V2 / lang / "plan_04_undone.png").crop((2770, 140, 3400, 1440)).save(out / "feed.png")
        Image.open(V2 / lang / "plan_04_undone.png").save(out / "viewer.png")
        svgs = {f: svg_lines((V2 / "svg" / f"{f}.svg").read_text(encoding="utf-8"), keep_text=lang == "en") for f in FLANGES}
        data = {"lang": lang, "t": TEXT[lang], "board": BOARD, "table": TABLE, "flanges": FLANGES, "svgs": svgs,
                "plan_svg": svg_lines((V2 / "svg" / "apartment.svg").read_text(encoding="utf-8"), keep_text=False, drop_fills=True),
                # both films use the English voice; the Chinese one shows Chinese and English subtitles
                "lines": [{"id": l["id"], "text": l[lang], "en": l["en"], "dur": durs[VOICE][l["id"]]} for l in lines],
                "logo": (REPO / "docs" / "assets" / "brand" / "logo-dark.svg").read_text(encoding="utf-8")}
        (HERE / f"data_{lang}.js").write_text("window.DATA = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
        print(lang, "ok")


if __name__ == "__main__":
    main()
