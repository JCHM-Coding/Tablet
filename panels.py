import bpy
from . import drawing
from .top_bar import BAR_H
from .sculpt_popups import open_panel_deferred, defer_op

# --- Estilo -------------------------------------------------------------
BTN = 40            # antes 36 — ancho común de botones y sliders
PAD = 3            # between buttons of a capsule (was 8)
MARGIN = 8
TOP_GAP = 14
SLIDER_H = 110
SLIDER_GAP = 6      # between the two sliders (was 16)
SIDE_GAP = 5        # sliders -> first button below them (was 14)
LBL_H = 20          # franja del número dentro del recuadro
BOT_H = 46

TRACK_COL = (0.13, 0.13, 0.15, 1.0)
FILL_COL = (0.22, 0.48, 0.85, 1.0)
COL_BAR = (0.06, 0.06, 0.07, 0.96)
COL_BTN = (0.16, 0.16, 0.18, 1.0)
COL_HOVER = (0.22, 0.48, 0.85, 1.0)
# Buttons of the side bars and of the navigation gizmo, like those of the top
# bar: at rest NOTHING is painted, the capsule behind them is the only
# background (painting its color again on top made the buttons darker and
# less see-through than the capsule). Only hover / active paints, with a
# see-through blue. Drawn with drawing.rrect so that nothing else is affected.
COL_SIDE_ON = (0.22, 0.48, 0.85, 0.45)
COL_GLYPH = (1, 1, 1, 1)
COL_TIP = (0.85, 0.87, 0.9, 1.0)

mouse = (0.0, 0.0)
drag = None      # None | 'size' | 'strength'
hover_tip = None


# --- Brush helpers ------------------------------------------------------

_PAINT_ATTR = {'SCULPT': "sculpt", 'PAINT_GREASE_PENCIL': "gpencil_paint",
               'PAINT_TEXTURE': "image_paint", 'PAINT_VERTEX': "vertex_paint",
               'PAINT_WEIGHT': "weight_paint",
               'VERTEX_GREASE_PENCIL': "gpencil_vertex_paint",
               'SCULPT_GREASE_PENCIL': "gpencil_sculpt_paint",
               'WEIGHT_GREASE_PENCIL': "gpencil_weight_paint"}


def _brush(context):
    attr = _PAINT_ATTR.get(context.mode, "sculpt")
    try:
        return getattr(context.tool_settings, attr).brush
    except AttributeError:
        return None


def _gp_strength_owner(context):
    """Grease Pencil keeps its opacity in gpencil_settings.pen_strength."""
    b = _brush(context)
    if b is not None:
        gs = getattr(b, "gpencil_settings", None)
        if gs is not None and hasattr(gs, "pen_strength"):
            return gs, "pen_strength"
    return b, "strength"


def get_strength(context):
    if context.mode == 'PAINT_GREASE_PENCIL':
        owner, attr = _gp_strength_owner(context)
        try:
            return float(getattr(owner, attr)) if owner else 0.5
        except (AttributeError, RuntimeError, TypeError):
            return 0.5
    _, use_unified_strength = _unified_flags(context)
    ps = _unified(context)
    if use_unified_strength and ps is not None:
        try:
            return ps.strength
        except RuntimeError:
            pass
    b = _brush(context)
    try:
        return b.strength if b else 0.5
    except (AttributeError, RuntimeError):
        return 0.5


def set_strength(context, v):
    v = max(0.0, min(1.0, v))
    if context.mode == 'PAINT_GREASE_PENCIL':
        owner, attr = _gp_strength_owner(context)
        if owner is not None:
            try:
                setattr(owner, attr, v)
            except (AttributeError, RuntimeError, TypeError):
                pass
        return
    disable_unified(context)
    b = _brush(context)
    if b is not None:
        try:
            b.strength = v
        except RuntimeError:
            pass
    ps = _unified(context)
    if ps is not None:
        try:
            ps.strength = v
        except RuntimeError:
            pass

def _unified(context):
    attr = _PAINT_ATTR.get(context.mode)
    paint = getattr(context.tool_settings, attr, None) if attr else None
    for owner in (paint, context.tool_settings):
        ups = getattr(owner, "unified_paint_settings", None)
        if ups is not None:
            return ups
    return None


def _unified_flags(context):
    """Devuelve (use_unified_size, use_unified_strength) según dónde
    viva el toggle: en 5.3 está en el brush, antes en unified_paint_settings."""
    b = _brush(context)
    ps = _unified(context)
    if b is not None and hasattr(b, "use_unified_size"):
        try:
            return bool(b.use_unified_size), bool(b.use_unified_strength)
        except RuntimeError:
            pass
    if ps is not None:
        try:
            return bool(ps.use_unified_size), bool(ps.use_unified_strength)
        except RuntimeError:
            pass
    return False, False


def disable_unified(context):
    """Apaga unified size/strength donde sea que viva el toggle (5.3: brush)."""
    b = _brush(context)
    if b is not None and hasattr(b, "use_unified_size"):
        try:
            b.use_unified_size = False
            b.use_unified_strength = False
            return
        except RuntimeError:
            pass
    ps = _unified(context)
    if ps is not None:
        try:
            ps.use_unified_size = False
            ps.use_unified_strength = False
        except RuntimeError:
            pass


def get_size(context):
    use_unified_size, _ = _unified_flags(context)
    ps = _unified(context)
    if use_unified_size and ps is not None:
        try:
            return ps.size
        except RuntimeError:
            pass
    b = _brush(context)
    try:
        return b.size if b else 32
    except (AttributeError, RuntimeError):
        return 32


def set_size(context, v):
    v = max(1, min(1000, int(v)))
    disable_unified(context)          # el brush manda, siempre
    b = _brush(context)
    if b is not None:
        try:
            b.size = v
        except RuntimeError:
            pass
    ps = _unified(context)
    if ps is not None:
        try:
            ps.size = v
        except RuntimeError:
            pass



        
        
def _direction_glyph(context):
    """Glifo del botón Direction según el estado de la brocha activa."""
    b = _brush(context)
    try:
        if b is not None and b.direction == 'SUBTRACT':
            return "-"
    except (AttributeError, RuntimeError):
        pass
    return "+"


# --- Geometría ----------------------------------------------------------
def sliders(w, h):
    """Sliders apilados a la IZQUIERDA: Size arriba, Strength debajo.
    Mismo ancho y alineación que los botones."""
    x1 = MARGIN + 4
    x2 = x1 + BTN
    sy2 = h - BAR_H - TOP_GAP
    sy1 = sy2 - SLIDER_H
    ty2 = sy1 - SLIDER_GAP
    ty1 = ty2 - SLIDER_H
    return (x1, sy1, x2, sy2), (x1, ty1, x2, ty2)


def side_buttons(w, h):
    """Botones bajo los sliders, alineados con ellos."""
    (_sx1, _sy1, _sx2, _sy2), (_tx1, ty1, _tx2, _ty2) = sliders(w, h)
    x1 = MARGIN + 4
    x2 = x1 + BTN
    y = ty1 - SIDE_GAP
    out = []
    for g, tip, cb in SIDE:
        out.append((x1, y - BTN, x2, y, tip, cb, g))
        y -= BTN + PAD
    return out


# --- Acciones (modo sculpt) ---------------------------------------------
def _direction(op, area):
    b = _brush(bpy.context)
    if b is None:
        op.report({'WARNING'}, "Sin brush activo")
        return
    try:
        b.direction = 'ADD' if b.direction == 'SUBTRACT' else 'SUBTRACT'
    except AttributeError:
        op.report({'INFO'}, "Direction: placeholder para este brush")

def _mask(op, area):
    from .brush_shelf import open_popup
    open_popup("NOMAD_PT_mask")


def _facesets(op, area):
    from .brush_shelf import open_popup
    open_popup("NOMAD_PT_facesets")

def _texture(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_texture")

def _symmetry(op, area):    
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_symmetry")

def _dyntopo_remesh(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_dyntopo")

# (glifo, tooltip, callback)

def _brush_tool(op, area):
    from . import tool_sidebar as ts
    ids = [m.idname for m in ts._members(bpy.context, "brush")]
    if ids:
        ts.activate_any(ids)


_brush_tool.tool_key = "brush"

SIDE = [
    ("⇅", "Direction", _direction),
    ("✎", "Brush", _brush_tool),
    ("⊘", "Mask", _mask),
    ("▦", "Face Sets", _facesets),
    ("▨", "Textures", _texture),
    ("✳", "Symmetry", _symmetry),
    ("❖", "Dyntopo / Remesh", _dyntopo_remesh),
]


def _history(op, area):
    from .modal import defer_operator
    defer_operator("view3d.simple_undo_history",
                   "ed.undo_history",
                   "screen.redo_last")


def _adjust(op, area):
    from .modal import defer_operator
    defer_operator("screen.redo_last")


def _dfirst(*ops, ctx='EXEC_DEFAULT'):
    """Bottom-bar action: run the first operator that works, in the next
    cycle with a viewport override (never from inside the modal)."""
    def cb(op, area):
        def _run():
            try:
                from .sculpt_popups import _view3d_override
                win, a, r = _view3d_override()
                if a is None:
                    return None
                with bpy.context.temp_override(window=win, area=a,
                                               region=r):
                    for op_id in ops:
                        mod, name = op_id.split(".")
                        try:
                            getattr(getattr(bpy.ops, mod), name)(ctx)
                        except (RuntimeError, AttributeError):
                            continue
                        return None
                print(f"NomadUI bottom bar: none of {ops} worked")
            except Exception as exc:
                print(f"NomadUI bottom bar: {exc!r}")
            return None
        try:
            bpy.app.timers.register(_run, first_interval=0.01)
        except RuntimeError:
            pass
    return cb


BOTTOM = [
    ("⌛", "History", _dfirst("ed.undo_history", ctx='INVOKE_DEFAULT')),
    ("⟲", "Undo", _dfirst("ed.undo")),
    ("⟳", "Redo", _dfirst("ed.redo")),
    ("⏎", "Repeat Last", _dfirst("screen.repeat_last")),
    ("⚙", "Adjust Last Operation",
     _dfirst("screen.redo_last", ctx='INVOKE_DEFAULT')),
    ("⌕", "Search", _dfirst("wm.search_menu", ctx='INVOKE_DEFAULT')),
]


def _safe(op, *op_ids):
    """Prueba operadores en orden; el primero que exista y funcione, gana."""
    last_err = None
    for op_id in op_ids:
        mod, name = op_id.split(".")
        try:
            ns = getattr(bpy.ops, mod)
        except AttributeError:
            last_err = f"{op_id}: módulo inexistente"
            continue
        fn = getattr(ns, name, None)
        if fn is None:
            last_err = f"{op_id}: no existe en esta versión"
            continue
        try:
            fn('INVOKE_DEFAULT')
            return
        # bpy.ops devuelve un "call" fantasma para operadores inexistentes:
        # el AttributeError salta AL INVOCAR, no al hacer getattr.
        except (RuntimeError, AttributeError) as exc:
            last_err = f"{op_id}: {exc}"
    op.report({'WARNING'}, last_err or "Operador no disponible")
    
    
# --- Quick favorites (Object mode, left bar) ----------------------------
def _select_toggle(op, area):
    defer_op("object", "select_all", action='TOGGLE')


def _duplicate(op, area):
    open_panel_deferred("NOMAD_PT_obj_duplicate")


def _join(op, area):
    open_panel_deferred("NOMAD_PT_obj_join")


def _showhide(op, area):
    open_panel_deferred("NOMAD_PT_obj_hide")


OBJ_SIDE = []   # Object-mode bars are drawn by tool_sidebar.py


def obj_buttons(w, h):
    x1 = MARGIN + 4
    x2 = x1 + BTN
    y = h - BAR_H - TOP_GAP
    out = []
    for g, tip, cb in OBJ_SIDE:
        out.append((x1, y - BTN, x2, y, tip, cb, g))
        y -= BTN + PAD
    return out

# --- Draw mode (Grease Pencil), left bar ----------------------------------



def _tool_cb(key, fallback_op=None):
    """Activate the first tool of a tool_sidebar group; if none can be
    activated, run `fallback_op` once."""
    def cb(op, area):
        from . import tool_sidebar as ts
        ids = [m.idname for m in ts._members(bpy.context, key)]
        if ids or fallback_op:
            ts.activate_any(ids, fallback_op)
    cb.tool_key = key
    return cb


def _brush_cb(kind):
    """Erase / Fill are brush assets, not tools."""
    def cb(op, area):
        from . import brush_shelf
        brush_shelf.activate_kind(kind)
    cb.brush_kind = kind
    return cb


def _popup_cb(panel, key=None):
    def cb(op, area):
        open_panel_deferred(panel)
    cb.tool_key = key
    return cb


GP_SIDE = [
    ("▭", "Select Lasso", _tool_cb("gp_select")),
    ("⌖", "Cursor", _tool_cb("cursor")),
    ("✎", "Draw", _tool_cb("gp_draw")),
    ("⌫", "Erase", _brush_cb("ERASE")),
    ("◼", "Fill", _brush_cb("FILL")),
    ("△", "Predefined strokes",
     _popup_cb("NOMAD_PT_tools_gp_shapes", "gp_shapes")),
    ("✂", "Trim", _tool_cb("gp_trim", "grease_pencil.stroke_trim")),
    ("⊙", "Eyedropper", _tool_cb("gp_eyedrop")),
    ("⇌", "Interpolate", _tool_cb("gp_interp")),
]





def _clone_cb():
    def cb(op, area):
        open_panel_deferred("NOMAD_PT_tp_clone")
    cb.brush_kind = "CLONE"
    return cb


TP_SIDE = [
    ("✎", "Brush", _brush_cb("DRAW")),
    ("◔", "Blur", _brush_cb("SOFTEN")),
    ("≈", "Smear", _brush_cb("SMEAR")),
    ("⎘", "Clone", _clone_cb()),
    ("◼", "Fill", _brush_cb("FILL")),
    ("⊘", "Mask", _brush_cb("MASK")),
    ("✐", "Annotate", _popup_cb("NOMAD_PT_tools_annot", "annot")),
    ("▨", "Texture (brush)", _texture),
    ("✳", "Symmetry", _symmetry),
]


# --- Weight (third slider) ------------------------------------------------
def _w_unified(context):
    for o in (_brush(context), _unified(context)):
        if o is not None and hasattr(o, "use_unified_weight"):
            try:
                return bool(o.use_unified_weight)
            except (AttributeError, RuntimeError):
                pass
    return False


def get_weight(context):
    b, ps = _brush(context), _unified(context)
    try:
        if _w_unified(context) and ps is not None and hasattr(ps, "weight"):
            return float(ps.weight)
        if b is not None and hasattr(b, "weight"):
            return float(b.weight)
        if ps is not None and hasattr(ps, "weight"):
            return float(ps.weight)
    except (AttributeError, RuntimeError, TypeError):
        pass
    return 1.0


def set_weight(context, v):
    v = max(0.0, min(1.0, v))
    owners = [o for o in (_brush(context), _unified(context))
              if o is not None]
    for o in owners:
        if hasattr(o, "use_unified_weight"):
            try:
                o.use_unified_weight = False       # the brush rules
            except (AttributeError, RuntimeError, TypeError):
                pass
    for o in owners:
        if hasattr(o, "weight"):
            try:
                o.weight = v
            except (AttributeError, RuntimeError, TypeError):
                pass


# --- Left bar per mode ------------------------------------------------------
SLIDERS = {
    'SCULPT': ('size', 'strength'),
    'PAINT_GREASE_PENCIL': ('size', 'strength'),
    'PAINT_TEXTURE': ('size', 'strength'),
    'PAINT_VERTEX': ('size', 'strength'),
    'PAINT_WEIGHT': ('size', 'strength', 'weight'),
    'VERTEX_GREASE_PENCIL': ('size', 'strength'),
    'SCULPT_GREASE_PENCIL': ('size', 'strength'),
    'WEIGHT_GREASE_PENCIL': ('size', 'strength', 'weight'),
}


def sliders(w, h, n=2):
    """n stacked sliders on the left; list of rects."""
    x1 = MARGIN + 4
    x2 = x1 + BTN
    sh = SLIDER_H if n <= 2 else 84
    y2 = h - BAR_H - TOP_GAP
    rects = []
    for _i in range(n):
        y1 = y2 - sh
        rects.append((x1, y1, x2, y2))
        y2 = y1 - SLIDER_GAP
    return rects


def _slider_specs(context, w, h):
    kinds = SLIDERS.get(context.mode, ())
    out = []
    for kind, rect in zip(kinds, sliders(w, h, len(kinds))):
        if kind == 'size':
            v = get_size(context)
            out.append((kind, rect, v, 1000, f"{v}"))
        elif kind == 'strength':
            v = get_strength(context)
            out.append((kind, rect, v, 1.0, f"{int(v * 100)}%"))
        else:
            v = get_weight(context)
            out.append((kind, rect, v, 1.0, f"{v:.2f}"))
    return out


def _mask_active(context):
    obj = context.active_object
    me = getattr(obj, "data", None)
    return bool(obj is not None and obj.type == 'MESH' and (
        getattr(me, "use_paint_mask", False)
        or getattr(me, "use_paint_mask_vertex", False)))


_select_cb = _popup_cb("NOMAD_PT_paint_select")
_select_cb.visible = _mask_active

VP_SIDE = [
    ("◩", "Selection mode (paint / face / vertex)",
     _popup_cb("NOMAD_PT_paint_mode")),
    ("✎", "Brush", _brush_cb("DRAW")),
    ("◔", "Blur", _brush_cb("BLUR")),
    ("◍", "Average", _brush_cb("AVERAGE")),
    ("≈", "Smear", _brush_cb("SMEAR")),
    ("✳", "Symmetry", _symmetry),
    ("✐", "Annotate", _popup_cb("NOMAD_PT_tools_annot", "annot")),
    ("▭", "Select (vertices / faces)", _select_cb),
]

WP_SIDE = [
    ("⊙", "Sample weight / vertex group", _popup_cb("NOMAD_PT_wp_sample")),
    ("◩", "Selection mode (paint / face / vertex)",
     _popup_cb("NOMAD_PT_paint_mode")),
    ("▭", "Select (vertices / faces)", _select_cb),
    ("✳", "Symmetry", _symmetry),
    ("✐", "Annotate", _popup_cb("NOMAD_PT_tools_annot", "annot")),
]


def _click_cb(action):
    """Arm a click action (tap, then tap the surface) from the left bar."""
    def cb(op, area):
        defer_op("nomad", "click_action", 'INVOKE_DEFAULT', action=action)
    return cb


GPV_SIDE = [
    ("✎", "Brush", _brush_cb("DRAW")),
    ("◔", "Blur", _brush_cb("BLUR")),
    ("◍", "Average", _brush_cb("AVERAGE")),
    ("≈", "Smear", _brush_cb("SMEAR")),
    ("◼", "Replace", _brush_cb("REPLACE")),
    ("✐", "Annotate", _popup_cb("NOMAD_PT_tools_annot", "annot")),
]
GPS_SIDE = [
    ("◈", "Select mode (point / stroke / segment)",
     _popup_cb("NOMAD_PT_gp_selmode_sculpt")),
    ("✐", "Annotate", _popup_cb("NOMAD_PT_tools_annot", "annot")),
]
GPW_SIDE = [
    ("✎", "Brush", _brush_cb("DRAW")),
    ("◔", "Blur", _brush_cb("BLUR")),
    ("◍", "Average", _brush_cb("AVERAGE")),
    ("≈", "Smear", _brush_cb("SMEAR")),
    ("⊙", "Sample weight (tap, then tap the surface)",
     _click_cb('GP_WEIGHT_SAMPLE')),
    ("✐", "Annotate", _popup_cb("NOMAD_PT_tools_annot", "annot")),
]


def _left_items(mode):
    return {'SCULPT': SIDE, 'PAINT_GREASE_PENCIL': GP_SIDE,
            'PAINT_TEXTURE': TP_SIDE, 'PAINT_VERTEX': VP_SIDE,
            'PAINT_WEIGHT': WP_SIDE,
            'VERTEX_GREASE_PENCIL': GPV_SIDE,
            'SCULPT_GREASE_PENCIL': GPS_SIDE,
            'WEIGHT_GREASE_PENCIL': GPW_SIDE,
            'OBJECT': OBJ_SIDE}.get(mode, [])


def _side_for(mode, w, h):
    """Left-bar buttons, stacked under the sliders of the mode."""
    context = bpy.context
    n = len(SLIDERS.get(mode, ()))
    x1 = MARGIN + 4
    x2 = x1 + BTN
    rects = sliders(w, h, n) if n else []
    y = (rects[-1][1] - SIDE_GAP) if rects else (h - BAR_H - TOP_GAP)
    out = []
    for g, tip, cb in _left_items(mode):
        vis = getattr(cb, "visible", None)
        if vis is not None and not vis(context):
            continue
        out.append((x1, y - BTN, x2, y, tip, cb, g))
        y -= BTN + PAD
    return out


# --- Dibujo -------------------------------------------------------------



def _bottom_base(context):
    from . import top_bar, fav_bar
    th = top_bar.timeline_height(context)
    return ((th + 8) if th else MARGIN) + fav_bar.bottom_offset(context)


def bottom_buttons(w, h):
    context = bpy.context
    mode = context.mode
    repeat_ok = mode == 'OBJECT' or mode.startswith('EDIT')
    items = [b for b in BOTTOM
             if not (b[1] == "Repeat Last" and not repeat_ok)]
    n = len(items)
    x = (w - (n * BTN + (n - 1) * PAD)) / 2
    y1 = _bottom_base(context) + 4
    y2 = y1 + BOT_H - 8
    out = []
    for g, tip, cb in items:
        out.append((x, y1, x + BTN, y2, tip, cb, g))
        x += BTN + PAD
    return out


def draw_bottom(context, w, h, mx, my):
    global hover_tip
    from . import style
    btns = bottom_buttons(w, h)
    if not btns:
        return
    style.pill(btns[0][0] - 8, btns[0][1] - 4, btns[-1][2] + 8,
               btns[0][3] + 4, style.COL_PILL_DARK)
    for x1, y1, x2, y2, tip, cb, glyph in btns:
        inside = x1 <= mx <= x2 and y1 <= my <= y2
        if inside:
            drawing.rrect(x1 + 2, y1 + 1, x2 - 2, y2 - 1, 7, COL_HOVER)
            hover_tip = tip
        drawing.glyph((x1 + x2) / 2, (y1 + y2) / 2, glyph, 18, COL_GLYPH)


# --- Interacción ---------------------------------------------------------






_SLIDER_TAG = {'size': "SZ", 'strength': "STR", 'weight': "WT"}


_SLIDER_TAG = {'size': "SZ", 'strength': "STR", 'weight': "WT"}


_SLIDER_TAG = {'size': "SZ", 'strength': "STR", 'weight': "WT"}


_SLIDER_TAG = {'size': "SZ", 'strength': "STR", 'weight': "WT"}


def draw_side(context, w, h, mx, my):
    global hover_tip
    mode = context.mode
    from . import tool_sidebar as ts
    from . import brush_shelf

    for kind, rect, value, max_v, label in _slider_specs(context, w, h):
        x1, y1, x2, y2 = rect
        track_h = (y2 - LBL_H) - y1
        t = max(0.0, min(1.0, value / max_v))
        drawing.rrect(x1 + 3, y1 + 3, x2 - 3, y2 - 3, 8, TRACK_COL)
        drawing.rrect_bottom(x1 + 7, y1 + 7, x2 - 7,
                             y1 + 7 + (track_h - 11) * t, 6, FILL_COL)
        drawing.text((x1 + x2) / 2, y2 - LBL_H + 4, label,
                     size=11, color=COL_GLYPH, align='CENTER')   # value
        drawing.text((x1 + x2) / 2, y1 + 5, _SLIDER_TAG.get(kind, ""),
                     size=10, color=COL_GLYPH, align='CENTER')   # SZ / STR

    buttons = _side_for(mode, w, h)
    active = ts._active_idname(context)
    for x1, y1, x2, y2, tip, cb, glyph in buttons:
        if cb is _direction:
            glyph = _direction_glyph(context)
        key = getattr(cb, "tool_key", None)
        kind = getattr(cb, "brush_kind", None)
        probe = getattr(cb, "is_on", None)
        gate = getattr(cb, "is_enabled", None)
        enabled = True if gate is None else bool(gate(context))
        if probe is not None:
            on = bool(probe(context)) and enabled
        elif kind:
            on = brush_shelf.is_kind(context, kind)
        else:
            on = bool(key) and bool(active) and any(
                m.idname == active for m in ts._members(context, key))
        inside = x1 <= mx <= x2 and y1 <= my <= y2
        hot = inside and enabled
        if hot or on:
            drawing.rrect(x1 + 2, y1 + 2, x2 - 2, y2 - 2, drawing.BEVEL,
                          COL_SIDE_ON)
        drawing.text(x1 + BTN / 2, (y1 + y2) / 2 - 9, glyph,
                     size=18, color=COL_GLYPH if enabled else COL_TIP,
                     align='CENTER')
        if inside:
            hover_tip = tip if enabled else tip + " (needs a stencil texture)"

    ts.draw(context, w, h, mx, my)



def drag_release():
    global drag
    kind = drag
    drag = None
    if not kind:
        return
    if kind.startswith('as_'):
        from . import asset_gpu
        asset_gpu.release(bpy.context)
    elif kind.startswith('ol_'):
        from . import outliner_gpu
        outliner_gpu.release(bpy.context)
    elif kind.startswith('fb_'):
        from . import fav_bar
        fav_bar.release(bpy.context)
    elif kind.startswith('nav_'):
        from . import color_overlay
        color_overlay.release(bpy.context)


def _update_from_drag(context, w, h, mx, my):
    from . import style
    s = style.ui_scale()
    if drag and drag.startswith('as_'):
        from . import asset_gpu
        asset_gpu.update(context, w, h, mx, my, drag)
        return
    if drag and drag.startswith('ol_'):
        from . import outliner_gpu
        outliner_gpu.update(context, w, h, mx, my, drag)
        return
    if drag and drag.startswith('fb_'):
        from . import fav_bar
        fav_bar.update(context, w, h, mx, my, drag)
        return
    if drag and drag.startswith(('nav_', 'st_')):
        from . import color_overlay          # these work in raw pixels
        color_overlay.update(context, w, h, mx * s, my * s, drag)
        return
    if drag and drag.startswith('color_'):
        from . import color_overlay
        color_overlay.update(context, w, h, mx, my, drag)
        return
    kinds = SLIDERS.get(context.mode, ())
    rect = dict(zip(kinds, sliders(w, h, len(kinds)))).get(drag)
    if rect is None:
        return
    x1, y1, x2, y2 = rect
    track_y2 = y2 - LBL_H
    t = max(0.0, min(1.0, (my - y1) / (track_y2 - y1)))
    if drag == 'size':
        set_size(context, 1 + 999 * (t * t))
    elif drag == 'strength':
        set_strength(context, t)
    elif drag == 'weight':
        set_weight(context, t)


def drag_update(area, mx, my):
    if drag is None:
        return False
    from . import style
    context = bpy.context
    region = next(r for r in area.regions if r.type == 'WINDOW')
    w, h = style.region_size(region)
    if drag.startswith('as_'):
        from . import asset_gpu
        s = style.ui_scale()
        asset_gpu._st["raw"] = (mx * s, my * s)   # region px for the drop
    _update_from_drag(context, w, h, mx, my)
    from .modal import tag_all_view3d_redraw
    tag_all_view3d_redraw(context)
    return True


def handle_press(area, mx, my, op):
    """Click on our UI. (mx, my) are in scaled UI units."""
    global drag
    from . import style
    context = bpy.context
    region = next(r for r in area.regions if r.type == 'WINDOW')
    s = style.ui_scale()
    w, h = style.region_size(region)

    from . import (color_overlay, tool_sidebar, outliner_gpu, fav_bar,
                   asset_gpu)

    for x1, y1, x2, y2, tip, cb, glyph in bottom_buttons(w, h):
        if x1 <= mx <= x2 and y1 <= my <= y2:
            print(f"NomadUI bottom: '{tip}'")
            cb(op, area)
            return True

    for module in (asset_gpu, outliner_gpu, fav_bar, color_overlay):
        hit = module.press(context, w, h, mx, my)
        if hit:
            if isinstance(hit, str):
                drag = hit
                if module is color_overlay and hit.startswith(('nav_', 'st_')):
                    color_overlay._nav["last"] = (mx * s, my * s)
                    color_overlay.update(context, w, h, mx * s, my * s, hit)
                else:
                    module.update(context, w, h, mx, my, hit)
                return 'drag'
            return True
    from . import style as _style
    if _style.press_bars(context, w, h, mx, my):
        return True

    if tool_sidebar.press(context, w, h, mx, my):
        return True

    for kind, rect, _v, _m, _l in _slider_specs(context, w, h):
        x1, y1, x2, y2 = rect
        if x1 <= mx <= x2 and y1 <= my <= y2:
            drag = kind
            _update_from_drag(context, w, h, mx, my)
            return 'drag'

    for x1, y1, x2, y2, tip, cb, glyph in _side_for(context.mode, w, h):
        if x1 <= mx <= x2 and y1 <= my <= y2:
            print(f"NomadUI side: '{tip}'")
            cb(op, area)
            return True

    # Click on the viewport itself: needs raw region pixels
    from . import nav_gizmo
    if nav_gizmo.is_quad(area):
        # sample / clone / stencil need one real region: not in Quad View yet
        hit = nav_gizmo.viewport_press(context, area, mx * s, my * s)
    else:
        hit = color_overlay.viewport_press(context, area, mx * s, my * s)
    if hit:
        if isinstance(hit, str):
            drag = hit
            color_overlay._nav["last"] = (mx * s, my * s)
            color_overlay.update(context, w, h, mx * s, my * s, hit)
            return 'drag'
        return True
    return False