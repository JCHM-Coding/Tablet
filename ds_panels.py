"""Dope Sheet menus: mode, View, Key, Pivot, Snap, Proportional editing,
the Action / Slot browsers and the properties panel of each mode.

The panels are popups opened from the buttons of the Dope Sheet row (see
timeline_ext._DS_PANELS). Select / Marker / Channel / Filters are shared with
the Graph Editor (graph_panels)."""

import bpy

from . import timeline_ext as tl
from .graph_panels import _panel, _grid

DS_MODES = [
    ('DOPESHEET', "Dope Sheet", "Keyframes of objects and bones"),
    ('ACTION', "Action Editor", "Every channel of the active object's action"),
    ('SHAPEKEY', "Shape Key Editor", "Animation of the shape keys"),
    ('GPENCIL', "Grease Pencil", "Grease Pencil layers and frames"),
    ('MASK', "Mask (Movie Clip Editor)",
     "Masks belong to the Movie Clip Editor"),
    ('CACHE', "Cache File", "Animation of the cache files"),
]
_PROPS = ("nomad_ds_mode", "nomad_ds_snap", "nomad_ds_snap_mode",
          "nomad_ds_prop", "nomad_ds_prop_size", "nomad_ds_falloff",
          "nomad_ds_pivot", "nomad_ds_overlays", "nomad_ds_ov_range",
          "nomad_ds_ov_seconds", "nomad_ds_ov_markers")


def _changed(self, context):
    tl.drop_caches()


# ----------------------------------------------------------------------
# Operators
# ----------------------------------------------------------------------

class NOMAD_OT_ds_view(bpy.types.Operator):
    bl_idname = "nomad.ds_view"
    bl_label = "Dope Sheet View"
    bl_options = {'INTERNAL'}

    name: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, properties):
        return {"fit": "Show every keyframe",
                "fit_sel": "Show the selected keyframes",
                "cur": "Center the view on the current frame"
                }.get(properties.name, "Change the view")

    def execute(self, context):
        tl.request(self.name)
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


class NOMAD_OT_ds_slot_set(bpy.types.Operator):
    bl_idname = "nomad.ds_slot_set"
    bl_label = "Set Slot"
    bl_description = "Use this slot of the action"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        idb = tl._target_id(context)
        ad = getattr(idb, "animation_data", None)
        act = getattr(ad, "action", None)
        if act is None or not 0 <= self.index < len(act.slots):
            return {'CANCELLED'}
        try:
            ad.action_slot = act.slots[self.index]
        except (RuntimeError, TypeError, AttributeError) as exc:
            self.report({'WARNING'}, f"Could not set the slot: {exc}")
            return {'CANCELLED'}
        tl.drop_caches()
        return {'FINISHED'}


class NOMAD_OT_ds_anim_create(bpy.types.Operator):
    bl_idname = "nomad.ds_anim_create"
    bl_label = "Create Animation Data"
    bl_description = "Add animation data so that an action can be assigned"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        idb = tl._target_id(context)
        if idb is None:
            return {'CANCELLED'}
        try:
            idb.animation_data_create()
        except (RuntimeError, AttributeError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


# ----------------------------------------------------------------------
# Menus
# ----------------------------------------------------------------------

def _d_mode(l, context):
    col = l.column()
    col.scale_y = 1.3
    col.prop(context.scene, "nomad_ds_mode", expand=True)


def _d_view(l, context):
    sc = context.scene
    g = l.grid_flow(row_major=True, columns=1, even_columns=True, align=True)
    g.scale_y = 1.3
    for text, name in (("Frame All", "fit"), ("Frame Selected", "fit_sel"),
                       ("Frame Current", "cur")):
        g.operator("nomad.ds_view", text=text).name = name
    l.separator()
    l.label(text="Overlays")
    l.prop(sc, "nomad_ds_overlays", text="Overlays")
    col = l.column()
    col.active = sc.nomad_ds_overlays
    col.prop(sc, "nomad_ds_ov_range", text="Frame Range")
    col.prop(sc, "nomad_ds_ov_seconds", text="Show Seconds")
    col.prop(sc, "nomad_ds_ov_markers", text="Markers")


def _d_key(l, context):
    from .anim_options import INTERP, EASING
    from . import graph_ext as gx
    _grid(l, [("Insert Key", "K_INSERT", ""),
              ("Delete Keys", "K_DELETE", ""),
              ("To Current Frame", "K_SNAP_CUR", ""),
              ("To Whole Frames", "K_SNAP_FRAME", ""),
              ("Mirror in Time", "K_MIRROR_T", "")], 2)
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


def _d_pivot(l, context):
    col = l.column()
    col.scale_y = 1.4
    col.prop(context.scene, "nomad_ds_pivot", expand=True)


def _d_snap(l, context):
    sc = context.scene
    row = l.row()
    row.scale_y = 1.4
    row.prop(sc, "nomad_ds_snap", text="Snap", toggle=True, icon='SNAP_ON')
    l.prop(sc, "nomad_ds_snap_mode", text="")


def _d_prop(l, context):
    sc = context.scene
    row = l.row()
    row.scale_y = 1.4
    row.prop(sc, "nomad_ds_prop", text="Proportional Editing", toggle=True,
             icon='PROP_ON')
    sub = l.column()
    sub.active = sc.nomad_ds_prop
    sub.prop(sc, "nomad_ds_prop_size", text="Radius (frames)")
    sub.prop(sc, "nomad_ds_falloff", text="")


# ----------------------------------------------------------------------
# Action and slot of the Action Editor / Shape Key Editor
# ----------------------------------------------------------------------

def _d_action(l, context):
    idb = tl._target_id(context)
    if idb is None:
        l.label(text=("This object has no shape keys"
                      if tl._ds_mode(context) == 'SHAPEKEY'
                      else "Select an object"), icon='INFO')
        return
    if getattr(idb, "animation_data", None) is None:
        l.label(text=f"{idb.name} has no animation data", icon='INFO')
        l.operator("nomad.ds_anim_create", icon='ADD')
        return
    if hasattr(l, "template_action"):            # action + slot (4.4+)
        try:
            l.template_action(idb, new="action.new", unlink="action.unlink")
            return
        except (TypeError, RuntimeError, AttributeError):
            pass
    l.template_ID(idb.animation_data, "action", new="action.new",
                  unlink="action.unlink")


def _d_slot(l, context):
    idb = tl._target_id(context)
    ad = getattr(idb, "animation_data", None)
    act = getattr(ad, "action", None)
    if act is None:
        l.label(text="Assign an action first", icon='INFO')
        return
    slots = list(getattr(act, "slots", ()))
    if not slots:
        l.label(text="This action has no slots", icon='INFO')
        return
    l.label(text=f"Slots of '{act.name}'", icon='ACTION')
    col = l.column(align=True)
    col.scale_y = 1.2
    for i, slot in enumerate(slots):
        ok = slot.target_id_type in ('UNSPECIFIED', idb.id_type)
        row = col.row(align=True)
        row.enabled = ok
        op = row.operator("nomad.ds_slot_set", text=slot.name_display,
                          depress=(slot == ad.action_slot))
        op.index = i


# ----------------------------------------------------------------------
# What the sidebar of each mode shows
# ----------------------------------------------------------------------

def _props(layout, owner, names):
    if owner is None:
        return
    for n in names:
        try:
            layout.prop(owner, n)
        except (TypeError, RuntimeError, AttributeError):
            pass


def _action_box(l, idb):
    ad = getattr(idb, "animation_data", None)
    act = getattr(ad, "action", None)
    if act is None:
        l.label(text="No action assigned", icon='INFO')
        return
    box = l.box()
    box.label(text=act.name, icon='ACTION')
    box.prop(act, "use_frame_range", text="Manual Frame Range")
    sub = box.column(align=True)
    sub.active = act.use_frame_range
    _props(sub, act, ("frame_start", "frame_end"))
    _props(box, act, ("use_cyclic",))


def _cache_file(context):
    ob = context.active_object
    for m in getattr(ob, "modifiers", ()):
        cf = getattr(m, "cache_file", None)
        if cf is not None:
            return cf
    return bpy.data.cache_files[0] if len(bpy.data.cache_files) else None


def _d_side(l, context):
    mode = tl._ds_mode(context)
    ob = context.active_object
    if mode == 'ACTION':
        if ob is None:
            l.label(text="Select an object", icon='INFO')
            return
        _action_box(l, ob)
    elif mode == 'SHAPEKEY':
        key = tl._active_key(context)
        if key is None:
            l.label(text="This object has no shape keys", icon='INFO')
            return
        _action_box(l, key)
        box = l.box()
        box.label(text="Shape Keys", icon='SHAPEKEY_DATA')
        _props(box, key, ("use_relative", "eval_time"))
        kb = ob.active_shape_key
        if kb is not None:
            box = l.box()
            box.label(text=kb.name, icon='SHAPEKEY_DATA')
            _props(box, kb, ("value", "slider_min", "slider_max",
                             "vertex_group", "relative_key", "mute",
                             "interpolation"))
    elif mode == 'CACHE':
        cf = _cache_file(context)
        if cf is None:
            l.label(text="No cache files in this file", icon='INFO')
            return
        box = l.box()
        box.label(text=cf.name, icon='FILE_CACHE')
        _props(box, cf, ("filepath", "scale", "override_frame", "frame",
                         "frame_offset", "is_sequence", "velocity_unit",
                         "velocity_name"))
    else:
        l.label(text=tl.DS_MODE_LABEL.get(mode, mode) + ": coming soon",
                icon='INFO')


NOMAD_PT_ds_mode = _panel("NOMAD_PT_ds_mode", "Mode", 12, _d_mode)
NOMAD_PT_ds_view = _panel("NOMAD_PT_ds_view", "View", 12, _d_view)
NOMAD_PT_ds_key = _panel("NOMAD_PT_ds_key", "Key", 15, _d_key)
NOMAD_PT_ds_pivot = _panel("NOMAD_PT_ds_pivot", "Pivot", 11, _d_pivot)
NOMAD_PT_ds_snap = _panel("NOMAD_PT_ds_snap", "Snap", 11, _d_snap)
NOMAD_PT_ds_prop = _panel("NOMAD_PT_ds_prop", "Proportional", 13, _d_prop)
NOMAD_PT_ds_action = _panel("NOMAD_PT_ds_action", "Action", 14, _d_action)
NOMAD_PT_ds_slot = _panel("NOMAD_PT_ds_slot", "Slot", 12, _d_slot)
NOMAD_PT_ds_side = _panel("NOMAD_PT_ds_side", "Panel", 15, _d_side)

CLASSES = (NOMAD_OT_ds_view, NOMAD_OT_ds_slot_set, NOMAD_OT_ds_anim_create,
           NOMAD_PT_ds_mode, NOMAD_PT_ds_view, NOMAD_PT_ds_key,
           NOMAD_PT_ds_pivot, NOMAD_PT_ds_snap, NOMAD_PT_ds_prop,
           NOMAD_PT_ds_action, NOMAD_PT_ds_slot, NOMAD_PT_ds_side)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass