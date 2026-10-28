from pathlib import Path
import ezdxf

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
except ImportError as ex:
    print("no preview:", ex)
    raise SystemExit(0)

HERE = Path(__file__).resolve().parent
doc = ezdxf.readfile(HERE / "part_rev.dxf")
for name, out in (("Model", "preview_model.png"), ("Base Plate", "preview_sheet.png")):
    fig = plt.figure(figsize=(16, 11))
    ax = fig.add_axes([0, 0, 1, 1])
    Frontend(RenderContext(doc), MatplotlibBackend(ax)).draw_layout(doc.layouts.get(name), finalize=True)
    fig.savefig(HERE / out, dpi=110)
    print("wrote", out)
