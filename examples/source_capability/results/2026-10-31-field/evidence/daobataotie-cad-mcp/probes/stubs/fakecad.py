"""Minimal in-memory stand-in for the CAD COM object model (written by the reviewer).

It is NOT a CAD backend. It records the calls the product makes so probes can check
argument wiring and the product's own success/failure reporting. Geometry produced here
is the fake's, so it is interface evidence only.

Env:
  FAKECAD=none   -> GetActiveObject/Dispatch raise (no CAD installed)
  FAKECAD=mem    -> an in-memory app with one document
  FAKE_FAIL_LAYER=1 -> setting entity.Layer raises (simulates a CAD rejecting a style write)
"""
import os

CALLS = []  # (object, method, args)


class ComError(Exception):
    def __init__(self, msg, hresult=-2147221005):
        super().__init__(msg)
        self.hresult = hresult
        self.excepinfo = None


class Entity:
    _next = 0x100

    def __init__(self, ms, kind, **geom):
        object.__setattr__(self, "_ms", ms)
        object.__setattr__(self, "ObjectName", kind)
        Entity._next += 1
        object.__setattr__(self, "Handle", format(Entity._next, "X"))
        object.__setattr__(self, "Layer", "0")
        object.__setattr__(self, "color", 256)
        object.__setattr__(self, "Lineweight", -1)
        for k, v in geom.items():
            object.__setattr__(self, k, v)

    def __setattr__(self, k, v):
        CALLS.append((self.Handle, "set:" + k, (v,)))
        if k == "Layer" and os.environ.get("FAKE_FAIL_LAYER") == "1":
            raise ComError("layer write rejected (injected)", hresult=-2145386476)
        object.__setattr__(self, k, v)

    def Delete(self):
        CALLS.append((self.Handle, "Delete", ()))
        self._ms._items.remove(self)

    def Move(self, a, b):
        CALLS.append((self.Handle, "Move", (list(a), list(b))))

    def Rotate(self, c, ang):
        CALLS.append((self.Handle, "Rotate", (list(c), ang)))

    def ScaleEntity(self, c, f):
        CALLS.append((self.Handle, "ScaleEntity", (list(c), f)))

    def Copy(self):
        CALLS.append((self.Handle, "Copy", ()))
        e = Entity(self._ms, self.ObjectName)
        self._ms._items.append(e)
        return e

    def Mirror(self, a, b):
        CALLS.append((self.Handle, "Mirror", (list(a), list(b))))
        return self.Copy()

    def Offset(self, d):
        CALLS.append((self.Handle, "Offset", (d,)))
        return (self.Copy(),)

    def AppendOuterLoop(self, objs):
        CALLS.append((self.Handle, "AppendOuterLoop", (len(objs),)))

    def Evaluate(self):
        CALLS.append((self.Handle, "Evaluate", ()))


class ModelSpace:
    def __init__(self):
        self._items = []

    @property
    def Count(self):
        return len(self._items)

    def Item(self, i):
        return self._items[i]

    def _add(self, kind, **g):
        e = Entity(self, kind, **g)
        self._items.append(e)
        CALLS.append(("MS", "Add:" + kind, tuple(g.items())))
        return e

    def AddLine(self, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        return self._add("AcDbLine", StartPoint=tuple(a), EndPoint=tuple(b), Length=(dx * dx + dy * dy) ** 0.5)

    def AddCircle(self, c, r):
        return self._add("AcDbCircle", Center=tuple(c), Radius=r, Area=3.141592653589793 * r * r)

    def AddArc(self, c, r, s, e):
        return self._add("AcDbArc", Center=tuple(c), Radius=r, StartAngle=s, EndAngle=e)

    def AddEllipse(self, c, major, ratio):
        return self._add("AcDbEllipse", Center=tuple(c), MajorAxis=tuple(major), RadiusRatio=ratio)

    def AddPolyline(self, pts):
        return self._add("AcDb2dPolyline", Coordinates=tuple(pts), Closed=False)

    def AddText(self, s, p, h):
        return self._add("AcDbText", TextString=s, InsertionPoint=tuple(p), Height=h, Rotation=0.0)

    def AddHatch(self, kind, pat, assoc):
        return self._add("AcDbHatch", PatternName=pat)

    def AddDimAligned(self, a, b, t):
        return self._add("AcDbAlignedDimension", ExtLine1Point=tuple(a), ExtLine2Point=tuple(b))

    def InsertBlock(self, p, name, sx, sy, sz, rot):
        return self._add("AcDbBlockReference", Name=name, InsertionPoint=tuple(p))


class Layer:
    def __init__(self, name):
        self.Name = name


class Layers:
    def __init__(self):
        self._l = [Layer("0")]

    @property
    def Count(self):
        return len(self._l)

    def Item(self, i):
        return self._l[i]

    def Add(self, name):
        CALLS.append(("Layers", "Add", (name,)))
        layer = Layer(name)
        self._l.append(layer)
        return layer


class Doc:
    def __init__(self, name="Drawing1.dwg"):
        self.Name = name
        self.FullName = ""
        self.ModelSpace = ModelSpace()
        self.Layers = Layers()
        self.ActiveLayer = self.Layers.Item(0)
        self.Blocks = Layers()

    def StartUndoMark(self):
        CALLS.append(("Doc", "StartUndoMark", ()))

    def EndUndoMark(self):
        CALLS.append(("Doc", "EndUndoMark", ()))

    def HandleToObject(self, h):
        for e in self.ModelSpace._items:
            if e.Handle == h:
                return e
        raise ComError("Unknown handle", hresult=-2145386484)

    def SendCommand(self, s):
        # A real CAD queues this asynchronously; the fake only records it.
        CALLS.append(("Doc", "SendCommand", (s,)))

    def SaveAs(self, *args):
        CALLS.append(("Doc", "SaveAs", args))

    def Regen(self, *a):
        CALLS.append(("Doc", "Regen", a))

    def Close(self, *a):
        CALLS.append(("Doc", "Close", a))


class Documents:
    def __init__(self, app):
        self._d = [Doc()]

    @property
    def Count(self):
        return len(self._d)

    def Item(self, i):
        return self._d[i]

    def Add(self):
        d = Doc("Drawing%d.dwg" % (len(self._d) + 1))
        self._d.append(d)
        return d

    def Open(self, p):
        d = Doc(os.path.basename(p))
        d.FullName = p
        self._d.append(d)
        return d


class App:
    def __init__(self):
        self.Documents = Documents(self)
        self.Visible = True
        self.HWND = 0

    @property
    def ActiveDocument(self):
        return self.Documents._d[-1]


_APP = None


def get_app(progid):
    global _APP
    if os.environ.get("FAKECAD", "none") != "mem":
        raise ComError("Operation unavailable (no CAD in this container): " + progid)
    if _APP is None:
        _APP = App()
    return _APP
