# Pose Library support for the GPU asset browser. Blender's own pose
# operators need the "context asset" of a native shelf or browser, which our
# browser does not have, so poses are applied here in Python (blend, flip,
# bone selection). Creating poses is delegated to poselib.create_pose_asset.
import re

import bpy
from mathutils import Euler, Quaternion

from .anim_options import bone_selected, set_bone_selected

_PATH = re.compile(r'^pose\.bones\["(.+)"\]\.'
                   r'(location|rotation_quaternion|rotation_euler|scale)$')


def _slots_for(act, obj):
    """Slots of the action that belong to the armature (Blender 4.4+).
    Multi-character poses have one slot per armature: take the one that
    matches the object, falling back to the first slot (as Blender does)."""
    slots = list(getattr(act, "slots", ()))
    if not slots or obj is None:
        return slots[:1]
    ident = "OB" + obj.name
    match = [s for s in slots if s.identifier == ident]
    return match or slots[:1]


def _fcurves_of(act, obj=None):
    out = []
    try:
        out.extend(act.fcurves)                  # legacy API (< 5.0)
    except (AttributeError, RuntimeError):
        pass
    if out:
        return out
    slots = _slots_for(act, obj)
    for layer in getattr(act, "layers", ()):
        for strip in layer.strips:
            bags = []
            for slot in slots:                   # only the matching slot
                try:
                    cb = strip.channelbag(slot)
                except (AttributeError, RuntimeError, TypeError):
                    cb = None
                if cb is not None:
                    bags.append(cb)
            if not bags and not slots:           # no slot info: take all
                bags = list(getattr(strip, "channelbags", ()))
            for cb in bags:
                out.extend(cb.fcurves)
    return out


def _pose_frame(act):
    try:
        markers = list(act.pose_markers)
    except (AttributeError, RuntimeError):
        markers = []
    return markers[0].frame if markers else act.frame_range[0]


def read_pose(act, obj=None):
    """{bone: {prop: {index: value}}} evaluated at the pose frame."""
    frame = _pose_frame(act)
    pose = {}
    for fc in _fcurves_of(act, obj):
        m = _PATH.match(fc.data_path)
        if not m:
            continue
        bone, prop = m.groups()
        try:
            val = fc.evaluate(frame)
        except (RuntimeError, ValueError, TypeError):
            continue
        pose.setdefault(bone, {}).setdefault(prop, {})[fc.array_index] = val
    return pose


# Starting pose of a blend: re-applying with another slider value blends
# from the pose as it was before the first Apply, instead of compounding.
_base = {"key": None, "data": {}}


def _snapshot(pb):
    return (tuple(pb.location), tuple(pb.rotation_quaternion),
            tuple(pb.rotation_euler), tuple(pb.scale))


def _restore(pb, snap):
    pb.location, pb.rotation_quaternion, pb.rotation_euler, pb.scale = snap


def reset_base():
    _base["key"], _base["data"] = None, {}


def _mix(cur, idxvals, flips, f):
    out = list(cur)
    for i, v in idxvals.items():
        if i < len(out):
            out[i] = cur[i] + ((-v if i in flips else v) - cur[i]) * f
    return out


def _apply_bone(pb, props, flipped, f):
    loc = props.get("location")
    if loc:
        pb.location = _mix(pb.location, loc, {0} if flipped else set(), f)
    sc = props.get("scale")
    if sc:
        pb.scale = _mix(pb.scale, sc, set(), f)

    quat = props.get("rotation_quaternion")
    eul = props.get("rotation_euler")
    qf = {2, 3} if flipped else set()
    ef = {1, 2} if flipped else set()
    mode = pb.rotation_mode
    if mode == 'QUATERNION':
        if quat:
            q = _mix(pb.rotation_quaternion, quat, qf, f)
        elif eul:
            cur = list(pb.rotation_euler)
            e = _mix(cur, eul, ef, 1.0)
            q = list(Euler(e).to_quaternion())
            q = [c + (n - c) * f for c, n in zip(pb.rotation_quaternion, q)]
        else:
            return
        pb.rotation_quaternion = Quaternion(q).normalized()
    elif mode != 'AXIS_ANGLE':
        if eul:
            pb.rotation_euler = _mix(pb.rotation_euler, eul, ef, f)
        elif quat:
            q = _mix(list(pb.rotation_euler.to_quaternion()), quat, qf, 1.0)
            e = Quaternion(q).normalized().to_euler(mode)
            pb.rotation_euler = [c + (n - c) * f for c, n in
                                 zip(pb.rotation_euler, e)]


def apply(context, act, flipped=False, factor=1.0, blend=False):
    """Apply the pose to the selected bones (all if none). Returns how many
    bones were changed."""
    obj = context.active_object
    if obj is None or obj.type != 'ARMATURE' or obj.pose is None:
        return 0
    pose = read_pose(act, obj)
    selected = {b.name for b in obj.data.bones
                if bone_selected(obj, b.name)}

    key = (obj.name, act.name, flipped)
    if blend:
        if _base["key"] != key:                  # first apply of this blend
            _base["key"] = key
            _base["data"] = {pb.name: _snapshot(pb) for pb in obj.pose.bones}
    else:
        reset_base()

    count = 0
    keyed = []
    for src, props in pose.items():
        dst = bpy.utils.flip_name(src) if flipped else src
        pb = obj.pose.bones.get(dst)
        if pb is None or (selected and dst not in selected):
            continue
        if blend and dst in _base["data"]:
            _restore(pb, _base["data"][dst])
        _apply_bone(pb, props, flipped, factor)
        keyed.append(pb)
        count += 1
    context.view_layer.update()

    if keyed and context.scene.tool_settings.use_keyframe_insert_auto:
        for pb in keyed:
            for path in ("location", "scale", pb.rotation_mode == 'QUATERNION'
                         and "rotation_quaternion" or "rotation_euler"):
                try:
                    pb.keyframe_insert(path, group=pb.name)
                except (RuntimeError, TypeError):
                    pass
    return count


def select_bones(context, act, extend=False):
    obj = context.active_object
    if obj is None or obj.type != 'ARMATURE':
        return 0
    names = set(read_pose(act, obj))
    if not extend:
        for b in obj.data.bones:
            set_bone_selected(obj, b.name, False)
    n = 0
    for name in names:
        b = obj.data.bones.get(name)
        if b is not None:
            set_bone_selected(obj, name, True)
            n += 1
            obj.data.bones.active = b
    context.view_layer.update()
    for area in context.screen.areas:
        area.tag_redraw()
    print(f"NomadUI pose bones: selected {n} of {len(names)} in the pose "
          f"({len(obj.data.bones)} bones in the armature)")
    return n


def with_action(asset, fn):
    """Load the action of a pose asset, run fn(action), clean up."""
    from . import asset_gpu
    act = asset_gpu._load(asset)
    if act is None:
        return None
    try:
        return fn(act)
    finally:
        if asset["file"]:                       # appended copy: remove it
            try:
                bpy.data.actions.remove(act)
            except (RuntimeError, ReferenceError):
                pass


# ----------------------------------------------------------------------
# Operators and popup
# ----------------------------------------------------------------------

class NOMAD_OT_pose_apply(bpy.types.Operator):
    bl_idname = "nomad.pose_apply"
    bl_label = "Apply Pose"
    bl_description = ("Apply the selected pose to the selected bones "
                      "(or to every bone)")
    bl_options = {'REGISTER', 'UNDO'}

    flipped: bpy.props.BoolProperty(default=False)
    use_blend: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        from . import asset_gpu
        a = asset_gpu.selected_asset()
        if a is None or a["kind"] != 'ACTION':
            self.report({'WARNING'}, "Select a pose in the browser first")
            return {'CANCELLED'}
        factor = context.scene.nomad_pose_blend if self.use_blend else 1.0
        n = with_action(a, lambda act: apply(context, act, self.flipped,
                                             factor, self.use_blend))
        if not n:
            self.report({'WARNING'}, "No matching bones to apply the pose "
                                     "to (select an armature in Pose Mode)")
            return {'CANCELLED'}
        return {'FINISHED'}


class NOMAD_OT_pose_select_bones(bpy.types.Operator):
    bl_idname = "nomad.pose_select_bones"
    bl_label = "Select Pose Bones"
    bl_description = "Select the bones that the selected pose affects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        from . import asset_gpu
        a = asset_gpu.selected_asset()
        if a is None or a["kind"] != 'ACTION':
            self.report({'WARNING'}, "Select a pose in the browser first")
            return {'CANCELLED'}
        n = with_action(a, lambda act: select_bones(context, act))
        if not n:
            self.report({'WARNING'}, "This pose affects none of the bones "
                                     "of the active armature")
            return {'CANCELLED'}
        self.report({'INFO'}, f"{n} bones selected")
        return {'FINISHED'}


class NOMAD_PT_pose_blend(bpy.types.Panel):
    bl_label = "Blend Pose"
    bl_idname = "NOMAD_PT_pose_blend"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 11
        from . import asset_gpu
        a = asset_gpu.selected_asset()
        l.label(text=a["name"] if a else "No pose selected", icon='ARMATURE_DATA')
        col = l.column()
        col.scale_y = 1.6
        col.prop(context.scene, "nomad_pose_blend", slider=True,
                 text="Blend")
        row = l.row(align=True)
        row.scale_y = 1.5
        op = row.operator("nomad.pose_apply", text="Apply", icon='CHECKMARK')
        op.use_blend, op.flipped = True, False
        op = row.operator("nomad.pose_apply", text="Apply Flipped",
                          icon='MOD_MIRROR')
        op.use_blend, op.flipped = True, True


CLASSES = (NOMAD_OT_pose_apply, NOMAD_OT_pose_select_bones,
           NOMAD_PT_pose_blend)


def register():
    bpy.types.Scene.nomad_pose_blend = bpy.props.FloatProperty(
        name="Pose Blend", default=1.0, min=0.0, max=1.0,
        options={'SKIP_SAVE'})
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    if hasattr(bpy.types.Scene, "nomad_pose_blend"):
        del bpy.types.Scene.nomad_pose_blend