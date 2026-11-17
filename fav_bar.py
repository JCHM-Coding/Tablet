# Favorite brushes as a strip of buttons. Placeable on any edge. Top and
# bottom strips are centred and grow from the middle; side strips start at
# the top. Never full width.
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

from . import brush_shelf, drawing, panels, style, top_bar
from .sculpt_popups import defer_op

ICON = 44
GAP = 6
PAD = 8
THICK = ICON + 2 * PAD
SIDE_MARGIN = 200            # free space kept at each end of a horizontal strip

_tex = {}               # (type, rel) -> GPUTexture
_tex_for = [None]
_scroll = 0.0
_st = {"last": (0, 0), "moved": 0.0, "press": None}


def _side(context):
    return getattr(context.scene, "nomad_fav_side", 'BOTTOM')


def _entries(context):
    mode = context.mode
    if (not getattr(context.scene, "nomad_fav_bar", False)
            or mode not in brush_shelf.MODES):
        return None
    ents = brush_shelf.favorite_entries(mode)
    if ents is None:
        brush_shelf.ensure_async(mode)
        return []
    return ents


def _tl_base(context):
    th = top_bar.timeline_height(context)
    return th + 8 if th else panels.MARGIN


def bottom_offset(context):
    """Height taken at the very bottom by the strip (Undo/Redo goes above)."""
    if _side(context) != 'BOTTOM' or _entries(context) is None:
        return 0
    return THICK + 8


def right_offset(context):
    """Width taken at the right edge (picker and gizmo move left of it)."""
    if _side(context) != 'RIGHT' or _entries(context) is None:
        return 0
    return THICK + 12


def left_offset(context):
    """Width taken at the far left; the toolbars move right of it."""
    if _side(context) != 'LEFT' or _entries(context) is None:
        return 0
    return THICK + 8


def top_offset(context):
    """Height taken under the top bar (info text and panels move down)."""
    if _side(context) != 'TOP' or _entries(context) is None:
        return 0
    return THICK + 8



def _panel(context, w, h, n):
    """((x1, y1, x2, y2), vertical)"""
    side = _side(context)
    inner = max(n, 1) * (ICON + GAP) - GAP + 2 * PAD
    if side in ('TOP', 'BOTTOM'):
        length = min(inner, w - 2 * SIDE_MARGIN)
        x1 = (w - length) / 2
        y1 = (_tl_base(context) if side == 'BOTTOM'
              else h - top_bar.BAR_H - 8 - THICK)
        return (x1, y1, x1 + length, y1 + THICK), False

    lo = _tl_base(context) + panels.BOT_H + 8
    hi = h - top_bar.BAR_H - 8
    length = min(inner, hi - lo)
    y2 = hi
    y1 = y2 - length                         # starts at the top
    if side == 'LEFT':
        x1 = panels.MARGIN                   # far left
    else:
        left = getattr(context.scene, "nomad_sidebar_left", False)
        x2 = w - (panels.MARGIN + 6 if left
                  else panels.MARGIN + 4 + panels.BTN + 14)
        x1 = x2 - THICK
    return (x1, y1, x1 + THICK, y2), True


def _texture(e):
    if _tex_for[0] is not brush_shelf._all:
        _tex.clear()
        _tex_for[0] = brush_shelf._all
    key = (e["type"], e["rel"])
    if key in _tex:
        return _tex[key]
    b = brush_shelf._brush_named(e["local"])
    tex = None
    try:
        pv = b.preview if b is not None else None
        if pv is not None:
            for size_attr, px_attr in (("image_size", "image_pixels_float"),
                                       ("icon_size", "icon_pixels_float")):
                w, h = getattr(pv, size_attr)
                px = list(getattr(pv, px_attr))
                if w > 0 and h > 0 and len(px) == w * h * 4:
                    buf = gpu.types.Buffer('FLOAT', len(px), px)
                    tex = gpu.types.GPUTexture((w, h), format='RGBA32F',
                                               data=buf)
                    break
    except Exception:
        tex = None
    if tex is not None:
        _tex[key] = tex
    return tex


def _draw_tex(tex, x1, y1, x2, y2):
    shader = gpu.shader.from_builtin('IMAGE')
    batch = batch_for_shader(shader, 'TRI_FAN', {
        "pos": ((x1, y1), (x2, y1), (x2, y2), (x1, y2)),
        "texCoord": ((0, 0), (1, 0), (1, 1), (0, 1))})
    shader.uniform_sampler("image", tex)
    batch.draw(shader)


def _slots(ents, rect, vertical):
    x1, y1, x2, y2 = rect
    out = []
    for i, e in enumerate(ents):
        off = PAD + i * (ICON + GAP)
        if vertical:
            top = y2 - off + _scroll
            r = (x1 + PAD, top - ICON, x1 + PAD + ICON, top)
            if r[1] < y1 + PAD - 0.5 or r[3] > y2 - PAD + 0.5:
                continue
        else:
            left = x1 + off - _scroll
            r = (left, y1 + PAD, left + ICON, y1 + PAD + ICON)
            if r[0] < x1 + PAD - 0.5 or r[2] > x2 - PAD + 0.5:
                continue
        out.append((i, e, r))
    return out


def draw(context, w, h, mx, my):
    global _scroll
    ents = _entries(context)
    if ents is None:
        return
    rect, vertical = _panel(context, w, h, len(ents))
    x1, y1, x2, y2 = rect
    style.pill(x1, y1, x2, y2, style.COL_PILL_DARK)
    if not ents:
        drawing.glyph((x1 + x2) / 2, (y1 + y2) / 2, "★", 18, panels.COL_TIP)
        return

    view = (y2 - y1 if vertical else x2 - x1) - 2 * PAD
    total = len(ents) * (ICON + GAP) - GAP
    _scroll = max(0.0, min(_scroll, total - view))
    ak = brush_shelf._active_key(context)
    for i, e, r in _slots(ents, rect, vertical):
        on = ak == (e["name"], e["fnorm"])
        inside = r[0] <= mx <= r[2] and r[1] <= my <= r[3]
        drawing.rrect(r[0] - 2, r[1] - 2, r[2] + 2, r[3] + 2, 9,
                      panels.COL_HOVER if inside
                      else panels.FILL_COL if on else style.COL_PILL)
        tex = _texture(e)
        if tex is not None:
            _draw_tex(tex, r[0], r[1], r[2], r[3])
        else:
            drawing.glyph((r[0] + r[2]) / 2, (r[1] + r[3]) / 2,
                          e["name"][:1].upper(), 18, panels.COL_GLYPH)
        if inside:
            panels.hover_tip = e["name"]


def press(context, w, h, mx, my):
    """False | 'fb_scroll' (a tap on a brush activates it on release)."""
    ents = _entries(context)
    if ents is None:
        return False
    rect, vertical = _panel(context, w, h, len(ents))
    if not (rect[0] <= mx <= rect[2] and rect[1] <= my <= rect[3]):
        return False
    _st.update(last=(mx, my), moved=0.0, press=None)
    for i, e, r in _slots(ents, rect, vertical):
        if r[0] <= mx <= r[2] and r[1] <= my <= r[3]:
            _st["press"] = e
            break
    return 'fb_scroll'


def update(context, w, h, mx, my, kind):
    global _scroll
    lx, ly = _st["last"]
    _st["last"] = (mx, my)
    dx, dy = mx - lx, my - ly
    _st["moved"] += abs(dx) + abs(dy)
    if _st["moved"] > 8:
        # the strip follows the finger
        _scroll += dy if _side(context) in ('LEFT', 'RIGHT') else -dx


def release(context):
    e, moved = _st["press"], _st["moved"]
    _st["press"] = None
    if e is not None and moved <= 8:
        defer_op("nomad", "brush_activate", 'EXEC_DEFAULT',
                 lib_type=e["type"], lib_id=e["lib_id"], rel=e["rel"])


def register():
    bpy.types.Scene.nomad_fav_side = bpy.props.EnumProperty(
        name="Position",
        items=[('BOTTOM', "Bottom", ""), ('TOP', "Top", ""),
               ('LEFT', "Left", ""), ('RIGHT', "Right", "")],
        default='BOTTOM')


def unregister():
    _tex.clear()
    if hasattr(bpy.types.Scene, "nomad_fav_side"):
        del bpy.types.Scene.nomad_fav_side