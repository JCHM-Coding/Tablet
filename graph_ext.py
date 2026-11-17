# Graph Editor on the expanded timeline: F-curves of object and bone
# transforms, rebuilt from the keyframes (no per-pixel evaluation), editable
# keys and handles. Its controls are two rows added to the control bar
# (nothing is drawn over the graph): menus (F-Curve, View, Select, Marker,
# Channel, Key, Normalize, Modifiers) and settings (Filters, Pivot, Snap,
# Proportional) on the first row, quick tools on the second.
# Easings other than Bezier / Linear / Constant are drawn as straight
# segments (speed over precision).
#
# SAFETY RULE (see timeline_ext): gestures keep only plain numbers; every
# write re-resolves its F-curve and checks the keyframe is still the same.
import bisect
import math
import time

import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from . import drawing, panels
from . import timeline_ext as tl

HIT_R = 14.0
PT = 4.0
MODEL_TTL = 0.35
TYPE_TTL = 0.35
COL_GRID = (0.24, 0.24, 0.28, 1.0)
COL_ZERO = (0.45, 0.45, 0.52, 1.0)
COL_HANDLE = (0.75, 0.75, 0.8, 1.0)
COL_BTN = (0.20, 0.20, 0.23, 1.0)
COL_MARK = (0.95, 0.85, 0.35, 1.0)

HANDLE_TYPES = (('AUTO_CLAMPED', "AC", "Auto Clamped"),
                ('AUTO', "A", "Automatic"),
                ('VECTOR', "V", "Vector"),
                ('ALIGNED', "AL", "Aligned"),
                ('FREE', "F", "Free"))
_PANELS = {"afc": "NOMAD_PT_gr_afc", "view": "NOMAD_PT_gr_view",
           "select": "NOMAD_PT_gr_select", "marker": "NOMAD_PT_gr_marker",
           "channel": "NOMAD_PT_gr_channel", "key": "NOMAD_PT_gr_key",
           "mods": "NOMAD_PT_gr_mods", "filters": "NOMAD_PT_gr_filters",
           "pivot": "NOMAD_PT_gr_pivot", "snap_o": "NOMAD_PT_gr_snap",
           "prop_o": "NOMAD_PT_gr_prop"}

_g = {"f0": 0.0, "ppf": 10.0, "v0": 0.0, "ppv": 10.0, "fit": True,
      "fit_sel": False, "cur": False, "only_sel": False}
_tool = {"box": False, "scale": False, "dup": False}
_s = {"mode": None, "op": None, "last": (0, 0), "moved": 0.0, "x0": 0.0,
      "y0": 0.0, "snap": [], "lo": -1e9, "hi": 1e9, "ref": None,
      "box": None, "d": (0.0, 0.0), "w": 0, "noupd": False, "piv": None,
      "pivref": (0.0, 0.0)}
_model = {}             # fcurve pointer -> cached keys / polyline
_dirty = set()          # fcurves edited since their model was built
_frozen = {}            # fcurve pointer -> normalization used while dragging
_tcache = {"t": 0.0, "v": None}


def _flush():
    _model.clear()
    _dirty.clear()
    _tcache["t"] = 0.0
    tl._flush()


def request(name):
    """View requests from the popups (applied while drawing)."""
    if name == 'fit':
        _g["fit"] = True
    elif name == 'fit_sel':
        _g["fit_sel"] = True
    elif name == 'cur':
        _g["cur"] = True


def _on(name, default=False):
    return bool(getattr(bpy.context.scene, name, default))


# ----------------------------------------------------------------------
# Mapping
# ----------------------------------------------------------------------

def _areas(context, w):
    G = tl._geom(context, w)
    return G, G["ruler"], G["keys"]


def _x(pa, f):
    return pa[0] + (f - _g["f0"]) * _g["ppf"]


def _fx_inv(pa, x):
    return _g["f0"] + (x - pa[0]) / _g["ppf"]


def _y(pa, v):
    return (pa[1] + pa[3]) / 2 + (v - _g["v0"]) * _g["ppv"]


def _v_inv(pa, y):
    return _g["v0"] + (y - (pa[1] + pa[3]) / 2) / _g["ppv"]


def _nice(x):
    if x <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(x))
    for m in (1, 2, 5, 10):
        if m * e >= x:
            return m * e
    return 10 * e


def _clip(a, b, r):
    """Liang-Barsky: the part of segment a-b inside rect r, or None."""
    x0, y0 = a
    x1, y1 = b
    dx, dy = x1 - x0, y1 - y0
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x0 - r[0]), (dx, r[2] - x0),
                 (-dy, y0 - r[1]), (dy, r[3] - y0)):
        if p == 0:
            if q < 0:
                return None
        else:
            t = q / p
            if p < 0:
                if t > t1:
                    return None
                t0 = max(t0, t)
            else:
                if t < t0:
                    return None
                t1 = min(t1, t)
    return ((x0 + t0 * dx, y0 + t0 * dy), (x0 + t1 * dx, y0 + t1 * dy))


def _segments(pts, r, out):
    """Append the visible part of a polyline (as line pairs) to out."""
    xmin, ymin, xmax, ymax = r
    for a, b in zip(pts, pts[1:]):
        ax, ay = a
        bx, by = b
        ina = xmin <= ax <= xmax and ymin <= ay <= ymax
        inb = xmin <= bx <= xmax and ymin <= by <= ymax
        if ina and inb:
            out.append(a)
            out.append(b)
            continue
        if ((ax < xmin and bx < xmin) or (ax > xmax and bx > xmax)
                or (ay < ymin and by < ymin) or (ay > ymax and by > ymax)):
            continue
        c = _clip(a, b, r)
        if c:
            out.extend(c)


def _lines(segs, color, width=1.5):
    if not segs:
        return
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    gpu.state.line_width_set(width)
    batch = batch_for_shader(shader, 'LINES', {"pos": segs})
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.line_width_set(1.0)


def _falloff(name, t):
    t = max(0.0, min(1.0, t))
    if name == 'LINEAR':
        return t
    if name == 'SHARP':
        return t * t
    if name == 'SPHERE':
        return math.sqrt(max(0.0, 1 - (1 - t) ** 2))
    if name == 'ROOT':
        return math.sqrt(t)
    if name == 'CONSTANT':
        return 1.0
    return t * t * (3 - 2 * t)


def _snap_t(sc, f):
    """Snap a frame according to the Snap settings."""
    if not sc.nomad_gr_snap:
        return f
    mode = sc.nomad_gr_snap_mode
    if mode == 'SECOND':
        fps = max(1.0, sc.render.fps / sc.render.fps_base)
        return round(f / fps) * fps
    if mode == 'MARKER':
        ms = [m.frame for m in sc.timeline_markers]
        if ms:
            near = min(ms, key=lambda x: abs(x - f))
            if abs(near - f) <= 3:
                return float(near)
    return float(round(f))


# ----------------------------------------------------------------------
# Model (READ ONLY): cached keys and a data-space polyline per curve
# ----------------------------------------------------------------------

def _lod(n_curves):
    return 12 if n_curves <= 6 else 8 if n_curves <= 16 else 5


def _build(fc, lod):
    kps = fc.keyframe_points
    n = len(kps)
    m = {"n": n, "co": [], "hl": [], "hr": [], "sel": [], "sl": [],
         "sr": [], "poly": [], "ext": fc.extrapolation,
         "bounds": (0.0, 0.0, 0.0, 0.0), "no": 0.0, "ns": 1.0}
    if not n:
        return m
    co, hl, hr = [0.0] * (2 * n), [0.0] * (2 * n), [0.0] * (2 * n)
    sel, sl, sr = [False] * n, [False] * n, [False] * n
    kps.foreach_get("co", co)
    kps.foreach_get("handle_left", hl)
    kps.foreach_get("handle_right", hr)
    kps.foreach_get("select_control_point", sel)
    kps.foreach_get("select_left_handle", sl)
    kps.foreach_get("select_right_handle", sr)
    ip = [kp.interpolation for kp in kps]
    poly = [(co[0], co[1])]
    for i in range(n - 1):
        x0, y0, x1, y1 = (co[2 * i], co[2 * i + 1], co[2 * i + 2],
                          co[2 * i + 3])
        kind = ip[i]
        if kind == 'BEZIER':
            ax, ay = hr[2 * i], hr[2 * i + 1]
            bx, by = hl[2 * i + 2], hl[2 * i + 3]
            for k in range(1, lod + 1):
                t = k / lod
                u = 1.0 - t
                a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
                poly.append((a * x0 + b * ax + c * bx + d * x1,
                             a * y0 + b * ay + c * by + d * y1))
        elif kind == 'CONSTANT':
            poly.append((x1, y0))
            poly.append((x1, y1))
        else:                       # LINEAR and every other easing
            poly.append((x1, y1))
    xs = co[0::2] + hl[0::2] + hr[0::2]
    ys = co[1::2] + hl[1::2] + hr[1::2]
    ymin, ymax = min(ys), max(ys)
    rng = ymax - ymin
    m.update(co=co, hl=hl, hr=hr, sel=sel, sl=sl, sr=sr, poly=poly,
             bounds=(min(xs), max(xs), ymin, ymax),
             no=(ymin + ymax) / 2, ns=(2.0 / rng if rng > 1e-6 else 1.0))
    return m


def _get(fc, lod):
    key = fc.as_pointer()
    now = time.time()
    m = _model.get(key)
    if (m is not None and key not in _dirty and m["lod"] == lod
            and now - m["t"] < MODEL_TTL):
        return m
    m = _build(fc, lod)
    m["t"], m["lod"] = now, lod
    _model[key] = m
    _dirty.discard(key)
    return m


def _factors(fc, m):
    """(offset, scale) of the Normalize mapping; frozen while dragging."""
    if not _on("nomad_gr_norm"):
        return 0.0, 1.0
    key = fc.as_pointer()
    if _s["mode"] in ('move', 'handle', 'edit') and key in _frozen:
        return _frozen[key]
    _frozen[key] = (m["no"], m["ns"])
    return _frozen[key]


def _shown(sc, fc):
    if fc.hide and not sc.nomad_gr_hidden:
        return False
    if sc.nomad_gr_errors and fc.is_valid:
        return False
    return True


def _items(context):
    """Cached [(key, fcurve)] visible in the graph (READ ONLY)."""
    sc = context.scene
    items = [(k, fc) for k, fc in tl.curve_items(context) if _shown(sc, fc)]
    if _g["only_sel"]:
        sel = [(k, fc) for k, fc in items if fc.select]
        if sel:
            return sel
    return items


def _vis_fresh(context):
    """Same filter, straight from the data (for edits)."""
    sc = context.scene
    items = [(k, fc) for k, fc in tl.fresh_items(context)
             if _shown(sc, fc)]
    if _g["only_sel"]:
        sel = [(k, fc) for k, fc in items if fc.select]
        if sel:
            return sel
    return items


def _selected(kp):
    return (kp.select_control_point or kp.select_left_handle
            or kp.select_right_handle)


def _deselect(context):
    for _k, fc in tl.fresh_items(context):
        for kp in fc.keyframe_points:
            kp.select_control_point = False
            kp.select_left_handle = False
            kp.select_right_handle = False
        _dirty.add(fc.as_pointer())


def _fit(context, pa, sel_only=False):
    sc = context.scene
    items = _items(context)
    lod = _lod(len(items))
    norm = _on("nomad_gr_norm")
    fr, vr = [], []
    for _k, fc in items:
        m = _get(fc, lod)
        if not m["n"]:
            continue
        no, ns = (m["no"], m["ns"]) if norm else (0.0, 1.0)
        if sel_only:
            for i in range(m["n"]):
                if m["sel"][i]:
                    fr.append(m["co"][2 * i])
                    vr.append((m["co"][2 * i + 1] - no) * ns)
        else:
            b = m["bounds"]
            fr += [b[0], b[1]]
            vr += [(b[2] - no) * ns, (b[3] - no) * ns]
    if not fr:
        fr, vr = [sc.frame_start, sc.frame_end], [-1.0, 1.0]
    elif not sel_only:
        fr += [sc.frame_start, sc.frame_end]      # always show both ends
    f0, f1, v0, v1 = min(fr), max(fr), min(vr), max(vr)
    if f1 - f0 < 1.0:
        f0, f1 = f0 - 0.5, f1 + 0.5
    if v1 - v0 < 1e-4:
        v0, v1 = v0 - 0.5, v1 + 0.5
    wpx = max(40.0, pa[2] - pa[0] - 110)
    hpx = max(40.0, pa[3] - pa[1] - 50)
    _g["ppf"] = wpx / (f1 - f0)
    _g["f0"] = f0 - 55 / _g["ppf"]
    _g["ppv"] = hpx / (v1 - v0)
    _g["v0"] = (v0 + v1) / 2
    _g["fit"] = False


def _sel_type(context):
    """Handle type of the selected keys (cached, read from fresh data)."""
    now = time.time()
    if now - _tcache["t"] < TYPE_TTL:
        return _tcache["v"]
    value = None
    for _k, fc in _vis_fresh(context):
        for kp in fc.keyframe_points:
            if kp.select_control_point:
                a, b = kp.handle_left_type, kp.handle_right_type
                value = a if a == b else None
                break
        else:
            continue
        break
    _tcache["t"], _tcache["v"] = now, value
    return value


def _extend(pts, pa, linear):
    """Constant (or linear) extrapolation to both edges of the view."""
    if len(pts) < 2:
        return pts
    out = list(pts)
    x0, y0 = out[0]
    if x0 > pa[0]:
        y = y0
        if linear:
            dx = out[1][0] - x0
            if abs(dx) > 1e-6:
                y = y0 - (out[1][1] - y0) / dx * (x0 - pa[0])
        out.insert(0, (pa[0], y))
    x1, y1 = out[-1]
    if x1 < pa[2]:
        y = y1
        if linear:
            dx = x1 - out[-2][0]
            if abs(dx) > 1e-6:
                y = y1 + (y1 - out[-2][1]) / dx * (pa[2] - x1)
        out.append((pa[2], y))
    return out


# ----------------------------------------------------------------------
# Control rows (added to the control bar)
# ----------------------------------------------------------------------

def _w(label, kind):
    if kind == 'field':
        return 140
    return max(30, int(len(label) * 6.8) + (24 if kind == 'menu' else 16))


def _place(rect, specs, left):
    total = sum(10 if s is None else _w(s[1], s[2]) + 3 for s in specs)
    x = rect[0] + 8 if left else rect[2] - 8 - total + 3
    out = []
    for s in specs:
        if s is None:
            x += 10
            continue
        key, label, kind, tip = s
        wb = _w(label, kind)
        out.append((key, label, kind,
                    (x, rect[1] + 3, x + wb, rect[3] - 3), tip))
        x += wb + 3
    return out


def _row_items(context, G):
    sc = context.scene
    r0 = G["rows"][0]
    left0 = [("afc", "F-Curve", 'menu', "Active F-Curve"),
             ("view", "View", 'menu', "View options"),
             ("select", "Select", 'menu', "Select keyframes"),
             ("marker", "Marker", 'menu', "Markers"),
             ("channel", "Channel", 'menu', "Channels"),
             ("key", "Key", 'menu', "Keyframes"),
             ("norm", "Normalize", 'toggle',
              "Show and edit every curve scaled to -1..1"),
             ("mods", "Modifiers", 'menu', "F-Curve modifiers")]
    right0 = [("search", "Search", 'toggle', "Search channels by name")]
    if sc.nomad_tl_search_on:
        right0.append(("sfield", (sc.nomad_tl_search
                                  or "type to search...")[:18], 'field',
                       "Edit the search text"))
    right0 += [("filters", "Filters", 'menu',
                "Filters (objects, bones, channel types)"),
               ("pivot", "Pivot", 'menu', "Pivot point"),
               ("snap", "Snap", 'toggle', "Snapping on / off"),
               ("snap_o", "", 'menu', "Snapping options"),
               ("prop", "Prop. Edit", 'toggle',
                "Proportional editing on / off"),
               ("prop_o", "", 'menu', "Proportional editing options")]
    return _place(r0, left0, True) + _place(r0, right0, False)


def _is_on(context, key):
    sc = context.scene
    if key in ("box", "scale", "dup"):
        return _tool[key]
    if key == "only":
        return _g["only_sel"]
    if key == "norm":
        return bool(sc.nomad_gr_norm)
    if key == "snap":
        return bool(sc.nomad_gr_snap)
    if key == "prop":
        return bool(sc.nomad_gr_prop)
    if key == "search":
        return bool(sc.nomad_tl_search_on)
    if key.startswith("t:"):
        return _sel_type(context) == key[2:]
    return False


def _draw_rows(context, G, mx, my):
    for key, label, kind, rect, tip in _row_items(context, G):
        hot = tl._in(rect, mx, my)
        on = _is_on(context, key)
        drawing.rrect(rect[0], rect[1], rect[2], rect[3], 6,
                      panels.COL_HOVER if hot
                      else tl.COL_PLAY if on else COL_BTN)
        cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        if kind == 'menu':
            if label:
                drawing.text(rect[0] + 8, cy - 4, label, size=11,
                             color=panels.COL_GLYPH)
                drawing.glyph(rect[2] - 10, cy, "▾", 10, panels.COL_GLYPH)
            else:
                drawing.glyph(cx, cy, "▾", 11, panels.COL_GLYPH)
        else:
            drawing.text(cx, cy - 4, label, size=11,
                         color=panels.COL_GLYPH, align='CENTER')
        if hot:
            panels.hover_tip = tip


def _zoom(pa, kx, ky):
    cx, cy = (pa[0] + pa[2]) / 2, (pa[1] + pa[3]) / 2
    f, v = _fx_inv(pa, cx), _v_inv(pa, cy)
    _g["ppf"] = max(0.02, min(2000.0, _g["ppf"] * kx))
    _g["ppv"] = max(1e-4, min(1e6, _g["ppv"] * ky))
    _g["f0"] = f - (cx - pa[0]) / _g["ppf"]
    _g["v0"] = v - (cy - (pa[1] + pa[3]) / 2) / _g["ppv"]


def _push(msg):
    try:
        bpy.ops.ed.undo_push(message=msg)
    except RuntimeError:
        pass


def _action(context, key, pa):
    sc = context.scene
    from .sculpt_popups import open_panel_deferred
    if key in _PANELS:
        open_panel_deferred(_PANELS[key])
        return
    if key in ("search", "sfield"):
        tl.shared_action(context, key)
        return
    if key == "norm":
        sc.nomad_gr_norm = not sc.nomad_gr_norm
        return
    if key == "snap":
        sc.nomad_gr_snap = not sc.nomad_gr_snap
        return
    if key == "prop":
        sc.nomad_gr_prop = not sc.nomad_gr_prop
        return
    if key == "fit":
        _g["fit"] = True
    elif key == "cur":
        _g["cur"] = True
    elif key in ("hz+", "hz-"):
        _zoom(pa, 1.25 if key == "hz+" else 0.8, 1.0)
    elif key in ("vz+", "vz-"):
        _zoom(pa, 1.0, 1.25 if key == "vz+" else 0.8)
    elif key in ("box", "scale", "dup"):
        on = not _tool[key]
        _tool.update(box=False, scale=False, dup=False)
        _tool[key] = on
    elif key == "only":
        _g["only_sel"] = not _g["only_sel"]
    elif key == "interp":
        open_panel_deferred("NOMAD_PT_key_options")
    elif key in ("all", "none", "inv"):
        for _k, fc in _vis_fresh(context):
            for kp in fc.keyframe_points:
                on = (not kp.select_control_point if key == "inv"
                      else key == "all")
                kp.select_control_point = on
                kp.select_left_handle = on
                kp.select_right_handle = on
    elif key == "key":
        f = sc.frame_current
        items = _vis_fresh(context)
        chosen = [p for p in items if p[1].select] or items
        for _k, fc in chosen:
            try:
                fc.keyframe_points.insert(f, fc.evaluate(f))
            except (RuntimeError, TypeError):
                continue
            fc.update()
        _push("Insert keyframes")
    elif key == "del":
        for _k, fc in _vis_fresh(context):
            kps = fc.keyframe_points
            idx = [i for i, kp in enumerate(kps) if kp.select_control_point]
            for i in reversed(idx):
                kps.remove(kps[i])
            if idx:
                fc.update()
        _push("Delete keyframes")
    elif key == "extrap":
        items = _vis_fresh(context)
        for _k, fc in [p for p in items if p[1].select] or items:
            fc.extrapolation = ('LINEAR' if fc.extrapolation == 'CONSTANT'
                                else 'CONSTANT')
        _push("Toggle extrapolation")
    elif key.startswith("t:"):
        t = key[2:]
        for _k, fc in _vis_fresh(context):
            changed = False
            for kp in fc.keyframe_points:
                if _selected(kp):
                    kp.handle_left_type = t
                    kp.handle_right_type = t
                    changed = True
            if changed:
                fc.update()
        _push("Set handle type")
    _flush()


# ----------------------------------------------------------------------
# Draw (everything of the same colour goes into one batch)
# ----------------------------------------------------------------------

def draw(context, w, mx, my):
    sc = context.scene
    G, rl, pa = _areas(context, w)
    if _g["fit"]:
        _fit(context, pa)
    if _g["fit_sel"]:
        _g["fit_sel"] = False
        _fit(context, pa, True)
    if _g["cur"]:
        _g["cur"] = False
        _g["f0"] = sc.frame_current - (pa[2] - pa[0]) / 2 / _g["ppf"]

    drawing.rect(pa[0], pa[1], pa[2], pa[3], tl.COL_ROW_B)
    drawing.rect(rl[0], rl[1], rl[2], rl[3], tl.COL_HEAD)

    f_left, f_right = _fx_inv(pa, pa[0]), _fx_inv(pa, pa[2])
    tl.draw_ruler(sc, rl, lambda f: _x(pa, f), f_left, f_right, _g["ppf"],
                  span=(pa[1], pa[3]), grid=COL_GRID)

    v_lo, v_hi = _v_inv(pa, pa[1]), _v_inv(pa, pa[3])
    vstep = _nice((v_hi - v_lo) / 6)
    v = math.floor(v_lo / vstep) * vstep
    grid, zero = [], []
    while v <= v_hi:
        y = _y(pa, v)
        if pa[1] <= y <= pa[3]:
            (zero if abs(v) < vstep * 1e-6 else grid).append(
                (pa[0], y, pa[2], y + 1))
            drawing.text(pa[0] + 4, y + 2, f"{v:.3g}", size=10,
                         color=panels.COL_TIP)
        v += vstep
    drawing.rects(grid, COL_GRID)
    drawing.rects(zero, COL_ZERO)

    items = _items(context)
    lod = _lod(len(items))
    any_sel = any(fc.select for _k, fc in items)
    show_h = _on("nomad_gr_handles", True)
    f0, ppf, v0, ppv = _g["f0"], _g["ppf"], _g["v0"], _g["ppv"]
    ox, ym = pa[0], (pa[1] + pa[3]) / 2

    groups = {}
    knorm, ksel, hnorm, hsel, hseg = [], [], [], [], []
    for _k, fc in items:
        m = _get(fc, lod)
        n = m["n"]
        if not n:
            continue
        no, ns = _factors(fc, m)
        b0, b1 = (m["bounds"][2] - no) * ns, (m["bounds"][3] - no) * ns
        if max(b0, b1) < v_lo or min(b0, b1) > v_hi:
            continue                                   # off screen
        pts = [(ox + (f - f0) * ppf, ym + ((val - no) * ns - v0) * ppv)
               for f, val in m["poly"]]
        pts = _extend(pts, pa, m["ext"] == 'LINEAR')
        base = tl._axis_color(fc)
        a = 1.0 if (fc.select or not any_sel) else 0.45
        key = ((base[0], base[1], base[2], a), 2.0 if fc.select else 1.5)
        _segments(pts, pa, groups.setdefault(key, []))

        co, hl, hr = m["co"], m["hl"], m["hr"]
        sel, sl, sr = m["sel"], m["sl"], m["sr"]
        for i in range(n):
            px = ox + (co[2 * i] - f0) * ppf
            py = ym + ((co[2 * i + 1] - no) * ns - v0) * ppv
            if show_h and (sel[i] or sl[i] or sr[i]):
                for hx, hy, s in ((hl[2 * i], hl[2 * i + 1], sl[i]),
                                  (hr[2 * i], hr[2 * i + 1], sr[i])):
                    hxp = ox + (hx - f0) * ppf
                    hyp = ym + ((hy - no) * ns - v0) * ppv
                    c = _clip((px, py), (hxp, hyp), pa)
                    if c:
                        hseg.extend(c)
                    if pa[0] <= hxp <= pa[2] and pa[1] <= hyp <= pa[3]:
                        (hsel if s else hnorm).append((hxp, hyp))
            if pa[0] <= px <= pa[2] and pa[1] <= py <= pa[3]:
                (ksel if sel[i] else knorm).append((px, py))

    for (col, width), segs in groups.items():
        _lines(segs, col, width)
    _lines(hseg, COL_HANDLE, 1.2)
    drawing.diamonds(hnorm, 3.5, COL_HANDLE)
    drawing.diamonds(hsel, 3.5, tl.COL_KEY_SEL)
    drawing.rects([(x - PT, y - PT, x + PT, y + PT) for x, y in knorm],
                  tl.COL_KEY)
    drawing.rects([(x - PT, y - PT, x + PT, y + PT) for x, y in ksel],
                  tl.COL_KEY_SEL)

    marks = []                                         # markers
    for mk in sc.timeline_markers:
        mxp = _x(pa, mk.frame)
        if pa[0] <= mxp <= pa[2]:
            marks.append((mxp, pa[1] + 9))
            drawing.text(mxp + 7, pa[1] + 4, mk.name[:14], size=10,
                         color=COL_MARK)
    drawing.diamonds(marks, 5, COL_MARK)

    if _s["mode"] == 'edit' and _s["op"] == 'DUP' and _s["snap"]:
        d, dvv = _s["d"]
        drawing.diamonds(
            [(_x(pa, e["x"] + d),
              _y(pa, (e["y"] - e["no"]) * e["ns"] + dvv))
             for e in _s["snap"]], 5, tl.COL_GHOST)
    if _s["mode"] == 'box' and _s["box"]:
        x0, y0, x1, y1 = _s["box"]
        xa, xb = sorted((x0, x1))
        ya, yb = sorted((y0, y1))
        drawing.rects([(xa, ya, xb, ya + 1), (xa, yb - 1, xb, yb),
                       (xa, ya, xa + 1, yb), (xb - 1, ya, xb, yb)],
                      tl.COL_BOX)

    px = _x(pa, sc.frame_current)                      # playhead
    if pa[0] <= px <= pa[2]:
        drawing.rect(px - 1, pa[1], px + 1, pa[3], tl.COL_PLAY)
        drawing.glyph(px, rl[1] + 6, "▼", 10, tl.COL_PLAY)
    drawing.rect(pa[0], pa[1], pa[0] + 1, pa[3], tl.COL_LINE)

    _draw_rows(context, G, mx, my)

    if not items:
        drawing.text(pa[0] + 16, (pa[1] + pa[3]) / 2 - 5,
                     "No channels: select an object or bone with "
                     "animation (or check the filters)", size=13,
                     color=panels.COL_TIP)


# ----------------------------------------------------------------------
# Interaction (indexes into the cached model are only used to PICK; every
# write goes through a fresh map and an identity check)
# ----------------------------------------------------------------------

def _pick(context, pa, mx, my):
    """('pt'|'hl'|'hr', curve key, keyframe index) under the finger."""
    items = _items(context)
    lod = _lod(len(items))
    best, bd = None, HIT_R
    for k, fc in items:                         # handles of selected keys
        m = _get(fc, lod)
        no, ns = _factors(fc, m)
        for i in range(m["n"]):
            if not (m["sel"][i] or m["sl"][i] or m["sr"][i]):
                continue
            for side, hx, hy in (('hl', m["hl"][2 * i], m["hl"][2 * i + 1]),
                                 ('hr', m["hr"][2 * i], m["hr"][2 * i + 1])):
                d = math.hypot(_x(pa, hx) - mx, _y(pa, (hy - no) * ns) - my)
                if d < bd:
                    best, bd = (side, k, i), d
    if best:
        return best
    bd = HIT_R
    for k, fc in items:
        m = _get(fc, lod)
        no, ns = _factors(fc, m)
        for i in range(m["n"]):
            d = math.hypot(_x(pa, m["co"][2 * i]) - mx,
                           _y(pa, (m["co"][2 * i + 1] - no) * ns) - my)
            if d < bd:
                best, bd = ('pt', k, i), d
    return best


def _entry(fc, i, kp, fk, w=1.0):
    m = _get(fc, _lod(1))
    no, ns = _factors(fc, m)
    return {"fk": fk, "i": i, "x": kp.co[0], "y": kp.co[1],
            "cx": kp.co[0], "hl": tuple(kp.handle_left),
            "hr": tuple(kp.handle_right), "no": no, "ns": ns, "w": w}


def _begin_move(context):
    sc = context.scene
    snap, lo, hi, eps = [], -1e9, 1e9, 0.001
    sel_x = []
    for fk, fc in _vis_fresh(context):
        kps = list(fc.keyframe_points)
        sel = [kp.select_control_point for kp in kps]
        for i, kp in enumerate(kps):
            if not sel[i]:
                continue
            snap.append(_entry(fc, i, kp, fk))
            sel_x.append(kp.co[0])
            j = i - 1
            while j >= 0 and sel[j]:
                j -= 1
            if j >= 0:
                lo = max(lo, kps[j].co[0] + eps - kp.co[0])
            j = i + 1
            while j < len(kps) and sel[j]:
                j += 1
            if j < len(kps):
                hi = min(hi, kps[j].co[0] - eps - kp.co[0])
    prop = []
    if sc.nomad_gr_prop and snap:
        radius = max(0.5, sc.nomad_gr_prop_size)
        sel_x.sort()
        for fk, fc in _vis_fresh(context):
            for i, kp in enumerate(fc.keyframe_points):
                if kp.select_control_point:
                    continue
                x = kp.co[0]
                j = bisect.bisect_left(sel_x, x)
                d = 1e18
                if j < len(sel_x):
                    d = abs(sel_x[j] - x)
                if j > 0:
                    d = min(d, abs(sel_x[j - 1] - x))
                if d < radius:
                    wgt = _falloff(sc.nomad_gr_falloff, 1.0 - d / radius)
                    if wgt > 0.001:
                        prop.append(_entry(fc, i, kp, fk, wgt))
        lo, hi = -1e9, 1e9              # neighbours move too: no clamping
    _s.update(snap=snap + prop, lo=lo, hi=hi, noupd=bool(prop))


def _snapshot_full(context):
    out = []
    for fk, fc in _vis_fresh(context):
        for i, kp in enumerate(fc.keyframe_points):
            if kp.select_control_point:
                e = _entry(fc, i, kp, fk)
                e.update(tl_=kp.handle_left_type, tr=kp.handle_right_type,
                         ip=kp.interpolation, ea=kp.easing)
                e["tl"] = e.pop("tl_")
                out.append(e)
    return out


def _pivot(context, snap):
    """Pivot data for Scale: bbox centre, 2D cursor or per-curve centres."""
    sc = context.scene
    mode = sc.nomad_gr_pivot
    xs = [e["x"] for e in snap]
    ys = [e["y"] for e in snap]
    bbox = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2)
    cur = (float(sc.frame_current), sc.nomad_gr_cursor)
    if mode == 'CURSOR':
        return {"all": cur, "per": {}}
    if mode == 'INDIVIDUAL_CENTERS':
        per = {}
        for fk in {e["fk"] for e in snap}:
            pts = [(e["x"], e["y"]) for e in snap if e["fk"] == fk]
            per[fk] = (sum(p[0] for p in pts) / len(pts),
                       sum(p[1] for p in pts) / len(pts))
        return {"all": bbox, "per": per}
    return {"all": bbox, "per": {}}


def _grab_handle(kp, side):
    """Moving an automatic handle turns it into an aligned one (a vector
    handle into a free one), as Blender does."""
    for name in ("handle_left_type", "handle_right_type"):
        if getattr(kp, name) in ('AUTO', 'AUTO_CLAMPED'):
            kp.handle_left_type = 'ALIGNED'
            kp.handle_right_type = 'ALIGNED'
            return
    attr = "handle_left_type" if side == 'hl' else "handle_right_type"
    if getattr(kp, attr) == 'VECTOR':
        setattr(kp, attr, 'FREE')


def _mirror(kp, side):
    if kp.handle_left_type == 'ALIGNED' and kp.handle_right_type == 'ALIGNED':
        cx, cy = kp.co
        hx, hy = kp.handle_left if side == 'hl' else kp.handle_right
        ox, oy = kp.handle_right if side == 'hl' else kp.handle_left
        dx, dy = cx - hx, cy - hy
        ln = math.hypot(dx, dy) or 1.0
        olen = math.hypot(ox - cx, oy - cy)
        new = (cx + dx / ln * olen, cy + dy / ln * olen)
        if side == 'hl':
            kp.handle_right = new
        else:
            kp.handle_left = new


def _box_select(context, pa, box):
    xa, xb = sorted((box[0], box[2]))
    ya, yb = sorted((box[1], box[3]))
    _deselect(context)
    for _k, fc in _vis_fresh(context):
        m = _get(fc, _lod(1))
        no, ns = _factors(fc, m)
        for i, kp in enumerate(fc.keyframe_points):
            px = _x(pa, kp.co[0])
            py = _y(pa, (kp.co[1] - no) * ns)
            if xa <= px <= xb and ya <= py <= yb:
                kp.select_control_point = True
                kp.select_left_handle = True
                kp.select_right_handle = True
        _dirty.add(fc.as_pointer())


def _set_active(context, fk):
    try:
        context.scene.nomad_gr_active = "{}|{}|{}".format(*fk)
    except (AttributeError, TypeError):
        pass


def press(context, w, mx, my):
    sc = context.scene
    G, rl, pa = _areas(context, w)
    _s.update(last=(mx, my), moved=0.0, x0=mx, y0=my, mode=None, op=None,
              snap=[], ref=None, box=None, d=(0.0, 0.0), w=w, noupd=False,
              piv=None)
    for key, label, kind, rect, tip in _row_items(context, G):
        if tl._in(rect, mx, my):
            _action(context, key, pa)
            return True
    if any(tl._in(r, mx, my) for r in G["rows"]):
        return True
    if tl._in(rl, mx, my):
        sc.frame_set(int(round(_fx_inv(pa, mx))))
        _s["mode"] = 'scrub'
        return True
    if not tl._in(pa, mx, my):
        return False

    if _tool["box"]:
        _s.update(mode='box', box=(mx, my, mx, my))
        return True
    hit = _pick(context, pa, mx, my)

    if _tool["scale"]:                          # scale the selection
        snap = _snapshot_full(context)
        if hit is not None and not snap:
            kind, fk, idx = hit
            fc = tl.fresh_map(context).get(fk)
            if fc is not None and idx < len(fc.keyframe_points):
                fc.keyframe_points[idx].select_control_point = True
                snap = _snapshot_full(context)
        if snap:
            piv = _pivot(context, snap)
            e0 = snap[0]
            ref = (piv["all"][0], (piv["all"][1] - e0["no"]) * e0["ns"])
            _s.update(mode='edit', op='SCALE', snap=snap, piv=piv,
                      pivref=ref, noupd=False)
            return True
        _s["mode"] = 'pan'
        return True

    if hit is None:
        _s["mode"] = 'pan'
        return True
    kind, fk, idx = hit
    fm = tl.fresh_map(context)
    fc = fm.get(fk)
    if fc is None or idx >= len(fc.keyframe_points):
        _s["mode"] = 'pan'
        return True
    kp = fc.keyframe_points[idx]
    for other in fm.values():
        other.select = False
    fc.select = True
    _set_active(context, fk)
    if kind == 'pt':
        if not kp.select_control_point:
            _deselect(context)
            kp = fc.keyframe_points[idx]            # (fresh, to be safe)
            kp.select_control_point = True
            kp.select_left_handle = True
            kp.select_right_handle = True
        if _tool["dup"]:
            _s.update(mode='edit', op='DUP', snap=_snapshot_full(context))
        else:
            _begin_move(context)
            _s["mode"] = 'move'
    else:
        _deselect(context)
        kp = fc.keyframe_points[idx]
        if kind == 'hl':
            kp.select_left_handle = True
        else:
            kp.select_right_handle = True
        _grab_handle(kp, kind)
        m = _get(fc, _lod(1))
        no, ns = _factors(fc, m)
        _s.update(mode='handle', ref=(fk, idx, kind, kp.co[0], no, ns))
    _dirty.add(fc.as_pointer())
    return True


def _handle_kp(fm, ref):
    fk, idx, side, cx, no, ns = ref
    fc = fm.get(fk)
    if fc is None or idx >= len(fc.keyframe_points):
        return None, None
    kp = fc.keyframe_points[idx]
    if abs(kp.co[0] - cx) > 1e-3:
        return None, None
    return fc, kp


def _mark(fm, fks):
    for fk in fks:
        fc = fm.get(fk)
        if fc is not None:
            _dirty.add(fc.as_pointer())


def update(context, w, mx, my):
    sc = context.scene
    G, rl, pa = _areas(context, w)
    lx, ly = _s["last"]
    dx, dy = mx - lx, my - ly
    _s["last"] = (mx, my)
    _s["moved"] += abs(dx) + abs(dy)
    mode = _s["mode"]
    if mode == 'scrub':
        sc.frame_set(int(round(_fx_inv(pa, mx))))
    elif mode == 'pan':
        if _s["moved"] > 6:
            _g["f0"] -= dx / _g["ppf"]
            _g["v0"] -= dy / _g["ppv"]
            _g["fit"] = False
    elif mode == 'box':
        _s["box"] = (_s["x0"], _s["y0"], mx, my)
    elif mode == 'move' and _s["moved"] > 4:
        snap = _s["snap"]
        if not snap:
            return
        ref = snap[0]
        df = _snap_t(sc, ref["x"] + (mx - _s["x0"]) / _g["ppf"]) - ref["x"]
        df = max(_s["lo"], min(_s["hi"], df))
        dvv = (my - _s["y0"]) / _g["ppv"]
        fm = tl.fresh_map(context)
        for e in snap:
            kp = tl._resolve(fm, e)
            if kp is None:
                _s["mode"] = None                  # stale: cancel
                return
            dv = dvv / e["ns"]
            if sc.nomad_gr_snap_v and sc.nomad_gr_snap_vstep > 0:
                st = sc.nomad_gr_snap_vstep
                dv = round((e["y"] + dv) / st) * st - e["y"]
            wt = e["w"]
            nx = e["x"] + df * wt
            kp.co = (nx, e["y"] + dv * wt)
            kp.handle_left = (e["hl"][0] + df * wt, e["hl"][1] + dv * wt)
            kp.handle_right = (e["hr"][0] + df * wt, e["hr"][1] + dv * wt)
            e["cx"] = nx
        fks = {e["fk"] for e in snap}
        if not _s["noupd"]:
            tl._touch(fm, fks)
        _mark(fm, fks)
    elif mode == 'edit' and _s["moved"] > 4:
        if _s["op"] == 'DUP':
            snap = _s["snap"]
            ref = snap[0]
            df = _snap_t(sc, ref["x"] + (mx - _s["x0"]) / _g["ppf"]) \
                - ref["x"]
            _s["d"] = (df, (my - _s["y0"]) / _g["ppv"])
        else:                                          # SCALE
            px, pyv = _s["pivref"]
            bx = _s["x0"] - _x(pa, px)
            by = _s["y0"] - _y(pa, pyv)
            bx = bx if abs(bx) >= 12 else (12.0 if bx >= 0 else -12.0)
            by = by if abs(by) >= 12 else (12.0 if by >= 0 else -12.0)
            kx = max(0.02, (mx - _x(pa, px)) / bx)
            ky = (my - _y(pa, pyv)) / by
            piv = _s["piv"]
            fm = tl.fresh_map(context)
            for e in _s["snap"]:
                kp = tl._resolve(fm, e)
                if kp is None:
                    _s["mode"] = None
                    return
                cx, cy = piv["per"].get(e["fk"], piv["all"])
                nx = _snap_t(sc, cx + (e["x"] - cx) * kx)
                kp.co = (nx, cy + (e["y"] - cy) * ky)
                kp.handle_left = (cx + (e["hl"][0] - cx) * kx,
                                  cy + (e["hl"][1] - cy) * ky)
                kp.handle_right = (cx + (e["hr"][0] - cx) * kx,
                                   cy + (e["hr"][1] - cy) * ky)
                e["cx"] = nx
            fks = {e["fk"] for e in _s["snap"]}
            tl._touch(fm, fks)
            _mark(fm, fks)
    elif mode == 'handle':
        fm = tl.fresh_map(context)
        fc, kp = _handle_kp(fm, _s["ref"])
        if kp is None:
            _s["mode"] = None                      # stale: cancel
            return
        side, no, ns = _s["ref"][2], _s["ref"][4], _s["ref"][5]
        f, v = _fx_inv(pa, mx), _v_inv(pa, my) / ns + no
        if side == 'hl':
            kp.handle_left = (min(f, kp.co[0] - 0.001), v)
        else:
            kp.handle_right = (max(f, kp.co[0] + 0.001), v)
        _mirror(kp, side)
        tl._touch(fm, {_s["ref"][0]})
        _dirty.add(fc.as_pointer())


def release(context):
    mode, moved = _s["mode"], _s["moved"]
    snap, ref = _s["snap"], _s["ref"]
    _s["mode"] = None
    G, rl, pa = _areas(context, _s["w"] or 1000)
    if mode == 'pan' and moved <= 6:
        _deselect(context)
    elif mode == 'box':
        if _s["box"] and moved > 6:
            _box_select(context, pa, _s["box"])
    elif mode in ('move', 'edit'):
        if mode == 'edit' and _s.get("op") == 'DUP':
            if snap and moved > 4:
                df, dvv = _s["d"]
                tl.duplicate_keys(context, snap, df, dvv / snap[0]["ns"])
                _push("Duplicate keyframes")
        else:
            fm = tl.fresh_map(context)
            tl._touch(fm, {e["fk"] for e in snap}, force=True)
            if moved > 4:
                _push("Edit keyframes" if mode == 'move'
                      else "Scale keyframes")
    elif mode == 'handle' and ref is not None:
        fm = tl.fresh_map(context)
        tl._touch(fm, {ref[0]}, force=True)
        if moved > 4:
            _push("Edit handle")
    _s["snap"] = []
    _s["ref"] = None
    _s["op"] = None
    _s["noupd"] = False
    _flush()


def wheel(context, w, mx, my, direction):
    G, rl, pa = _areas(context, w)
    if not tl._in(pa, mx, my):
        return False
    k = 1.15 ** direction
    f, v = _fx_inv(pa, mx), _v_inv(pa, my)
    _g["ppf"] = max(0.02, min(2000.0, _g["ppf"] * k))
    _g["ppv"] = max(1e-4, min(1e6, _g["ppv"] * k))
    _g["f0"] = f - (mx - pa[0]) / _g["ppf"]
    _g["v0"] = v - (my - (pa[1] + pa[3]) / 2) / _g["ppv"]
    _g["fit"] = False
    return True