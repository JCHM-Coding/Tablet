# Navigation gizmo for the single view and for Quad View (one gizmo per
# quadrant, each acting on its own 3D region).
import math

import bpy
from bpy_extras import view3d_utils
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
            co._r(rect, co.COL_HOVER if hot
                  else co.COL_ON if _is_on(mode, rv3d, qp) else co.COL_BTN)
            label = glyph
            if mode == 'PERSP':
                label = "P" if rv3d.is_perspective else "O"
            drawing.text((rect[0] + rect[2]) / 2,
                         (rect[1] + rect[3]) / 2 - 8, label, size=18,
                         color=co.COL_TEXT, align='CENTER')
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