# Curve / Surface: Data popup (Object + Edit) and Edit-mode Operators.
import bpy
from .sculpt_popups import _p, _section
from .sculpt_panels import _safe
from .paint_panels import _menu_section

CURVE_MENUS = {
    'EDIT_CURVE': [("Curve", "VIEW3D_MT_edit_curve"),
                   ("Control Points", "VIEW3D_MT_edit_curve_ctrlpoints"),
                   ("Segments", "VIEW3D_MT_edit_curve_segments")],
    'EDIT_SURFACE': [("Surface", "VIEW3D_MT_edit_surface"),
                     ("Control Points", "VIEW3D_MT_edit_curve_ctrlpoints"),
                     ("Segments", "VIEW3D_MT_edit_curve_segments")],
}

SHAPE = ("dimensions", "resolution_u", "resolution_v",
         "render_resolution_u", "render_resolution_v", "twist_mode",
         "twist_smooth", "fill_mode", "use_fill_deform", "use_radius",
         "use_stretch", "use_deform_bounds")
TEXSPACE = ("use_auto_texspace", "texspace_location", "texspace_size")
GEOM = (("Modification", ("offset", "extrude")),
        ("Taper", ("taper_object", "taper_radius_mode", "use_map_taper")),
        ("Bevel", ("bevel_mode", "bevel_depth", "bevel_resolution",
                   "bevel_object", "use_fill_caps")))


class NOMAD_PT_curve_ops(bpy.types.Panel):
    bl_label = "Operators"
    bl_idname = "NOMAD_PT_curve_ops"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        menus = CURVE_MENUS.get(context.mode)
        if not menus:
            l.label(text="Curve or Surface edit mode only", icon='INFO')
            return
        for title, menu in menus:
            _menu_section(l, f"nomad_cvo_{menu}", title, menu)


class NOMAD_PT_curve_data(bpy.types.Panel):
    bl_label = "Data"
    bl_idname = "NOMAD_PT_curve_data"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        obj = context.active_object
        if obj is None or obj.type not in {'CURVE', 'SURFACE'}:
            l.label(text="Select a curve or surface", icon='INFO')
            return
        data = obj.data

        body = _section(l, "nomad_cvd_shape", "Shape", closed=True)
        if body is not None:
            def _shape(lay):
                for name in SHAPE:
                    _p(lay, data, name)
            _safe(body, "shape", _shape)

        body = _section(l, "nomad_cvd_tex", "Texture Space", closed=True)
        if body is not None:
            def _tex(lay):
                for name in TEXSPACE:
                    _p(lay, data, name)
            _safe(body, "texture space", _tex)

        body = _section(l, "nomad_cvd_geo", "Geometry", closed=True)
        if body is not None:
            def _geo(lay):
                for title, names in GEOM:
                    lay.label(text=title)
                    for name in names:
                        _p(lay, data, name)
            _safe(body, "geometry", _geo)


CLASSES = (NOMAD_PT_curve_ops, NOMAD_PT_curve_data)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass