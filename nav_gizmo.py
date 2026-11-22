# Navigation gizmo for the single view and for Quad View (one gizmo per
# quadrant, each acting on its own 3D region).
import math

import bpy
import gpu
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Quaternion, Vector

from . import color_overlay as co
from . import drawing, panels, style
from .top_bar import BAR_H


_TIPS = {"ZOOM": "Zoom (drag in the viewport)",
         "PAN": "Pan (drag in the viewport)",
         "ROLL": "Roll (drag in the viewport)",
         "CAMERA": "Camera view", "PERSP": "Perspective / Orthographic",
         "LOCK": "Lock rotation (Quad View)",
         "SYNC": "Synchronize views (Quad View)"}
         
         
def _area(context):
    a = context.area
    if a is not None and a.type == 'VIEW_3D':
        return a
    scr = context.screen
    for a in (scr.areas if scr else ()):
        if a.type == 'VIEW_3D':
            return a
    return None


def regions(area):
    return [r for r in area.regions if r.type == 'WINDOW']


def is_quad(area):
    return area is not None and len(regions(area)) > 1


def _quad_props(area):
    """Quad View settings live on the third quad region."""
    try:
        return area.spaces.active.region_quadviews[2]
    except (IndexError, AttributeError, TypeError):
        return None


def _quads(context):
    area = _area(context)
    if area is None:
        return []
    regs = regions(area)
    if not regs:
        return []
    s = style.ui_scale()                 # our UI units, not raw pixels
    sp = area.spaces.active
    ux, uy, uw, uh = style.union(regs)
    main = sp.region_3d.as_pointer() if sp.region_3d is not None else None
    out = []
    for r in regs:
        try:
            rv = r.data
        except (AttributeError, RuntimeError):
            continue
        if rv is None:
            continue
        out.append({"region": r, "rv3d": rv, "x": (r.x - ux) / s,
                    "y": (r.y - uy) / s, "w": r.width / s,
                    "h": r.height / s, "uw": uw / s, "uh": uh / s,
                    "main": len(regs) == 1 or rv.as_pointer() == main})
    if out and not any(q["main"] for q in out):
        out[-1]["main"] = True
    return out


def _items(context, w, h):
    sc = context.scene
    left = getattr(sc, "nomad_sidebar_left", False)
    rm_edge = (8 if left else co.RIGHT_MARGIN) + co._fav_shift(context)
    quad = is_quad(_area(context))
    qp = _quad_props(_area(context)) if quad else None
    lock = bool(qp.lock_rotation) if qp is not None else True
    size, gap = co.NAV_BTN, co.GAP

    items = []
    for q in _quads(context):
        rv = q["rv3d"]
        rm = rm_edge if q["x"] + q["w"] >= q["uw"] - 1 else 10
        topm = BAR_H if q["y"] + q["h"] >= q["uh"] - 1 else 6
        xr = q["x"] + q["w"] - rm
        side_view = (quad and lock and not q["main"]
                     and rv.is_orthographic_side_view)
        if side_view:
            rows = [[("ZOOM", "⊕"), ("PAN", "✥")]]
            ball = None
            cx = xr - (2 * size + gap) / 2 - 4
            y_top = q["y"] + q["h"] - topm - 6
        else:
            rows = [[("ZOOM", "⊕"), ("PAN", "✥"), ("ROLL", "↻")]]
            cx = xr - co.NAV_R - 12
            cy = q["y"] + q["h"] - topm - co.NAV_R - 16
            ball = (cx, cy)
            y_top = cy - co.NAV_R - 8
        if q["main"]:
            row2 = [("CAMERA", "▢"), ("PERSP", "P")]
            if quad:
                row2 += [("LOCK", "⛓"), ("SYNC", "⇄")]
            rows.append(row2)
        buttons, bottom = [], y_top
        for ri, row in enumerate(rows):
            width = len(row) * size + (len(row) - 1) * gap
            bx = min(cx - width / 2, xr - width)
            y2 = y_top - ri * (size + gap)
            y1 = y2 - size
            for i, (mode, glyph) in enumerate(row):
                x1 = bx + i * (size + gap)
                buttons.append(((x1, y1, x1 + size, y2), mode, glyph))
            bottom = min(bottom, y1)
        items.append({"q": q, "ball": ball, "buttons": buttons,
                      "bottom": bottom})
    return items


def legacy_geometry(context, w, h):
    its = _items(context, w, h)
    main = next((i for i in its if i["q"]["main"]), None)
    if main is None:
        return 0, 0, [], 0
    cx, cy = main["ball"] or (0, 0)
    return cx, cy, main["buttons"], main["bottom"]


def groups(context, w, h):
    return [[b[0] for b in it["buttons"]]
            for it in _items(context, w, h) if it["buttons"]]


def _is_on(mode, rv3d, qp):
    if mode in ('ZOOM', 'PAN', 'ROLL'):
        return co.nav_mode == mode
    if mode == 'CAMERA':
        return rv3d.view_perspective == 'CAMERA'
    if mode == 'PERSP':
        return not rv3d.is_perspective
    if qp is None:
        return False
    if mode == 'LOCK':
        return bool(qp.lock_rotation)
    if mode == 'SYNC':
        return bool(qp.show_sync_view)
    return False


# ----------------------------------------------------------------------
# Button icons: vector shapes centred on the middle of the button (the font
# glyphs have different metrics, so drawing them from the same height left
# some of them off centre)
# ----------------------------------------------------------------------

def _seg(t, x1, y1, x2, y2, w):
    dx, dy = x2 - x1, y2 - y1
    n = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / n * w / 2, dx / n * w / 2
    a, b = (x1 + nx, y1 + ny), (x1 - nx, y1 - ny)
    c, d = (x2 - nx, y2 - ny), (x2 + nx, y2 + ny)
    t += [a, b, c, a, c, d]


def _arc(t, cx, cy, r, a0, a1, w, n=16):
    pts = [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
            cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
           for i in range(n + 1)]
    for p, q in zip(pts, pts[1:]):
        _seg(t, p[0], p[1], q[0], q[1], w)


def _box(t, x1, y1, x2, y2):
    t += [(x1, y1), (x2, y1), (x2, y2), (x1, y1), (x2, y2), (x1, y2)]


def _outline(t, x1, y1, x2, y2, w):
    _seg(t, x1 - w / 2, y1, x2 + w / 2, y1, w)
    _seg(t, x1 - w / 2, y2, x2 + w / 2, y2, w)
    _seg(t, x1, y1, x1, y2, w)
    _seg(t, x2, y1, x2, y2, w)


def _arrow_head(t, x, y, dx, dy, big=4.5, half=3.2):
    """Triangle with its tip at (x, y) + direction * big."""
    nx, ny = -dy, dx
    t += [(x + dx * big, y + dy * big), (x + nx * half, y + ny * half),
          (x - nx * half, y - ny * half)]


def _icon_tris(mode):
    t = []
    if mode == 'ZOOM':                      # magnifier
        _arc(t, -1.5, 1.5, 5.5, 0, 360, 2.0, 20)
        _seg(t, 2.4, -2.4, 7.0, -7.0, 3.0)
    elif mode == 'PAN':                     # four arrows
        _seg(t, -6, 0, 6, 0, 2.0)
        _seg(t, 0, -6, 0, 6, 2.0)
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            _arrow_head(t, dx * 5.5, dy * 5.5, dx, dy, 4.5, 3.4)
    elif mode == 'ROLL':                    # clockwise arc with arrow head
        _arc(t, 0, 0, 7.0, 120, -150, 2.0, 22)
        a = math.radians(-150)
        px, py = 7.0 * math.cos(a), 7.0 * math.sin(a)
        tx, ty = math.sin(a), -math.cos(a)  # clockwise tangent
        _arrow_head(t, px, py, tx, ty, 4.8, 3.6)
    elif mode == 'CAMERA':                  # body + lens
        _outline(t, -8.5, -5, 2.5, 5, 2.0)
        t += [(2.5, 0), (8.5, 5), (8.5, -5)]
    elif mode == 'LOCK':                    # padlock
        _box(t, -6, -6.5, 6, 2.5)
        _arc(t, 0, 2.5, 4.0, 0, 180, 2.0, 12)
    elif mode == 'SYNC':                    # two opposite arrows
        _seg(t, -8, 3, 5, 3, 2.0)
        _arrow_head(t, 5, 3, 1, 0, 4.0, 3.2)
        _seg(t, 8, -3, -5, -3, 2.0)
        _arrow_head(t, -5, -3, -1, 0, 4.0, 3.2)
    return t


_VECTOR = ('ZOOM', 'PAN', 'ROLL', 'CAMERA', 'LOCK', 'SYNC')
# the arrow head / lens / shackle make the shape lopsided: nudge it so that
# the middle of the icon (not of the strokes) is the middle of the button
_NUDGE = {'ROLL': (0.6, 0.0), 'CAMERA': (0.5, 0.0), 'LOCK': (0.0, -0.5)}


def _draw_icon(mode, rect, color):
    tris = _icon_tris(mode)
    if not tris:
        return
    cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
    k = (rect[3] - rect[1]) / 36.0
    ox, oy = _NUDGE.get(mode, (0.0, 0.0))
    pos = [(cx + (x + ox) * k, cy + (y + oy) * k) for x, y in tris]
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch = batch_for_shader(shader, 'TRIS', {"pos": pos})
    shader.uniform_float("color", color)
    batch.draw(shader)


def draw(context, w, h, mx, my):
    qp = _quad_props(_area(context)) if is_quad(_area(context)) else None
    for it in _items(context, w, h):
        rv3d = it["q"]["rv3d"]
        if it["ball"]:
            cx, cy = it["ball"]
            drawing.circle(cx, cy, co.NAV_R, (0.08, 0.08, 0.09, 0.55))
            hover = co._ball_at(rv3d, cx, cy, mx, my)
            for z, bx, by, label, view, col, pos in co._balls(rv3d, cx, cy):
                if hover is not None and hover[4] == view:
                    drawing.circle(bx, by, co.BALL_R + 2, (1, 1, 1, 0.85))
                if pos:
                    drawing.circle(bx, by, co.BALL_R, (*col, 1.0))
                    drawing.text(bx, by - 5, label, size=11,
                                 color=(0.05, 0.05, 0.05, 1), align='CENTER')
                else:
                    drawing.circle(bx, by, co.BALL_R,
                                   (col[0] * 0.55, col[1] * 0.55,
                                    col[2] * 0.55, 0.9))
        for rect, mode, glyph in it["buttons"]:
            hot = co._in(rect, mx, my)
            if hot or _is_on(mode, rv3d, qp):  # at rest only the capsule shows
                drawing.rrect(rect[0], rect[1], rect[2], rect[3],
                              drawing.BEVEL, panels.COL_SIDE_ON)
            if mode in _VECTOR:
                _draw_icon(mode, rect, co.COL_TEXT)
            else:                       # letters: centred on the button
                label = glyph
                if mode == 'PERSP':
                    label = "P" if rv3d.is_perspective else "O"
                drawing.glyph((rect[0] + rect[2]) / 2,
                              (rect[1] + rect[3]) / 2, label, 18,
                              co.COL_TEXT)
            if hot:
                panels.hover_tip = _TIPS.get(mode, "")


def _run_on(region_ptr, module, name, **kw):
    """Run a view3d operator on one specific region (next cycle)."""
    def _go():
        try:
            for win in bpy.context.window_manager.windows:
                for area in win.screen.areas:
                    if area.type != 'VIEW_3D':
                        continue
                    for r in area.regions:
                        if (r.type == 'WINDOW'
                                and r.as_pointer() == region_ptr):
                            with bpy.context.temp_override(
                                    window=win, area=area, region=r):
                                getattr(getattr(bpy.ops, module), name)(
                                    'EXEC_DEFAULT', **kw)
                            return None
        except Exception as exc:
            print(f"NomadUI nav {module}.{name}: {exc!r}")
        return None
    try:
        bpy.app.timers.register(_go, first_interval=0.01)
    except RuntimeError:
        pass


def press(context, w, h, mx, my):
    """False | True | 'nav_orbit'."""
    area = _area(context)
    qp = _quad_props(area) if is_quad(area) else None
    for it in _items(context, w, h):
        q = it["q"]
        ptr = q["region"].as_pointer()
        for rect, mode, _g in it["buttons"]:
            if not co._in(rect, mx, my):
                continue
            if mode in ('ZOOM', 'PAN', 'ROLL'):
                co.nav_mode = None if co.nav_mode == mode else mode
            elif mode == 'CAMERA':
                _run_on(ptr, "view3d", "view_camera")
            elif mode == 'PERSP':
                _run_on(ptr, "view3d", "view_persportho")
            elif mode == 'LOCK' and qp is not None:
                qp.lock_rotation = not qp.lock_rotation
            elif mode == 'SYNC' and qp is not None:
                qp.show_sync_view = not qp.show_sync_view
            return True
        if it["ball"]:
            cx, cy = it["ball"]
            if (mx - cx) ** 2 + (my - cy) ** 2 <= co.NAV_R ** 2:
                ball = co._ball_at(q["rv3d"], cx, cy, mx, my)
                co._nav.update(last=(mx, my), moved=0.0,
                               ball=ball[4] if ball else None, target=ptr)
                return 'nav_orbit'
    return False


def viewport_press(context, area, mx, my):
    """Armed Zoom / Pan / Roll drag in the viewport (Quad View)."""
    if co.nav_mode in ('ZOOM', 'PAN', 'ROLL'):
        co._nav.update(last=(mx, my), moved=0.0, ball=None, target=None)
        return 'nav_' + co.nav_mode.lower()
    return False


def update(context, mx, my, kind):
    area = _area(context)
    regs = regions(area)
    if not regs:
        return
    ux, uy, uw, uh = style.union(regs)
    nav = co._nav
    tgt = nav.get("target")
    if tgt is None:                       # the quadrant under the finger
        ax, ay = ux + mx, uy + my
        r = next((r for r in regs
                  if r.x <= ax < r.x + r.width
                  and r.y <= ay < r.y + r.height), regs[-1])
        tgt = nav["target"] = r.as_pointer()
    region = next((r for r in regs if r.as_pointer() == tgt), None)
    if region is None or region.data is None:
        return
    rv3d = region.data
    ox, oy = region.x - ux, region.y - uy
    lx, ly = nav["last"]
    dx, dy = mx - lx, my - ly
    nav["last"] = (mx, my)
    nav["moved"] += abs(dx) + abs(dy)

    if kind == 'nav_orbit':
        if nav["moved"] < 4:                      # dead zone for taps
            return
        q = rv3d.view_rotation.copy()
        qz = Quaternion((0, 0, 1), -dx * 0.01)               # turntable
        qx = Quaternion(q @ Vector((1, 0, 0)), dy * 0.01)
        rv3d.view_rotation = qx @ qz @ q
    elif kind == 'nav_zoom':
        d = rv3d.view_distance * math.exp(-dy * 0.01)       # drag up = in
        rv3d.view_distance = max(0.001, min(100000.0, d))
    elif kind == 'nav_pan':
        loc = rv3d.view_location.copy()
        p0 = view3d_utils.region_2d_to_location_3d(
            region, rv3d, (lx - ox, ly - oy), loc)
        p1 = view3d_utils.region_2d_to_location_3d(
            region, rv3d, (mx - ox, my - oy), loc)
        rv3d.view_location = loc - (p1 - p0)
    elif kind == 'nav_roll':
        q = rv3d.view_rotation.copy()
        qr = Quaternion(q @ Vector((0, 0, -1)), dx * 0.01)
        rv3d.view_rotation = qr @ q


def release(context):
    nav = co._nav
    ball, tgt = nav.get("ball"), nav.get("target")
    if ball and nav.get("moved", 0) < 4 and tgt:
        _run_on(tgt, "view3d", "view_axis", type=ball)
    nav["ball"] = None
    nav["target"] = None