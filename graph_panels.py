# Popups and actions of the Graph Editor rows (F-Curve, View, Select,
# Marker, Channel, Key, Modifiers, Filters, Pivot, Snap, Proportional).
# Every action works on fresh F-curves and re-reads the keyframes; nothing
# from Blender is kept between calls.
import bpy

from . import graph_ext as gx
from . import timeline_ext as tl

_PROPS = ("nomad_gr_active", "nomad_gr_norm", "nomad_gr_hidden",
          "nomad_gr_errors", "nomad_gr_handles", "nomad_gr_pivot",
          "nomad_gr_cursor", "nomad_gr_snap", "nomad_gr_snap_mode",
          "nomad_gr_snap_v", "nomad_gr_snap_vstep", "nomad_gr_prop",
          "nomad_gr_prop_size", "nomad_gr_falloff")


def _changed(self, context):
    gx._flush()


def _norm_changed(self, context):
    gx._flush()
    gx.request('fit')


def active_curve(context):
    s = context.scene.nomad_gr_active
    try:
        o, path, idx = s.rsplit("|", 2)
        fk = (o, path, int(idx))
    except ValueError:
        return None, None
    fc = tl.fresh_map(context, False).get(fk)
    return (fk, fc) if fc is not None else (None, None)


# ----------------------------------------------------------------------
# Actions
# ----------------------------------------------------------------------

def _pairs(context):
    return [(fc, kp) for _k, fc in gx._vis_fresh(context)
            for kp in fc.keyframe_points]


def _sel_pairs(context):
    return [(fc, kp) for fc, kp in _pairs(context)
            if kp.select_control_point]


def _set_sel(kp, on):
    kp.select_control_point = on
    kp.select_left_handle = on
    kp.select_right_handle = on


def _upd(pairs):
    seen = {}
    for fc, _kp in pairs:
        seen[fc.as_pointer()] = fc
    for fc in seen.values():
        fc.update()


def _shift(kp, dx, dy):
    kp.co = (kp.co[0] + dx, kp.co[1] + dy)
    kp.handle_left = (kp.handle_left[0] + dx, kp.handle_left[1] + dy)
    kp.handle_right = (kp.handle_right[0] + dx, kp.handle_right[1] + dy)


def a_sel_all(c, v):
    for fc, kp in _pairs(c):
        _set_sel(kp, True)


def a_sel_none(c, v):
    for fc, kp in _pairs(c):
        _set_sel(kp, False)


def a_sel_invert(c, v):
    for fc, kp in _pairs(c):
        _set_sel(kp, not kp.select_control_point)


def a_sel_col(c, v):
    f = c.scene.frame_current
    for fc, kp in _pairs(c):
        _set_sel(kp, abs(kp.co[0] - f) < 0.5)


def a_sel_before(c, v):
    f = c.scene.frame_current
    for fc, kp in _pairs(c):
        _set_sel(kp, kp.co[0] < f - 0.001)


def a_sel_after(c, v):
    f = c.scene.frame_current
    for fc, kp in _pairs(c):
        _set_sel(kp, kp.co[0] > f + 0.001)


def a_sel_linked(c, v):
    pairs = _pairs(c)
    curves = {fc.as_pointer() for fc, kp in pairs if kp.select_control_point}
    for fc, kp in pairs:
        if fc.as_pointer() in curves:
            _set_sel(kp, True)


# --- markers ---------------------------------------------------------

def a_mk_add(c, v):
    sc = c.scene
    f = sc.frame_current
    if not any(m.frame == f for m in sc.timeline_markers):
        sc.timeline_markers.new(f"F_{f:02d}", frame=f)


def a_mk_del(c, v):
    sc = c.scene
    ms = [m for m in sc.timeline_markers if m.select]
    if not ms:
        ms = [m for m in sc.timeline_markers if m.frame == sc.frame_current]
    for m in ms:
        sc.timeline_markers.remove(m)


def a_mk_next(c, v):
    sc = c.scene
    after = sorted(m.frame for m in sc.timeline_markers
                   if m.frame > sc.frame_current)
    if after:
        sc.frame_set(after[0])


def a_mk_prev(c, v):
    sc = c.scene
    before = sorted((m.frame for m in sc.timeline_markers
                     if m.frame < sc.frame_current), reverse=True)
    if before:
        sc.frame_set(before[0])


# --- channels --------------------------------------------------------

def _all_curves(c):
    return tl.fresh_items(c, False)


def a_ch_hide_sel(c, v):
    for _k, fc in _all_curves(c):
        if fc.select:
            fc.hide = True


def a_ch_hide_unsel(c, v):
    for _k, fc in _all_curves(c):
        if not fc.select:
            fc.hide = True


def a_ch_reveal(c, v):
    for _k, fc in _all_curves(c):
        fc.hide = False


def a_ch_mute_sel(c, v):
    for _k, fc in _all_curves(c):
        if fc.select:
            fc.mute = True


def a_ch_unmute(c, v):
    for _k, fc in _all_curves(c):
        fc.mute = False


def a_ch_lock_sel(c, v):
    for _k, fc in _all_curves(c):
        if fc.select:
            fc.lock = True


def a_ch_unlock(c, v):
    for _k, fc in _all_curves(c):
        fc.lock = False


def a_ch_sel_all(c, v):
    for _k, fc in _all_curves(c):
        fc.select = True


def a_ch_sel_none(c, v):
    for _k, fc in _all_curves(c):
        fc.select = False


def a_ch_expand(c, v):
    tl._fold.clear()


def a_ch_collapse(c, v):
    tl._fold.update(r["key"] for r in tl._rows(c)
                    if r["kind"] in tl._FOLDABLE)


# --- keys ------------------------------------------------------------

def a_k_insert(c, v):
    f = c.scene.frame_current
    items = gx._vis_fresh(c)
    chosen = [p for p in items if p[1].select] or items
    for _k, fc in chosen:
        try:
            fc.keyframe_points.insert(f, fc.evaluate(f))
        except (RuntimeError, TypeError):
            continue
        fc.update()


def a_k_delete(c, v):
    for _k, fc in gx._vis_fresh(c):
        kps = fc.keyframe_points
        idx = [i for i, kp in enumerate(kps) if kp.select_control_point]
        for i in reversed(idx):
            kps.remove(kps[i])
        if idx:
            fc.update()


def a_k_snap_cur(c, v):
    f = c.scene.frame_current
    pairs = _sel_pairs(c)
    for fc, kp in pairs:
        _shift(kp, f - kp.co[0], 0.0)
    _upd(pairs)


def a_k_snap_frame(c, v):
    pairs = _sel_pairs(c)
    for fc, kp in pairs:
        _shift(kp, round(kp.co[0]) - kp.co[0], 0.0)
    _upd(pairs)


def a_k_snap_val(c, v):
    cur = c.scene.nomad_gr_cursor
    pairs = _sel_pairs(c)
    for fc, kp in pairs:
        _shift(kp, 0.0, cur - kp.co[1])
    _upd(pairs)


def a_k_mirror_t(c, v):
    f = c.scene.frame_current
    pairs = _sel_pairs(c)
    for fc, kp in pairs:
        x, y = kp.co
        hl, hr = tuple(kp.handle_left), tuple(kp.handle_right)
        kp.co = (2 * f - x, y)
        kp.handle_left = (2 * f - hr[0], hr[1])
        kp.handle_right = (2 * f - hl[0], hl[1])
    _upd(pairs)


def a_k_mirror_v(c, v):
    cur = c.scene.nomad_gr_cursor
    pairs = _sel_pairs(c)
    for fc, kp in pairs:
        x, y = kp.co
        hl, hr = tuple(kp.handle_left), tuple(kp.handle_right)
        kp.co = (x, 2 * cur - y)
        kp.handle_left = (hl[0], 2 * cur - hl[1])
        kp.handle_right = (hr[0], 2 * cur - hr[1])
    _upd(pairs)


def a_k_handle(c, v):
    pairs = [(fc, kp) for fc, kp in _pairs(c)
             if (kp.select_control_point or kp.select_left_handle
                 or kp.select_right_handle)]
    for fc, kp in pairs:
        kp.handle_left_type = v
        kp.handle_right_type = v
    _upd(pairs)


def _target_curves(c):
    items = gx._vis_fresh(c)
    return [fc for _k, fc in ([p for p in items if p[1].select] or items)]


def a_k_ext(c, v):
    for fc in _target_curves(c):
        fc.extrapolation = v


def a_k_cycle(c, v):
    for fc in _target_curves(c):
        if not any(m.type == 'CYCLES' for m in fc.modifiers):
            fc.modifiers.new('CYCLES')
        fc.update()


def a_k_uncycle(c, v):
    for fc in _target_curves(c):
        for m in [m for m in fc.modifiers if m.type == 'CYCLES']:
            fc.modifiers.remove(m)
        fc.update()


# --- modifiers, cursor, view ----------------------------------------

def a_mod_add(c, v):
    fk, fc = active_curve(c)
    if fc is not None:
        fc.modifiers.new(v)
        fc.update()


def a_mod_del(c, v):
    fk, fc = active_curve(c)
    if fc is not None and 0 <= int(v) < len(fc.modifiers):
        fc.modifiers.remove(fc.modifiers[int(v)])
        fc.update()


def a_cur_sel(c, v):
    ys = [kp.co[1] for fc, kp in _sel_pairs(c)]
    if ys:
        c.scene.nomad_gr_cursor = sum(ys) / len(ys)


def a_view(c, v):
    gx.request(v)


_ACTIONS = {
    "SEL_ALL": a_sel_all, "SEL_NONE": a_sel_none,
    "SEL_INVERT": a_sel_invert, "SEL_COL": a_sel_col,
    "SEL_BEFORE": a_sel_before, "SEL_AFTER": a_sel_after,
    "SEL_LINKED": a_sel_linked,
    "MK_ADD": a_mk_add, "MK_DEL": a_mk_del, "MK_NEXT": a_mk_next,
    "MK_PREV": a_mk_prev,
    "CH_HIDE_SEL": a_ch_hide_sel, "CH_HIDE_UNSEL": a_ch_hide_unsel,
    "CH_REVEAL": a_ch_reveal, "CH_MUTE_SEL": a_ch_mute_sel,
    "CH_UNMUTE": a_ch_unmute, "CH_LOCK_SEL": a_ch_lock_sel,
    "CH_UNLOCK": a_ch_unlock, "CH_SEL_ALL": a_ch_sel_all,
    "CH_SEL_NONE": a_ch_sel_none, "CH_EXPAND": a_ch_expand,
    "CH_COLLAPSE": a_ch_collapse,
    "K_INSERT": a_k_insert, "K_DELETE": a_k_delete,
    "K_SNAP_CUR": a_k_snap_cur, "K_SNAP_FRAME": a_k_snap_frame,
    "K_SNAP_VAL": a_k_snap_val, "K_MIRROR_T": a_k_mirror_t,
    "K_MIRROR_V": a_k_mirror_v, "K_HANDLE": a_k_handle, "K_EXT": a_k_ext,
    "K_CYCLE": a_k_cycle, "K_UNCYCLE": a_k_uncycle,
    "MOD_ADD": a_mod_add, "MOD_DEL": a_mod_del, "CUR_SEL": a_cur_sel,
    "VIEW": a_view,
}

_DESC = {
    "SEL_ALL": "Select every keyframe", "SEL_NONE": "Deselect every keyframe",
    "SEL_INVERT": "Invert the keyframe selection",
    "SEL_COL": "Select the keys on the current frame",
    "SEL_BEFORE": "Select the keys before the current frame",
    "SEL_AFTER": "Select the keys after the current frame",
    "SEL_LINKED": "Select every key of the curves that have a selection",
    "K_SNAP_CUR": "Move the selected keys to the current frame",
    "K_SNAP_FRAME": "Round the selected keys to whole frames",
    "K_SNAP_VAL": "Set the value of the selected keys to the cursor value",
    "K_MIRROR_T": "Mirror the selected keys in time around the current frame",
    "K_MIRROR_V": "Mirror the selected keys in value around the cursor",
    "CUR_SEL": "Put the value cursor at the mean of the selected keys",
}


class NOMAD_OT_gr_action(bpy.types.Operator):
    bl_idname = "nomad.gr_action"
    bl_label = "Graph Editor"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.StringProperty()
    value: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, properties):
        return _DESC.get(properties.action, "Graph Editor action")

    def execute(self, context):
        fn = _ACTIONS.get(self.action)
        if fn is None:
            return {'CANCELLED'}
        try:
            fn(context, self.value)
        except Exception as exc:
            self.report({'WARNING'}, f"{self.action}: {exc}")
            return {'CANCELLED'}
        gx._flush()
        return {'FINISHED'}


# ----------------------------------------------------------------------
# Popups
# ----------------------------------------------------------------------

def _grid(layout, items, cols=2):
    g = layout.grid_flow(row_major=True, columns=cols, even_columns=True,
                         align=True)
    g.scale_y = 1.3
    for text, action, value in items:
        op = g.operator("nomad.gr_action", text=text)
        op.action, op.value = action, value
    return g


def _panel(idname, title, units, draw_fn):
    def draw(self, context):
        self.layout.ui_units_x = units
        draw_fn(self.layout, context)
    return type(idname, (bpy.types.Panel,), {
        "bl_label": title, "bl_idname": idname,
        "bl_space_type": 'VIEW_3D', "bl_region_type": 'WINDOW',
        "draw": draw})


def _d_afc(l, context):
    fk, fc = active_curve(context)
    if fc is None:
        l.label(text="No active F-Curve (tap a channel or a key)",
                icon='INFO')
        return
    l.label(text=f"{fk[0]}   {tl._label(fc)}", icon='FCURVE')
    box = l.box()
    row = box.row(align=True)
    row.prop(fc, "mute", toggle=True, icon='HIDE_ON')
    row.prop(fc, "hide", toggle=True, icon='RESTRICT_VIEW_ON')
    row.prop(fc, "lock", toggle=True, icon='LOCKED')
    box.prop(fc, "color_mode", text="")
    if fc.color_mode == 'CUSTOM':
        box.prop(fc, "color", text="")
    box.prop(fc, "auto_smoothing", text="")
    box.prop(fc, "extrapolation", text="")
    kp = next((k for k in fc.keyframe_points if k.select_control_point),
              None)
    box = l.box()
    box.label(text="Active Keyframe")
    if kp is None:
        box.label(text="Tap a point in the graph", icon='INFO')
        return
    col = box.column(align=True)
    col.prop(kp, "co", index=0, text="Frame")
    col.prop(kp, "co", index=1, text="Value")
    box.prop(kp, "interpolation", text="")
    box.prop(kp, "easing", text="")
    row = box.row(align=True)
    row.prop(kp, "handle_left_type", text="")
    row.prop(kp, "handle_right_type", text="")
    col = box.column(align=True)
    col.prop(kp, "handle_left", index=0, text="Left Frame")
    col.prop(kp, "handle_left", index=1, text="Left Value")
    col.prop(kp, "handle_right", index=0, text="Right Frame")
    col.prop(kp, "handle_right", index=1, text="Right Value")


def _d_view(l, context):
    sc = context.scene
    col = l.column(align=True)
    col.scale_y = 1.3
    col.prop(sc, "nomad_tl_f_sel", text="Only Show Selected", toggle=True)
    col.prop(sc, "nomad_gr_hidden", text="Show Hidden", toggle=True)
    col.prop(sc, "nomad_gr_errors", text="Only Show Errors", toggle=True)
    col.prop(sc, "nomad_gr_handles", text="Show Handles", toggle=True)
    l.separator()
    _grid(l, [("Frame All", "VIEW", "fit"),
              ("Frame Selected", "VIEW", "fit_sel"),
              ("Frame Current", "VIEW", "cur")], 1)


def _d_select(l, context):
    _grid(l, [("All", "SEL_ALL", ""), ("None", "SEL_NONE", ""),
              ("Invert", "SEL_INVERT", ""), ("Linked", "SEL_LINKED", ""),
              ("On Current Frame", "SEL_COL", ""),
              ("Before Frame", "SEL_BEFORE", ""),
              ("After Frame", "SEL_AFTER", "")], 2)


def _d_marker(l, context):
    sc = context.scene
    _grid(l, [("Add", "MK_ADD", ""), ("Delete", "MK_DEL", ""),
              ("Previous", "MK_PREV", ""), ("Next", "MK_NEXT", "")], 2)
    ms = list(sc.timeline_markers)
    if ms:
        l.separator()
        for m in ms[:10]:
            row = l.row(align=True)
            row.prop(m, "name", text="")
            row.prop(m, "frame", text="")
            row.prop(m, "select", text="",
                     icon='RESTRICT_SELECT_OFF' if m.select
                     else 'RESTRICT_SELECT_ON')


def _d_channel(l, context):
    _grid(l, [("Hide Selected", "CH_HIDE_SEL", ""),
              ("Hide Unselected", "CH_HIDE_UNSEL", ""),
              ("Reveal All", "CH_REVEAL", ""),
              ("Mute Selected", "CH_MUTE_SEL", ""),
              ("Unmute All", "CH_UNMUTE", ""),
              ("Lock Selected", "CH_LOCK_SEL", ""),
              ("Unlock All", "CH_UNLOCK", ""),
              ("Select All", "CH_SEL_ALL", ""),
              ("Select None", "CH_SEL_NONE", ""),
              ("Expand All", "CH_EXPAND", ""),
              ("Collapse All", "CH_COLLAPSE", "")], 2)


def _d_key(l, context):
    from .anim_options import INTERP, EASING
    _grid(l, [("Insert Key", "K_INSERT", ""),
              ("Delete Keys", "K_DELETE", ""),
              ("To Current Frame", "K_SNAP_CUR", ""),
              ("To Whole Frames", "K_SNAP_FRAME", ""),
              ("Values to Cursor", "K_SNAP_VAL", ""),
              ("Cursor to Selection", "CUR_SEL", ""),
              ("Mirror in Time", "K_MIRROR_T", ""),
              ("Mirror in Value", "K_MIRROR_V", "")], 2)
    l.label(text="Interpolation")
    g = l.grid_flow(row_major=True, columns=3, even_columns=True, align=True)
    g.scale_y = 1.2
    for ident, name in INTERP:
        op = g.operator("nomad.key_set", text=name)
        op.prop, op.value = 'interpolation', ident
    l.label(text="Easing")
    g = l.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
    g.scale_y = 1.2
    for ident, name in EASING:
        op = g.operator("nomad.key_set", text=name)
        op.prop, op.value = 'easing', ident
    l.label(text="Handle type")
    _grid(l, [(lbl, "K_HANDLE", t) for t, lbl, _tip in gx.HANDLE_TYPES], 3)
    l.label(text="Extrapolation")
    _grid(l, [("Constant", "K_EXT", "CONSTANT"),
              ("Linear", "K_EXT", "LINEAR"),
              ("Make Cyclic", "K_CYCLE", ""),
              ("Clear Cyclic", "K_UNCYCLE", "")], 2)


_MOD_TYPES = (("Generator", 'GENERATOR'), ("Built-in Function", 'FNGENERATOR'),
              ("Envelope", 'ENVELOPE'), ("Cycles", 'CYCLES'),
              ("Noise", 'NOISE'), ("Limits", 'LIMITS'),
              ("Stepped", 'STEPPED'))
_MOD_SKIP = {"type", "name", "show_expanded", "mute", "active", "is_valid",
             "is_override_data", "rna_type"}


def _d_mods(l, context):
    from .pose_panels import _props_where
    fk, fc = active_curve(context)
    if fc is None:
        l.label(text="No active F-Curve (tap a channel or a key)",
                icon='INFO')
        return
    l.label(text=f"{fk[0]}   {tl._label(fc)}", icon='FCURVE')
    _grid(l, [(name, "MOD_ADD", t) for name, t in _MOD_TYPES], 2)
    for i, m in enumerate(fc.modifiers):
        box = l.box()
        row = box.row(align=True)
        row.prop(m, "show_expanded", text="", emboss=False,
                 icon='TRIA_DOWN' if m.show_expanded else 'TRIA_RIGHT')
        row.label(text=m.type.replace("_", " ").title())
        row.prop(m, "mute", text="",
                 icon='HIDE_ON' if m.mute else 'HIDE_OFF')
        op = row.operator("nomad.gr_action", text="", icon='X')
        op.action, op.value = "MOD_DEL", str(i)
        if m.show_expanded:
            _props_where(box, m, lambda n: n not in _MOD_SKIP)


def _d_filters(l, context):
    sc = context.scene
    col = l.column(align=True)
    col.scale_y = 1.3
    col.prop(sc, "nomad_tl_f_sel", toggle=True)
    col.prop(sc, "nomad_tl_f_bones", toggle=True)
    col.prop(sc, "nomad_gr_hidden", text="Show Hidden", toggle=True)
    col.prop(sc, "nomad_gr_errors", text="Only Show Errors", toggle=True)
    l.label(text="Channel types")
    row = l.row(align=True)
    row.scale_y = 1.3
    row.prop(sc, "nomad_tl_f_loc", text="Location", toggle=True)
    row.prop(sc, "nomad_tl_f_rot", text="Rotation", toggle=True)
    row.prop(sc, "nomad_tl_f_scale", text="Scale", toggle=True)
    l.separator()
    l.prop(sc, "nomad_tl_search_on", text="Search", toggle=True,
           icon='VIEWZOOM')
    if sc.nomad_tl_search_on:
        l.prop(sc, "nomad_tl_search", text="")


def _d_pivot(l, context):
    sc = context.scene
    col = l.column()
    col.scale_y = 1.4
    col.prop(sc, "nomad_gr_pivot", expand=True)
    l.separator()
    l.prop(sc, "nomad_gr_cursor", text="Cursor value")
    _grid(l, [("Cursor to Selection", "CUR_SEL", "")], 1)


def _d_snap(l, context):
    sc = context.scene
    row = l.row()
    row.scale_y = 1.4
    row.prop(sc, "nomad_gr_snap", text="Snap", toggle=True, icon='SNAP_ON')
    l.prop(sc, "nomad_gr_snap_mode", text="")
    l.separator()
    row = l.row()
    row.scale_y = 1.3
    row.prop(sc, "nomad_gr_snap_v", text="Snap Values", toggle=True)
    sub = l.row()
    sub.active = sc.nomad_gr_snap_v
    sub.prop(sc, "nomad_gr_snap_vstep", text="Step")


def _d_prop(l, context):
    sc = context.scene
    row = l.row()
    row.scale_y = 1.4
    row.prop(sc, "nomad_gr_prop", text="Proportional Editing", toggle=True,
             icon='PROP_ON')
    sub = l.column()
    sub.active = sc.nomad_gr_prop
    sub.prop(sc, "nomad_gr_prop_size", text="Radius (frames)")
    sub.prop(sc, "nomad_gr_falloff", text="")


NOMAD_PT_gr_afc = _panel("NOMAD_PT_gr_afc", "Active F-Curve", 16, _d_afc)
NOMAD_PT_gr_view = _panel("NOMAD_PT_gr_view", "View", 11, _d_view)
NOMAD_PT_gr_select = _panel("NOMAD_PT_gr_select", "Select", 11, _d_select)
NOMAD_PT_gr_marker = _panel("NOMAD_PT_gr_marker", "Marker", 14, _d_marker)
NOMAD_PT_gr_channel = _panel("NOMAD_PT_gr_channel", "Channel", 11,
                             _d_channel)
NOMAD_PT_gr_key = _panel("NOMAD_PT_gr_key", "Key", 15, _d_key)
NOMAD_PT_gr_mods = _panel("NOMAD_PT_gr_mods", "F-Curve Modifiers", 15,
                          _d_mods)
NOMAD_PT_gr_filters = _panel("NOMAD_PT_gr_filters", "Filters", 11,
                             _d_filters)
NOMAD_PT_gr_pivot = _panel("NOMAD_PT_gr_pivot", "Pivot Point", 11, _d_pivot)
NOMAD_PT_gr_snap = _panel("NOMAD_PT_gr_snap", "Snapping", 11, _d_snap)
NOMAD_PT_gr_prop = _panel("NOMAD_PT_gr_prop", "Proportional Editing", 11,
                          _d_prop)

CLASSES = (NOMAD_OT_gr_action, NOMAD_PT_gr_afc, NOMAD_PT_gr_view,
           NOMAD_PT_gr_select, NOMAD_PT_gr_marker, NOMAD_PT_gr_channel,
           NOMAD_PT_gr_key, NOMAD_PT_gr_mods, NOMAD_PT_gr_filters,
           NOMAD_PT_gr_pivot, NOMAD_PT_gr_snap, NOMAD_PT_gr_prop)


def register():
    S = bpy.types.Scene
    S.nomad_gr_active = bpy.props.StringProperty(
        default="", options={'SKIP_SAVE'})
    S.nomad_gr_norm = bpy.props.BoolProperty(
        name="Normalize", default=False, update=_norm_changed)
    S.nomad_gr_hidden = bpy.props.BoolProperty(
        name="Show Hidden", default=False, update=_changed)
    S.nomad_gr_errors = bpy.props.BoolProperty(
        name="Only Show Errors", default=False, update=_changed)
    S.nomad_gr_handles = bpy.props.BoolProperty(
        name="Show Handles", default=True, update=_changed)
    S.nomad_gr_pivot = bpy.props.EnumProperty(
        name="Pivot Point", default='BOUNDING_BOX_CENTER',
        items=[('BOUNDING_BOX_CENTER', "Bounding Box Center", ""),
               ('CURSOR', "2D Cursor", "Current frame and cursor value"),
               ('INDIVIDUAL_CENTERS', "Individual Centers", "")])
    S.nomad_gr_cursor = bpy.props.FloatProperty(
        name="Cursor Value", default=0.0)
    S.nomad_gr_snap = bpy.props.BoolProperty(name="Snap", default=True)
    S.nomad_gr_snap_mode = bpy.props.EnumProperty(
        name="Snap To", default='FRAME',
        items=[('FRAME', "Frames", ""), ('SECOND', "Seconds", ""),
               ('MARKER', "Nearest Marker", "")])
    S.nomad_gr_snap_v = bpy.props.BoolProperty(
        name="Snap Values", default=False)
    S.nomad_gr_snap_vstep = bpy.props.FloatProperty(
        name="Step", default=0.1, min=0.0001)
    S.nomad_gr_prop = bpy.props.BoolProperty(
        name="Proportional Editing", default=False)
    S.nomad_gr_prop_size = bpy.props.FloatProperty(
        name="Radius", default=10.0, min=0.5, max=500.0)
    S.nomad_gr_falloff = bpy.props.EnumProperty(
        name="Falloff", default='SMOOTH',
        items=[('SMOOTH', "Smooth", ""), ('SPHERE', "Sphere", ""),
               ('ROOT', "Root", ""), ('SHARP', "Sharp", ""),
               ('LINEAR', "Linear", ""), ('CONSTANT', "Constant", "")])
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    for name in _PROPS:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)