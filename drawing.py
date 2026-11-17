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
    blf.size(fid, size)
    blf.color(fid, *color)
    w, h = blf.dimensions(fid, s)
    dy = GLYPH_DY.get(s, 0.0) * size / 18.0     # table values are for 18 px
    blf.position(fid, round(cx - w / 2),
                 round(cy - h / 2 + 0.06 * size + dy), 0)
    blf.draw(fid, s)


def text(x, y, s, size=14, color=(1, 1, 1, 1), align='LEFT'):
    fid = 0
    if align == 'CENTER' and ((len(s) <= 2 and size >= 14)
                              or s.startswith("icon:")):
        # legacy glyph buttons: the caller passes baseline = centre - size/2
        glyph(x, y + size / 2, s, size, color)
        return
    blf.size(fid, size)
    blf.color(fid, *color)
    w, _ = blf.dimensions(fid, s)
    if align == 'CENTER':
        x -= w / 2
    elif align == 'RIGHT':
        x -= w
    blf.position(fid, round(x), round(y), 0)
    blf.draw(fid, s)


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