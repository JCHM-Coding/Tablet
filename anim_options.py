# Keyframe interpolation / easing from the tablet timeline. Blender's own
# operators only work inside an animation editor, so the values are set on
# the keyframes directly.
import bpy

try:
    from bpy_extras import anim_utils
except ImportError:
    anim_utils = None

INTERP = (('CONSTANT', "Constant"), ('LINEAR', "Linear"),
          ('BEZIER', "Bezier"), ('SINE', "Sine"), ('QUAD', "Quad"),
          ('CUBIC', "Cubic"), ('QUART', "Quart"), ('QUINT', "Quint"),
          ('EXPO', "Expo"), ('CIRC', "Circ"), ('BACK', "Back"),
          ('BOUNCE', "Bounce"), ('ELASTIC', "Elastic"))
EASING = (('AUTO', "Automatic"), ('EASE_IN', "Ease In"),
          ('EASE_OUT', "Ease Out"), ('EASE_IN_OUT', "Ease In-Out"))


def _fcurves(obj):
    """Every F-curve of the object's action: slot channelbag, legacy API,
    then all layers / strips / channelbags."""
    ad = getattr(obj, "animation_data", None)
    act = getattr(ad, "action", None)
    if act is None:
        return []
    out, seen = [], set()

    def add(seq):
        for fc in seq:
            k = fc.as_pointer()
            if k not in seen:
                seen.add(k)
                out.append(fc)

    slot = getattr(ad, "action_slot", None)
    if anim_utils is not None and slot is not None:
        try:
            cb = anim_utils.action_get_channelbag_for_slot(act, slot)
            if cb is not None:
                add(cb.fcurves)
        except (AttributeError, TypeError, RuntimeError):
            pass
    if not out:
        try:
            add(act.fcurves)
        except (AttributeError, RuntimeError):
            pass
    if not out:
        handle = getattr(slot, "handle", None)
        for layer in getattr(act, "layers", ()):
            for strip in layer.strips:
                for cb in getattr(strip, "channelbags", ()):
                    if handle is None or cb.slot_handle == handle:
                        add(cb.fcurves)
    if not out:                          # last resort: any channelbag
        for layer in getattr(act, "layers", ()):
            for strip in layer.strips:
                for cb in getattr(strip, "channelbags", ()):
                    add(cb.fcurves)
    return out


def _bone_ok(obj, fc):
    prefix = 'pose.bones["'
    dp = fc.data_path
    if obj.mode != 'POSE' or not dp.startswith(prefix):
        return True
    name = dp[len(prefix):].split('"]', 1)[0]
    try:
        return bool(obj.data.bones[name].select)
    except (KeyError, AttributeError):
        return True


def _targets(context):
    objs = {o.name: o for o in context.selected_objects}
    if context.active_object is not None:
        objs[context.active_object.name] = context.active_object
    frame = context.scene.frame_current
    pairs, at_frame = [], []
    for obj in objs.values():
        for fc in _fcurves(obj):
            if not _bone_ok(obj, fc):
                continue
            for kp in fc.keyframe_points:
                pairs.append((fc, kp))
                if abs(kp.co[0] - frame) < 0.5:
                    at_frame.append((fc, kp))
    sel = [(fc, kp) for fc, kp in pairs if kp.select_control_point]
    return sel or at_frame


class NOMAD_OT_key_set(bpy.types.Operator):
    bl_idname = "nomad.key_set"
    bl_label = "Set Keyframe Type"
    bl_description = ("Apply to the selected keyframes, or to the keys at "
                      "the current frame")
    bl_options = {'REGISTER', 'UNDO'}

    prop: bpy.props.StringProperty()      # 'interpolation' | 'easing'
    value: bpy.props.StringProperty()

    def execute(self, context):
        targets = _targets(context)
        if not targets:
            self.report({'INFO'}, "No keyframes selected or at this frame")
            return {'CANCELLED'}
        curves = set()
        for fc, kp in targets:
            try:
                setattr(kp, self.prop, self.value)
            except (TypeError, ValueError, AttributeError):
                continue
            curves.add(fc)
        for fc in curves:
            fc.update()
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                area.tag_redraw()
        return {'FINISHED'}


class NOMAD_PT_key_options(bpy.types.Panel):
    bl_label = "Keyframe Options"
    bl_idname = "NOMAD_PT_key_options"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        l.label(text="Applies to the selected keys,")
        l.label(text="or to the keys at the current frame")

        l.label(text="Interpolation")
        grid = l.grid_flow(row_major=True, columns=3, even_columns=True,
                           align=True)
        grid.scale_y = 1.4
        for ident, name in INTERP:
            op = grid.operator("nomad.key_set", text=name)
            op.prop, op.value = 'interpolation', ident

        l.label(text="Easing")
        grid = l.grid_flow(row_major=True, columns=2, even_columns=True,
                           align=True)
        grid.scale_y = 1.4
        for ident, name in EASING:
            op = grid.operator("nomad.key_set", text=name)
            op.prop, op.value = 'easing', ident

        l.separator()
        l.label(text="New keyframes")
        edit = context.preferences.edit
        l.prop(edit, "keyframe_new_interpolation_type",
               text="Interpolation")
        l.prop(edit, "keyframe_new_handle_type", text="Handles")


CLASSES = (NOMAD_OT_key_set, NOMAD_PT_key_options)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass