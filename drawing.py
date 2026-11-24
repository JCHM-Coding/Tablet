import colorsys
import math

import blf
import bpy
import gpu
from gpu_extras.batch import batch_for_shader

BEVEL = 7
_BTN = set()          # colours that identify buttons (see button_colors)

# Per-glyph vertical fine tuning, in px (positive = up). Estimated: tweak.
GLYPH_DY = {"⋯": -4.5, "⏎": -1.5, "⚙": 1.5, "◫": -1.5, "⊕": 2.0,
            "-": -4.5, "−": -4.0, "–": -4.0, "－": -3.5}


def button_colors(*cols):
    for c in cols:
        if c is not None:
            _BTN.add(tuple(round(v, 4) for v in c))


def _fill(x1, y1, x2, y2, color):
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {
        "pos": [(x1, y1), (x2, y1), (x2, y2),
                (x1, y1), (x2, y2), (x1, y2)],
    })
    shader.uniform_float("color", color)
    batch.draw(shader)


def rect(x1, y1, x2, y2, color):
    """Rectángulo relleno (redondeado si es un botón)."""
    if x2 <= x1 or y2 <= y1:
        return
    if (_BTN and min(x2 - x1, y2 - y1) <= 90
            and tuple(round(c, 4) for c in color) in _BTN):
        rrect(x1, y1, x2, y2, BEVEL, color)
        return
    _fill(x1, y1, x2, y2, color)


def rrect(x1, y1, x2, y2, r, color, seg=5):
    """Rectángulo relleno con esquinas redondeadas."""
    if x2 <= x1 or y2 <= y1:
        return
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    if r < 1.0:
        _fill(x1, y1, x2, y2, color)
        return
    pts = []
    for cx, cy, a0 in ((x2 - r, y2 - r, 0), (x1 + r, y2 - r, 90),
                       (x1 + r, y1 + r, 180), (x2 - r, y1 + r, 270)):
        for i in range(seg + 1):
            a = math.radians(a0 + 90.0 * i / seg)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRI_FAN', {
        "pos": [((x1 + x2) / 2, (y1 + y2) / 2)] + pts + [pts[0]]})
    shader.uniform_float("color", color)
    batch.draw(shader)


SCALE = 1.0               # UI scale of the frame being drawn (set by __init__)


def _draw_dev(fid, text, dx, dy):
    """Draw text at DEVICE pixels (dx, dy), undoing the UI scale matrix: the
    font is rasterised at its real size instead of being stretched (blurry
    on screens with a high DPI)."""
    k = SCALE
    if k != 1.0:
        gpu.matrix.push()
        gpu.matrix.scale((1.0 / k, 1.0 / k))
    blf.position(fid, dx, dy, 0)
    blf.draw(fid, text)
    if k != 1.0:
        gpu.matrix.pop()


_ink = {}               # (glyph, size) -> (dx, dy) from the blf origin to the INK centre


def _ink_centre(pix, w, h, ox, oy):
    """Centre of the drawn pixels relative to the point (ox, oy) where the
    glyph was drawn. `pix` is RGBA, row after row from the bottom."""
    minx, maxx, miny, maxy = w, -1, h, -1
    for y in range(h):
        row = y * w * 4
        for x in range(w):
            i = row + x * 4
            if pix[i + 3] > 16 or pix[i] > 16:
                if x < minx:
                    minx = x
                if x > maxx:
                    maxx = x
                if y < miny:
                    miny = y
                if y > maxy:
                    maxy = y
    if maxx < 0:
        return None
    return (minx + maxx + 1) / 2.0 - ox, (miny + maxy + 1) / 2.0 - oy


def _ink_offset(s, size):
    """Offset from the point blf draws a glyph at to the middle of what is
    visible, measured once by drawing it in a small offscreen buffer. The
    font metrics (blf.dimensions) do not say where the symbol really is, so
    centring with them left many icons high or low in their buttons."""
    key = (s, round(size, 1))
    if key in _ink:
        return _ink[key]
    res = None
    try:
        from mathutils import Matrix
        w = h = max(48, int(size * 3))
        ox, oy = w // 3, h // 3
        off = gpu.types.GPUOffScreen(w, h)
        try:
            with off.bind():
                fb = gpu.state.active_framebuffer_get()
                fb.clear(color=(0.0, 0.0, 0.0, 0.0))
                gpu.matrix.push()
                gpu.matrix.push_projection()
                try:
                    gpu.matrix.load_identity()
                    gpu.matrix.load_projection_matrix(Matrix((
                        (2.0 / w, 0, 0, -1), (0, 2.0 / h, 0, -1),
                        (0, 0, -1, 0), (0, 0, 0, 1))))
                    blf.size(0, size)
                    blf.color(0, 1.0, 1.0, 1.0, 1.0)
                    blf.position(0, ox, oy, 0)
                    blf.draw(0, s)
                finally:
                    gpu.matrix.pop_projection()
                    gpu.matrix.pop()
                buf = fb.read_color(0, 0, w, h, 4, 0, 'UBYTE')
            buf.dimensions = w * h * 4
            res = _ink_centre(buf, w, h, ox, oy)
        finally:
            off.free()
    except Exception as exc:            # keep the old centring
        print(f"NomadUI glyph centring {s!r}: {exc!r}")
        res = None
    _ink[key] = res
    return res


DEBUG_GLYPHS = False      # True: prints each glyph (mode) without an icon
_seen = set()


def plain(x1, y1, x2, y2, color):
    """Rectángulo relleno que NUNCA se redondea (barras de sliders)."""
    if x2 > x1 and y2 > y1:
        _fill(x1, y1, x2, y2, color)


def glyph(cx, cy, s, size=18, color=(1, 1, 1, 1)):
    """Símbolo (o icono real de Blender) centrado en (cx, cy)."""
    if s.startswith("icon:"):                 # dynamic group icon
        try:
            from . import icons
            if icons.draw(s[5:], cx, cy, size * 1.45):
                return
        except Exception:
            pass
        s = "●"
    if len(s) == 1:
        try:
            from . import icons
            mode = bpy.context.mode
            name = icons.lookup(s, mode)
            if name and icons.draw(name, cx, cy, size * 1.45):
                return
            if DEBUG_GLYPHS and (s, mode) not in _seen:
                _seen.add((s, mode))
                print(f"NomadUI glyph without icon: {s!r} in {mode}")
        except Exception:
            pass
    fid = 0
    k = SCALE
    px = size * k                               # real size on the screen
    blf.size(fid, px)
    blf.color(fid, *color)
    ink = _ink_offset(s, px)
    if ink is not None:                         # exact: middle of the ink
        _draw_dev(fid, s, round(cx * k - ink[0]), round(cy * k - ink[1]))
        return
    w, h = blf.dimensions(fid, s)
    dy = GLYPH_DY.get(s, 0.0) * px / 18.0       # table values are for 18 px
    _draw_dev(fid, s, round(cx * k - w / 2),
              round(cy * k - h / 2 + 0.06 * px + dy))


def text(x, y, s, size=14, color=(1, 1, 1, 1), align='LEFT'):
    fid = 0
    if align == 'CENTER' and ((len(s) <= 2 and size >= 14)
                              or s.startswith("icon:")):
        # legacy glyph buttons: the caller passes baseline = centre - size/2
        glyph(x, y + size / 2, s, size, color)
        return
    k = SCALE
    blf.size(fid, size * k)
    blf.color(fid, *color)
    w = blf.dimensions(fid, s)[0] / k           # width in our units
    if align == 'CENTER':
        x -= w / 2
    elif align == 'RIGHT':
        x -= w
    _draw_dev(fid, s, round(x * k), round(y * k))


def begin_2d():
    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')


def end_2d():
    gpu.state.blend_set('NONE')


def circle(cx, cy, r, color, seg=28):
    """Disco relleno."""
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    pts = [(cx + math.cos(2 * math.pi * i / seg) * r,
            cy + math.sin(2 * math.pi * i / seg) * r)
           for i in range(seg + 1)]
    batch = batch_for_shader(shader, 'TRI_FAN', {"pos": [(cx, cy)] + pts})
    shader.uniform_float("color", color)
    batch.draw(shader)


def gradient_sv(x1, y1, x2, y2, hue, steps=24):
    """Cuadrado saturación (x) / valor (y) para un hue dado."""
    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    pure = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
    black = (0.0, 0.0, 0.0, 1.0)
    pos, col = [], []
    for i in range(steps):
        t0, t1 = i / steps, (i + 1) / steps
        xa = x1 + (x2 - x1) * t0
        xb = x1 + (x2 - x1) * t1
        ca = tuple((1 - t0) + t0 * p for p in pure) + (1.0,)
        cb = tuple((1 - t1) + t1 * p for p in pure) + (1.0,)
        bl, br, tr, tl = (xa, y1), (xb, y1), (xb, y2), (xa, y2)
        pos += [bl, br, tr, bl, tr, tl]
        col += [black, black, cb, black, cb, ca]
    batch_for_shader(shader, 'TRIS', {"pos": pos, "color": col}).draw(shader)


def hue_bar(x1, y1, x2, y2):
    """Barra vertical de hue (rojo abajo → rojo arriba)."""
    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    pos, col = [], []
    for k in range(6):
        ya = y1 + (y2 - y1) * k / 6
        yb = y1 + (y2 - y1) * (k + 1) / 6
        ca = colorsys.hsv_to_rgb(k / 6, 1.0, 1.0) + (1.0,)
        cb = colorsys.hsv_to_rgb((k + 1) / 6, 1.0, 1.0) + (1.0,)
        bl, br, tr, tl = (x1, ya), (x2, ya), (x2, yb), (x1, yb)
        pos += [bl, br, tr, bl, tr, tl]
        col += [ca, ca, cb, ca, cb, cb]
    batch_for_shader(shader, 'TRIS', {"pos": pos, "color": col}).draw(shader)


def rects(rs, color):
    """Many filled rectangles in ONE batch."""
    pos = []
    for x1, y1, x2, y2 in rs:
        if x2 > x1 and y2 > y1:
            pos += [(x1, y1), (x2, y1), (x2, y2),
                    (x1, y1), (x2, y2), (x1, y2)]
    if not pos:
        return
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": pos})
    shader.uniform_float("color", color)
    batch.draw(shader)


def diamonds(points, r, color):
    """Many diamonds (keyframes) in ONE batch."""
    pos = []
    for x, y in points:
        pos += [(x - r, y), (x, y + r), (x + r, y),
                (x - r, y), (x + r, y), (x, y - r)]
    if not pos:
        return
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": pos})
    shader.uniform_float("color", color)
    batch.draw(shader)
    
    
def rrect_bottom(x1, y1, x2, y2, r, color, seg=5):
    """Rounded bottom corners, straight top (slider fill)."""
    if x2 <= x1 or y2 <= y1:
        return
    r = max(0.0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    if r < 1.0:
        _fill(x1, y1, x2, y2, color)
        return
    rrect(x1, y1, x2, y2, r, color, seg)
    _fill(x1, y1 + r, x2, y2, color)        # square the top corners