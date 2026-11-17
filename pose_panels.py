# Pose mode popups: hide, Data (bone collections, motion paths), Bone
# (bendy bones, relations, IK, deform) and Copy / Paste Selected.
import bpy
from .sculpt_popups import _p, _section
from .sculpt_panels import _act


def _armature(context):
    obj = context.active_object
    if obj is None or obj.type != 'ARMATURE':
        return None, None
    return obj, obj.data


def _active_pose_bone(context):
    """Active pose bone: in Pose mode, or the active bone in Object mode."""
    obj = context.active_object
    if obj is None or obj.type != 'ARMATURE':
        return None
    pb = getattr(context, "active_pose_bone", None)
    if pb is not None:
        return pb
    try:
        bone = obj.data.bones.active
        return obj.pose.bones.get(bone.name) if bone else None
    except (AttributeError, RuntimeError):
        return None


class NOMAD_PT_armature_edit(bpy.types.Panel):
    bl_label = "Armature"
    bl_idname = "NOMAD_PT_armature_edit"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        from .paint_panels import _menu_section
        l = self.layout
        l.ui_units_x = 12
        obj, arm = _armature(context)
        if arm is None:
            l.label(text="No armature", icon='INFO')
            return
        _menu_section(l, "nomad_are_menu", "Armature",
                      "VIEW3D_MT_edit_armature")
        body = _section(l, "nomad_are_opts", "Options", closed=True)
        if body is not None:
            _p(body, arm, "use_mirror_x", text="X-Axis Mirror", toggle=True)


def _props_where(layout, owner, pred):
    """Draw every editable property of `owner` whose id passes `pred`."""
    for prop in owner.bl_rna.properties:
        ident = prop.identifier
        if (ident == "rna_type" or prop.is_hidden or prop.is_readonly
                or not pred(ident)):
            continue
        try:
            layout.prop(owner, ident)
        except (TypeError, RuntimeError):
            pass


# ----------------------------------------------------------------------
# Show / Hide
# ----------------------------------------------------------------------

class NOMAD_PT_pose_hide(bpy.types.Panel):
    bl_label = "Show / Hide"
    bl_idname = "NOMAD_PT_pose_hide"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 8
        col = l.column()
        col.scale_y = 1.4
        _act(col, "pose.hide", "Hide Selected", icon='HIDE_ON',
             unselected=False)
        _act(col, "pose.hide", "Hide Unselected", icon='HIDE_ON',
             unselected=True)
        _act(col, "pose.reveal", "Show All", icon='HIDE_OFF')


# ----------------------------------------------------------------------
# Data: bone collections + motion paths
# ----------------------------------------------------------------------

class NOMAD_PT_pose_data(bpy.types.Panel):
    bl_label = "Data"
    bl_idname = "NOMAD_PT_pose_data"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        obj, arm = _armature(context)
        if arm is None:
            l.label(text="No armature", icon='INFO')
            return
        body = _section(l, "nomad_pd_bcoll", "Bone Collections",
                        closed=True)
        if body is not None:
            self._collections(body, arm)
        body = _section(l, "nomad_pd_mpath", "Motion Paths", closed=True)
        if body is not None:
            self._motion_paths(body, obj)

    def _collections(self, body, arm):
        if not hasattr(arm, "collections_all"):
            body.label(text="Bone collections not available", icon='INFO')
            return
        row = body.row()
        row.template_list("UI_UL_list", "nomad_bcoll", arm,
                          "collections_all", arm.collections,
                          "active_index", rows=4)
        col = row.column(align=True)
        _act(col, "armature.collection_add", "", icon='ADD')
        _act(col, "armature.collection_remove", "", icon='REMOVE')
        col.separator()
        _act(col, "armature.collection_move", "", icon='TRIA_UP',
             direction='UP')
        _act(col, "armature.collection_move", "", icon='TRIA_DOWN',
             direction='DOWN')

        active = getattr(arm.collections, "active", None)
        if active is not None:
            _p(body, active, "name", text="Name")
            row = body.row(align=True)
            _p(row, active, "is_visible", text="Visible", toggle=True)
            _p(row, active, "is_solo", text="Solo", toggle=True)
        row = body.row(align=True)
        _act(row, "armature.collection_assign", "Assign")
        _act(row, "armature.collection_unassign", "Remove")
        row = body.row(align=True)
        _act(row, "armature.collection_select", "Select")
        _act(row, "armature.collection_deselect", "Deselect")

    def _motion_paths(self, body, obj):
        viz = getattr(obj.pose, "animation_visualization", None)
        mp = getattr(viz, "motion_path", None)
        if mp is None:
            body.label(text="Motion paths not available", icon='INFO')
            return
        _p(body, mp, "type", text="Type")
        if getattr(mp, "type", 'RANGE') == 'RANGE':
            _p(body, mp, "frame_start", text="Start")
            _p(body, mp, "frame_end", text="End")
        else:
            _p(body, mp, "frame_before", text="Before")
            _p(body, mp, "frame_after", text="After")
        _p(body, mp, "frame_step", text="Step")
        _p(body, mp, "bake_location", text="Bake Location")
        row = body.row(align=True)
        row.scale_y = 1.3
        _act(row, "pose.paths_calculate", "Calculate")
        _act(row, "pose.paths_update", "Update")
        _act(row, "pose.paths_clear", "Clear")
        disp = _section(body, "nomad_pd_mpdisp", "Display", closed=True)
        if disp is not None:
            for name in ("show_frame_numbers", "show_keyframe_highlight",
                         "show_keyframe_numbers", "show_lines",
                         "line_thickness", "use_custom_color", "color"):
                _p(disp, mp, name)


# ----------------------------------------------------------------------
# Bone: bendy bones, relations, inverse kinematics, deform
# ----------------------------------------------------------------------

class NOMAD_PT_pose_bone(bpy.types.Panel):
    bl_label = "Bone"
    bl_idname = "NOMAD_PT_pose_bone"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        obj, arm = _armature(context)
        pb = _active_pose_bone(context)
        if arm is None or pb is None:
            l.label(text="No active bone", icon='INFO')
            return
        bone = pb.bone
        l.label(text=pb.name, icon='BONE_DATA')

        body = _section(l, "nomad_pb_bbone", "Bendy Bones", closed=True)
        if body is not None:
            body.label(text="Bone")
            _props_where(body, bone, lambda i: i.startswith("bbone_")
                         or i == "use_endroll_as_inroll")
            body.label(text="Pose")
            _props_where(body, pb, lambda i: i.startswith("bbone_"))

        body = _section(l, "nomad_pb_rel", "Relations", closed=True)
        if body is not None:
            if bone.parent is not None:
                body.label(text=f"Parent: {bone.parent.name}",
                           icon='BONE_DATA')
            for name in ("use_connect", "use_inherit_rotation",
                         "inherit_scale", "use_local_location",
                         "use_relative_parent"):
                _p(body, bone, name)

        body = _section(l, "nomad_pb_ik", "Inverse Kinematics",
                        closed=True)
        if body is not None:
            pose = obj.pose
            _p(body, pose, "ik_solver", text="Solver")
            if getattr(pose, "ik_solver", None) == 'ITASC':
                param = getattr(pose, "ik_param", None)
                if param is not None:
                    for name in ("mode", "reiteration_method", "precision",
                                 "iterations", "solver"):
                        _p(body, param, name)
            _props_where(body, pb, lambda i: i.startswith(
                ("ik_", "lock_ik", "use_ik")))

        body = _section(l, "nomad_pb_deform", "Deform", closed=True)
        if body is not None:
            _p(body, bone, "use_deform", text="Deform")
            sub = body.column()
            sub.active = bool(getattr(bone, "use_deform", True))
            for name in ("envelope_distance", "envelope_weight",
                         "use_envelope_multiply", "head_radius",
                         "tail_radius"):
                _p(sub, bone, name)


# ----------------------------------------------------------------------
# Copy / Paste Selected (timeline, Object + Pose)
# ----------------------------------------------------------------------

_buffer = []


def _rot_path(mode):
    return ("rotation_quaternion" if mode == 'QUATERNION'
            else "rotation_axis_angle" if mode == 'AXIS_ANGLE'
            else "rotation_euler")


class NOMAD_OT_copy_selected(bpy.types.Operator):
    bl_idname = "nomad.copy_selected"
    bl_label = "Copy Selected"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        if context.mode == 'POSE':
            try:
                bpy.ops.pose.copy()
            except RuntimeError as exc:
                self.report({'WARNING'}, str(exc))
                return {'CANCELLED'}
            return {'FINISHED'}
        if context.mode != 'OBJECT':
            self.report({'WARNING'}, "Object or Pose mode only")
            return {'CANCELLED'}
        objs = list(context.selected_objects)
        if not objs:
            self.report({'WARNING'}, "Nothing selected")
            return {'CANCELLED'}
        _buffer.clear()
        for ob in objs:
            loc, rot, scale = ob.matrix_basis.decompose()
            _buffer.append({"name": ob.name, "loc": loc.copy(),
                            "rot": rot.copy(), "scale": scale.copy()})
        self.report({'INFO'}, f"Copied {len(objs)} object(s)")
        return {'FINISHED'}


class NOMAD_OT_paste_selected(bpy.types.Operator):
    bl_idname = "nomad.paste_selected"
    bl_label = "Paste Selected"
    bl_options = {'REGISTER', 'UNDO'}

    flipped: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        if context.mode == 'POSE':
            try:
                bpy.ops.pose.paste(flipped=self.flipped)
            except RuntimeError as exc:
                self.report({'WARNING'}, str(exc))
                return {'CANCELLED'}
            return {'FINISHED'}
        if context.mode != 'OBJECT':
            self.report({'WARNING'}, "Object or Pose mode only")
            return {'CANCELLED'}
        objs = list(context.selected_objects)
        if not _buffer or not objs:
            self.report({'WARNING'}, "Nothing to paste")
            return {'CANCELLED'}

        by_name = {d["name"]: d for d in _buffer}
        auto = context.tool_settings.use_keyframe_insert_auto
        for i, ob in enumerate(objs):
            d = by_name.get(ob.name) or _buffer[i % len(_buffer)]
            ob.location = d["loc"]
            ob.scale = d["scale"]
            mode = ob.rotation_mode
            if mode == 'QUATERNION':
                ob.rotation_quaternion = d["rot"]
            elif mode == 'AXIS_ANGLE':
                axis, angle = d["rot"].to_axis_angle()
                ob.rotation_axis_angle = (angle, axis.x, axis.y, axis.z)
            else:
                ob.rotation_euler = d["rot"].to_euler(
                    mode, ob.rotation_euler)
            if auto:
                for path in ("location", _rot_path(mode), "scale"):
                    try:
                        ob.keyframe_insert(path)
                    except RuntimeError:
                        pass
        return {'FINISHED'}


class NOMAD_PT_copy_paste(bpy.types.Panel):
    bl_label = "Copy / Paste"
    bl_idname = "NOMAD_PT_copy_paste"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 8
        if context.mode not in {'OBJECT', 'POSE'}:
            l.label(text="Object or Pose mode only", icon='INFO')
            return
        col = l.column()
        col.scale_y = 1.4
        col.operator("nomad.copy_selected", text="Copy Selected",
                     icon='COPYDOWN')
        col.operator("nomad.paste_selected", text="Paste Selected",
                     icon='PASTEDOWN').flipped = False
        if context.mode == 'POSE':
            col.operator("nomad.paste_selected", text="Paste Flipped",
                         icon='PASTEFLIPDOWN').flipped = True


CLASSES = (NOMAD_PT_pose_hide, NOMAD_PT_pose_data, NOMAD_PT_pose_bone,
           NOMAD_OT_copy_selected, NOMAD_OT_paste_selected,
           NOMAD_PT_copy_paste, NOMAD_PT_armature_edit)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass