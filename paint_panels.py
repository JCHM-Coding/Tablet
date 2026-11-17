# Vertex Paint / Weight Paint popups: selection mode, select tools,
# attributes, operators, vertex groups and weight sampling.
import bpy
from . import tool_sidebar as ts
from .sculpt_popups import _p, _section
from .sculpt_panels import _act, _actions, _safe, _automasking, _op_exists
from .texture_panels import _dialog_button
from .object_panels import _popover


def mask_active(context):
    obj = context.active_object
    me = getattr(obj, "data", None)
    return bool(obj is not None and obj.type == 'MESH' and (
        getattr(me, "use_paint_mask", False)
        or getattr(me, "use_paint_mask_vertex", False)))


def _mesh(context):
    obj = context.active_object
    if obj is not None and obj.type == 'MESH':
        return obj, obj.data
    return None, None


def _menu_section(layout, key, title, menu):
    body = _section(layout, key, title, closed=True)
    if body is None:
        return
    if hasattr(bpy.types, menu):
        body.menu_contents(menu)
    else:
        body.label(text=f"{menu} not found", icon='INFO')


# ----------------------------------------------------------------------
# Selection mode (paint / face / vertex) + select tools
# ----------------------------------------------------------------------

class NOMAD_OT_paint_mask_mode(bpy.types.Operator):
    bl_idname = "nomad.paint_mask_mode"
    bl_label = "Selection Mode"
    bl_options = {'INTERNAL'}

    mode: bpy.props.EnumProperty(items=[
        ('PAINT', "Paint", ""), ('FACE', "Face Selection", ""),
        ('VERTEX', "Vertex Selection", "")])

    def execute(self, context):
        obj, me = _mesh(context)
        if me is None:
            return {'CANCELLED'}
        try:
            if self.mode == 'PAINT':
                me.use_paint_mask = False
                me.use_paint_mask_vertex = False
            elif self.mode == 'FACE':
                me.use_paint_mask_vertex = False
                me.use_paint_mask = True
            else:
                me.use_paint_mask = False
                me.use_paint_mask_vertex = True
        except (AttributeError, RuntimeError) as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class NOMAD_PT_paint_mode(bpy.types.Panel):
    bl_label = "Selection Mode"
    bl_idname = "NOMAD_PT_paint_mode"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 8
        obj, me = _mesh(context)
        if me is None:
            l.label(text="No active mesh", icon='INFO')
            return
        face = getattr(me, "use_paint_mask", False)
        vert = getattr(me, "use_paint_mask_vertex", False)
        for mode, text, icon, on in (
                ('PAINT', "Paint", 'BRUSH_DATA', not face and not vert),
                ('FACE', "Face Selection", 'FACESEL', face),
                ('VERTEX', "Vertex Selection", 'VERTEXSEL', vert)):
            row = l.row()
            row.scale_y = 1.5
            op = row.operator("nomad.paint_mask_mode", text=text, icon=icon,
                              depress=on)
            op.mode = mode


class NOMAD_PT_paint_select(bpy.types.Panel):
    bl_label = "Select"
    bl_idname = "NOMAD_PT_paint_select"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 10
        if not mask_active(context):
            l.label(text="Turn on face or vertex selection", icon='INFO')
            return
        members = ts._members(context, "select")
        if not members:
            members = [ts._Fake(i, lbl, icon) for i, lbl, icon in
                       ts.FALLBACK["select"]]
        ts.tool_buttons(l, context, members)

        obj, me = _mesh(context)
        menu = ("VIEW3D_MT_select_paint_mask"
                if getattr(me, "use_paint_mask", False)
                else "VIEW3D_MT_select_paint_mask_vertex")
        _menu_section(l, "nomad_psel_menu", "Select Menu", menu)


# ----------------------------------------------------------------------
# Vertex Paint: attributes + operators
# ----------------------------------------------------------------------

class NOMAD_PT_vp_attributes(bpy.types.Panel):
    bl_label = "Attributes"
    bl_idname = "NOMAD_PT_vp_attributes"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        obj, me = _mesh(context)
        if me is None:
            l.label(text="No active mesh", icon='INFO')
            return
        body = _section(l, "nomad_vpa_color", "Color Attributes",
                        closed=False)
        if body is not None:
            _safe(body, "color attributes",
                  lambda lay: self._attrs(lay, me))
        body = _section(l, "nomad_vpa_auto", "Automasking", closed=True)
        if body is not None:
            _safe(body, "automasking",
                  lambda lay: _automasking(lay, context))
        _popover(l, "VIEW3D_PT_overlay_vertex_paint",
                 "Vertex Paint Overlays", 'OVERLAY')

    def _attrs(self, lay, me):
        ca = getattr(me, "color_attributes", None)
        if ca is None:
            lay.label(text="Color attributes not available", icon='INFO')
            return
        row = lay.row()
        row.template_list("MESH_UL_color_attributes", "", me,
                          "color_attributes", ca, "active_color_index",
                          rows=3)
        col = row.column(align=True)
        _dialog_button(col, "", "geometry.color_attribute_add", icon='ADD')
        _act(col, "geometry.color_attribute_remove", "", icon='REMOVE')
        col.separator()
        try:
            col.menu("MESH_MT_color_attribute_context_menu",
                     icon='DOWNARROW_HLT', text="")
        except (TypeError, RuntimeError, KeyError):
            pass
        active = getattr(ca, "active_color", None)
        if active is not None:
            _p(lay, active, "name", text="Name")


VP_PAINT_OPS = [
    ("Set Vertex Colors", "paint.vertex_color_set"),
    ("Smooth Vertex Colors", "paint.vertex_color_smooth"),
    ("Dirty Vertex Colors", "paint.vertex_color_dirt"),
    ("Invert", "paint.vertex_color_invert"),
    ("Levels", "paint.vertex_color_levels"),
    ("Hue/Saturation/Value", "paint.vertex_color_hsv"),
    ("Brightness/Contrast", "paint.vertex_color_brightness_contrast"),
]


def _bake(lay):
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


class NOMAD_PT_vp_operators(bpy.types.Panel):
    bl_label = "Operators"
    bl_idname = "NOMAD_PT_vp_operators"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        body = _section(l, "nomad_vpo_paint", "Paint", closed=False)
        if body is not None:
            def _paint(lay):
                col = lay.column()
                col.scale_y = 1.3
                for text, op in VP_PAINT_OPS:
                    if _op_exists(op):
                        _dialog_button(col, text, op)
                    else:
                        col.label(text=f"{text} (n/a)")
                _act(col, "nomad.click_action", "Sample Color (tap)",
                     icon='EYEDROPPER', action='SAMPLE_COLOR')
            _safe(body, "paint operators", _paint)
        body = _section(l, "nomad_vpo_bake", "Bake (Ucupaint)", closed=True)
        if body is not None:
            _safe(body, "bake", _bake)


# ----------------------------------------------------------------------
# Weight Paint: sample, vertex groups, operators
# ----------------------------------------------------------------------

class NOMAD_PT_wp_sample(bpy.types.Panel):
    bl_label = "Sample"
    bl_idname = "NOMAD_PT_wp_sample"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 10
        col = l.column()
        col.scale_y = 1.5
        _act(col, "nomad.click_action", "Sample Weight (tap)",
             icon='EYEDROPPER', action='WEIGHT_SAMPLE')
        _act(col, "nomad.click_action", "Sample Vertex Group (tap)",
             icon='GROUP_VERTEX', action='WEIGHT_SAMPLE_GROUP')
        l.label(text="Tap a button, then tap the surface", icon='INFO')


class NOMAD_PT_wp_operators(bpy.types.Panel):
    bl_label = "Operators"
    bl_idname = "NOMAD_PT_wp_operators"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        _menu_section(l, "nomad_wpo_weights", "Weights",
                      "VIEW3D_MT_paint_weight")

        obj, me = _mesh(context)
        body = _section(l, "nomad_wpo_select", "Select", closed=True)
        if body is not None:
            if getattr(me, "use_paint_mask", False):
                body.menu_contents("VIEW3D_MT_select_paint_mask")
            elif getattr(me, "use_paint_mask_vertex", False):
                body.menu_contents("VIEW3D_MT_select_paint_mask_vertex")
            else:
                body.label(text="Turn on face or vertex selection",
                           icon='INFO')

        body = _section(l, "nomad_wpo_options", "Options", closed=True)
        if body is not None:
            ts_ = context.tool_settings
            for name, text in WP_OPTIONS:
                _p(body, ts_, name, text=text, toggle=True)
            _p(body, ts_, "vertex_group_user", text="Restrict")

        body = _section(l, "nomad_wpo_snap", "Snapping", closed=True)
        if body is not None:
            _popover(body, "VIEW3D_PT_snapping", "Snapping", 'SNAP_ON')

        body = _section(l, "nomad_wpo_auto", "Automasking", closed=True)
        if body is not None:
            _safe(body, "automasking",
                  lambda lay: _automasking(lay, context))


WP_OPTIONS = (("use_auto_normalize", "Auto Normalize"),
              ("use_lock_relative", "Lock-Relative"),
              ("use_multipaint", "Multi-Paint"))


class NOMAD_PT_wp_operators(bpy.types.Panel):
    bl_label = "Operators"
    bl_idname = "NOMAD_PT_wp_operators"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        _menu_section(l, "nomad_wpo_weights", "Weights",
                      "VIEW3D_MT_paint_weight")

        obj, me = _mesh(context)
        body = _section(l, "nomad_wpo_select", "Select", closed=True)
        if body is not None:
            if getattr(me, "use_paint_mask", False):
                body.menu_contents("VIEW3D_MT_select_paint_mask")
            elif getattr(me, "use_paint_mask_vertex", False):
                body.menu_contents("VIEW3D_MT_select_paint_mask_vertex")
            else:
                body.label(text="Turn on face or vertex selection",
                           icon='INFO')

        body = _section(l, "nomad_wpo_options", "Options", closed=True)
        if body is not None:
            ts_ = context.tool_settings
            for name, text in WP_OPTIONS:
                _p(body, ts_, name, text=text, toggle=True)
            _p(body, ts_, "vertex_group_user", text="Restrict")


CLASSES = (NOMAD_OT_paint_mask_mode, NOMAD_PT_paint_mode,
           NOMAD_PT_paint_select, NOMAD_PT_vp_attributes,
           NOMAD_PT_vp_operators, NOMAD_PT_wp_sample,
           NOMAD_PT_wp_operators)

def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass