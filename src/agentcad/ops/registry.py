"""Declarative operation registry.

Each operation declares typed parameters once; the same definition drives
parameter validation, the JSON-schema catalog exposed over MCP/CLI/HTTP, and
execution. Lengths accept numbers (drawing units) or strings like ``"8mm"``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from ezdxf.document import Drawing
from ezdxf.entities import DXFGraphic

from ..errors import input_error
from ..model import set_tag, tag_index
from ..units import parse_length


@dataclass
class Param:
    type: str  # length|number|angle|int|bool|string|enum|point|points|selector|object|list|dim|any
    required: bool = False
    default: Any = None
    description: str = ""
    enum: list[str] | None = None
    gt: float | None = None  # exclusive lower bound
    ge: float | None = None  # inclusive lower bound
    le: float | None = None

    def json_schema(self) -> dict[str, Any]:
        t = self.type
        unit_note = " (drawing units, or string with unit e.g. '8mm')"
        if t in ("length",):
            s: dict[str, Any] = {"type": ["number", "string"], "description": self.description + unit_note}
        elif t == "number":
            s = {"type": "number", "description": self.description}
        elif t == "angle":
            s = {"type": "number", "description": self.description + " (degrees, counter-clockwise)"}
        elif t == "int":
            s = {"type": "integer", "description": self.description}
        elif t == "bool":
            s = {"type": "boolean", "description": self.description}
        elif t == "string":
            s = {"type": "string", "description": self.description}
        elif t == "enum":
            s = {"type": "string", "enum": self.enum, "description": self.description}
        elif t == "point":
            s = {"type": "array", "items": {"type": ["number", "string"]}, "minItems": 2, "maxItems": 2,
                 "description": self.description + " [x, y]" + unit_note}
        elif t == "points":
            s = {"type": "array", "items": {"type": "array"},
                 "description": self.description + " list of [x, y] (or [x, y, bulge])" + unit_note}
        elif t == "selector":
            s = {"description": self.description + " — entity selector: handle id, 'tag:<name>', '$<op index>', "
                 "a list of these, or a filter object {type, layer, tag, tag_prefix}"}
        elif t == "object":
            s = {"type": "object", "description": self.description}
        elif t == "dim":
            s = {"type": ["number", "string"], "description": self.description + " (mm, a string with a unit "
                 "such as '0.5in', or an expression such as '=Params.width * 2')"}
        elif t == "any":
            s = {"description": self.description}
        else:
            s = {"type": "array", "description": self.description}
        for k, v in (("exclusiveMinimum", self.gt), ("minimum", self.ge), ("maximum", self.le)):
            if v is not None:
                s[k] = v
        if self.default is not None:
            s["default"] = self.default
        return s


@dataclass
class OpDef:
    name: str
    category: str
    description: str
    params: dict[str, Param]
    fn: Callable[..., dict[str, Any]]
    common_draw: bool = False  # accepts layer/color/linetype/lineweight/tag
    common_all: bool = True  # accepts layout (2D ops; 3D part ops have no layouts)

    def schema(self) -> dict[str, Any]:
        props = {k: p.json_schema() for k, p in self.all_params().items()}
        req = [k for k, p in self.all_params().items() if p.required]
        return {"op": self.name, "category": self.category, "description": self.description,
                "params": {"type": "object", "properties": props, "required": req,
                           "additionalProperties": False}}

    def all_params(self) -> dict[str, Param]:
        if not self.common_all:
            return dict(self.params)
        if not self.common_draw:
            return {**self.params, **COMMON_ALL}
        return {**self.params, **COMMON_DRAW, **COMMON_ALL}


COMMON_ALL: dict[str, Param] = {
    "layout": Param("string", description="Layout to work in: 'Model' (default) or a paper-space layout name "
                    "from read_drawing. New entities go there and filter selectors search it; edits that derive "
                    "entities from an existing one (copy, offset, trim, fillet) keep them in that entity's layout"),
}

COMMON_DRAW: dict[str, Param] = {
    "layer": Param("string", description="Layer name (created on the fly if missing)"),
    "color": Param("int", ge=0, le=257, description="ACI color (256 = BYLAYER)"),
    "linetype": Param("string", description="Linetype name, e.g. CONTINUOUS, CENTER, DASHED"),
    "lineweight": Param("int", description="Lineweight in 1/100 mm (e.g. 50 = 0.50 mm), -1 = BYLAYER"),
    "tag": Param("string", description="Semantic tag for later reference as 'tag:<name>'"),
    "if_tag_exists": Param("enum", enum=["error", "skip", "replace"], default="error",
                           description="Behaviour when an entity with this tag already exists (use 'skip' for idempotent replays)"),
}

REGISTRY: dict[str, OpDef] = {}


def op(name: str, category: str, description: str, params: dict[str, Param], *, common_draw: bool = False):
    def deco(fn: Callable[..., dict[str, Any]]):
        REGISTRY[name] = OpDef(name, category, description, params, fn, common_draw)
        return fn
    return deco


# --- execution context --------------------------------------------------------

class Ctx:
    def __init__(self, doc: Drawing, unit: str | None, policy: Any) -> None:
        self.doc = doc
        self.model = doc.modelspace()
        # The active layout of the current op ('layout' parameter, default model space). Ops add new
        # entities here; ops that derive entities from an existing one use space_of() instead.
        self.msp = self.model
        self.layout = self.msp
        self.unit = unit
        self.policy = policy
        self.refs: dict[int, list[str]] = {}
        self.added: list[str] = []
        self.modified: list[str] = []
        self.deleted: list[str] = []
        self.op_index = 0
        self._tags: dict[str, list[DXFGraphic]] | None = None

    def use_layout(self, name: str | None) -> None:
        if not name or name.lower() == "model":
            self.msp = self.layout = self.model
            return
        try:
            self.msp = self.layout = self.doc.layouts.get(name)
        except Exception:
            raise input_error("LAYOUT_NOT_FOUND", f"No layout named {name!r}",
                              hint=f"Layouts: {self.doc.layouts.names_in_taborder()}")

    def space_of(self, e: DXFGraphic):
        """The layout (model or paper space) that owns ``e``."""
        lay = self.doc.layouts.get_layout_for_entity(e)
        return lay if lay is not None else self.msp

    # change tracking -------------------------------------------------------
    def created(self, e: DXFGraphic) -> str:
        h = e.dxf.handle
        self.added.append(h)
        return h

    def touched(self, e: DXFGraphic) -> None:
        h = e.dxf.handle
        if h not in self.added and h not in self.modified:
            self.modified.append(h)

    def removed(self, e: DXFGraphic) -> None:
        h = e.dxf.handle
        if h in self.added:
            self.added.remove(h)
        else:
            if h in self.modified:
                self.modified.remove(h)
            self.deleted.append(h)
        self._tags = None
        blk = e.dxf.get("geometry") if e.dxftype() == "DIMENSION" else None
        self.space_of(e).delete_entity(e)
        if blk and blk in self.doc.blocks:  # drop the orphaned *D anonymous block
            self.doc.blocks.delete_block(blk, safe=False)

    def tags(self) -> dict[str, list[DXFGraphic]]:
        if self._tags is None:
            self._tags = tag_index(self.doc)
        return self._tags

    # common attributes -----------------------------------------------------
    def attribs(self, p: dict[str, Any]) -> dict[str, Any]:
        a: dict[str, Any] = {}
        layer = p.get("layer")
        if layer:
            if layer not in self.doc.layers:
                self.doc.layers.add(layer)
            a["layer"] = layer
        if p.get("color") is not None:
            a["color"] = p["color"]
        lt = p.get("linetype")
        if lt:
            if lt not in self.doc.linetypes and lt.upper() not in ("BYLAYER", "BYBLOCK", "CONTINUOUS"):
                raise input_error("UNKNOWN_LINETYPE", f"Linetype {lt!r} is not defined",
                                  hint=f"Available: {sorted(l.dxf.name for l in self.doc.linetypes)}")
            a["linetype"] = lt
        if p.get("lineweight") is not None:
            a["lineweight"] = p["lineweight"]
        return a

    def finish(self, e: DXFGraphic, p: dict[str, Any]) -> str:
        tag = p.get("tag")
        if tag:
            set_tag(self.doc, e, tag)
            self.tags().setdefault(tag, []).append(e)
        return self.created(e)


def check_tag(ctx: Ctx, p: dict[str, Any]) -> list[str] | None:
    """Apply ``if_tag_exists``. Returns existing handles if the op must be skipped."""
    tag = p.get("tag")
    if not tag:
        return None
    existing = ctx.tags().get(tag)
    if not existing:
        return None
    mode = p.get("if_tag_exists") or "error"
    if mode == "skip":
        return [e.dxf.handle for e in existing]
    if mode == "replace":
        for e in list(existing):
            ctx.removed(e)
        ctx.tags().pop(tag, None)
        return None
    raise input_error("TAG_EXISTS", f"An entity tagged {tag!r} already exists",
                      entities=[e.dxf.handle for e in existing],
                      hint="Use if_tag_exists='skip' for idempotent replays or 'replace' to redraw it")


# --- parameter coercion ---------------------------------------------------------

def _point(v: Any, unit: str | None, name: str, allow_bulge: bool = False) -> tuple:
    if isinstance(v, dict) and "x" in v and "y" in v:
        v = [v["x"], v["y"]]
    if not isinstance(v, (list, tuple)) or len(v) not in ((2, 3) if allow_bulge else (2,)):
        raise input_error("INVALID_POINT", f"{name}: expected [x, y]{' or [x, y, bulge]' if allow_bulge else ''}, got {v!r}")
    x = parse_length(v[0], unit, name + ".x")
    y = parse_length(v[1], unit, name + ".y")
    if not (math.isfinite(x) and math.isfinite(y)):
        raise input_error("INVALID_POINT", f"{name}: coordinates must be finite")
    if len(v) == 3:
        b = v[2]
        if not isinstance(b, (int, float)) or isinstance(b, bool):
            raise input_error("INVALID_POINT", f"{name}: bulge must be a number")
        return (x, y, float(b))
    return (x, y)


def coerce(opdef: OpDef, raw: dict[str, Any], unit: str | None, index: int) -> dict[str, Any]:
    params = opdef.all_params()
    unknown = [k for k in raw if k not in params and k not in ("op", "comment")]
    if unknown:
        raise input_error("UNKNOWN_PARAM", f"{opdef.name}: unknown parameter(s) {unknown}",
                          op=opdef.name, op_index=index, hint=f"Valid parameters: {sorted(params)}")
    out: dict[str, Any] = {}
    for name, p in params.items():
        fname = f"{opdef.name}.{name}"
        if name not in raw or raw[name] is None:
            if p.required:
                raise input_error("MISSING_PARAM", f"{opdef.name}: missing required parameter {name!r}",
                                  op=opdef.name, op_index=index, details={"param": name, "schema": p.json_schema()})
            out[name] = p.default
            continue
        v = raw[name]
        try:
            if p.type == "length" or p.type == "number" or p.type == "angle":
                if p.type == "length":
                    v = parse_length(v, unit, fname)
                elif isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise input_error("INVALID_NUMBER", f"{fname}: expected a number, got {v!r}")
                v = float(v)
                if not math.isfinite(v):
                    raise input_error("INVALID_NUMBER", f"{fname}: must be finite")
            elif p.type == "int":
                if isinstance(v, bool) or not isinstance(v, int):
                    if isinstance(v, float) and v.is_integer():
                        v = int(v)
                    else:
                        raise input_error("INVALID_INT", f"{fname}: expected an integer, got {v!r}")
            elif p.type == "bool":
                if not isinstance(v, bool):
                    raise input_error("INVALID_BOOL", f"{fname}: expected true/false")
            elif p.type == "string":
                if not isinstance(v, str) or not v:
                    raise input_error("INVALID_STRING", f"{fname}: expected a non-empty string")
            elif p.type == "enum":
                if v not in (p.enum or []):
                    raise input_error("INVALID_ENUM", f"{fname}: {v!r} not in {p.enum}")
            elif p.type == "point":
                v = _point(v, unit, fname)
            elif p.type == "points":
                if not isinstance(v, list) or not v:
                    raise input_error("INVALID_POINTS", f"{fname}: expected a non-empty list of points")
                v = [_point(q, unit, f"{fname}[{i}]", allow_bulge=True) for i, q in enumerate(v)]
            elif p.type == "object":
                if not isinstance(v, dict):
                    raise input_error("INVALID_OBJECT", f"{fname}: expected an object")
            elif p.type == "list":
                if not isinstance(v, list):
                    raise input_error("INVALID_LIST", f"{fname}: expected a list")
            elif p.type == "selector":
                if not isinstance(v, (str, list, dict)):
                    raise input_error("BAD_SELECTOR", f"{fname}: invalid selector {v!r}")
            elif p.type == "dim":  # parsed by the 3D backend, which also evaluates expressions
                if isinstance(v, bool) or not isinstance(v, (int, float, str)) or v == "":
                    raise input_error("INVALID_LENGTH", f"{fname}: expected a number, a length string or "
                                                        f"'=expression', got {v!r}")
        except Exception as exc:  # attach op context
            from ..errors import AgentCADError
            if isinstance(exc, AgentCADError):
                exc.op = opdef.name
                exc.op_index = index
            raise
        if isinstance(v, float):
            for bound, ok, word in ((p.gt, lambda a, b: a > b, ">"), (p.ge, lambda a, b: a >= b, ">="),
                                    (p.le, lambda a, b: a <= b, "<=")):
                if bound is not None and not ok(v, bound):
                    raise input_error("OUT_OF_RANGE", f"{fname}: must be {word} {bound}, got {v}",
                                      op=opdef.name, op_index=index)
        if isinstance(v, int) and not isinstance(v, bool):
            if (p.ge is not None and v < p.ge) or (p.le is not None and v > p.le) or (p.gt is not None and v <= p.gt):
                raise input_error("OUT_OF_RANGE", f"{fname}: value {v} out of range",
                                  op=opdef.name, op_index=index)
        out[name] = v
    return out


def catalog() -> list[dict[str, Any]]:
    return [REGISTRY[k].schema() for k in sorted(REGISTRY)]
