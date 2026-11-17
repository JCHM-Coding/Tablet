# Object-mode popups: quick favorites (duplicate, join/parenting,
# show/hide), Options (orientation, pivot, snap, proportional) and
# Constraints.
import bpy
import bmesh
from mathutils import Vector
from .sculpt_popups import _p, _section
from .sculpt_panels import _act
from .pose_panels import _active_pose_bone


def _popover(layout, panel, text="", icon='NONE'):
    try:
        layout.popover(panel=panel, text=text, icon=icon)
    except (TypeError, RuntimeError, KeyError):
        layout.label(text=f"{panel} (n/a)")

def _vec_row(layout, owner, prop, label):
    """Label + one compact row of X Y Z (W X Y Z for 4-component props)."""
    try:
        n = len(getattr(owner, prop))
    except (AttributeError, TypeError):
        return
    layout.label(text=label)
    row = layout.row(align=True)
    letters = "WXYZ" if n == 4 else "XYZ"
    for i in range(n):
        row.prop(owner, prop, index=i, text=letters[i])

def _lock_row(layout, owner, prop):
    try:
        values = getattr(owner, prop)
        n = len(values)
    except (AttributeError, TypeError):
        return
    row = layout.row(align=True)
    row.label(text="Lock")
    for i in range(n):
        row.prop(owner, prop, index=i, text="", toggle=True,
                 icon='LOCKED' if values[i] else 'UNLOCKED')


def _shape_keys(layout, context):
    obj = context.active_object
    if obj is None or obj.type not in {'MESH', 'CURVE', 'SURFACE',
                                       'LATTICE'}:
        layout.label(text="This object has no shape keys", icon='INFO')
        return
    cls = getattr(bpy.types, "DATA_PT_shape_keys", None)
    if cls is None:
        layout.label(text="Shape Keys panel not found", icon='INFO')
        return
    from .render_view_panels import _draw_native
    _draw_native(layout, cls, context, context.scene.render.engine,
                 flat=True)


# ----------------------------------------------------------------------
# Quick favorites
# ----------------------------------------------------------------------

class NOMAD_PT_obj_duplicate(bpy.types.Panel):
    bl_label = "Duplicate"
    bl_idname = "NOMAD_PT_obj_duplicate"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 8
        col = l.column()
        col.scale_y = 1.4
        _act(col, "object.duplicate", "Duplicate", icon='DUPLICATE',
             linked=False)
        _act(col, "object.duplicate", "Duplicate Linked", icon='LINKED',
             linked=True)


class NOMAD_PT_obj_join(bpy.types.Panel):
    bl_label = "Join / Parenting"
    bl_idname = "NOMAD_PT_obj_join"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 10
        col = l.column()
        col.scale_y = 1.4
        _act(col, "object.join", "Join", icon='SELECT_EXTEND')

        body = _section(l, "nomad_obj_parent", "Parenting", closed=False)
        if body is None:
            return
        body.label(text="Set Parent To")
        col = body.column()
        col.scale_y = 1.3
        _act(col, "object.parent_set", "Object", type='OBJECT')
        sub = _section(body, "nomad_obj_parent_arm", "Armature",
                       closed=False)
        if sub is not None:
            col = sub.column()
            col.scale_y = 1.3
            _act(col, "object.parent_set", "Armature Deform",
                 type='ARMATURE')
            _act(col, "object.parent_set", "With Automatic Weights",
                 type='ARMATURE_AUTO')
            _act(col, "object.parent_set", "Bone", type='BONE')
        col = body.column()
        col.scale_y = 1.3
        _act(col, "object.parent_clear", "Clear Parent", icon='X',
             type='CLEAR')


class NOMAD_PT_obj_hide(bpy.types.Panel):
    bl_label = "Show / Hide"
    bl_idname = "NOMAD_PT_obj_hide"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 8
        col = l.column()
        col.scale_y = 1.4
        _act(col, "object.hide_view_set", "Hide Selected", icon='HIDE_ON',
             unselected=False)
        _act(col, "object.hide_view_set", "Hide Unselected",
             icon='HIDE_ON', unselected=True)
        _act(col, "object.hide_view_clear", "Show All", icon='HIDE_OFF')


# ----------------------------------------------------------------------
# Options: orientation, pivot, snap, proportional editing
# ----------------------------------------------------------------------
# --- Edit Mesh median (Item Transform) -------------------------------------
def _edit_selection(context):
    obj = context.edit_object
    if obj is None or obj.type != 'MESH':
        return None, None, []
    bm = bmesh.from_edit_mesh(obj.data)
    return obj, bm, [v for v in bm.verts if v.select]


def _median(context, world):
    obj, bm, verts = _edit_selection(context)
    if not verts:
        return (0.0, 0.0, 0.0)
    m = Vector((0.0, 0.0, 0.0))
    for v in verts:
        m += v.co
    m /= len(verts)
    if world:
        m = obj.matrix_world @ m
    return tuple(m)


def _set_median(context, world, value):
    obj, bm, verts = _edit_selection(context)
    if not verts:
        return
    delta = Vector(value) - Vector(_median(context, world))
    if world:
        delta = obj.matrix_world.to_3x3().inverted_safe() @ delta
    for v in verts:
        v.co += delta
    bmesh.update_edit_mesh(obj.data)
    try:
        bpy.ops.ed.undo_push(message="Median")
    except RuntimeError:
        pass


def _make_median(world):
    def get(self):
        return _median(bpy.context, world)

    def set_(self, value):
        _set_median(bpy.context, world, value)
    return get, set_


class NOMAD_PT_options(bpy.types.Panel):
    bl_label = "Options"
    bl_idname = "NOMAD_PT_options"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        sc = context.scene
        ts = context.tool_settings
        mode = context.mode

        l.label(text="Transform Orientation")
        row = l.row(align=True)
        try:
            row.prop(sc.transform_orientation_slots[0], "type", text="")
        except (IndexError, AttributeError, TypeError):
            row.label(text="n/a")
        _popover(row, "VIEW3D_PT_transform_orientations", "",
                 'PREFERENCES')

        l.label(text="Pivot Point")
        _p(l, ts, "transform_pivot_point", text="")

        l.separator()
        row = l.row(align=True)
        row.scale_y = 1.3
        row.prop(ts, "use_snap", text="Snap", toggle=True,
                 icon='SNAP_ON' if ts.use_snap else 'SNAP_OFF')
        _popover(row, "VIEW3D_PT_snapping", "", 'DOWNARROW_HLT')

        l.separator()
        attr = ("use_proportional_edit_objects"
                if mode in {'OBJECT', 'POSE'} else "use_proportional_edit")
        on = bool(getattr(ts, attr, False))
        row = l.row(align=True)
        row.scale_y = 1.3
        if hasattr(ts, attr):
            row.prop(ts, attr, text="Proportional Editing", toggle=True,
                     icon='PROP_ON' if on else 'PROP_OFF')
        _p(l, ts, "proportional_edit_falloff", text="Falloff")
        _p(l, ts, "proportional_size", text="Size")

        if mode == 'POSE':
            self._pose_options(l, context, ts)

        body = _section(l, "nomad_opt_item", "Item Transform", closed=False)
        if body is None:
            return
        if mode == 'EDIT_MESH':
            self._item_edit_mesh(body, context)
        elif mode == 'OBJECT':
            self._item_object(body, context)
        elif mode == 'POSE':
            self._item_pose(body, context)
        else:
            body.label(text="Not available in this mode yet", icon='INFO')

    def _pose_options(self, l, context, ts):
        obj = context.active_object
        pose = getattr(obj, "pose", None)
        body = _section(l, "nomad_opt_pose", "Pose Options", closed=False)
        if body is None or pose is None:
            return
        _p(body, pose, "use_auto_ik", text="Auto IK")
        _p(body, pose, "use_mirror_x", text="X-Axis Mirror")
        if getattr(pose, "use_mirror_x", False):
            _p(body, pose, "use_mirror_relative", text="Mirror Relative")
        _p(body, ts, "use_transform_pivot_point_align",
           text="Affect Only Locations")

    def _item_pose(self, body, context):
        pb = getattr(context, "active_pose_bone", None)
        if pb is None:
            body.label(text="No active bone", icon='INFO')
            return
        body.label(text=pb.name, icon='BONE_DATA')
        _vec_row(body, pb, "location", "Location")
        _lock_row(body, pb, "lock_location")
        rmode = pb.rotation_mode
        rot = ("rotation_quaternion" if rmode == 'QUATERNION'
               else "rotation_axis_angle" if rmode == 'AXIS_ANGLE'
               else "rotation_euler")
        _vec_row(body, pb, rot, "Rotation")
        if rmode in {'QUATERNION', 'AXIS_ANGLE'}:
            row = body.row(align=True)
            _p(row, pb, "lock_rotations_4d", text="4L", toggle=True)
            _p(row, pb, "lock_rotation_w", text="Lock W", toggle=True)
        _lock_row(body, pb, "lock_rotation")
        body.prop(pb, "rotation_mode", text="")
        _vec_row(body, pb, "scale", "Scale")
        _lock_row(body, pb, "lock_scale")
        body.label(text=f"Length: {pb.length:.3f}")

    def _item_object(self, body, context):
        obj = context.active_object
        if obj is None:
            body.label(text="No active object", icon='INFO')
            return
        _vec_row(body, obj, "location", "Location")
        rmode = obj.rotation_mode
        rot = ("rotation_quaternion" if rmode == 'QUATERNION'
               else "rotation_axis_angle" if rmode == 'AXIS_ANGLE'
               else "rotation_euler")
        _vec_row(body, obj, rot, "Rotation")
        body.prop(obj, "rotation_mode", text="")
        _vec_row(body, obj, "scale", "Scale")
        _vec_row(body, obj, "dimensions", "Dimensions")

    def _item_edit_mesh(self, body, context):
        obj = context.edit_object
        if obj is None or obj.type != 'MESH':
            body.label(text="No mesh in edit mode", icon='INFO')
            return
        n = getattr(obj.data, "total_vert_sel", 0)
        if n == 0:
            body.label(text="Nothing selected", icon='INFO')
            return
        wm = context.window_manager
        row = body.row(align=True)
        row.label(text="Vertex" if n == 1 else f"Median ({n})")
        row.prop(wm, "nomad_item_global", text="Global", toggle=True)
        _vec_row(body, wm, "nomad_median_global" if wm.nomad_item_global
                 else "nomad_median_local", "Position")


# ----------------------------------------------------------------------
# Constraints (same idea as the modifiers popup)
# ----------------------------------------------------------------------

_SKIP = {"rna_type", "name", "type", "is_valid", "active", "show_expanded",
         "error_location", "error_rotation", "is_proxy_local", "enabled",
         "mute"}


def _enabled_attr(con):
    return "enabled" if hasattr(con, "enabled") else "mute"


def _is_on(con):
    attr = _enabled_attr(con)
    value = bool(getattr(con, attr, True))
    return value if attr == "enabled" else not value


def _generic_props(layout, con):
    for prop in con.bl_rna.properties:
        ident = prop.identifier
        if ident in _SKIP or prop.is_readonly or prop.is_hidden:
            continue
        if ident == "subtarget":
            target = getattr(con, "target", None)
            if target is not None and target.type == 'ARMATURE':
                layout.prop_search(con, "subtarget", target.data, "bones",
                                   text="Bone")
            elif target is not None and target.type == 'MESH':
                layout.prop_search(con, "subtarget", target,
                                   "vertex_groups", text="Vertex Group")
            continue
        try:
            layout.prop(con, ident)
        except (TypeError, RuntimeError):
            pass


def _stack(context, owner):
    """(owner, constraints) for 'OBJECT' or 'BONE', or (None, None)."""
    obj = context.active_object
    if obj is None:
        return None, None
    if owner == 'BONE':
        pb = _active_pose_bone(context)
        return ('BONE', pb.constraints) if pb is not None else (None, None)
    return 'OBJECT', obj.constraints


def _index_prop(owner):
    return "nomad_con_index" if owner == 'OBJECT' else "nomad_bcon_index"


class NOMAD_OT_constraint_action(bpy.types.Operator):
    bl_idname = "nomad.constraint_action"
    bl_label = "Constraint Action"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()
    action: bpy.props.EnumProperty(items=[
        ('UP', "Up", ""), ('DOWN', "Down", ""), ('TOGGLE', "Toggle", ""),
        ('REMOVE', "Remove", ""), ('APPLY', "Apply", "")])
    select: bpy.props.BoolProperty(default=False)
    owner: bpy.props.EnumProperty(items=[
        ('OBJECT', "Object", ""), ('BONE', "Bone", "")], default='OBJECT')

    def execute(self, context):
        owner, cons = _stack(context, self.owner)
        if cons is None or not (0 <= self.index < len(cons)):
            return {'CANCELLED'}
        con = cons[self.index]
        name = con.name
        sc = context.scene
        idx_prop = _index_prop(self.owner)

        if self.select:
            setattr(sc, idx_prop, self.index)
        elif self.action == 'TOGGLE':
            attr = _enabled_attr(con)
            setattr(con, attr, not getattr(con, attr))
        elif self.action == 'REMOVE':
            cons.remove(con)
            setattr(sc, idx_prop, max(0, min(self.index, len(cons) - 1)))
        else:
            fn = {'UP': bpy.ops.constraint.move_up,
                  'DOWN': bpy.ops.constraint.move_down,
                  'APPLY': bpy.ops.constraint.apply}[self.action]
            try:
                fn(constraint=name, owner=owner)
            except RuntimeError as exc:
                self.report({'WARNING'}, str(exc))
                return {'CANCELLED'}
        return {'FINISHED'}


def _draw_stack(layout, context, owner_kind):
    owner, cons = _stack(context, owner_kind)
    if cons is None:
        layout.label(text="No active bone" if owner_kind == 'BONE'
                     else "No active object", icon='INFO')
        return
    if context.mode.startswith("EDIT"):
        layout = layout.column()
        layout.enabled = False          # constraints can't be edited here
        layout.label(text="Not available in Edit Mode", icon='INFO')

    add_op = ("object.constraint_add" if owner == 'OBJECT'
              else "pose.constraint_add")
    layout.operator_menu_enum(add_op, "type", text="Add Constraint",
                              icon='ADD')
    if not cons:
        layout.label(text="No constraints", icon='INFO')
        return

    idx_prop = _index_prop(owner_kind)
    idx = min(getattr(context.scene, idx_prop), len(cons) - 1)
    box = layout.box()
    for i, con in enumerate(cons):
        row = box.row(align=True)
        row.alert = not _is_on(con)
        op = row.operator("nomad.constraint_action", text=con.name,
                          depress=(i == idx))
        op.select, op.index, op.owner = True, i, owner_kind
        for action, icon in (
                ('UP', 'TRIA_UP'), ('DOWN', 'TRIA_DOWN'),
                ('TOGGLE', 'HIDE_OFF' if _is_on(con) else 'HIDE_ON'),
                ('APPLY', 'CHECKMARK'), ('REMOVE', 'X')):
            op = row.operator("nomad.constraint_action", text="",
                              icon=icon)
            op.action, op.index, op.owner = action, i, owner_kind

    con = cons[idx]
    box = layout.box()
    box.label(text=con.name, icon='CONSTRAINT')
    _generic_props(box, con)


class NOMAD_PT_constraints(bpy.types.Panel):
    bl_label = "Constraints / Shape Keys"
    bl_idname = "NOMAD_PT_constraints"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        obj = context.active_object
        if obj is None:
            l.label(text="No active object", icon='INFO')
            return

        body = _section(l, "nomad_con_list", "Object Constraints",
                        closed=False)
        if body is not None:
            _draw_stack(body, context, 'OBJECT')

        if obj.type == 'ARMATURE':
            body = _section(l, "nomad_bcon_list", "Bone Constraints",
                            closed=False)
            if body is not None:
                _draw_stack(body, context, 'BONE')

        keys = _section(l, "nomad_shape_keys", "Shape Keys", closed=True)
        if keys is not None:
            _shape_keys(keys, context)


CLASSES = (NOMAD_PT_obj_duplicate, NOMAD_PT_obj_join, NOMAD_PT_obj_hide,
           NOMAD_PT_options, NOMAD_OT_constraint_action,
           NOMAD_PT_constraints)


def register():
    bpy.types.Scene.nomad_con_index = bpy.props.IntProperty(
        name="Constraint Index", default=0, min=0)
    bpy.types.Scene.nomad_bcon_index = bpy.props.IntProperty(
        name="Bone Constraint Index", default=0, min=0)
    wm_t = bpy.types.WindowManager
    wm_t.nomad_item_global = bpy.props.BoolProperty(
        name="Global", default=False, options={'SKIP_SAVE'})
    for name, world in (("nomad_median_local", False),
                        ("nomad_median_global", True)):
        get, set_ = _make_median(world)
        setattr(wm_t, name, bpy.props.FloatVectorProperty(
            name="Median", size=3, subtype='TRANSLATION', unit='LENGTH',
            get=get, set=set_, options={'SKIP_SAVE'}))
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    for name in ("nomad_item_global", "nomad_median_local",
                 "nomad_median_global"):
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
    for name in ("nomad_con_index", "nomad_bcon_index"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)