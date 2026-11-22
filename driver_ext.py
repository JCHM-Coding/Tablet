# Drivers editor on the expanded timeline (objects and bones): channel list
# of the drivers, an editable mapping curve (driver value on X, property
# value on Y, with live input / output markers) and a popup with the full
# driver settings. Gestures keep only plain data; every write re-finds the
# driver and checks that a keyframe is still the one it expects.
import math
import re
import time

import bpy

from . import drawing, panels
from . import graph_ext as gx
from . import timeline_ext as tl

ROWH = tl.ROWH
CH_W = tl.CH_W
INFO_H = 24
HIT_R = 14.0
PT = 4.0
UPDATE_EVERY = 0.06
BTN = (0.20, 0.20, 0.23, 1.0)
COL_OK = (0.45, 0.85, 0.45, 1.0)
COL_BAD = (1.0, 0.35, 0.35, 1.0)
COL_TXT = (0.9, 0.9, 0.92, 1.0)
COL_IN = (0.35, 0.75, 1.0, 1.0)
COL_OUT = (0.55, 0.90, 0.45, 1.0)
COL_GRID = (0.24, 0.24, 0.28, 1.0)
COL_ZERO = (0.45, 0.45, 0.52, 1.0)
COL_HANDLE = (0.75, 0.75, 0.8, 1.0)

_TYPE_NAME = {'AVERAGE': "Average", 'SUM': "Sum", 'SCRIPTED': "Scripted",
              'MIN': "Min", 'MAX': "Max"}
_SAFE = re.compile(r"^[A-Za-z0-9_+\-*/%().,<>=! ]*$")
_MATH = {"abs": abs, "min": min, "max": max, "round": round,
         "sin": math.sin, "cos": math.cos, "tan": math.tan,
         "asin": math.asin, "acos": math.acos, "atan": math.atan,
         "atan2": math.atan2, "sqrt": math.sqrt, "pow": pow,
         "exp": math.exp, "log": math.log, "floor": math.floor,
         "ceil": math.ceil, "radians": math.radians,
         "degrees": math.degrees, "pi": math.pi, "True": True,
         "False": False}

_fold = set()
_scroll = 0.0
_g = {"x0": -0.5, "ppx": 120.0, "y0": 0.0, "ppy": 120.0, "fit": True,
      "key": None}
_s = {"mode": None, "last": (0, 0), "moved": 0.0, "x0": 0.0, "y0": 0.0,
      "snap": [], "lo": -1e9, "hi": 1e9, "ref": None, "row": None, "w": 0}
_poly = {}
_dirty = set()
_last_up = [0.0]


def _in(r, mx, my):
    return r[0] <= mx <= r[2] and r[1] <= my <= r[3]


def _push(msg):
    try:
        bpy.ops.ed.undo_push(message=msg)
    except RuntimeError:
        pass


# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------

def _key_str(oname, path, idx):
    return f"{oname}|{path}|{idx}"


def _parse(s):
    try:
        oname, path, idx = s.rsplit("|", 2)
        return oname, path, int(idx)
    except (ValueError, AttributeError):
        return None


def _find(key):
    """Fresh (object, fcurve) of a key string, or (None, None)."""
    p = _parse(key)
    if p is None:
        return None, None
    oname, path, idx = p
    obj = bpy.data.objects.get(oname)
    ad = obj.animation_data if obj else None
    if ad is None:
        return None, None
    try:
        fc = ad.drivers.find(path, index=idx)
    except (TypeError, RuntimeError):
        fc = None
    return (obj, fc) if fc is not None else (None, None)


def _curve(context):
    return _find(context.scene.nomad_drv_active)


def _words(context):
    sc = context.scene
    if getattr(sc, "nomad_tl_search_on", False):
        return sc.nomad_tl_search.strip().lower().split()
    return []


def _allowed(sc):
    out = set()
    if sc.nomad_tl_f_loc:
        out.add('LOC')
    if sc.nomad_tl_f_rot:
        out.add('ROT')
    if sc.nomad_tl_f_scale:
        out.add('SCALE')
    return out


def _driver_curves(obj, words, allowed):
    out = []
    for fc in obj.animation_data.drivers:
        if tl._is_transform(fc) and tl._type_of(fc) not in allowed:
            continue
        if words:
            name = (f"{obj.name} {tl._bone_of(fc) or ''} "
                    f"{tl._label(fc)} {fc.data_path}").lower()
            if not all(t in name for t in words):
                continue
        out.append(fc)
    return out


def _rows(context):
    sc = context.scene
    words, allowed = _words(context), _allowed(sc)
    rows = []
    for obj in tl._objects(context):
        if obj.animation_data is None or not len(obj.animation_data.drivers):
            continue
        fcs = _driver_curves(obj, words, allowed)
        if not fcs:
            continue
        okey = "d:o:" + obj.name
        fold = okey in _fold
        rows.append({"kind": "obj", "key": okey, "label": obj.name,
                     "level": 0, "fold": fold})
        if fold:
            continue
        own, bones = [], {}
        for fc in sorted(fcs, key=lambda f: (f.data_path, f.array_index)):
            b = tl._bone_of(fc)
            (own if b is None else bones.setdefault(b, [])).append(fc)

        def drv(fc, level):
            return {"kind": "drv", "level": level,
                    "key": _key_str(obj.name, fc.data_path, fc.array_index),
                    "label": tl._label(fc)}
        for fc in own:
            rows.append(drv(fc, 1))
        for bname, lst in bones.items():
            bkey = f"d:b:{obj.name}:{bname}"
            bfold = bkey in _fold
            rows.append({"kind": "bone", "key": bkey, "label": bname,
                         "level": 1, "fold": bfold})
            if bfold:
                continue
            for fc in lst:
                rows.append(drv(fc, 2))
    return rows


def _row_at(rows, G, my):
    top = G["chan"][3]
    off = int(round(_scroll / ROWH)) * ROWH
    for i, row in enumerate(rows):
        y2 = top - i * ROWH + off
        y1 = y2 - ROWH
        if y1 < G["chan"][1] - 0.5 or y2 > top + 0.5:
            continue
        if y1 <= my <= y2:
            return row
    return None


def _current_value(obj, fc):
    try:
        v = obj.path_resolve(fc.data_path)
        if fc.array_index >= 0 and hasattr(v, "__len__"):
            v = v[fc.array_index]
        return float(v)
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


# ----------------------------------------------------------------------
# The driver's current input value (best effort, no arbitrary Python)
# ----------------------------------------------------------------------

def _var_value(var):
    t = var.targets[0] if len(var.targets) else None
    idb = getattr(t, "id", None)
    if t is None or idb is None:
        return None
    if var.type == 'SINGLE_PROP':
        try:
            v = idb.path_resolve(t.data_path)
        except (ValueError, TypeError, KeyError, AttributeError):
            return None
        return float(v) if isinstance(v, (int, float, bool)) else None
    if var.type == 'TRANSFORMS' and hasattr(idb, "matrix_world"):
        try:
            pb = None
            if t.bone_target and getattr(idb, "pose", None):
                pb = idb.pose.bones.get(t.bone_target)
            world = t.transform_space == 'WORLD_SPACE'
            if pb is not None:
                m = (idb.matrix_world @ pb.matrix) if world else pb.matrix_basis
            else:
                m = idb.matrix_world if world else idb.matrix_basis
            loc, rot, scl = m.translation, m.to_euler(), m.to_scale()
            tt = t.transform_type
            table = {"LOC_X": loc[0], "LOC_Y": loc[1], "LOC_Z": loc[2],
                     "ROT_X": rot[0], "ROT_Y": rot[1], "ROT_Z": rot[2],
                     "SCALE_X": scl[0], "SCALE_Y": scl[1],
                     "SCALE_Z": scl[2],
                     "SCALE_AVG": (scl[0] + scl[1] + scl[2]) / 3}
            return float(table[tt]) if tt in table else None
        except (AttributeError, RuntimeError, TypeError, ValueError):
            return None
    return None


def _eval_simple(expr, vals, frame):
    """Evaluate a Blender 'simple expression' with a closed namespace.
    Anything with attribute access, subscripts, '__' or other characters
    is refused."""
    if ("__" in expr or not _SAFE.match(expr)
            or re.search(r"[A-Za-z_]\s*\.", expr)):
        return None
    ns = dict(_MATH)
    ns.update(vals)
    ns["frame"] = frame
    try:
        return float(eval(expr, {"__builtins__": {}}, ns))
    except Exception:
        return None


def _driver_input(obj, fc, scene):
    d = fc.driver
    vals = {}
    for var in d.variables:
        v = _var_value(var)
        if v is None:
            return None
        vals[var.name] = v
    if not vals:
        return None
    seq = list(vals.values())
    if d.type == 'AVERAGE':
        return sum(seq) / len(seq)
    if d.type == 'SUM':
        return sum(seq)
    if d.type == 'MIN':
        return min(seq)
    if d.type == 'MAX':
        return max(seq)
    if d.type == 'SCRIPTED' and d.is_simple_expression:
        return _eval_simple(d.expression, vals, scene.frame_current)
    return None


# ----------------------------------------------------------------------
# View mapping (X = driver value, Y = property value)
# ----------------------------------------------------------------------

def _areas(context, w):
    G = tl._geom(context, w)
    k = G["keys"]
    return G, (k[0], k[1], k[2], k[3] - INFO_H), (k[0], k[3] - INFO_H,
                                                  k[2], k[3])


def _x(pa, v):
    return pa[0] + (v - _g["x0"]) * _g["ppx"]


def _xi(pa, px):
    return _g["x0"] + (px - pa[0]) / _g["ppx"]


def _y(pa, v):
    return (pa[1] + pa[3]) / 2 + (v - _g["y0"]) * _g["ppy"]


def _yi(pa, py):
    return _g["y0"] + (py - (pa[1] + pa[3]) / 2) / _g["ppy"]


def _fit(obj, fc, pa, scene):
    xs, ys = [], []
    for kp in fc.keyframe_points:
        xs += [kp.co[0], kp.handle_left[0], kp.handle_right[0]]
        ys += [kp.co[1], kp.handle_left[1], kp.handle_right[1]]
    xin = _driver_input(obj, fc, scene)
    if xin is not None:
        xs.append(xin)
    if len(fc.keyframe_points) < 2:
        xs += [-1.0, 1.0]
    for xv in (min(xs), max(xs)):
        try:
            ys.append(fc.evaluate(xv))
        except (RuntimeError, ValueError, TypeError):
            pass
    cur = _current_value(obj, fc)
    if cur is not None:
        ys.append(cur)
    if not ys:
        ys = [-1.0, 1.0]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 - x0 < 1e-4:
        x0, x1 = x0 - 0.5, x1 + 0.5
    if y1 - y0 < 1e-4:
        y0, y1 = y0 - 0.5, y1 + 0.5
    mx_, my_ = (x1 - x0) * 0.15, (y1 - y0) * 0.15
    x0, x1, y0, y1 = x0 - mx_, x1 + mx_, y0 - my_, y1 + my_
    _g["ppx"] = max(10.0, (pa[2] - pa[0])) / (x1 - x0)
    _g["x0"] = x0 - 0.0
    _g["ppy"] = max(10.0, (pa[3] - pa[1])) / (y1 - y0)
    _g["y0"] = (y0 + y1) / 2
    _g["fit"] = False


def _zoom(pa, px, py, k):
    x, y = _xi(pa, px), _yi(pa, py)
    _g["ppx"] = max(1e-3, min(1e6, _g["ppx"] * k[0]))
    _g["ppy"] = max(1e-3, min(1e6, _g["ppy"] * k[1]))
    _g["x0"] = x - (px - pa[0]) / _g["ppx"]
    _g["y0"] = y - (py - (pa[1] + pa[3]) / 2) / _g["ppy"]


def _samples(fc, pa):
    stamp = (round(_g["x0"], 4), round(_g["ppx"], 4), round(_g["y0"], 4),
             round(_g["ppy"], 4), int(pa[2] - pa[0]), int(pa[3] - pa[1]))
    key = fc.as_pointer()
    now = time.time()
    ent = _poly.get(key)
    if (ent is not None and ent[0] == stamp and now - ent[1] < 0.4
            and key not in _dirty):
        return ent[2]
    n = max(16, min(100, int((pa[2] - pa[0]) / 5)))
    pts = []
    for i in range(n + 1):
        px = pa[0] + (pa[2] - pa[0]) * i / n
        try:
            pts.append((px, _y(pa, fc.evaluate(_xi(pa, px)))))
        except (RuntimeError, ValueError, TypeError):
            pass
    segs = []
    gx._segments(pts, pa, segs)
    _poly[key] = (stamp, now, segs)
    _dirty.discard(key)
    return segs


# ----------------------------------------------------------------------
# Curve operations
# ----------------------------------------------------------------------

def _sel_idx(fc):
    return [i for i, kp in enumerate(fc.keyframe_points)
            if kp.select_control_point]


def _deselect(fc):
    for kp in fc.keyframe_points:
        kp.select_control_point = False
        kp.select_left_handle = False
        kp.select_right_handle = False


def _to_keys(fc):
    """Generator / empty curve -> keyframe curve with the same shape."""
    gen = next((m for m in fc.modifiers if m.type == 'GENERATOR'), None)
    xs = (0.0, 1.0)
    if gen is not None and gen.poly_order > 1:
        xs = tuple(-2.0 + i * 0.5 for i in range(11))
    pts = []
    for xv in xs:
        try:
            pts.append((xv, fc.evaluate(xv)))
        except (RuntimeError, ValueError, TypeError):
            pass
    for m in list(fc.modifiers):
        fc.modifiers.remove(m)
    fc.keyframe_points.clear()
    for xv, yv in pts:
        kp = fc.keyframe_points.insert(xv, yv)
        kp.interpolation = 'LINEAR' if len(pts) == 2 else 'BEZIER'
    fc.extrapolation = 'LINEAR'
    fc.update()


def _reset(fc):
    fc.keyframe_points.clear()
    for m in list(fc.modifiers):
        fc.modifiers.remove(m)
    fc.modifiers.new('GENERATOR')
    fc.extrapolation = 'CONSTANT'
    fc.update()


def _add_point(context, obj, fc, pa):
    if not len(fc.keyframe_points):
        _to_keys(fc)
    xin = _driver_input(obj, fc, context.scene)
    x = xin if xin is not None else _xi(pa, (pa[0] + pa[2]) / 2)
    while any(abs(kp.co[0] - x) < 1e-4 for kp in fc.keyframe_points):
        x += 0.05
    try:
        y = fc.evaluate(x)
    except (RuntimeError, ValueError, TypeError):
        y = 0.0
    _deselect(fc)
    kp = fc.keyframe_points.insert(x, y)
    kp.select_control_point = True
    kp.select_left_handle = True
    kp.select_right_handle = True
    fc.update()


def _delete_points(fc):
    kps = fc.keyframe_points
    idx = _sel_idx(fc)
    for i in reversed(idx):
        kps.remove(kps[i])
    if idx and not len(kps):
        _reset(fc)
    elif idx:
        fc.update()


def _set_handle(fc, t):
    for kp in fc.keyframe_points:
        if (kp.select_control_point or kp.select_left_handle
                or kp.select_right_handle):
            kp.handle_left_type = t
            kp.handle_right_type = t
    fc.update()


def _set_interp(fc, v):
    for kp in fc.keyframe_points:
        if kp.select_control_point:
            kp.interpolation = v
    fc.update()


# ----------------------------------------------------------------------
# Toolbar
# ----------------------------------------------------------------------

_HANDLES = (('AUTO_CLAMPED', "AC", "Auto Clamped"), ('AUTO', "A", "Automatic"),
            ('VECTOR', "V", "Vector"), ('ALIGNED', "AL", "Aligned"),
            ('FREE', "F", "Free"))
_MENUS = ("driver", "view", "select", "key")
_PANELS = {"driver": "NOMAD_PT_drv_driver", "view": "NOMAD_PT_drv_view",
           "select": "NOMAD_PT_drv_select", "key": "NOMAD_PT_drv_key"}
_TB = [("add", "Add Driver", "Add a driver to the active object or bone"),
       None,
       ("driver", "Driver", "Edit, mute or delete the active driver"),
       ("view", "View", "View options"),
       ("select", "Select", "Select the points of the curve"),
       ("key", "Key", "Points, handles, interpolation, extrapolation")]


def _buttons(context, tb):
    out, x = [], tb[0] + 8
    for it in _TB:
        if it is None:
            x += 12
            continue
        key, label, tip = it
        if key in _MENUS:
            wb = int(len(label) * 6.8) + 24
        else:
            wb = max(40, int(len(label) * 6.8) + 16)
        out.append((key, label, (x, tb[1] + 3, x + wb, tb[3] - 3), tip))
        x += wb + 3
    out += tl.shared_buttons(context, x, tb)
    return out


def _select_points(fc, mode):
    for kp in fc.keyframe_points:
        on = (True if mode == 'ALL' else False if mode == 'NONE'
              else not kp.select_control_point)
        kp.select_control_point = on
        kp.select_left_handle = on
        kp.select_right_handle = on
    fc.update()


def _tb_action(context, key, pa):
    from .sculpt_popups import open_panel_deferred
    sc = context.scene
    if key in tl.SHARED_KEYS:
        tl.shared_action(context, key)
        return
    if key in _PANELS:
        open_panel_deferred(_PANELS[key])
        return
    obj, fc = _curve(context)
    if key == "add":
        open_panel_deferred("NOMAD_PT_driver_add")
    elif key == "upd":
        context.view_layer.update()
    elif fc is None:
        return
    elif key in ("sel_all", "sel_none", "sel_inv"):
        _select_points(fc, {"sel_all": 'ALL', "sel_none": 'NONE',
                            "sel_inv": 'INVERT'}[key])
    elif key == "edit":
        open_panel_deferred("NOMAD_PT_driver_edit")
    elif key == "del":
        obj.animation_data.drivers.remove(fc)
        sc.nomad_drv_active = ""
        _push("Remove driver")
    elif key == "mute":
        fc.mute = not fc.mute
    elif key == "fit":
        _g["fit"] = True
    elif key in ("hz+", "hz-"):
        cx, cy = (pa[0] + pa[2]) / 2, (pa[1] + pa[3]) / 2
        _zoom(pa, cx, cy, (1.25 if key == "hz+" else 0.8, 1.0))
    elif key in ("vz+", "vz-"):
        cx, cy = (pa[0] + pa[2]) / 2, (pa[1] + pa[3]) / 2
        _zoom(pa, cx, cy, (1.0, 1.25 if key == "vz+" else 0.8))
    elif key == "pt+":
        _add_point(context, obj, fc, pa)
        _push("Add driver curve point")
    elif key == "pt-":
        _delete_points(fc)
        _push("Delete driver curve points")
    elif key.startswith("t:"):
        _set_handle(fc, key[2:])
        _push("Set handle type")
    elif key.startswith("i:"):
        _set_interp(fc, key[2:])
        _push("Set interpolation")
    elif key == "ext":
        fc.extrapolation = ('LINEAR' if fc.extrapolation == 'CONSTANT'
                            else 'CONSTANT')
        _push("Toggle extrapolation")
    elif key == "keys":
        _to_keys(fc)
        _push("Driver curve to points")
    elif key == "reset":
        _reset(fc)
        _push("Reset driver curve")
    _dirty.add(fc.as_pointer()) if fc is not None else None


def _draw_toolbar(context, tb, mx, my):
    for key, label, rect, tip in _buttons(context, tb):
        hot = _in(rect, mx, my)
        on = key in tl.SHARED_KEYS and tl.shared_on(context, key)
        drawing.rrect(rect[0], rect[1], rect[2], rect[3], 6,
                      panels.COL_HOVER if hot else tl.COL_PLAY if on
                      else BTN)
        cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        if key in _MENUS:
            drawing.text(rect[0] + 8, cy - 4, label, size=11,
                         color=panels.COL_GLYPH)
            drawing.glyph(rect[2] - 10, cy, "\u25be", 10, panels.COL_GLYPH)
        else:
            drawing.text(cx, cy - 4, label, size=11,
                         color=panels.COL_GLYPH, align='CENTER')
        if hot:
            panels.hover_tip = tip


# ----------------------------------------------------------------------
# Draw
# ----------------------------------------------------------------------

def _draw_graph(context, obj, fc, pa, info, rl):
    sc = context.scene
    x_lo, x_hi = _xi(pa, pa[0]), _xi(pa, pa[2])
    y_lo, y_hi = _yi(pa, pa[1]), _yi(pa, pa[3])

    xstep = gx._nice((x_hi - x_lo) / 8)
    v = math.floor(x_lo / xstep) * xstep
    vgrid, vzero = [], []
    while v <= x_hi:
        px = _x(pa, v)
        if pa[0] <= px <= pa[2]:
            (vzero if abs(v) < xstep * 1e-6 else vgrid).append(
                (px, pa[1], px + 1, pa[3]))
            drawing.text(px + 3, rl[1] + 9, f"{v:.3g}", size=10,
                         color=panels.COL_TIP)
        v += xstep
    ystep = gx._nice((y_hi - y_lo) / 6)
    v = math.floor(y_lo / ystep) * ystep
    hgrid, hzero = [], []
    while v <= y_hi:
        py = _y(pa, v)
        if pa[1] <= py <= pa[3]:
            (hzero if abs(v) < ystep * 1e-6 else hgrid).append(
                (pa[0], py, pa[2], py + 1))
            drawing.text(pa[0] + 4, py + 2, f"{v:.3g}", size=10,
                         color=panels.COL_TIP)
        v += ystep
    drawing.rects(vgrid + hgrid, COL_GRID)
    drawing.rects(vzero + hzero, COL_ZERO)
    drawing.text(rl[2] - 8, rl[1] + 9, "driver value", size=10,
                 color=panels.COL_TIP, align='RIGHT')
    drawing.text(pa[0] + 46, pa[3] - 14, "property value", size=10,
                 color=panels.COL_TIP)

    gx._lines(_samples(fc, pa), tl.COL_KEY_SEL, 2.0)

    knorm, ksel, hnorm, hsel, hseg = [], [], [], [], []
    for kp in fc.keyframe_points:
        px, py = _x(pa, kp.co[0]), _y(pa, kp.co[1])
        sel = kp.select_control_point
        if sel or kp.select_left_handle or kp.select_right_handle:
            for h, s in ((kp.handle_left, kp.select_left_handle),
                         (kp.handle_right, kp.select_right_handle)):
                hxp, hyp = _x(pa, h[0]), _y(pa, h[1])
                c = gx._clip((px, py), (hxp, hyp), pa)
                if c:
                    hseg.extend(c)
                if pa[0] <= hxp <= pa[2] and pa[1] <= hyp <= pa[3]:
                    (hsel if s else hnorm).append((hxp, hyp))
        if pa[0] <= px <= pa[2] and pa[1] <= py <= pa[3]:
            (ksel if sel else knorm).append((px, py))
    gx._lines(hseg, COL_HANDLE, 1.2)
    drawing.diamonds(hnorm, 3.5, COL_HANDLE)
    drawing.diamonds(hsel, 3.5, tl.COL_KEY_SEL)
    drawing.rects([(x - PT, y - PT, x + PT, y + PT) for x, y in knorm],
                  tl.COL_KEY)
    drawing.rects([(x - PT, y - PT, x + PT, y + PT) for x, y in ksel],
                  tl.COL_KEY_SEL)

    # live markers
    xin = _driver_input(obj, fc, sc)
    cur = _current_value(obj, fc)
    segs = []
    if xin is not None:
        mxp = _x(pa, xin)
        if pa[0] <= mxp <= pa[2]:
            segs += [(mxp, pa[1]), (mxp, pa[3])]
        try:
            yv = fc.evaluate(xin)
            if cur is None:
                cur = yv
            dx, dy = mxp, _y(pa, yv)
            if pa[0] <= dx <= pa[2] and pa[1] <= dy <= pa[3]:
                drawing.circle(dx, dy, 5, (1, 1, 1, 1), 14)
        except (RuntimeError, ValueError, TypeError):
            pass
    gx._lines(segs, COL_IN, 1.4)
    if cur is not None:
        myp = _y(pa, cur)
        if pa[1] <= myp <= pa[3]:
            gx._lines([(pa[0], myp), (pa[2], myp)], COL_OUT, 1.4)

    # info strip
    drawing.rect(info[0], info[1], info[2], info[3], tl.COL_HEAD)
    d = fc.driver
    ok = bool(d.is_valid)
    cy = (info[1] + info[3]) / 2 - 4
    x = info[0] + 12
    head = f"{obj.name}  {tl._label(fc)}  |  " \
           f"{_TYPE_NAME.get(d.type, d.type)}"
    drawing.text(x, cy, head, size=12, color=COL_TXT)
    x += len(head) * 6.6 + 14
    drawing.text(x, cy, "Valid" if ok else "Invalid", size=12,
                 color=COL_OK if ok else COL_BAD)
    x += 62
    if xin is not None:
        drawing.text(x, cy, f"In {xin:.4g}", size=12, color=COL_IN)
        x += 84
    if cur is not None:
        drawing.text(x, cy, f"Out {cur:.4g}", size=12, color=COL_OUT)
        x += 92
    drawing.text(info[2] - 10, cy, "tap here to edit the driver", size=11,
                 color=panels.COL_TIP, align='RIGHT')


def draw(context, w, mx, my):
    global _scroll
    sc = context.scene
    G, pa, info = _areas(context, w)
    rows = _rows(context)
    cx1, cy1, cx2, cy2 = G["chan"]
    _scroll = max(0.0, min(_scroll, tl._max_scroll(len(rows), G)))
    off = int(round(_scroll / ROWH)) * ROWH

    hd, rl, tb = G["head"], G["ruler"], G["tb"]
    drawing.rect(hd[0], hd[1], hd[2], hd[3], tl.COL_HEAD)
    drawing.text(hd[0] + 10, (hd[1] + hd[3]) / 2 - 5, "Drivers", size=12,
                 color=panels.COL_TIP)
    drawing.rect(tb[0], tb[1], tb[2], tb[3], tl.COL_HEAD)
    drawing.rect(rl[0], rl[1], rl[2], rl[3], tl.COL_HEAD)
    drawing.rect(pa[0], pa[1], pa[2], pa[3], tl.COL_ROW_B)
    drawing.rect(info[0], info[1], info[2], info[3], tl.COL_HEAD)

    key = sc.nomad_drv_active
    obj, fc = _find(key)
    if fc is not None:
        if _g["fit"] or _g["key"] != key:
            _fit(obj, fc, pa, sc)
            _g["key"] = key
        _draw_graph(context, obj, fc, pa, info, rl)
    else:
        drawing.text(pa[0] + 16, (pa[1] + pa[3]) / 2 - 5,
                     "Select a driver in the list (or press Add)",
                     size=13, color=panels.COL_TIP)
    _draw_toolbar(context, tb, mx, my)

    bg, visible = {}, []
    for i, row in enumerate(rows):
        y2 = cy2 - i * ROWH + off
        y1 = y2 - ROWH
        if y1 < cy1 - 0.5 or y2 > cy2 + 0.5:
            continue
        base = (tl.COL_OBJ if row["kind"] == "obj"
                else tl.COL_GRP if row["kind"] == "bone"
                else tl.COL_ROW_A if i % 2 else tl.COL_ROW_B)
        bg.setdefault(base, []).append((0, y1, CH_W, y2 - 1))
        if row["kind"] == "drv" and row["key"] == key:
            bg.setdefault(tl.COL_SEL, []).append((0, y1, CH_W, y2 - 1))
        visible.append((row, y1, y2))
    for col, rs in bg.items():
        drawing.rects(rs, col)

    for row, y1, y2 in visible:
        kind = row["kind"]
        cy = (y1 + y2) / 2
        x = 8 + row["level"] * 14
        if kind in ("obj", "bone"):
            drawing.glyph(x + 5, cy, "▸" if row["fold"] else "▾", 12,
                          panels.COL_GLYPH)
            x += 16
        label = row["label"]
        maxc = max(4, int((CH_W - x - 44) / 6.6))
        if len(label) > maxc:
            label = label[:maxc - 1] + "…"
        drawing.text(x, cy - 4, label, size=12, color=panels.COL_GLYPH)
        if kind == "drv":
            o2, f2 = _find(row["key"])
            if f2 is not None:
                drawing.glyph(CH_W - 16, cy, "○" if f2.mute else "◉", 12,
                              panels.COL_TIP if f2.mute
                              else panels.COL_GLYPH)
                if not f2.driver.is_valid:
                    drawing.glyph(CH_W - 36, cy, "!", 13, COL_BAD)
    if not rows:
        drawing.text(10, (cy1 + cy2) / 2, "No drivers on the selection", 
                     size=12, color=panels.COL_TIP)


# ----------------------------------------------------------------------
# Interaction
# ----------------------------------------------------------------------

def _pick(fc, pa, mx, my):
    """('pt'|'hl'|'hr', keyframe index) under the finger."""
    best, bd = None, HIT_R
    for i, kp in enumerate(fc.keyframe_points):
        if not (kp.select_control_point or kp.select_left_handle
                or kp.select_right_handle):
            continue
        for side, h in (('hl', kp.handle_left), ('hr', kp.handle_right)):
            d = math.hypot(_x(pa, h[0]) - mx, _y(pa, h[1]) - my)
            if d < bd:
                best, bd = (side, i), d
    if best:
        return best
    bd = HIT_R
    for i, kp in enumerate(fc.keyframe_points):
        d = math.hypot(_x(pa, kp.co[0]) - mx, _y(pa, kp.co[1]) - my)
        if d < bd:
            best, bd = ('pt', i), d
    return best


def _begin_move(fc):
    snap, lo, hi, eps = [], -1e9, 1e9, 0.001
    kps = list(fc.keyframe_points)
    sel = [kp.select_control_point for kp in kps]
    for i, kp in enumerate(kps):
        if not sel[i]:
            continue
        c0, c1 = kp.co
        snap.append({"i": i, "x": c0, "y": c1, "cx": c0,
                     "hl": tuple(kp.handle_left),
                     "hr": tuple(kp.handle_right)})
        j = i - 1
        while j >= 0 and sel[j]:
            j -= 1
        if j >= 0:
            lo = max(lo, kps[j].co[0] + eps - c0)
        j = i + 1
        while j < len(kps) and sel[j]:
            j += 1
        if j < len(kps):
            hi = min(hi, kps[j].co[0] - eps - c0)
    _s.update(snap=snap, lo=lo, hi=hi)


def _resolve(fc, e):
    """The keyframe an entry refers to, or None if it is not the same
    any more (nothing is written to a stale keyframe)."""
    kps = fc.keyframe_points
    if e["i"] >= len(kps):
        return None
    kp = kps[e["i"]]
    return kp if abs(kp.co[0] - e["cx"]) <= 1e-3 else None


def _touch(fc, force=False):
    now = time.time()
    if force or now - _last_up[0] >= UPDATE_EVERY:
        _last_up[0] = now
        fc.update()
    _dirty.add(fc.as_pointer())


def press(context, w, mx, my):
    G, pa, info = _areas(context, w)
    _s.update(last=(mx, my), moved=0.0, x0=mx, y0=my, mode=None, snap=[],
              ref=None, row=None, w=w)
    if tl._in(G["tb"], mx, my):
        for key, label, rect, tip in _buttons(context, G["tb"]):
            if tl._in(rect, mx, my):
                _tb_action(context, key, pa)
                break
        return True
    if tl._in(G["ruler"], mx, my) or tl._in(G["head"], mx, my):
        return True
    rows = _rows(context)
    if tl._in(G["chan"], mx, my):
        row = _row_at(rows, G, my)
        _s["mode"] = 'chan'
        _s["row"] = row["key"] if row else None
        return True
    if tl._in(info, mx, my):
        _s["mode"] = 'info'
        return True
    if not tl._in(pa, mx, my):
        return True

    obj, fc = _curve(context)
    if fc is None:
        _s["mode"] = 'pan'
        return True
    hit = _pick(fc, pa, mx, my)
    if hit is None:
        _s["mode"] = 'pan'
        return True
    kind, idx = hit
    kp = fc.keyframe_points[idx]
    if kind == 'pt':
        if not kp.select_control_point:
            _deselect(fc)
            kp = fc.keyframe_points[idx]
            kp.select_control_point = True
            kp.select_left_handle = True
            kp.select_right_handle = True
        _begin_move(fc)
        _s["mode"] = 'move'
    else:
        _deselect(fc)
        kp = fc.keyframe_points[idx]
        if kind == 'hl':
            kp.select_left_handle = True
        else:
            kp.select_right_handle = True
        gx._grab_handle(kp, kind)
        _s.update(mode='handle', ref=(idx, kind, kp.co[0]))
    _dirty.add(fc.as_pointer())
    return True


def update(context, w, mx, my):
    global _scroll
    G, pa, info = _areas(context, w)
    lx, ly = _s["last"]
    dx, dy = mx - lx, my - ly
    _s["last"] = (mx, my)
    _s["moved"] += abs(dx) + abs(dy)
    mode = _s["mode"]
    if mode == 'chan' and _s["moved"] > 8:
        _scroll = max(0.0, min(_scroll + dy, tl._max_scroll(
            len(_rows(context)), G)))
    elif mode == 'pan' and _s["moved"] > 6:
        _g["x0"] -= dx / _g["ppx"]
        _g["y0"] -= dy / _g["ppy"]
        _g["fit"] = False
        _poly.clear()
    elif mode == 'move' and _s["moved"] > 4:
        obj, fc = _curve(context)
        if fc is None:
            _s["mode"] = None
            return
        df = max(_s["lo"], min(_s["hi"], (mx - _s["x0"]) / _g["ppx"]))
        dv = (my - _s["y0"]) / _g["ppy"]
        for e in _s["snap"]:
            kp = _resolve(fc, e)
            if kp is None:
                _s["mode"] = None                  # stale: cancel
                return
            nx = e["x"] + df
            kp.co = (nx, e["y"] + dv)
            kp.handle_left = (e["hl"][0] + df, e["hl"][1] + dv)
            kp.handle_right = (e["hr"][0] + df, e["hr"][1] + dv)
            e["cx"] = nx
        _touch(fc)
    elif mode == 'handle':
        obj, fc = _curve(context)
        if fc is None:
            _s["mode"] = None
            return
        idx, side, cx = _s["ref"]
        kps = fc.keyframe_points
        if idx >= len(kps) or abs(kps[idx].co[0] - cx) > 1e-3:
            _s["mode"] = None
            return
        kp = kps[idx]
        f, v = _xi(pa, mx), _yi(pa, my)
        if side == 'hl':
            kp.handle_left = (min(f, kp.co[0] - 0.001), v)
        else:
            kp.handle_right = (max(f, kp.co[0] + 0.001), v)
        gx._mirror(kp, side)
        _touch(fc)


def release(context):
    mode, moved = _s["mode"], _s["moved"]
    _s["mode"] = None
    if mode in ('move', 'handle'):
        obj, fc = _curve(context)
        if fc is not None:
            _touch(fc, force=True)
            if moved > 4:
                _push("Edit driver curve")
    elif mode == 'pan' and moved <= 6:
        obj, fc = _curve(context)
        if fc is not None:
            _deselect(fc)
            _dirty.add(fc.as_pointer())
    elif mode == 'info' and moved <= 8:
        if _curve(context)[1] is not None:
            from .sculpt_popups import open_panel_deferred
            open_panel_deferred("NOMAD_PT_driver_edit")
    elif mode == 'chan' and moved <= 8 and _s["row"]:
        row = next((r for r in _rows(context) if r["key"] == _s["row"]),
                   None)
        if row is None:
            return
        if row["kind"] in ("obj", "bone"):
            _fold.symmetric_difference_update({row["key"]})
        else:
            o2, f2 = _find(row["key"])
            if f2 is not None and _s["x0"] >= CH_W - 28:
                f2.mute = not f2.mute
            else:
                context.scene.nomad_drv_active = row["key"]
                _g["fit"] = True
    _s["snap"] = []


def wheel(context, w, mx, my, direction):
    global _scroll
    G, pa, info = _areas(context, w)
    if tl._in(pa, mx, my):
        k = 1.15 ** direction
        _zoom(pa, mx, my, (k, k))
        _g["fit"] = False
        _poly.clear()
        return True
    if tl._in(G["panel"], mx, my):
        _scroll = max(0.0, min(_scroll - direction * ROWH, tl._max_scroll(
            len(_rows(context)), G)))
        return True
    return False


# ----------------------------------------------------------------------
# Operators and popups
# ----------------------------------------------------------------------

class NOMAD_OT_driver_add(bpy.types.Operator):
    bl_idname = "nomad.driver_add"
    bl_label = "Add Driver"
    bl_description = "Add a driver to this property of the object or bone"
    bl_options = {'REGISTER', 'UNDO'}

    prop: bpy.props.StringProperty(default="location")
    index: bpy.props.IntProperty(default=-1)       # -1 = every axis
    bone: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        obj = context.active_object
        if obj is None:
            return {'CANCELLED'}
        target = obj
        if self.bone:
            from .pose_panels import _active_pose_bone
            target = _active_pose_bone(context)
            if target is None:
                self.report({'WARNING'}, "No active bone")
                return {'CANCELLED'}
        try:
            n = len(getattr(target, self.prop))
        except (AttributeError, TypeError):
            return {'CANCELLED'}
        idxs = range(n) if self.index < 0 else [self.index]
        first = None
        for i in idxs:
            try:
                fc = target.driver_add(self.prop, i)
            except (TypeError, RuntimeError, ValueError):
                continue
            if fc is None:
                continue
            d = fc.driver
            d.type = 'SCRIPTED'
            d.expression = "var"
            if not len(d.variables):
                d.variables.new().name = "var"
            if first is None:
                first = _key_str(obj.name, fc.data_path, fc.array_index)
        if first:
            context.scene.nomad_drv_active = first
            _g["fit"] = True
        context.view_layer.update()
        return {'FINISHED'}


class NOMAD_OT_driver_var(bpy.types.Operator):
    bl_idname = "nomad.driver_var"
    bl_label = "Driver Variable"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.EnumProperty(items=[('ADD', "Add", ""),
                                          ('REMOVE', "Remove", "")])
    index: bpy.props.IntProperty(default=0)

    def execute(self, context):
        obj, fc = _curve(context)
        if fc is None:
            return {'CANCELLED'}
        vs = fc.driver.variables
        if self.action == 'ADD':
            v = vs.new()
            v.name = f"var{len(vs)}"
        elif 0 <= self.index < len(vs):
            vs.remove(vs[self.index])
        context.view_layer.update()
        return {'FINISHED'}


class NOMAD_OT_driver_curve(bpy.types.Operator):
    bl_idname = "nomad.driver_curve"
    bl_label = "Driver Curve"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.EnumProperty(items=[
        ('KEYS', "To Points", "Convert to editable points"),
        ('RESET', "Reset", "Back to a straight 1:1 mapping")])

    def execute(self, context):
        obj, fc = _curve(context)
        if fc is None:
            return {'CANCELLED'}
        (_to_keys if self.action == 'KEYS' else _reset)(fc)
        _dirty.add(fc.as_pointer())
        _g["fit"] = True
        return {'FINISHED'}


class NOMAD_PT_driver_add(bpy.types.Panel):
    bl_label = "Add Driver"
    bl_idname = "NOMAD_PT_driver_add"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def _block(self, layout, title, bone):
        layout.label(text=title)
        for prop, text in (("location", "Location"),
                           ("rotation_euler", "Rotation"),
                           ("scale", "Scale")):
            row = layout.row(align=True)
            row.label(text=text)
            for i, ax in enumerate("XYZ"):
                op = row.operator("nomad.driver_add", text=ax)
                op.prop, op.index, op.bone = prop, i, bone
            op = row.operator("nomad.driver_add", text="All")
            op.prop, op.index, op.bone = prop, -1, bone

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 13
        obj = context.active_object
        if obj is None:
            l.label(text="No active object", icon='INFO')
            return
        self._block(l, f"Object: {obj.name}", False)
        if obj.type == 'ARMATURE':
            from .pose_panels import _active_pose_bone
            pb = _active_pose_bone(context)
            if pb is not None:
                l.separator()
                self._block(l, f"Bone: {pb.name}", True)


class NOMAD_PT_driver_edit(bpy.types.Panel):
    bl_label = "Driver"
    bl_idname = "NOMAD_PT_driver_edit"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 16
        obj, fc = _curve(context)
        if fc is None:
            l.label(text="No driver selected", icon='INFO')
            return
        d = fc.driver
        l.label(text=f"{obj.name}   {tl._label(fc)}")
        l.prop(d, "type", text="")
        if d.type == 'SCRIPTED':
            l.prop(d, "expression", text="")
            if not d.is_simple_expression:
                l.label(text="Not a simple expression (Python needed)",
                        icon='ERROR')
        row = l.row()
        row.label(text="Valid" if d.is_valid else "Invalid driver",
                  icon='CHECKMARK' if d.is_valid else 'ERROR')

        l.separator()
        box = l.box()
        box.label(text="Mapping curve")
        for m in fc.modifiers:
            if m.type == 'GENERATOR':
                box.prop(m, "poly_order", text="Order")
                col = box.column(align=True)
                for i in range(m.poly_order + 1):
                    col.prop(m, "coefficients", index=i, text=f"x^{i}")
                box.prop(m, "use_additive")
            else:
                box.label(text=f"Modifier: {m.type.title()}")
        kp = next((k for k in fc.keyframe_points
                   if k.select_control_point), None)
        if kp is not None:
            col = box.column(align=True)
            col.prop(kp, "co", index=0, text="Driver value")
            col.prop(kp, "co", index=1, text="Property value")
            box.prop(kp, "interpolation", text="")
            row = box.row(align=True)
            row.prop(kp, "handle_left_type", text="")
            row.prop(kp, "handle_right_type", text="")
        elif len(fc.keyframe_points):
            box.label(text="Tap a point in the graph to edit its values")
        box.prop(fc, "extrapolation", text="")
        row = box.row(align=True)
        row.operator("nomad.driver_curve", text="To Points").action = 'KEYS'
        row.operator("nomad.driver_curve", text="Reset").action = 'RESET'

        l.separator()
        l.label(text="Variables")
        for i, var in enumerate(d.variables):
            box = l.box()
            row = box.row(align=True)
            row.prop(var, "name", text="")
            row.prop(var, "type", text="")
            op = row.operator("nomad.driver_var", text="", icon='X')
            op.action, op.index = 'REMOVE', i
            ntg = {'SINGLE_PROP': 1, 'TRANSFORMS': 1, 'CONTEXT_PROP': 1,
                   'LOC_DIFF': 2, 'ROTATION_DIFF': 2}.get(var.type, 1)
            for t in list(var.targets)[:ntg]:
                if var.type == 'SINGLE_PROP':
                    box.prop(t, "id_type", text="")
                    box.prop(t, "id", text="")
                    box.prop(t, "data_path", text="")
                elif var.type == 'CONTEXT_PROP':
                    box.prop(t, "context_property", text="")
                    box.prop(t, "data_path", text="")
                else:
                    box.prop(t, "id", text="")
                    if getattr(t.id, "type", "") == 'ARMATURE':
                        box.prop_search(t, "bone_target", t.id.data,
                                        "bones", text="")
                    if var.type == 'TRANSFORMS':
                        box.prop(t, "transform_type", text="")
                        box.prop(t, "transform_space", text="")
        op = l.operator("nomad.driver_var", text="Add Variable", icon='ADD')
        op.action = 'ADD'


_DESC = {
    "edit": "Edit the driver (type, expression, variables)",
    "mute": "Mute the selected driver", "del": "Remove the selected driver",
    "upd": "Update dependencies", "fit": "Fit the curve in the view",
    "hz+": "Zoom in (driver value)", "hz-": "Zoom out (driver value)",
    "vz+": "Zoom in (property value)", "vz-": "Zoom out (property value)",
    "sel_all": "Select every point of the curve",
    "sel_none": "Deselect every point",
    "sel_inv": "Invert the point selection",
    "pt+": "Add a point on the curve (at the current input value)",
    "pt-": "Delete the selected points",
    "ext": "Toggle extrapolation (constant / linear)",
    "keys": "Convert the curve to editable points",
    "reset": "Back to a straight 1:1 mapping",
}


class NOMAD_OT_drv_action(bpy.types.Operator):
    bl_idname = "nomad.drv_action"
    bl_label = "Drivers"
    bl_options = {'REGISTER'}

    key: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, properties):
        k = properties.key
        if k.startswith("t:"):
            return "Set the handle type of the selected points"
        if k.startswith("i:"):
            return "Set the interpolation of the selected points"
        return _DESC.get(k, "Drivers action")

    def execute(self, context):
        try:
            G, pa, info = _areas(context, _s["w"] or 900)
            _tb_action(context, self.key, pa)
        except Exception as exc:
            self.report({'WARNING'}, f"{self.key}: {exc}")
            return {'CANCELLED'}
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


def _grid(layout, items, cols=2):
    g = layout.grid_flow(row_major=True, columns=cols, even_columns=True,
                         align=True)
    g.scale_y = 1.3
    for text, key in items:
        g.operator("nomad.drv_action", text=text).key = key
    return g


def _drv_panel(idname, title, units, draw_fn):
    def draw(self, context):
        self.layout.ui_units_x = units
        draw_fn(self.layout, context)
    return type(idname, (bpy.types.Panel,), {
        "bl_label": title, "bl_idname": idname,
        "bl_space_type": 'VIEW_3D', "bl_region_type": 'WINDOW',
        "draw": draw})


def _d_driver(l, context):
    obj, fc = _curve(context)
    if fc is None:
        l.label(text="No driver selected (tap a channel)", icon='INFO')
    else:
        l.label(text=f"{obj.name}   {fc.data_path}[{fc.array_index}]",
                icon='DRIVER')
    _grid(l, [("Edit Driver", "edit"), ("Mute", "mute"),
              ("Delete", "del"), ("Update Dependencies", "upd")], 2)


def _d_view(l, context):
    _grid(l, [("Frame All", "fit"), ("Zoom In (Driver)", "hz+"),
              ("Zoom Out (Driver)", "hz-"), ("Zoom In (Property)", "vz+"),
              ("Zoom Out (Property)", "vz-")], 2)


def _d_select(l, context):
    _grid(l, [("All", "sel_all"), ("None", "sel_none"),
              ("Invert", "sel_inv")], 3)


def _d_key(l, context):
    _grid(l, [("Add Point", "pt+"), ("Delete Points", "pt-"),
              ("To Points", "keys"), ("Reset", "reset")], 2)
    l.label(text="Handle type")
    _grid(l, [(name, "t:" + t) for t, _lbl, name in _HANDLES], 3)
    l.label(text="Interpolation")
    _grid(l, [("Constant", "i:CONSTANT"), ("Linear", "i:LINEAR"),
              ("Bezier", "i:BEZIER")], 3)
    l.label(text="Extrapolation")
    _grid(l, [("Toggle Constant / Linear", "ext")], 1)


NOMAD_PT_drv_driver = _drv_panel("NOMAD_PT_drv_driver", "Driver", 13,
                                 _d_driver)
NOMAD_PT_drv_view = _drv_panel("NOMAD_PT_drv_view", "View", 12, _d_view)
NOMAD_PT_drv_select = _drv_panel("NOMAD_PT_drv_select", "Select", 11,
                                 _d_select)
NOMAD_PT_drv_key = _drv_panel("NOMAD_PT_drv_key", "Key", 13, _d_key)

CLASSES = (NOMAD_OT_driver_add, NOMAD_OT_driver_var, NOMAD_OT_driver_curve,
           NOMAD_PT_driver_add, NOMAD_PT_driver_edit, NOMAD_OT_drv_action,
           NOMAD_PT_drv_driver, NOMAD_PT_drv_view, NOMAD_PT_drv_select,
           NOMAD_PT_drv_key)


def register():
    bpy.types.Scene.nomad_drv_active = bpy.props.StringProperty(
        default="", options={'SKIP_SAVE'})
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    if hasattr(bpy.types.Scene, "nomad_drv_active"):
        del bpy.types.Scene.nomad_drv_active