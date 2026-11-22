import bpy
from . import drawing
from . import style

# --- Estilo -------------------------------------------------------------
BAR_H = 46
BTN = 36
MODE_W = 70
PAD = 6
MARGIN = 8
COL_BAR = (0.06, 0.06, 0.07, 0.96)
COL_BTN = (0.16, 0.16, 0.18, 1.0)
COL_HOVER = (0.22, 0.48, 0.85, 1.0)
COL_GLYPH = (1, 1, 1, 1)
COL_TIP = (0.85, 0.87, 0.9, 1.0)

mouse = (0.0, 0.0)
tip_now = None
drag_state = None   # (kind, val0, mx0) mientras se arrastra

# --- Helpers ------------------------------------------------------------
def view3d_areas(context=None):
    ctx = context or bpy.context
    for screen in [w.screen for w in ctx.window_manager.windows]:
        for a in screen.areas:
            if a.type == 'VIEW_3D':
                yield a


def toggle_fullscreen(op, area=None):
    if area is None:
        area = next(view3d_areas(), None)
    if area is None:
        if op:
            op.report({'WARNING'}, "No hay viewport 3D")
        return
    try:
        with bpy.context.temp_override(area=area):
            bpy.ops.screen.screen_full_area('INVOKE_DEFAULT',
                                            use_hide_panels=True)
    except RuntimeError as exc:
        if op:
            op.report({'WARNING'}, f"Pantalla completa: {exc}")


# --- Timeline scrub ------------------------------------------------------
SCRUB_H = 51        # strip = SCRUB_H - 6 = 45 = 1.5 x CTRL_H
CTRL_H = 30
SCRUB_Y = 0
COL_PLAY = (0.22, 0.48, 0.85, 1.0)
COL_KEY = (0.95, 0.78, 0.25, 1.0)
COL_AUTO_ON = (0.85, 0.25, 0.25, 1.0)
COL_AUTO_OFF = (0.45, 0.45, 0.5, 1.0)


def _scrub_modes(context):
    mode = context.mode
    obj = context.active_object
    return (mode in {'OBJECT', 'POSE'} or
            (obj is not None and
             (mode in {'PAINT_GPENCIL', 'PAINT_GREASE_PENCIL'}
              or mode.startswith('DRAW'))))
              

def _frame_at_x(w, mx, sc):
    t = (mx - MARGIN) / max(1, (w - 2 * MARGIN))
    return int(round(sc.frame_start + t * (sc.frame_end
                                           - sc.frame_start)))


def _x_at_frame(w, f, sc):
    t = (f - sc.frame_start) / max(1, (sc.frame_end - sc.frame_start))
    return MARGIN + t * (w - 2 * MARGIN)


def _keyframes(obj):
    from . import timeline_ext
    return timeline_ext.object_frames(obj)


def _defer(fn):
    """Ejecutar un operador de pantalla fuera del modal (regla de oro)."""
    def _run():
        try:
            fn()
        except RuntimeError as exc:
            print(f"NomadUI scrub: {exc}")
        return None
    try:
        bpy.app.timers.register(_run, first_interval=0.01)
    except RuntimeError:
        pass


def _kf_paths():
    return ('location', 'rotation_euler', 'scale')


def _ins_keyframe(context):
    obj = context.active_object
    targets = []
    if context.mode == 'POSE' and context.selected_pose_bones:
        targets = list(context.selected_pose_bones)
    elif obj is not None:
        targets = [obj]
    for target in targets:
        for path in _kf_paths():
            try:
                target.keyframe_insert(path)
            except RuntimeError:
                pass


def _del_keyframe(context):
    obj = context.active_object
    targets = []
    if context.mode == 'POSE' and context.selected_pose_bones:
        targets = list(context.selected_pose_bones)
    elif obj is not None:
        targets = [obj]
    for target in targets:
        for path in _kf_paths():
            try:
                target.keyframe_delete(path)
            except RuntimeError:
                pass


_drag_moved = [0]       # px moved while dragging a numeric field


# --- Acciones -----------------------------------------------------------
def _file(op, area):
    import bpy

    def _run():
        try:
            bpy.ops.wm.call_menu('INVOKE_DEFAULT', name="TOPBAR_MT_file")
        except (RuntimeError, AttributeError) as exc:
            print(f"NomadUI file: {exc}")
        return None

    try:
        bpy.app.timers.register(_run, first_interval=0.01)
    except RuntimeError:
        pass


def _outliner(op, area):
    from . import outliner_gpu
    outliner_gpu.toggle()


def _modifiers(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_modifiers")


def _material(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_material")


def _render(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_render")


def _view(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_view")


def _mode_selector(op, area):
    from .sculpt_popups import open_menu_deferred
    open_menu_deferred("NOMAD_MT_modes")


def _tool_options(op, area):
    from .sculpt_panels import open_tool_props
    open_tool_props()


def _layers(op, area):
    import bpy

    def _run():
        C = bpy.context
        try:
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
            with C.temp_override(area=area, region=region):
                bpy.ops.wm.call_panel('INVOKE_DEFAULT', name="VIEW3D_PT_YPaint_main_ui")
        except (RuntimeError, AttributeError) as exc:
            print(f"NomadUI layers: {exc}")
        return None

    try:
        bpy.app.timers.register(_run, first_interval=0.01)
    except RuntimeError:
        pass


def _tool_picker(op, area):
    from .brush_shelf import open_popup
    open_popup("NOMAD_PT_brushes")


def _settings(op, area):
    space = area.spaces.active
    space.show_region_ui = not space.show_region_ui
    area.tag_redraw()


def _timeline(op, area):
    sc = bpy.context.scene
    sc.nomad_scrub_visible = not sc.nomad_scrub_visible


def _exit(op, area):
    bpy.context.scene.nomad_ui_active = False
    toggle_fullscreen(op, area)


# --- Nuevos botones --------------------------------------------------------
def _constraints(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_constraints")


def _add_menu(op, area):
    from .sculpt_popups import open_menu_deferred
    open_menu_deferred("VIEW3D_MT_add")


def _object_menu(op, area):
    from .sculpt_popups import open_menu_deferred
    open_menu_deferred("VIEW3D_MT_object")


def _options(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_options")

def _operators(op, area):
    from .sculpt_popups import open_menu_deferred
    # a menu closes when an item is activated: the next press reaches the
    # viewport, where the armed operator starts (see edit_ops.py)
    open_menu_deferred("NOMAD_MT_edit_operators")


def _uv_menu(op, area):
    from .mesh_panels import UV_MENU
    from .sculpt_popups import open_menu_deferred
    menu = UV_MENU.get(bpy.context.mode)
    if menu:
        open_menu_deferred(menu)
        
        
def _pose_menu(op, area):
    from .sculpt_popups import open_menu_deferred
    open_menu_deferred("VIEW3D_MT_pose")


def _pose_data(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_pose_data")


def _pose_bone(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_pose_bone")
    

def _gp_layers(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_gp_layers")


def _gp_options(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_gp_options")
    

def _gp_edit_ops(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_gp_edit_ops")


def _curve_ops(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_curve_ops")


def _curve_data(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_curve_data")
    
    
def _armature_edit(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_armature_edit")


def _gp_mf(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_gp_mf")
    
    
def _obj_data(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_object_data")


def _assets_popup(op, area):
    from . import asset_gpu
    asset_gpu.toggle()
    

RIGHT_ASSETS = ("❏", "Assets", _assets_popup)


def _poselib_popup(op, area):
    from . import asset_gpu
    asset_gpu.toggle()


RIGHT_POSELIB = ("☺", "Pose Library", _poselib_popup)


def _edit_menu(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_edit_menu")


def _options_c(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_options_c")


def _tex_obj(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_tp_object")


def _tex_options(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_tp_options")
    
    
def _vp_attr(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_vp_attributes")


def _vp_ops(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_vp_operators")


def _wp_groups(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_wp_groups")


def _wp_ops(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_wp_operators")

# --- Definición de la barra ----------------------------------------------
LEFT = [
    ("☰", "File", _file),
    ("≣", "Outliner", _outliner),
    ("⊞", "Modifiers", _modifiers),
    ("⛓", "Constraints / Shape Keys", _constraints),
    ("▶", "Render", _render),
    ("◫", "View", _view),
]

RIGHT_MATERIAL = ("◈", "Material", _material)
RIGHT_TOOL = ("⚒", "Tool (opciones)", _tool_options)
RIGHT_ADD = ("✚", "Add", _add_menu)
RIGHT_OBJECT = ("❒", "Object", _object_menu)
RIGHT_OPTIONS = ("⋯", "Options", _options)
RIGHT_OPERATORS = ("☷", "Operators", _operators)
RIGHT_UV = ("▥", "UV", _uv_menu)
RIGHT_POSE = ("♙", "Pose", _pose_menu)
RIGHT_DATA = ("⊟", "Data (bone collections, motion paths)", _pose_data)
RIGHT_BONE = ("⊢", "Bone", _pose_bone)
RIGHT_GP_LAYER = ("⧈", "Layer", _gp_layers)
RIGHT_GP_OPTIONS = ("⋯", "Options (Draw)", _gp_options)
RIGHT_GP_OPS = ("☷", "Operators (Grease Pencil, Point, Stroke)",
                _gp_edit_ops)
RIGHT_CURVE_OPS = ("☷", "Operators (Curve / Surface, Control Points, "
                   "Segments)", _curve_ops)
RIGHT_CURVE_DATA = ("⊟", "Data (shape, texture space, geometry)",
                    _curve_data)
RIGHT_ARMATURE = ("♘", "Armature (operators, options)", _armature_edit)
RIGHT_GP_MF = ("⋯", "Options (multiframe)", _gp_mf)
RIGHT_OBJ_DATA = ("⊟", "Data", _obj_data)
RIGHT_EDIT_MENU = ("☷", "Menu (Metaball / Point Cloud / Lattice / Text)",
                   _edit_menu)
RIGHT_OPTIONS_C = ("⋯", "Options (orientation, pivot, snapping, falloff)",
                   _options_c)

OBJ_DATA_TYPES = {'META', 'POINTCLOUD', 'LATTICE', 'FONT', 'VOLUME',
                  'EMPTY', 'LIGHT', 'LIGHT_PROBE', 'CAMERA', 'SPEAKER'}
EDIT_C_MODES = {'EDIT_METABALL', 'EDIT_POINTCLOUD', 'EDIT_LATTICE',
                'EDIT_TEXT'}
RIGHT_TEXOBJ = ("▩", "Texture (object): slots + masking", _tex_obj)
RIGHT_TEXOPT = ("⋮", "Texture Paint options (bleed, dither, external editor)",
                _tex_options)
RIGHT_VP_ATTR = ("▦", "Attributes (color attributes, automasking)", _vp_attr)
RIGHT_VP_OPS = ("☷", "Operators (Paint menu)", _vp_ops)
RIGHT_WP_GROUPS = ("⌗", "Vertex groups", _wp_groups)
RIGHT_WP_OPS = ("☷", "Operators (Weights, Select, Options)", _wp_ops)
RIGHT_LAYERS = ("▤", "Layers (Ucupaint)", _layers)
RIGHT_BRUSHES = ("▣", "Brushes", _tool_picker)
RIGHT_SETTINGS = ("⚙", "Ajustes (panel N)", _settings)
RIGHT_EXIT = ("✕", "Salir del modo tablet", _exit)

LAYER_MODES = {'SCULPT', 'PAINT_VERTEX', 'PAINT_TEXTURE'}
BRUSH_MODES = LAYER_MODES | {'PAINT_WEIGHT'}

MODE_GLYPHS = {
    'OBJECT': '▣',
    'EDIT_MESH': '✎', 'EDIT_ARMATURE': '✎', 'EDIT_CURVE': '✎',
    'EDIT_SURFACE': '✎', 'EDIT_TEXT': '✎', 'EDIT_METABALL': '✎',
    'EDIT_LATTICE': '✎', 'EDIT_CURVES': '✎', 'EDIT_GPENCIL': '✎',
    'POSE': '♙',
    'SCULPT': '✒', 'SCULPT_CURVES': '✒', 'PAINT_GPENCIL': '✒',
    'PAINT_VERTEX': '◉',
    'PAINT_WEIGHT': '◐',
    'PAINT_TEXTURE': '▤',
    'PAINT_GREASE_PENCIL': '✒',
    'EDIT_GREASE_PENCIL': '✎',
    'VERTEX_GREASE_PENCIL': '◉',
    'SCULPT_GREASE_PENCIL': '✒',
    'WEIGHT_GREASE_PENCIL': '◐',
    'EDIT_POINTCLOUD': '✎',
}


def _right_buttons_raw(context):
    mode = context.mode
    obj = context.active_object
    otype = obj.type if obj is not None else ""

    if mode == 'SCULPT':
        return [RIGHT_TOOL, RIGHT_LAYERS, RIGHT_BRUSHES]
    if mode == 'PAINT_TEXTURE':
        return [RIGHT_TOOL, RIGHT_LAYERS, RIGHT_BRUSHES, RIGHT_TEXOBJ,
                RIGHT_TEXOPT]
    if mode == 'PAINT_VERTEX':
        return [RIGHT_TOOL, RIGHT_LAYERS, RIGHT_BRUSHES, RIGHT_VP_OPS,
                RIGHT_VP_ATTR]
    if mode == 'PAINT_WEIGHT':
        return [RIGHT_TOOL, RIGHT_BRUSHES, RIGHT_WP_OPS]
    if mode == 'PAINT_GREASE_PENCIL':
        return [RIGHT_TOOL, RIGHT_GP_LAYER, RIGHT_BRUSHES, RIGHT_GP_OPTIONS]
    if mode in {'VERTEX_GREASE_PENCIL', 'SCULPT_GREASE_PENCIL',
                'WEIGHT_GREASE_PENCIL'}:
        return [RIGHT_TOOL, RIGHT_GP_LAYER, RIGHT_BRUSHES, RIGHT_GP_MF]
    if mode == 'EDIT_GREASE_PENCIL':
        return [RIGHT_TOOL, RIGHT_GP_LAYER, RIGHT_GP_OPS]
    if mode in {'EDIT_CURVE', 'EDIT_SURFACE'}:
        return [RIGHT_TOOL, RIGHT_CURVE_OPS, RIGHT_CURVE_DATA, RIGHT_OPTIONS]
    if mode == 'EDIT_ARMATURE':
        return [RIGHT_TOOL, RIGHT_ARMATURE, RIGHT_OPTIONS]
    if mode in EDIT_C_MODES:
        return [RIGHT_TOOL, RIGHT_EDIT_MENU, RIGHT_OBJ_DATA, RIGHT_OPTIONS_C]
    if mode == 'EDIT_MESH':
        return [RIGHT_TOOL, RIGHT_OPERATORS, RIGHT_UV, RIGHT_OPTIONS]
    if mode == 'POSE':
        return [RIGHT_TOOL, RIGHT_POSE, RIGHT_POSELIB, RIGHT_DATA,
                RIGHT_BONE, RIGHT_OPTIONS]

    btns = [RIGHT_TOOL]
    if otype in {'GREASEPENCIL', 'GPENCIL'}:
        btns.append(RIGHT_GP_LAYER)
    btns += [RIGHT_ADD, RIGHT_OBJECT, RIGHT_ASSETS]
    if otype in {'CURVE', 'SURFACE'}:
        btns.append(RIGHT_CURVE_DATA)
    if otype == 'ARMATURE':
        btns += [RIGHT_DATA, RIGHT_BONE]
    if otype in OBJ_DATA_TYPES:
        btns.append(RIGHT_OBJ_DATA)
    btns.append(RIGHT_OPTIONS)
    return btns


def _right_buttons(context):
    """Settings (N panel) and Exit moved out; Pose Library only when its
    add-on is enabled."""
    from . import requirements
    out = [b for b in _right_buttons_raw(context)
           if b not in (RIGHT_SETTINGS, RIGHT_EXIT)]
    if not requirements.enabled("pose_library"):
        out = [b for b in out if b is not RIGHT_POSELIB]
    if _supports_materials(context):       # only for objects with materials
        at = len(out)
        if out and out[-1] in (RIGHT_OPTIONS, RIGHT_OPTIONS_C):
            at -= 1                        # Options stays the last one
        out.insert(at, RIGHT_MATERIAL)
    return out
            
            
def _supports_materials(context):
    objs = list(context.selected_objects)
    ao = context.active_object
    if ao is not None:
        objs.append(ao)
    return any(getattr(o.data, "materials", None) is not None for o in objs)


def _top_groups(width, context):
    y1, y2 = MARGIN, BAR_H - MARGIN
    left = list(LEFT)

    L, x = [], MARGIN + 10
    for g, tip, cb in left:
        L.append((x, y1, x + BTN, y2, tip, cb, g))
        x += BTN + PAD

    R, x = [], width - 26 - BTN       # keeps Blender's corner free
    for g, tip, cb in reversed(_right_buttons(context)):
        R.append((x, y1, x + BTN, y2, tip, cb, g))
        x -= BTN + PAD

    x = (width - MODE_W) / 2
    M = [(x, y1, x + MODE_W, y2, "Mode (tap to change)", _mode_selector,
          MODE_GLYPHS.get(context.mode, '●'))]
    return L, M, R


def build(width, context):
    L, M, R = _top_groups(width, context)
    return L + R + M


# When the three pills (left tools, mode, right tools) get closer than this
# they become one single row that scrolls horizontally by dragging it.
GAP_MIN = 28
DRAG_PX = 6
_bar = {"off": 0.0, "max": 0.0, "mx0": 0.0, "off0": 0.0, "moved": 0.0,
        "hit": None, "op": None, "area": None}


def _merge_needed(L, M, R):
    groups = [g for g in (L, M, R) if g]
    return any(min(b[0] for b in nxt) - max(b[2] for b in prev) < GAP_MIN
               for prev, nxt in zip(groups, groups[1:]))


def _merged(width, L, M, R):
    """One row: left tools, mode, right tools, shifted by the scroll."""
    items = (sorted(L, key=lambda b: b[0]) + list(M)
             + sorted(R, key=lambda b: b[0]))
    x_lo, x_hi = MARGIN + 10, width - 26      # keeps Blender's corner free
    content = sum(b[2] - b[0] for b in items) + PAD * (len(items) - 1)
    _bar["max"] = max(0.0, content - (x_hi - x_lo))
    _bar["off"] = max(0.0, min(_bar["off"], _bar["max"]))
    out, x = [], x_lo - _bar["off"]
    for x1, y1, x2, y2, tip, cb, glyph in items:
        out.append((x, y1, x + (x2 - x1), y2, tip, cb, glyph))
        x += (x2 - x1) + PAD
    if _bar["max"] > 0:                       # only what fits in the pill
        out = [b for b in out if b[0] >= x_lo - 1 and b[2] <= x_hi + 1]
    return out, x_lo - 8, x_hi + 8


def _layout(width, context):
    """([(buttons, pill_x1, pill_x2)], scrollable)."""
    L, M, R = _top_groups(width, context)
    if _merge_needed(L, M, R):
        g, xa, xb = _merged(width, L, M, R)
        return [(g, xa, xb)], _bar["max"] > 0
    _bar["off"] = _bar["max"] = 0.0
    return [(g, min(b[0] for b in g) - 8, max(b[2] for b in g) + 8)
            for g in (L, M, R) if g], False


def _bar_drag(mx):
    dx = _bar["mx0"] - mx
    _bar["moved"] = max(_bar["moved"], abs(dx))
    if _bar["moved"] > DRAG_PX:
        _bar["off"] = max(0.0, min(_bar["off0"] + dx, _bar["max"]))


def _bar_release():
    hit, op, area = _bar["hit"], _bar["op"], _bar["area"]
    tap = _bar["moved"] <= DRAG_PX
    _bar.update(hit=None, op=None, area=None, moved=0.0)
    if tap and hit is not None and op is not None:
        print(f"NomadUI: botón '{hit[4]}'")
        hit[5](op, area)


# --- Dibujo --------------------------------------------------------------
def draw():
    context = bpy.context
    if not context.area or context.area.type != 'VIEW_3D':
        return
    if not getattr(context.scene, "nomad_ui_active", False):
        return

    region = next(r for r in context.area.regions if r.type == 'WINDOW')
    w, h = style.region_size(region)
    mx, my = mouse

    drawing.begin_2d()
    hover_tip = None
    for group, xa, xb in _layout(w, context)[0]:
        style.pill(xa, h - (BAR_H - MARGIN) - 5, xb, h - MARGIN + 5,
                   style.COL_PILL_DARK)
        for x1, y1, x2, y2, tip, cb, glyph in group:
            by1, by2 = h - y2, h - y1
            inside = (x1 <= mx <= x2 and by1 - 5 <= my <= by2 + 5)
            if inside:
                drawing.rrect(x1 + 2, by1 + 1, x2 - 2, by2 - 1, 7,
                              COL_HOVER)
                hover_tip = tip
            cx = (x1 + x2) / 2 - (8 if cb is _mode_selector else 0)
            drawing.glyph(cx, (by1 + by2) / 2, glyph, 18, COL_GLYPH)
            if cb is _mode_selector:
                drawing.glyph(x2 - 14, (by1 + by2) / 2, "▾", 13, COL_GLYPH)

    globals()["tip_now"] = hover_tip      # drawn as a tooltip (viewport_ui)
    draw_scrub(w, h, context)
    drawing.end_2d()


# --- Interacción ---------------------------------------------------------
def handle_click(area, mx, my, op):
    context = bpy.context
    region = next(r for r in area.regions if r.type == 'WINDOW')
    w, h = style.region_size(region)

    if scrub_click(area, mx, my, op):
        return True

    global drag_state
    layout, scrollable = _layout(w, context)
    for group, xa, xb in layout:
        in_pill = xa <= mx <= xb and h - (BAR_H - MARGIN) - 5 <= my <= h
        if scrollable and in_pill:
            # drag the row to scroll it; a tap (no drag) is the click
            hit = next((b for b in group if b[0] <= mx <= b[2]
                        and h - b[3] - 5 <= my <= h - b[1] + 5), None)
            _bar.update(op=op, area=area, mx0=mx, off0=_bar["off"],
                        moved=0.0, hit=hit)
            drag_state = ('bar', 0, mx)
            return True
        for x1, y1, x2, y2, tip, cb, glyph in group:
            by1, by2 = h - y2 - 5, h - y1 + 5
            if x1 <= mx <= x2 and by1 <= my <= by2:
                print(f"NomadUI: botón '{tip}' @ ({mx:.0f}, {my:.0f})")
                cb(op, area)
                return True
        if in_pill:
            return True                 # on a group, between buttons
    return False                        # gaps pass through to the viewport


def scrub_h(context):
    """Strip height: normal, or expanded (channel list) when enabled."""
    from . import timeline_ext
    return SCRUB_H + timeline_ext.extra(context)


def timeline_height(context):
    """Pixels the timeline occupies at the bottom (0 when hidden)."""
    if (not _scrub_modes(context)
            or not getattr(context.scene, "nomad_scrub_visible", False)):
        return 0
    from . import timeline_ext
    return (SCRUB_Y + scrub_h(context) - 4 + CTRL_H
            + timeline_ext.rows_h(context))


def scrub_drag(area, mx, my):
    """MOUSEMOVE con el dedo puesto: actualizar el valor arrastrado."""
    global drag_state
    if drag_state is None:
        return
    kind, val0, mx0 = drag_state
    if kind == 'bar':
        _bar_drag(mx)
        area.tag_redraw()
        return
    sc = bpy.context.scene
    w = style.region_size(
        next(r for r in area.regions if r.type == 'WINDOW'))[0]

    if kind == 'tlx':
        from . import timeline_ext
        timeline_ext.update(bpy.context, w, mx, my)
        area.tag_redraw()
        return
    if kind == 'strip':
        sc.frame_set(_frame_at_x(w, mx, sc))
        area.tag_redraw()
        return

    _drag_moved[0] = max(_drag_moved[0], abs(mx - mx0))
    delta = int((mx - mx0) / 2)   # 2 pixeles por frame
    v = val0 + delta
    if kind == 'cur':
        sc.frame_set(v)
    elif kind == 'start':
        sc.frame_start = min(v, sc.frame_end - 1)
    elif kind == 'end':
        sc.frame_end = max(v, sc.frame_start + 1)
    area.tag_redraw()


def scrub_release():
    """Fin del drag. A tap on a numeric field opens the entry popup."""
    global drag_state
    st = drag_state
    drag_state = None
    if st is not None and st[0] == 'bar':
        _bar_release()
    elif st is not None and st[0] == 'tlx':
        from . import timeline_ext
        timeline_ext.release(bpy.context)
    elif (st is not None and st[0] in ('cur', 'start', 'end')
            and _drag_moved[0] < 4):
        from .sculpt_popups import open_panel_deferred
        open_panel_deferred("NOMAD_PT_frame_entry")
    _drag_moved[0] = 0


def _scrub_zones(w):
    """(x1, y1, x2, y2, kind) de la fila de controles."""
    zones = []
    from . import timeline_ext
    y1 = (SCRUB_Y + scrub_h(bpy.context) - 4    
          + timeline_ext.rows_h(bpy.context))
    y2 = y1 + CTRL_H

    # Izquierda: insertar / borrar / copiar-pegar / autokey / opciones / modo
    x = MARGIN
    for kind in ('ins', 'del', 'cp', 'autokey', 'opts'):
        zones.append((x, y1, x + 30, y2, kind))
        x += 32
    

    # Centro: transporte
    order = ('first', 'prevkey', 'play', 'nextkey', 'last')
    total = 5 * 30 + 4 * 2
    x = w / 2 - total / 2
    for kind in order:
        zones.append((x, y1, x + 30, y2, kind))
        x += 32

    # Derecha: campos numericos (current, start, end)
    x = w - MARGIN
    for kind in ('end', 'start', 'cur'):
        x -= 64
        zones.append((x, y1, x + 64, y2, kind))
    return zones


def scrub_click(area, mx, my, op):
    global drag_state
    context = bpy.context
    if not _scrub_modes(context):
        return False
    sc = context.scene
    if not getattr(sc, "nomad_scrub_visible", False):
        return False
    from . import timeline_ext
    w = style.region_size(
        next(r for r in area.regions if r.type == 'WINDOW'))[0]

    # 1) Fila de controles
    for x1, y1, x2, y2, kind in _scrub_zones(w):
        if not (x1 <= mx <= x2 and y1 <= my <= y2):
            continue
        if kind == 'ins':
            _ins_keyframe(context)
        elif kind == 'del':
            _del_keyframe(context)
        elif kind == 'cp':
            from .sculpt_popups import open_panel_deferred
            open_panel_deferred("NOMAD_PT_copy_paste")
        elif kind == 'opts':
            from .sculpt_popups import open_panel_deferred
            open_panel_deferred("NOMAD_PT_key_options")
        elif kind == 'mode':
            from .sculpt_popups import open_panel_deferred
            open_panel_deferred("NOMAD_PT_tl_mode")
        elif kind == 'autokey':
            ts = sc.tool_settings
            ts.use_keyframe_insert_auto = not ts.use_keyframe_insert_auto
        elif kind == 'play':
            _defer(lambda: bpy.ops.screen.animation_play())
        elif kind == 'prevkey':
            _defer(lambda: bpy.ops.screen.keyframe_jump(next=False))
        elif kind == 'nextkey':
            _defer(lambda: bpy.ops.screen.keyframe_jump(next=True))
        elif kind == 'first':
            _defer(lambda: bpy.ops.screen.frame_jump(end=False))
        elif kind == 'last':
            _defer(lambda: bpy.ops.screen.frame_jump(end=True))
        elif kind in ('cur', 'start', 'end'):
            if kind == 'cur':
                val0 = sc.frame_current
            elif kind == 'start':
                val0 = sc.frame_start
            else:
                val0 = sc.frame_end
            drag_state = (kind, val0, mx)
            _drag_moved[0] = 0
        area.tag_redraw()
        return True

    # 2) El cuerpo del timeline
    strip_top = SCRUB_Y
    strip_bot = (SCRUB_Y + scrub_h(context) - 6
                 + timeline_ext.rows_h(context))
    if not (strip_top <= my <= strip_bot):
        return False

    if timeline_ext.expanded(context):
        if timeline_ext.press(context, w, mx, my):
            drag_state = ('tlx', 0, mx)
            area.tag_redraw()
            return True
        return False

    f = _frame_at_x(w, mx, sc)
    for kf in _keyframes(context.active_object):
        if abs(_x_at_frame(w, kf, sc) - mx) < 8:
            f = kf
            break
    sc.frame_set(f)
    drag_state = ('strip', 0, mx)
    return True


def draw_scrub(w, h, context):
    """Timeline: full width at the very bottom. Strip below (or the channel
    list when expanded), button row (own background) on top."""
    sc = context.scene
    if timeline_height(context) == 0:
        return
    from . import timeline_ext
    mx, my = mouse
    H = scrub_h(context)

    ty1 = SCRUB_Y
    ty2 = SCRUB_Y + H - 6
    y1 = SCRUB_Y + H - 4 + timeline_ext.rows_h(context)
    y2 = y1 + CTRL_H
    drawing.rect(0, ty1, w, ty2, style.COL_TL_STRIP)
    drawing.rect(0, ty2, w, y2, style.COL_TL_CTRL)

    glyphs = {
        'ins': "＋", 'del': "－", 'cp': "❐",
        'first': "|◀", 'prevkey': "◆◀",
        'nextkey': "▶◆", 'last': "▶|", 'opts': "⋯",
    }
    playing = context.screen.is_animation_playing
    for x1, zy1, x2, zy2, kind in _scrub_zones(w):
        inside = x1 <= mx <= x2 and zy1 <= my <= zy2
        cy = (zy1 + zy2) / 2

        if kind in ('cur', 'start', 'end'):
            label = (f"f:{sc.frame_current}" if kind == 'cur'
                     else f"S:{sc.frame_start}" if kind == 'start'
                     else f"E:{sc.frame_end}")
            drawing.rrect(x1 + 1, zy1 + 3, x2 - 1, zy2 - 3, 6,
                          COL_HOVER if inside else style.COL_FIELD)
            drawing.text(x2 - 8, cy - 5, label, size=13, color=COL_TIP,
                         align='RIGHT')
            continue

        drawing.rrect(x1 + 2, zy1 + 3, x2 - 2, zy2 - 3, 6,
                      COL_HOVER if inside else style.COL_BTN_IDLE)
        if kind == 'play':
            drawing.glyph((x1 + x2) / 2, cy,
                          "❚❚" if playing else "▶", 15, COL_GLYPH)
        elif kind == 'autokey':
            drawing.glyph((x1 + x2) / 2, cy, "●", 16,
                          COL_AUTO_ON
                          if sc.tool_settings.use_keyframe_insert_auto
                          else COL_AUTO_OFF)
        else:
            drawing.glyph((x1 + x2) / 2, cy, glyphs[kind], 15, COL_GLYPH)

    if timeline_ext.expanded(context):
        timeline_ext.draw(context, w, mx, my)
        return

    # compact strip: keys, frame range and the current frame
    cy = (ty1 + ty2) / 2
    drawing.diamonds([(_x_at_frame(w, kf, sc), cy)
                      for kf in _keyframes(context.active_object)],
                     5, COL_KEY)
    drawing.text(MARGIN + 2, cy - 5, str(sc.frame_start), size=11,
                 color=COL_TIP)
    drawing.text(w - MARGIN - 2, cy - 5, str(sc.frame_end), size=11,
                 color=COL_TIP, align='RIGHT')

    px = _x_at_frame(w, sc.frame_current, sc)
    drawing.rect(px - 1, ty1, px + 1, ty2, COL_PLAY)           # line
    tag = str(sc.frame_current)
    tw = len(tag) * 7 + 12
    tx = max(tw / 2 + 2, min(w - tw / 2 - 2, px))
    drawing.rrect(tx - tw / 2, ty2 - 18, tx + tw / 2, ty2 - 2, 5, COL_PLAY)
    drawing.text(tx, ty2 - 15, tag, size=11, color=(1, 1, 1, 1),
                 align='CENTER')