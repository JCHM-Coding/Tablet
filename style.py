# Shared look: rounded groups (pills), colours, grouped backgrounds behind
# the side bars (with vertical scrolling), and the link to Preferences >
# Resolution Scale.
import math
import gpu
import bpy
from mathutils import Matrix
from . import drawing

COL_PILL = (0.16, 0.16, 0.18, 1.0)
COL_PILL_DARK = (0.06, 0.06, 0.07, 0.96)
# timeline: the track is the light one, the button row the dark one
COL_TL_STRIP = (0.19, 0.19, 0.22, 1.0)
COL_TL_CTRL = (0.07, 0.07, 0.08, 1.0)
COL_FIELD = (0.16, 0.16, 0.18, 1.0)
COL_BTN_IDLE = (0.16, 0.16, 0.18, 1.0)
COL_ARROW_OFF = (0.4, 0.4, 0.44, 1.0)
RADIUS = 10
GROUP_SIZE = 4
STEP = 48            # side-bar button pitch (BTN + PAD)
ARROW_H = 26
EDGE = 10            # clearance between the bars and the rest of the UI

_bar = {"L": 0, "R": 0}      # scroll of each side column, in steps
_info = {}                    # side -> geometry of an overflowing column


def ui_scale():
    """Preferences > Interface > Resolution Scale."""
    try:
        return max(0.5, float(bpy.context.preferences.view.ui_scale))
    except Exception:
        return 1.0


def _regions(area):
    return [r for r in area.regions if r.type == 'WINDOW']


def union(regs):
    x1 = min(r.x for r in regs)
    y1 = min(r.y for r in regs)
    x2 = max(r.x + r.width for r in regs)
    y2 = max(r.y + r.height for r in regs)
    return x1, y1, x2 - x1, y2 - y1


class _Rect:
    def __init__(self, x, y, width, height):
        self.x, self.y, self.width, self.height = x, y, width, height


def ui_region(area):
    """The region our UI lives in: the union of the 4 Quad View regions."""
    regs = _regions(area)
    if not regs:
        return None
    return regs[0] if len(regs) == 1 else _Rect(*union(regs))


def region_size(region):
    """UI size in our (scaled) units; in Quad View, the whole area."""
    s = ui_scale()
    try:
        ptr = region.as_pointer()
        for win in bpy.context.window_manager.windows:
            for area in win.screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                regs = _regions(area)
                if len(regs) > 1 and any(r.as_pointer() == ptr
                                         for r in regs):
                    _x, _y, w, h = union(regs)
                    return w / s, h / s
    except (AttributeError, RuntimeError, ReferenceError):
        pass
    return region.width / s, region.height / s


def begin_full(x, y, w, h):
    """Make the viewport / projection cover the whole area (Quad View)."""
    vp = gpu.state.viewport_get()
    try:
        sc = gpu.state.scissor_get()
    except Exception:
        sc = None
    gpu.state.viewport_set(int(x), int(y), int(w), int(h))
    gpu.state.scissor_set(int(x), int(y), int(w), int(h))
    gpu.matrix.push_projection()
    gpu.matrix.load_projection_matrix(Matrix((
        (2.0 / w, 0, 0, -1), (0, 2.0 / h, 0, -1),
        (0, 0, -1, 0), (0, 0, 0, 1))))
    gpu.matrix.push()
    gpu.matrix.load_identity()
    return vp, sc


def end_full(saved):
    gpu.matrix.pop()
    gpu.matrix.pop_projection()
    vp, sc = saved
    gpu.state.viewport_set(*vp)
    if sc:
        gpu.state.scissor_set(*sc)


def pill(x1, y1, x2, y2, color=COL_PILL, r=RADIUS):
    drawing.rrect(x1, y1, x2, y2, r, color)


def _bbox(rects, pad):
    return (min(r[0] for r in rects) - pad, min(r[1] for r in rects) - pad,
            max(r[2] for r in rects) + pad, max(r[3] for r in rects) + pad)


def _in(r, mx, my):
    return r[0] <= mx <= r[2] and r[1] <= my <= r[3]


def left_inset(context):
    from . import fav_bar
    return fav_bar.left_offset(context)


def top_inset(context):
    from . import fav_bar
    return fav_bar.top_offset(context)


def _stack_top(context):
    """Top edge of whatever sits at the bottom (timeline, favorites,
    Undo/Redo pill), plus a clearance."""
    from . import panels
    return panels._bottom_base(context) + panels.BOT_H + EDGE


def _y_limits(context, h):
    from . import top_bar
    return _stack_top(context), h - top_bar.BAR_H - EDGE


# ----------------------------------------------------------------------
# Wrappers around the geometry functions of panels / tool_sidebar
# ----------------------------------------------------------------------

def _wrap_left(fn, shift):
    """Shift the left toolbars right of a favorites strip on the left."""
    if getattr(fn, "_nomad_left", False):
        return fn

    def wrapped(*args, **kw):
        out = fn(*args, **kw)
        inset = left_inset(bpy.context)
        if not inset:
            return out
        return shift(out, inset, args[1])
    wrapped._nomad_left = True
    return wrapped


def _shift_side(out, d, w):
    return [((b[0] + d, b[1], b[2] + d, b[3]) + tuple(b[4:]))
            if b[0] < w / 2 else b for b in out]


def _shift_sliders(out, d, w):
    res = []
    for s in out:
        x1, y1, x2, y2 = s[1]
        res.append((s[0], (x1 + d, y1, x2 + d, y2)) + tuple(s[2:]))
    return res


def _wrap_bars(fn):
    """Vertical scroll for columns taller than the free space: buttons
    that do not fit are left out (so they are neither drawn nor pressed)."""
    if getattr(fn, "_nomad_bars", False):
        return fn

    def wrapped(*args, **kw):
        out = list(fn(*args, **kw))
        if not out:
            return out
        from . import panels
        context = bpy.context
        w, h = args[1], args[2]
        direction = getattr(panels, "_direction", None)
        fixed = [b for b in out if len(b) > 5 and b[5] is direction]
        pool = [b for b in out if not (len(b) > 5 and b[5] is direction)]
        res = list(fixed)
        y_lo, _hi = _y_limits(context, h)
        for side, sel in (("L", [b for b in pool if b[0] < w / 2]),
                          ("R", [b for b in pool if b[0] >= w / 2])):
            if not sel:
                continue
            top = max(b[3] for b in sel)
            bottom = min(b[1] for b in sel)
            if bottom >= y_lo - 0.5:
                res += sel
                continue
            lo_eff = y_lo + ARROW_H + 6
            kmax = max(0, math.ceil((lo_eff - bottom) / STEP))
            k = max(0, min(_bar[side], kmax))
            _bar[side] = k
            off = k * STEP
            _info[side] = (min(b[0] for b in sel), max(b[2] for b in sel),
                           y_lo, lo_eff, kmax)
            for b in sel:
                y1, y2 = b[1] + off, b[3] + off
                if y1 >= lo_eff - 0.5 and y2 <= top + 0.5:
                    res.append((b[0], y1, b[2], y2) + tuple(b[4:]))
        return res
    wrapped._nomad_bars = True
    return wrapped


_KEY_ACTIONS = {}


def _delete_objects():
    from .sculpt_popups import defer_op
    defer_op("object", "delete", 'EXEC_DEFAULT', use_global=False)


_KEY_ACTIONS["qf_delete"] = _delete_objects


def _wrap_press(orig):
    if getattr(orig, "_nomad_press", False):
        return orig

    def press(context, w, h, mx, my):
        try:
            from . import tool_sidebar
            for b in tool_sidebar._layout(context, w, h):
                if _in(b[:4], mx, my):
                    key = b[4][0] if isinstance(b[4], (tuple, list)) else b[4]
                    act = _KEY_ACTIONS.get(key)
                    if act is not None:
                        act()
                        return True
                    break
        except Exception:
            pass
        return orig(context, w, h, mx, my)
    press._nomad_press = True
    return press


def install():
    """Buttons are every rect drawn with one of these colours; the bars get
    left inset, vertical scrolling, extra actions and dynamic icons."""
    from . import (panels, tool_sidebar, color_overlay, outliner_gpu,
                   asset_gpu)
    cols = [panels.COL_BTN, panels.COL_HOVER, panels.FILL_COL]
    for mod, names in (
            (color_overlay, ("COL_BTN", "COL_HOVER", "COL_ON")),
            (outliner_gpu, ("COL_ROW", "COL_SEL", "COL_DROP")),
            (asset_gpu, ("COL_ROW", "COL_SEL"))):
        cols += [getattr(mod, n, None) for n in names]
    drawing.button_colors(*cols)

    panels._side_for = _wrap_icons(_wrap_bars(_wrap_left(
        _wrap_sculpt_annot(_wrap_move_brushes(panels._side_for)),
        _shift_side)), 'side')
    panels._slider_specs = _wrap_left(panels._slider_specs, _shift_sliders)
    tool_sidebar._layout = _wrap_icons(_wrap_bars(_wrap_left(
        tool_sidebar._layout, _shift_side)), 'layout')
    tool_sidebar.press = _wrap_press(tool_sidebar.press)


# ----------------------------------------------------------------------
# Scroll arrows and wheel
# ----------------------------------------------------------------------

def bar_arrows(context, w, h):
    """{side: (x1, x2, y_lo, lo_eff, kmax)} for the overflowing columns."""
    from . import panels, tool_sidebar
    _info.clear()
    try:
        panels._side_for(context.mode, w, h)
    except Exception:
        pass
    try:
        tool_sidebar._layout(context, w, h)
    except Exception:
        pass
    return dict(_info)


def _arrow_rects(info):
    x1, x2, y_lo, lo_eff, kmax = info
    xc = (x1 + x2) / 2
    return ((x1 + 1, y_lo + 2, xc - 1, y_lo + ARROW_H),
            (xc + 1, y_lo + 2, x2 - 1, y_lo + ARROW_H))


def press_bars(context, w, h, mx, my):
    for side, info in bar_arrows(context, w, h).items():
        up, down = _arrow_rects(info)
        if _in(up, mx, my):
            _bar[side] = max(0, _bar[side] - 1)
            return True
        if _in(down, mx, my):
            _bar[side] = min(info[4], _bar[side] + 1)
            return True
    return False


def wheel(area, region, mx, my, direction):
    context = bpy.context
    w, h = region_size(region)
    for side, info in bar_arrows(context, w, h).items():
        x1, x2, y_lo, lo_eff, kmax = info
        if x1 - 6 <= mx <= x2 + 6 and y_lo <= my <= h:
            _bar[side] = max(0, min(kmax, _bar[side] - direction))
            return True
    return False


# ----------------------------------------------------------------------
# Drawing
# ----------------------------------------------------------------------

def draw_groups(context, w, h):
    from . import panels, tool_sidebar
    mode = context.mode

    side = []
    try:
        side = list(panels._side_for(mode, w, h))
    except Exception:
        pass
    direction = [b for b in side
                 if len(b) > 5 and b[5] is getattr(panels, "_direction", None)]

    # sliders (+ Direction) form one group
    group = []
    try:
        group = [s[1] for s in panels._slider_specs(context, w, h)]
    except Exception:
        pass
    group += [tuple(b[:4]) for b in direction]
    if group:
        pill(*_bbox(group, 4))

    # the rest of each column, in groups of GROUP_SIZE
    btns = [tuple(b[:4]) for b in side if b not in direction]
    try:
        btns += [tuple(b[:4]) for b in tool_sidebar._layout(context, w, h)]
    except Exception:
        pass
    cols = {}
    for r in btns:
        cols.setdefault(round(r[0]), []).append(r)
    for col in cols.values():
        col.sort(key=lambda r: -r[3])                  # top to bottom
        for i in range(0, len(col), GROUP_SIZE):
            pill(*_bbox(col[i:i + GROUP_SIZE], 2))

    # scroll arrows of the overflowing columns
    mx, my = panels.mouse
    for side_key, info in bar_arrows(context, w, h).items():
        x1, x2, y_lo, lo_eff, kmax = info
        pill(x1 - 2, y_lo, x2 + 2, y_lo + ARROW_H + 4)
        for rc, g, can in zip(_arrow_rects(info), ("▲", "▼"),
                              (_bar[side_key] > 0, _bar[side_key] < kmax)):
            drawing.rrect(*rc, 6, panels.COL_HOVER
                          if can and _in(rc, mx, my) else COL_BTN_IDLE)
            drawing.glyph((rc[0] + rc[2]) / 2, (rc[1] + rc[3]) / 2, g, 11,
                          panels.COL_GLYPH if can else COL_ARROW_OFF)

    # navigation gizmo: its buttons in one pill (one per quadrant)
    if getattr(context.scene, "nomad_nav_gizmo", True):
        try:
            from . import nav_gizmo
            for rects in nav_gizmo.groups(context, w, h):
                pill(*_bbox(rects, 3))
        except Exception:
            pass


def _annot_cb(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_tools_annot")


_annot_cb.tool_key = "annot"


def _wrap_move_brushes(fn):
    """Vertex / Texture Paint: brush-kind buttons live in the right bar."""
    if getattr(fn, "_nomad_mb", False):
        return fn

    def wrapped(*args, **kw):
        out = list(fn(*args, **kw))
        if not (args and args[0] in ('PAINT_VERTEX', 'PAINT_TEXTURE')):
            return out
        keep = [b for b in out
                if not (len(b) > 5 and getattr(b[5], "brush_kind", None))]
        if len(keep) == len(out) or not keep:
            return out
        from . import panels
        pitch = panels.BTN + panels.PAD
        top = max(b[3] for b in out)
        keep.sort(key=lambda b: -b[3])
        res = []
        for i, b in enumerate(keep):
            y2 = top - i * pitch
            res.append((b[0], y2 - (b[3] - b[1]), b[2], y2) + tuple(b[4:]))
        return res
    wrapped._nomad_mb = True
    return wrapped


def _facemask_cb(op, area):
    def _go():
        ob = bpy.context.active_object
        if ob is not None and ob.type == 'MESH':
            ob.data.use_paint_mask = not ob.data.use_paint_mask
        return None
    try:
        bpy.app.timers.register(_go, first_interval=0.01)
    except RuntimeError:
        pass


def _facemask_on(context):
    ob = context.active_object
    return bool(ob is not None and ob.type == 'MESH'
                and ob.data.use_paint_mask)


_facemask_cb.is_on = _facemask_on


def _stencil_cb(op, area):
    from . import color_overlay as co
    try:
        if not co.stencil_available(bpy.context):
            return                        # greyed out: ignore the tap
    except Exception:
        return
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_tp_stencil")


def _stencil_enabled(context):
    from . import color_overlay as co
    try:
        return bool(co.stencil_available(context))
    except Exception:
        return False


def _stencil_on(context):
    from . import color_overlay as co
    return getattr(co, "stencil_mode", None) is not None


_stencil_cb.is_enabled = _stencil_enabled
_stencil_cb.is_on = _stencil_on


def _wrap_sculpt_annot(fn):
    """Left bar extras: Annotate in Sculpt; in Texture Paint, Stencil
    controls under "Texture (brush)" and Face Selection Masking at the end."""
    if getattr(fn, "_nomad_sa", False):
        return fn

    def wrapped(*args, **kw):
        out = list(fn(*args, **kw))
        if not (args and out):
            return out
        from . import panels
        pitch = panels.BTN + panels.PAD
        mode = args[0]

        if mode == 'SCULPT':
            if not any(len(b) > 5 and getattr(b[5], "tool_key", None)
                       == "annot" for b in out):
                low = min(out, key=lambda b: b[1])
                x1, y1, x2, y2 = low[:4]
                out.append((x1, y1 - pitch, x2, y2 - pitch, "Annotate",
                            _annot_cb, "✐"))

        elif mode == 'PAINT_TEXTURE':
            if not any(len(b) > 5 and b[5] is _stencil_cb for b in out):
                idx = next((i for i, b in enumerate(out)
                            if len(b) > 5 and "Texture" in str(b[4])), None)
                if idx is not None:
                    ref = out[idx]
                    moved = [(b[0], b[1] - pitch, b[2], b[3] - pitch)
                             + tuple(b[4:]) if i > idx else b
                             for i, b in enumerate(out)]
                    moved.insert(idx + 1, (
                        ref[0], ref[1] - pitch, ref[2], ref[3] - pitch,
                        "Stencil controls", _stencil_cb, "▧"))
                    out = moved
            if not any(len(b) > 5 and b[5] is _facemask_cb for b in out):
                low = min(out, key=lambda b: b[1])
                x1, y1, x2, y2 = low[:4]
                out.append((x1, y1 - pitch, x2, y2 - pitch,
                            "Face selection masking", _facemask_cb, "◩"))
        return out
    wrapped._nomad_sa = True
    return wrapped


_last_icon = {}


def _group_icon(context, key):
    """Icon of the active tool of a group (or the last one used)."""
    from . import tool_sidebar as ts, icons
    try:
        members = ts._members(context, key)
        active = ts._active_idname(context)
    except Exception:
        return None
    for m in members or ():
        if getattr(m, "idname", None) == active:
            name = getattr(m, "icon", None)
            if isinstance(name, str) and icons.exists(name):
                _last_icon[(context.mode, key)] = name
            break
    return _last_icon.get((context.mode, key))


def _wrap_icons(fn, kind):
    if getattr(fn, "_nomad_icons", False):
        return fn

    def wrapped(*args, **kw):
        out = fn(*args, **kw)
        context = bpy.context
        res = []
        for b in out:
            try:
                if kind == 'layout':
                    key, glyph, tip, panel = b[4]
                    if panel and str(panel).startswith("NOMAD_PT_tools_"):
                        name = _group_icon(context, key)
                        if name:
                            b = tuple(b[:4]) + (
                                (key, "icon:" + name, tip, panel),)
                else:
                    key = getattr(b[5], "tool_key", None)
                    if key:
                        name = _group_icon(context, key)
                        if name:
                            b = tuple(b[:6]) + ("icon:" + name,)
            except Exception:
                pass
            res.append(b)
        return res
    wrapped._nomad_icons = True
    return wrapped