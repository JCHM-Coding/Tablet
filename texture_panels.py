# Texture Paint popups: Texture (object) = slots + masking + bake,
# face selection masking, clone, and the stencil controls (also Sculpt).
import json

import bpy
from .sculpt_popups import _p, _section, defer_op
from .sculpt_panels import _act, _actions, _safe, _op_exists
from . import color_overlay


def _brush(context):
    from . import brush_shelf
    return brush_shelf.active_brush(context)


# ----------------------------------------------------------------------
# Dialog operators, launched from the viewport (not from inside a popup)
# ----------------------------------------------------------------------

class NOMAD_OT_invoke(bpy.types.Operator):
    """Run an operator that opens a dialog / file browser. It's launched
    outside the popup, so the dialog keeps a valid context."""
    bl_idname = "nomad.invoke"
    bl_label = "Run"
    bl_options = {'INTERNAL'}

    op: bpy.props.StringProperty()
    args: bpy.props.StringProperty(default="{}")

    def execute(self, context):
        try:
            kw = json.loads(self.args)
        except ValueError:
            kw = {}
        mod, name = self.op.split(".", 1)
        defer_op(mod, name, 'INVOKE_DEFAULT', **kw)
        return {'FINISHED'}


_pending = {"target": None, "before": set(), "ticks": 0}


def _assign_image(context, target, img):
    ts = context.tool_settings
    try:
        if target == 'CANVAS':
            ts.image_paint.canvas = img
        elif target == 'STENCIL':
            ts.image_paint.stencil_image = img
        elif target in ('TEXTURE', 'MASK_TEXTURE'):
            brush = _brush(context)
            tex = getattr(brush, "mask_texture" if target == 'MASK_TEXTURE'
                          else "texture", None)
            if tex is not None:
                tex.image = img
        elif target.startswith("CAMBG:"):
            cam, idx = target.split(":", 1)[1].rsplit(":", 1)
            bpy.data.cameras[cam].background_images[int(idx)].image = img
        elif target.startswith("EMPTY:"):
            bpy.data.objects[target[6:]].data = img
    except (AttributeError, RuntimeError, TypeError, KeyError,
            IndexError, ValueError) as exc:
        print(f"NomadUI assign image ({target}): {exc!r}")


def _watch_images():
    """Waits for the image created / opened by the dialog, then assigns it."""
    p = _pending
    if p["target"] is None:
        return None
    p["ticks"] += 1
    new = [im for im in bpy.data.images if im.name not in p["before"]]
    if new:
        _assign_image(bpy.context, p["target"], new[-1])
        p["target"] = None
        return None
    if p["ticks"] > 240:            # about two minutes
        p["target"] = None
        return None
    return 0.5


class NOMAD_OT_image_add(bpy.types.Operator):
    """New / Open image, assigned to the target when it's created."""
    bl_idname = "nomad.image_add"
    bl_label = "Image"
    bl_options = {'INTERNAL'}

    operator_id: bpy.props.StringProperty()      # image.new | image.open
    target: bpy.props.StringProperty()           # CANVAS | STENCIL | ...

    def execute(self, context):
        _pending.update(target=self.target, ticks=0,
                        before={im.name for im in bpy.data.images})
        mod, name = self.operator_id.split(".", 1)
        defer_op(mod, name, 'INVOKE_DEFAULT')
        try:
            bpy.app.timers.register(_watch_images, first_interval=0.5)
        except (RuntimeError, ValueError):
            pass
        return {'FINISHED'}


def image_buttons(layout, target):
    row = layout.row(align=True)
    row.scale_y = 1.3
    op = row.operator("nomad.image_add", text="New Image", icon='FILE_NEW')
    op.operator_id, op.target = "image.new", target
    op = row.operator("nomad.image_add", text="Open Image",
                      icon='FILE_FOLDER')
    op.operator_id, op.target = "image.open", target


def _dialog_button(layout, text, operator_id, icon='NONE', **kw):
    op = layout.operator("nomad.invoke", text=text, icon=icon)
    op.op = operator_id
    op.args = json.dumps(kw)


class NOMAD_OT_brush_kind(bpy.types.Operator):
    bl_idname = "nomad.brush_kind"
    bl_label = "Brush"
    bl_options = {'INTERNAL'}

    kind: bpy.props.StringProperty()

    def execute(self, context):
        from . import brush_shelf
        brush_shelf.activate_kind(self.kind)
        return {'FINISHED'}


# ----------------------------------------------------------------------
# Texture (object): slots + masking + bake
# ----------------------------------------------------------------------

_REMOVE_SLOT = ("paint.delete_texture_paint_slot",
                "paint.texture_paint_slot_remove",
                "paint.remove_texture_paint_slot",
                "image.delete_texture_paint_slot")
                
def _slot_types():
    try:
        rna = bpy.ops.paint.add_texture_paint_slot.get_rna_type()
        return [(i.identifier, i.name)
                for i in rna.properties["type"].enum_items]
    except Exception:
        return [('BASE_COLOR', "Base Color"), ('SPECULAR', "Specular"),
                ('ROUGHNESS', "Roughness"), ('METALLIC', "Metallic"),
                ('NORMAL', "Normal"), ('BUMP', "Bump"),
                ('DISPLACEMENT', "Displacement")]


class NOMAD_PT_tp_object(bpy.types.Panel):
    bl_label = "Texture"
    bl_idname = "NOMAD_PT_tp_object"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        ipaint = getattr(context.tool_settings, "image_paint", None)
        if context.mode != 'PAINT_TEXTURE' or ipaint is None:
            l.label(text="Texture Paint mode only", icon='INFO')
            return


        body = _section(l, "nomad_tpo_slots", "Texture Slots", closed=False)
        if body is not None:
            _safe(body, "texture slots",
                  lambda lay: self._slots(lay, context, ipaint))
        body = _section(l, "nomad_tpo_mask", "Masking", closed=True)
        if body is not None:
            _safe(body, "masking",
                  lambda lay: self._masking(lay, context, ipaint))
        body = _section(l, "nomad_tpo_bake", "Bake (Ucupaint)", closed=True)
        if body is not None:
            _safe(body, "bake", lambda lay: self._bake(lay))
        row = l.row()
        row.scale_y = 1.4
        _act(row, "image.save_all_modified", "Save All Images",
             icon='FILE_TICK')

    def _slots(self, lay, context, ipaint):
        _p(lay, ipaint, "mode", text="Mode")
        obj = context.active_object
        mat = obj.active_material if obj else None
        if getattr(ipaint, "mode", '') == 'MATERIAL':
            if mat is None:
                lay.label(text="No active material", icon='INFO')
                return
            row = lay.row()
            row.template_list("TEXTURE_UL_texpaintslots", "", mat,
                              "texture_paint_slots", mat,
                              "paint_active_slot", rows=3)
            col = row.column(align=True)
            if any(_op_exists(c) for c in _REMOVE_SLOT):
                _act(col, _REMOVE_SLOT, "", icon='REMOVE')
            else:
                print("NomadUI: no remove-slot operator found. Similar: "
                      f"{[n for n in dir(bpy.ops.paint) if 'slot' in n]}")
            body = _section(lay, "nomad_tpo_addslot", "Add Slot",
                            closed=True)
            if body is not None:
                grid = body.grid_flow(row_major=True, columns=2,
                                      even_columns=True, align=True)
                grid.scale_y = 1.3
                for ident, name in _slot_types():
                    _dialog_button(grid, name,
                                   "paint.add_texture_paint_slot",
                                   type=ident)
        else:
            lay.template_ID(ipaint, "canvas")
            image_buttons(lay, 'CANVAS')

    def _masking(self, lay, context, ipaint):
        row = lay.row()
        row.scale_y = 1.4
        try:
            row.popover(panel="VIEW3D_PT_overlay_texture_paint",
                        text="Texture Paint Overlays", icon='OVERLAY')
        except (TypeError, RuntimeError, KeyError):
            lay.label(text="Overlay popover not found", icon='INFO')

        for name, text in (("use_occlude", "Occlude"),
                           ("use_backface_culling", "Backface Culling"),
                           ("use_normal_falloff", "Normal Falloff")):
            _p(lay, ipaint, name, text=text)
        if getattr(ipaint, "use_normal_falloff", False):
            _p(lay, ipaint, "normal_angle", text="Angle")

        lay.separator()
        _p(lay, ipaint, "use_cavity", text="Cavity Mask", toggle=True)
        if (getattr(ipaint, "use_cavity", False)
                and hasattr(ipaint, "cavity_curve")):
            try:
                lay.template_curve_mapping(ipaint, "cavity_curve")
            except (TypeError, RuntimeError):
                pass

        lay.separator()
        _p(lay, ipaint, "use_stencil_layer", text="Stencil Mask",
           toggle=True)
        if getattr(ipaint, "use_stencil_layer", False):
            lay.template_ID(ipaint, "stencil_image")
            image_buttons(lay, 'STENCIL')
            row = lay.row(align=True)
            _p(row, ipaint, "invert_stencil", text="Invert", toggle=True)
            _p(row, ipaint, "stencil_color", text="")

    def _bake(self, lay):
        mod = getattr(bpy.ops, "node", None)
        names = sorted(n for n in dir(mod) if n.startswith("y_bake")) \
            if mod is not None else []
        if not names:
            lay.label(text="Ucupaint bake operators not found", icon='INFO')
            return
        col = lay.column()
        col.scale_y = 1.3
        for n in names:
            _dialog_button(col, n[2:].replace("_", " ").title(),
                           f"node.{n}", icon='RENDER_STILL')


# ----------------------------------------------------------------------
# Clone: set source (3D cursor) + paint
# ----------------------------------------------------------------------

class NOMAD_OT_clone_arm(bpy.types.Operator):
    """Arm 'Set Clone': the next tap on the surface places the source."""
    bl_idname = "nomad.clone_arm"
    bl_label = "Set Clone"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        color_overlay.clone_armed = True
        from . import brush_shelf
        brush_shelf.activate_kind('CLONE')
        print("NomadUI: tap the surface to set the clone source")
        return {'FINISHED'}


class NOMAD_PT_tp_clone(bpy.types.Panel):
    bl_label = "Clone"
    bl_idname = "NOMAD_PT_tp_clone"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 10
        col = l.column()
        col.scale_y = 1.5
        col.operator("nomad.clone_arm", text="Set Clone", icon='CURSOR',
                     depress=color_overlay.clone_armed)
        op = col.operator("nomad.brush_kind", text="Paint Clone",
                          icon='AREA_DOCK')
        op.kind = 'CLONE'
        l.label(text="Set Clone: tap the surface for the source",
                icon='INFO')
        ipaint = getattr(context.tool_settings, "image_paint", None)
        if ipaint is not None:
            box = l.box()
            _p(box, ipaint, "use_clone_layer", text="Clone from Image",
               toggle=True)
            if getattr(ipaint, "use_clone_layer", False):
                box.template_ID(ipaint, "clone_image")
                _p(box, ipaint, "clone_alpha", text="Alpha", slider=True)


class NOMAD_PT_tp_options(bpy.types.Panel):
    bl_label = "Texture Paint Options"
    bl_idname = "NOMAD_PT_tp_options"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        ts = context.tool_settings
        ipaint = getattr(ts, "image_paint", None)
        if context.mode != 'PAINT_TEXTURE' or ipaint is None:
            l.label(text="Texture Paint mode only", icon='INFO')
            return
        for name, text in (("seam_bleed", "Bleed"), ("dither", "Dither"),
                           ("use_occlude", "Occlude"),
                           ("use_backface_culling", "Backface Culling")):
            _p(l, ipaint, name, text=text)

        body = _section(l, "nomad_tpopt_ext", "External Editor",
                        closed=False)
        if body is None:
            return
        owner = ipaint if hasattr(ipaint, "screen_grab_size") else ts
        _p(body, owner, "screen_grab_size", text="Screen Grab Size")
        col = body.column()
        col.scale_y = 1.3
        _dialog_button(col, "Quick Edit", "image.project_edit",
                       icon='IMAGE_DATA')
        _dialog_button(col, "Apply", "image.project_apply",
                       icon='FILE_TICK')
        _dialog_button(col, "Camera", "paint.image_from_view",
                       icon='CAMERA_DATA')
        _dialog_button(col, "Apply Camera Image", "paint.project_image",
                       icon='CAMERA_DATA')


# ----------------------------------------------------------------------
# Face selection masking: select options
# ----------------------------------------------------------------------

TP_SELECT = [
    ("Select All", "paint.face_select_all", {"action": 'SELECT'}),
    ("Select None", "paint.face_select_all", {"action": 'DESELECT'}),
    ("Select Invert", "paint.face_select_all", {"action": 'INVERT'}),
    ("Select More", "paint.face_select_more", {}),
    ("Select Less", "paint.face_select_less", {}),
    ("Select Linked", "paint.face_select_linked", {}),
    ("Hide Selected", "paint.face_select_hide", {"unselected": False}),
    ("Hide Unselected", "paint.face_select_hide", {"unselected": True}),
    ("Show All", "paint.face_select_reveal", {}),
]


class NOMAD_PT_tp_select(bpy.types.Panel):
    bl_label = "Select"
    bl_idname = "NOMAD_PT_tp_select"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 10
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            l.label(text="No mesh", icon='INFO')
            return
        row = l.row()
        row.scale_y = 1.5
        row.prop(obj.data, "use_paint_mask", text="Face Selection Masking",
                 toggle=True, icon='FACESEL')
        if not obj.data.use_paint_mask:
            l.label(text="Turn it on to select faces", icon='INFO')
        _actions(l, TP_SELECT, cols=2)


# ----------------------------------------------------------------------
# Stencil controls (drag in the viewport, handled by color_overlay)
# ----------------------------------------------------------------------

class NOMAD_OT_stencil_mode(bpy.types.Operator):
    bl_idname = "nomad.stencil_mode"
    bl_label = "Stencil Control"
    bl_options = {'INTERNAL'}

    mode: bpy.props.EnumProperty(items=[
        ('MOVE', "Move", ""), ('SCALE', "Scale", ""),
        ('ROTATE', "Rotate", ""),
        ('TARGET_PRIMARY', "Texture", ""),
        ('TARGET_SECONDARY', "Mask Texture", "")])

    def execute(self, context):
        co = color_overlay
        if self.mode.startswith("TARGET"):
            co.stencil_target = ('SECONDARY' if self.mode.endswith(
                "SECONDARY") else 'PRIMARY')
        else:
            co.stencil_mode = None if co.stencil_mode == self.mode \
                else self.mode
            if co.stencil_mode:
                co.nav_mode = None
        return {'FINISHED'}


class NOMAD_PT_tp_stencil(bpy.types.Panel):
    bl_label = "Stencil"
    bl_idname = "NOMAD_PT_tp_stencil"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 10
        brush = _brush(context)
        if brush is None:
            l.label(text="No active brush", icon='INFO')
            return
        co = color_overlay
        target = co.stencil_target

        row = l.row(align=True)
        row.scale_y = 1.4
        for mode, label, tgt in (('TARGET_PRIMARY', "Texture", 'PRIMARY'),
                                 ('TARGET_SECONDARY', "Mask Texture",
                                  'SECONDARY')):
            op = row.operator("nomad.stencil_mode", text=label,
                              depress=(target == tgt))
            op.mode = mode

        l.label(text="Tap a mode, then drag in the viewport")
        row = l.row(align=True)
        row.scale_y = 1.5
        for mode, label in (('MOVE', "Move"), ('SCALE', "Scale"),
                            ('ROTATE', "Rotate")):
            op = row.operator("nomad.stencil_mode", text=label,
                              depress=(co.stencil_mode == mode))
            op.mode = mode

        pos_attr, dim_attr, slot = co.stencil_props(brush, target)
        mask = target == 'SECONDARY'
        row = l.row(align=True)
        row.scale_y = 1.3
        _act(row, "brush.stencil_fit_image_aspect", "Fit Image Aspect",
             mask=mask)
        _act(row, "brush.stencil_reset_transform", "Reset Transform",
             mask=mask)

        box = l.box()
        _p(box, brush, pos_attr, text="Position")
        _p(box, brush, dim_attr, text="Size")
        _p(box, slot, "angle", text="Rotation")


CLASSES = (NOMAD_OT_invoke, NOMAD_OT_image_add, NOMAD_OT_brush_kind,
           NOMAD_PT_tp_object, NOMAD_OT_clone_arm, NOMAD_PT_tp_clone,
           NOMAD_PT_tp_options, NOMAD_PT_tp_select, NOMAD_OT_stencil_mode,
           NOMAD_PT_tp_stencil)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    _pending["target"] = None
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass