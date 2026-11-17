# Viewport tools: color picker (+ palettes) and navigation gizmo.
# GPU-drawn. Orbit/zoom/pan/roll edit the view directly (no operators).
import colorsys
import math
import random

import bpy
from bpy_extras import view3d_utils
from mathutils import Color, Quaternion, Vector

from . import drawing
from .top_bar import BAR_H

UNITS_WIDE = 10
PX_PER_UNIT = 20.0      # 1 UI unit in px at scale 1.0
RIGHT_MARGIN = 64       # px kept free for the right tool sidebar
PAD = 8
GAP = 6
HUE_W = 24
BTN_H = 34
PBTN_H = 28
PAL_COLS = 10
PAL_GAP = 2
PAL_MAX_ROWS = 15
NAV_R = 44
NAV_BTN = 34
BALL_R = 9

COL_BG = (0.06, 0.06, 0.07, 0.96)
COL_BTN = (0.16, 0.16, 0.18, 1.0)
COL_HOVER = (0.22, 0.48, 0.85, 1.0)
COL_ON = (0.22, 0.48, 0.85, 1.0)
COL_TEXT = (1, 1, 1, 1)
COL_WHITE = (1, 1, 1, 1)
COL_BLACK = (0, 0, 0, 1)

hsv = [0.0, 0.0, 1.0]
_last_rgb = None
armed = False               # Sample armed: next viewport click samples
nav_mode = None             # None | 'ZOOM' | 'PAN' | 'ROLL'
_color_logged = False
stencil_mode = None         # None | 'MOVE' | 'SCALE' | 'ROTATE'
clone_armed = False
stencil_target = 'PRIMARY'  # PRIMARY = brush texture, SECONDARY = mask
_nav = {"last": (0, 0), "moved": 0.0, "ball": None}


# ----------------------------------------------------------------------
# View helpers
# ----------------------------------------------------------------------

def _view3d(context):
    for win in context.window_manager.windows:
        for a in win.screen.areas:
            if a.type != 'VIEW_3D':
                continue
            r = next((r for r in a.regions if r.type == 'WINDOW'), None)
            sp = a.spaces.active
            if r is not None and sp is not None and sp.region_3d:
                return a, r, sp.region_3d
    return None, None, None

def _fav_shift(context):
    from . import fav_bar
    return fav_bar.right_offset(context)


def _defer_view3d(op_name, **kw):
    """Run a view3d operator outside the modal, with a viewport override."""
    def _run():
        try:
            C = bpy.context
            for win in C.window_manager.windows:
                for a in win.screen.areas:
                    if a.type != 'VIEW_3D':
                        continue
                    r = next((r for r in a.regions
                              if r.type == 'WINDOW'), None)
                    if r is None:
                        continue
                    with C.temp_override(window=win, area=a, region=r):
                        getattr(bpy.ops.view3d, op_name)(**kw)
                    return None
        except (RuntimeError, AttributeError, ReferenceError) as exc:
            print(f"NomadUI view3d.{op_name}: {exc}")
        return None
    try:
        bpy.app.timers.register(_run, first_interval=0.01)
    except RuntimeError:
        pass


# ----------------------------------------------------------------------
# Paint / brush / color access
# ----------------------------------------------------------------------

def _paint(context):
    ts = context.tool_settings
    mode = context.mode
    try:
        if mode == 'PAINT_VERTEX':
            paint = ts.vertex_paint
        elif mode == 'PAINT_TEXTURE':
            paint = ts.image_paint
        elif mode == 'SCULPT':
            paint = ts.sculpt
        elif mode == 'PAINT_GREASE_PENCIL':
            paint = ts.gpencil_paint
        elif mode == 'VERTEX_GREASE_PENCIL':
            paint = ts.gpencil_vertex_paint
        else:
            return None, None
    except AttributeError:
        return None, None
    if paint is None:
        return None, None
    brush = getattr(paint, "brush", None)
    if brush is None:
        return None, None
    if mode == 'SCULPT':
        kind = (getattr(brush, "sculpt_brush_type", None)
                or getattr(brush, "sculpt_tool", None))
        if kind not in {'PAINT', 'SMEAR'}:
            return None, None
    return paint, brush


def visible(context):
    if not getattr(context.scene, "nomad_color_overlay", True):
        return False
    return _paint(context)[0] is not None





def _color_owners(context, brush):
    """Every struct that holds a 'color' in this build."""
    paint = _paint(context)[0]
    return [(n, o) for n, o in (("unified", _ups(context)),
                                ("paint", paint), ("brush", brush))
            if o is not None and hasattr(o, "color")]


def _unified(context, brush):
    paint = _paint(context)[0]
    for o in (brush, _ups(context), paint):
        if o is not None and hasattr(o, "use_unified_color"):
            try:
                return bool(o.use_unified_color)
            except (AttributeError, RuntimeError):
                pass
    return False


def get_color(context, brush):
    owners = dict(_color_owners(context, brush))
    if not owners:
        return (1.0, 1.0, 1.0)
    if _unified(context, brush) and "unified" in owners:
        src = owners["unified"]
    elif "brush" in owners:
        src = owners["brush"]
    else:
        src = next(iter(owners.values()))
    try:
        return tuple(src.color)[:3]
    except (AttributeError, RuntimeError):
        return (1.0, 1.0, 1.0)


def _ups(context):
    """Unified paint settings: per paint mode in 5.x, global before."""
    paint = _paint(context)[0]
    for owner in (paint, context.tool_settings):
        ups = getattr(owner, "unified_paint_settings", None)
        if ups is not None:
            return ups
    return None


def set_color(context, brush, rgb):
    global _color_logged
    rgb = tuple(max(0.0, min(1.0, c)) for c in rgb[:3])
    owners = _color_owners(context, brush)
    wrote, failed = [], []
    for name, o in owners:
        try:
            o.color = rgb
            wrote.append(name)
        except (AttributeError, RuntimeError, TypeError):
            failed.append(name)
    if _unified(context, brush) and "unified" not in wrote:
        # the unified color can't be written: let the brush color paint
        for o in (brush, _ups(context)):
            if o is not None and hasattr(o, "use_unified_color"):
                try:
                    o.use_unified_color = False
                    break
                except (AttributeError, RuntimeError, TypeError):
                    continue
    if not _color_logged:
        _color_logged = True
        print(f"NomadUI color [{context.mode}]: owners="
              f"{[n for n, _o in owners]} written={wrote} failed={failed} "
              f"unified={_unified(context, brush)} "
              f"ups={type(_ups(context)).__name__}")


def _sync(rgb):
    """Refresh HSV when the brush color changed externally."""
    global _last_rgb
    if _last_rgb is not None and all(
            abs(a - b) < 1e-4 for a, b in zip(rgb, _last_rgb)):
        return
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    if s < 1e-4 or v < 1e-4:
        h = hsv[0]
    if v < 1e-4:
        s = hsv[1]
    hsv[:] = [h, s, v]
    _last_rgb = tuple(rgb)


def _apply_hsv(context, brush):
    global _last_rgb
    rgb = colorsys.hsv_to_rgb(*hsv)
    set_color(context, brush, rgb)
    _last_rgb = tuple(rgb)


# ----------------------------------------------------------------------
# Picker layout
# ----------------------------------------------------------------------

def _fav_shift(context):
    """Width taken by the favorites strip when it sits on the right."""
    from . import fav_bar
    return fav_bar.right_offset(context)


def _in(r, mx, my):
    return r[0] <= mx <= r[2] and r[1] <= my <= r[3]


def _r(rect, color):
    drawing.rect(rect[0], rect[1], rect[2], rect[3], color)


def _outline(rect, t, color):
    x1, y1, x2, y2 = rect
    drawing.rect(x1, y2 - t, x2, y2, color)
    drawing.rect(x1, y1, x2, y1 + t, color)
    drawing.rect(x1, y1, x1 + t, y2, color)
    drawing.rect(x2 - t, y1, x2, y2, color)


def _fit(text, size, max_w):
    """Cut the text (with an ellipsis) so it fits in max_w px."""
    import blf
    blf.size(0, size)
    if blf.dimensions(0, text)[0] <= max_w:
        return text
    while len(text) > 1 and blf.dimensions(0, text + "…")[0] > max_w:
        text = text[:-1]
    return text + "…"


# ----------------------------------------------------------------------
# Navigation gizmo
# ----------------------------------------------------------------------

# (label, world axis, view name, color, positive)
_AXES = (
    ("X", (1, 0, 0), 'RIGHT', (0.93, 0.25, 0.32), True),
    ("-X", (-1, 0, 0), 'LEFT', (0.93, 0.25, 0.32), False),
    ("Y", (0, 1, 0), 'BACK', (0.55, 0.80, 0.20), True),
    ("-Y", (0, -1, 0), 'FRONT', (0.55, 0.80, 0.20), False),
    ("Z", (0, 0, 1), 'TOP', (0.25, 0.55, 0.95), True),
    ("-Z", (0, 0, -1), 'BOTTOM', (0.25, 0.55, 0.95), False),
)


def _balls(rv3d, cx, cy):
    """(depth, x, y, label, view, color, positive), far to near."""
    m = rv3d.view_matrix.to_3x3()
    ring = NAV_R - BALL_R - 3
    out = []
    for label, vec, view, col, pos in _AXES:
        v = m @ Vector(vec)
        out.append((v.z, cx + v.x * ring, cy + v.y * ring,
                    label, view, col, pos))
    out.sort(key=lambda b: b[0])
    return out


def _ball_at(rv3d, cx, cy, mx, my):
    for b in reversed(_balls(rv3d, cx, cy)):      # nearest first
        if (b[1] - mx) ** 2 + (b[2] - my) ** 2 <= (BALL_R + 3) ** 2:
            return b
    return None


def _nav_geometry(context, w, h):
    from . import nav_gizmo
    return nav_gizmo.legacy_geometry(context, w, h)


def _draw_nav(context, w, h, mx, my):
    from . import nav_gizmo
    nav_gizmo.draw(context, w, h, mx, my)


def _nav_press(context, w, h, mx, my):
    from . import nav_gizmo
    return nav_gizmo.press(context, w, h, mx, my)


def _nav_update(context, mx, my, kind):
    from . import nav_gizmo
    nav_gizmo.update(context, mx, my, kind)


def release(context):
    """Drag ended (navigation): a tap on an axis ball jumps to that view."""
    from . import nav_gizmo
    nav_gizmo.release(context)




# ----------------------------------------------------------------------
# Sampling
# ----------------------------------------------------------------------

def _sample_attribute(context, area, mx, my):
    """Color of the nearest vertex under (mx, my), as brush (sRGB) color."""
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    obj = context.active_object
    if region is None or obj is None or obj.type != 'MESH':
        return None
    rv3d = area.spaces.active.region_3d
    view = view3d_utils.region_2d_to_vector_3d(region, rv3d, (mx, my))
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, (mx, my))
    inv = obj.matrix_world.inverted()
    o = inv @ origin
    d = ((inv @ (origin + view)) - o).normalized()
    hit, loc, _nor, idx = obj.ray_cast(o, d)
    if not hit or idx < 0:
        return None
    me = obj.data
    attr = me.color_attributes.active_color
    if attr is None:
        return None
    poly = me.polygons[idx]
    best = min(poly.vertices,
               key=lambda v: (me.vertices[v].co - loc).length_squared)
    c = None
    if attr.domain == 'POINT':
        c = attr.data[best].color
    else:
        for li in poly.loop_indices:
            if me.loops[li].vertex_index == best:
                c = attr.data[li].color
                break
    if c is None:
        return None
    col = Color((c[0], c[1], c[2])).from_scene_linear_to_srgb()
    return (col.r, col.g, col.b)


def _defer_native_sample(mx, my):
    """Texture paint: native sampler, EXEC with the exact click position
    (the modal INVOKE version waited for a release that never came)."""
    def _run():
        try:
            C = bpy.context
            for win in C.window_manager.windows:
                for a in win.screen.areas:
                    if a.type != 'VIEW_3D':
                        continue
                    r = next((r for r in a.regions
                              if r.type == 'WINDOW'), None)
                    if r is None:
                        continue
                    with C.temp_override(window=win, area=a, region=r):
                        bpy.ops.paint.sample_color(
                            'EXEC_DEFAULT', location=(int(mx), int(my)))
                    return None
        except (RuntimeError, AttributeError, TypeError,
                ReferenceError) as exc:
            print(f"NomadUI sample color: {exc}")
        return None
    try:
        bpy.app.timers.register(_run, first_interval=0.01)
    except RuntimeError:
        pass


def _do_sample(context, area, mx, my):
    paint, brush = _paint(context)
    if brush is None:
        return
    rgb = None
    if context.mode in {'SCULPT', 'PAINT_VERTEX'}:
        try:
            rgb = _sample_attribute(context, area, mx, my)
        except Exception as exc:
            print(f"NomadUI sample attribute: {exc!r}")
    if rgb is not None:
        set_color(context, brush, rgb)
    else:
        _defer_native_sample(mx, my)





def stencil_props(brush, target):
    """(position attr, dimension attr, texture slot) of the chosen one."""
    if target == 'SECONDARY':
        return ("mask_stencil_pos", "mask_stencil_dimension",
                getattr(brush, "mask_texture_slot", None))
    return ("stencil_pos", "stencil_dimension",
            getattr(brush, "texture_slot", None))


def _image_brush(context):
    from . import brush_shelf
    return brush_shelf.active_brush(context)


def stencil_available(context):
    """True if the brush texture or its mask uses stencil mapping."""
    if context.mode not in {'PAINT_TEXTURE', 'SCULPT'}:
        return False
    brush = _image_brush(context)
    if brush is None:
        return False
    slot = getattr(brush, "texture_slot", None)
    mslot = getattr(brush, "mask_texture_slot", None)
    return (any(getattr(slot, a, None) == 'STENCIL'
                for a in ("map_mode", "tex_paint_map_mode"))
            or getattr(mslot, "mask_map_mode", None) == 'STENCIL')


def _set_cursor_at(context, area, mx, my):
    """Put the 3D cursor where the user tapped (the clone source)."""
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    if region is None:
        return
    rv3d = area.spaces.active.region_3d
    scene = context.scene
    obj = context.active_object
    point = None
    if obj is not None and obj.type == 'MESH':
        view = view3d_utils.region_2d_to_vector_3d(region, rv3d, (mx, my))
        origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, (mx, my))
        inv = obj.matrix_world.inverted()
        o = inv @ origin
        d = ((inv @ (origin + view)) - o).normalized()
        hit, loc, _n, _i = obj.ray_cast(o, d)
        if hit:
            point = obj.matrix_world @ loc
    if point is None:
        point = view3d_utils.region_2d_to_location_3d(
            region, rv3d, (mx, my), scene.cursor.location)
    scene.cursor.location = point


def _stencil_update(context, mx, my, kind):
    brush = _image_brush(context)
    if brush is None:
        return
    pos_attr, dim_attr, slot = stencil_props(brush, stencil_target)
    lx, ly = _nav["last"]
    dx, dy = mx - lx, my - ly
    _nav["last"] = (mx, my)
    try:
        if kind == 'st_move':
            p = getattr(brush, pos_attr)
            setattr(brush, pos_attr, (p[0] + dx, p[1] + dy))
        elif kind == 'st_scale':
            f = math.exp(dy * 0.01)             # drag up = bigger
            d = getattr(brush, dim_attr)
            setattr(brush, dim_attr, (d[0] * f, d[1] * f))
        elif kind == 'st_rotate' and slot is not None:
            slot.angle = slot.angle - dx * 0.01
    except (AttributeError, RuntimeError, TypeError) as exc:
        print(f"NomadUI stencil: {exc!r}")


# ----------------------------------------------------------------------
# Interaction
# ----------------------------------------------------------------------

def _randomize(context, brush):
    h = random.random()
    s = hsv[1] if hsv[1] > 0.15 else random.uniform(0.5, 1.0)
    v = hsv[2] if hsv[2] > 0.15 else random.uniform(0.6, 1.0)
    hsv[:] = [h, s, v]
    _apply_hsv(context, brush)


def _add_to_palette(context, paint, brush):
    pal = getattr(paint, "palette", None)
    if pal is None:
        pal = bpy.data.palettes.new("Nomad Palette")
        try:
            paint.palette = pal
        except (AttributeError, RuntimeError) as exc:
            print(f"NomadUI palette: {exc}")
            return
    pal.colors.new().color = get_color(context, brush)


def _remove_from_palette(paint):
    pal = getattr(paint, "palette", None)
    if pal is None:
        return
    try:
        if pal.colors.active is not None:
            pal.colors.remove(pal.colors.active)
    except (AttributeError, RuntimeError, ReferenceError):
        pass


ARROW_H = 24
_pal_scroll = 0          # first visible palette row


def layout(context, w, h, paint):
    global _pal_scroll
    from . import style
    pw = UNITS_WIDE * PX_PER_UNIT
    iw = pw - 2 * PAD
    sq = iw - HUE_W - GAP
    tile = (iw - (PAL_COLS - 1) * PAL_GAP) / PAL_COLS

    pal = getattr(paint, "palette", None)
    ncol = len(pal.colors) if pal is not None else 0
    rows_total = math.ceil(ncol / PAL_COLS)

    left = getattr(context.scene, "nomad_sidebar_left", False)
    x2 = w - (8 if left else RIGHT_MARGIN) - _fav_shift(context)
    x1 = x2 - pw
    y_lo = style._stack_top(context)
    y_hi = h - BAR_H - 10.0
    if getattr(context.scene, "nomad_nav_gizmo", True):
        y_hi = min(y_hi, _nav_geometry(context, w, h)[3] - 10.0)

    fixed = PAD + sq + GAP + BTN_H + GAP + PBTN_H + PAD
    avail = y_hi - y_lo

    def tiles_h(r):
        return (GAP + r * tile + (r - 1) * PAL_GAP) if r else 0

    rows = min(PAL_MAX_ROWS, rows_total)
    while rows > 1 and (fixed + tiles_h(rows)
                        + (ARROW_H + GAP if rows_total > rows else 0)) > avail:
        rows -= 1
    scrollable = rows_total > rows
    max_scroll = rows_total - rows if scrollable else 0
    _pal_scroll = max(0, min(_pal_scroll, max_scroll))
    ph = fixed + tiles_h(rows) + (ARROW_H + GAP if scrollable else 0)

    cy = (y_lo + h - BAR_H) / 2
    y2 = min(cy + ph / 2, y_hi)
    y1 = y2 - ph
    if y1 < y_lo:
        y1 = y_lo
        y2 = y1 + ph

    ix = x1 + PAD
    sv = (ix, y2 - PAD - sq, ix + sq, y2 - PAD)
    hue = (sv[2] + GAP, sv[1], sv[2] + GAP + HUE_W, sv[3])
    ry2 = sv[1] - GAP
    ry1 = ry2 - BTN_H
    sw_w = iw * 0.34
    bw = (iw - sw_w - 2 * GAP) / 2
    swatch = (ix, ry1, ix + sw_w, ry2)
    sample = (swatch[2] + GAP, ry1, swatch[2] + GAP + bw, ry2)
    rand = (sample[2] + GAP, ry1, sample[2] + GAP + bw, ry2)

    pb2 = ry1 - GAP
    pb1 = pb2 - PBTN_H
    palbtn = (ix, pb1, ix + iw - 2 * (PBTN_H + GAP), pb2)
    paladd = (palbtn[2] + GAP, pb1, palbtn[2] + GAP + PBTN_H, pb2)
    paldel = (paladd[2] + GAP, pb1, ix + iw, pb2)

    top = pb1 - GAP
    first = _pal_scroll * PAL_COLS
    count = max(0, min(rows * PAL_COLS, ncol - first))
    tiles = []
    for n in range(count):
        r, c = divmod(n, PAL_COLS)
        tx = ix + c * (tile + PAL_GAP)
        ty2 = top - r * (tile + PAL_GAP)
        tiles.append(((tx, ty2 - tile, tx + tile, ty2), first + n))

    arrows = None
    if scrollable:
        bottom = top - rows * tile - (rows - 1) * PAL_GAP
        ay2 = bottom - GAP
        ay1 = ay2 - ARROW_H
        mid = ix + iw / 2
        arrows = ((ix, ay1, mid - 2, ay2), (mid + 2, ay1, ix + iw, ay2))

    return {"panel": (x1, y1, x2, y2), "sv": sv, "hue": hue,
            "swatch": swatch, "sample": sample, "rand": rand,
            "palbtn": palbtn, "paladd": paladd, "paldel": paldel,
            "tiles": tiles, "pal": pal, "arrows": arrows,
            "max_scroll": max_scroll}


def draw(context, w, h, mx, my):
    global armed
    if getattr(context.scene, "nomad_nav_gizmo", True):
        _draw_nav(context, w, h, mx, my)

    if not visible(context):
        armed = False
        return
    paint, brush = _paint(context)
    L = layout(context, w, h, paint)
    rgb = get_color(context, brush)
    _sync(rgb)

    _r(L["panel"], COL_BG)

    sv = L["sv"]
    drawing.gradient_sv(sv[0], sv[1], sv[2], sv[3], hsv[0])
    px = sv[0] + hsv[1] * (sv[2] - sv[0])
    py = sv[1] + hsv[2] * (sv[3] - sv[1])
    _outline((px - 7, py - 7, px + 7, py + 7), 3, COL_BLACK)
    _outline((px - 6, py - 6, px + 6, py + 6), 1, COL_WHITE)

    hb = L["hue"]
    drawing.hue_bar(hb[0], hb[1], hb[2], hb[3])
    hy = hb[1] + hsv[0] * (hb[3] - hb[1])
    drawing.rect(hb[0] - 2, hy - 3, hb[2] + 2, hy + 3, COL_BLACK)
    drawing.rect(hb[0] - 1, hy - 2, hb[2] + 1, hy + 2, COL_WHITE)

    sw = L["swatch"]
    drawing.rrect(sw[0], sw[1], sw[2], sw[3], 7, COL_WHITE)
    drawing.rrect(sw[0] + 1, sw[1] + 1, sw[2] - 1, sw[3] - 1, 6,
                  (rgb[0], rgb[1], rgb[2], 1.0))

    for key, label in (("sample", "Pick..." if armed else "Sample"),
                       ("rand", "Random")):
        rc = L[key]
        hot = _in(rc, mx, my) or (key == "sample" and armed)
        _r(rc, COL_HOVER if hot else COL_BTN)
        drawing.text((rc[0] + rc[2]) / 2, (rc[1] + rc[3]) / 2 - 4, label,
                     size=12, color=COL_TEXT, align='CENTER')

    # Palette row: browser | add color | delete color
    pal = L["pal"]
    pb = L["palbtn"]
    _r(pb, COL_HOVER if _in(pb, mx, my) else COL_BTN)
    name = pal.name if pal is not None else "Palettes..."
    drawing.text((pb[0] + pb[2]) / 2, (pb[1] + pb[3]) / 2 - 4,
                 _fit(name, 12, pb[2] - pb[0] - 12),
                 size=12, color=COL_TEXT, align='CENTER')
    for key, glyph in (("paladd", "+"), ("paldel", "-")):
        rc = L[key]
        _r(rc, COL_HOVER if _in(rc, mx, my) else COL_BTN)
        drawing.text((rc[0] + rc[2]) / 2, (rc[1] + rc[3]) / 2 - 7, glyph,
                     size=18, color=COL_TEXT, align='CENTER')

    active_ptr = None
    if pal is not None:
        try:
            if pal.colors.active is not None:
                active_ptr = pal.colors.active.as_pointer()
        except (AttributeError, RuntimeError):
            pass
    for rc, idx in L["tiles"]:
        pc = pal.colors[idx]
        c = pc.color
        _r(rc, (c[0], c[1], c[2], 1.0))
        if active_ptr is not None and pc.as_pointer() == active_ptr:
            _outline(rc, 2, COL_WHITE)
        elif all(abs(a - b) < 0.004 for a, b in zip(c, rgb)):
            _outline(rc, 1, COL_WHITE)

    if L["arrows"]:
        for rc, g, can in zip(L["arrows"], ("▲", "▼"),
                              (_pal_scroll > 0, _pal_scroll < L["max_scroll"])):
            _r(rc, COL_HOVER if can and _in(rc, mx, my) else COL_BTN)
            drawing.glyph((rc[0] + rc[2]) / 2, (rc[1] + rc[3]) / 2, g, 11,
                          COL_TEXT if can else (0.4, 0.4, 0.44, 1.0))


def _remove_from_palette(paint):
    pal = getattr(paint, "palette", None)
    if pal is None:
        return
    try:
        if pal.colors.active is not None:
            pal.colors.remove(pal.colors.active)
    except (AttributeError, RuntimeError, ReferenceError):
        pass


def press(context, w, h, mx, my):
    """False | True | 'color_sv' | 'color_hue' | 'nav_orbit'."""
    global armed, _pal_scroll
    if getattr(context.scene, "nomad_nav_gizmo", True):
        r = _nav_press(context, w, h, mx, my)
        if r:
            return r
    if not visible(context):
        return False
    paint, brush = _paint(context)
    L = layout(context, w, h, paint)
    if not _in(L["panel"], mx, my):
        return False
    if _in(L["sv"], mx, my):
        return 'color_sv'
    if _in(L["hue"], mx, my):
        return 'color_hue'
    if _in(L["sample"], mx, my):
        armed = not armed
        return True
    if _in(L["rand"], mx, my):
        _randomize(context, brush)
        return True
    if _in(L["palbtn"], mx, my):
        from .sculpt_popups import open_panel_deferred
        open_panel_deferred("NOMAD_PT_palettes")
        return True
    if _in(L["paladd"], mx, my):
        _add_to_palette(context, paint, brush)
        return True
    if _in(L["paldel"], mx, my):
        _remove_from_palette(paint)
        return True
    if L["arrows"]:
        if _in(L["arrows"][0], mx, my):
            _pal_scroll = max(0, _pal_scroll - 1)
            return True
        if _in(L["arrows"][1], mx, my):
            _pal_scroll = min(L["max_scroll"], _pal_scroll + 1)
            return True
    for rc, idx in L["tiles"]:
        if _in(rc, mx, my):
            pc = L["pal"].colors[idx]
            try:
                L["pal"].colors.active = pc
            except (AttributeError, RuntimeError):
                pass
            set_color(context, brush, tuple(pc.color))
            return True
    return True      # panel background: don't paint through it


def wheel(area, region, mx, my, direction):
    global _pal_scroll
    from . import style
    context = bpy.context
    if not visible(context):
        return False
    w, h = style.region_size(region)
    paint, brush = _paint(context)
    L = layout(context, w, h, paint)
    if not _in(L["panel"], mx, my) or not L["arrows"]:
        return False
    _pal_scroll = max(0, min(L["max_scroll"], _pal_scroll - direction))
    return True


def viewport_press(context, area, mx, my):
    """Click on the viewport itself (not on our UI)."""
    global armed, clone_armed
    if armed:
        armed = False
        _do_sample(context, area, mx, my)
        return True
    if clone_armed:
        clone_armed = False
        _set_cursor_at(context, area, mx, my)
        return True
    if stencil_mode and stencil_available(context):
        _nav.update(last=(mx, my), moved=0.0, ball=None)
        return 'st_' + stencil_mode.lower()
    if nav_mode and getattr(context.scene, "nomad_nav_gizmo", True):
        _nav.update(last=(mx, my), moved=0.0, ball=None)
        return 'nav_' + nav_mode.lower()
    return False


def update(context, w, h, mx, my, kind):
    if kind.startswith('st_'):
        _stencil_update(context, mx, my, kind)
        return
    if kind.startswith('nav_'):
        _nav_update(context, mx, my, kind)
        return
    paint, brush = _paint(context)
    if brush is None:
        return
    L = layout(context, w, h, paint)
    if kind == 'color_sv':
        x1, y1, x2, y2 = L["sv"]
        hsv[1] = max(0.0, min(1.0, (mx - x1) / (x2 - x1)))
        hsv[2] = max(0.0, min(1.0, (my - y1) / (y2 - y1)))
    elif kind == 'color_hue':
        x1, y1, x2, y2 = L["hue"]
        hsv[0] = max(0.0, min(0.9999, (my - y1) / (y2 - y1)))
    _apply_hsv(context, brush)


# ----------------------------------------------------------------------
# Palette browser (native popup)
# ----------------------------------------------------------------------

class NOMAD_OT_palette_new(bpy.types.Operator):
    bl_idname = "nomad.palette_new"
    bl_label = "New Palette"
    bl_options = {'INTERNAL', 'UNDO'}

    def execute(self, context):
        paint, brush = _paint(context)
        if paint is None:
            return {'CANCELLED'}
        pal = bpy.data.palettes.new("Palette")
        try:
            paint.palette = pal
        except (AttributeError, RuntimeError) as exc:
            print(f"NomadUI palette: {exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


class NOMAD_OT_palette_color(bpy.types.Operator):
    bl_idname = "nomad.palette_color"
    bl_label = "Palette Color"
    bl_options = {'INTERNAL', 'UNDO'}

    action: bpy.props.EnumProperty(
        items=[('ADD', "Add", ""), ('REMOVE', "Remove", "")])

    def execute(self, context):
        paint, brush = _paint(context)
        if paint is None:
            return {'CANCELLED'}
        pal = getattr(paint, "palette", None)
        if self.action == 'ADD':
            _add_to_palette(context, paint, brush)
        elif pal is not None and pal.colors.active is not None:
            pal.colors.remove(pal.colors.active)
        return {'FINISHED'}


class NOMAD_PT_palettes(bpy.types.Panel):
    bl_label = "Palettes"
    bl_idname = "NOMAD_PT_palettes"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 10
        paint, brush = _paint(context)
        if paint is None:
            l.label(text="Paint modes only", icon='INFO')
            return
        l.template_ID(paint, "palette", new="nomad.palette_new")
        if getattr(paint, "palette", None) is not None:
            l.template_palette(paint, "palette", color=True)
            row = l.row(align=True)
            op = row.operator("nomad.palette_color", text="Add Color",
                              icon='ADD')
            op.action = 'ADD'
            op = row.operator("nomad.palette_color", text="Remove",
                              icon='REMOVE')
            op.action = 'REMOVE'


CLASSES = (NOMAD_OT_palette_new, NOMAD_OT_palette_color, NOMAD_PT_palettes)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    global nav_mode
    nav_mode = None
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass