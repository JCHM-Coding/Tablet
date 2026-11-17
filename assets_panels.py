# Details of the active object asset (mark / preview / metadata). The
# browser itself is the GPU one in asset_gpu.py.
import bpy

from .sculpt_popups import _p, _section
from .sculpt_panels import _act
from .texture_panels import _dialog_button


class NOMAD_OT_material_new(bpy.types.Operator):
    bl_idname = "nomad.material_new"
    bl_label = "New Material"
    bl_description = "Create a material and assign it to the active slot"
    bl_options = {'REGISTER', 'UNDO'}

    duplicate: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        obj = context.active_object
        if obj is None or not hasattr(obj.data, "materials"):
            return {'CANCELLED'}
        cur = obj.active_material
        if self.duplicate and cur is not None:
            ma = cur.copy()
        else:
            ma = bpy.data.materials.new("Material")
            if obj.type in {'GREASEPENCIL', 'GPENCIL'}:
                try:
                    bpy.data.materials.create_gpencil_data(ma)
                except (AttributeError, RuntimeError):
                    pass
            else:
                try:
                    ma.use_nodes = True
                except (AttributeError, RuntimeError):
                    pass
        slots = len(obj.material_slots)
        if slots and obj.active_material_index < slots:
            obj.active_material = ma          # the active slot
        else:
            obj.data.materials.append(ma)
            obj.active_material_index = len(obj.material_slots) - 1
        return {'FINISHED'}


class NOMAD_PT_assets(bpy.types.Panel):
    bl_label = "Asset Details"
    bl_idname = "NOMAD_PT_assets"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        if context.mode != 'OBJECT':
            l.label(text="Object mode only", icon='INFO')
            return
        obj = context.active_object
        body = _section(l, "nomad_as_active", "Active Asset", closed=False)
        if body is None:
            return
        if obj is None:
            body.label(text="No active object", icon='INFO')
            return
        ad = obj.asset_data
        row = body.row(align=True)
        op = row.operator("nomad.outliner_asset", text="Mark Asset",
                          icon='ASSET_MANAGER')
        op.action, op.what = 'MARK', 'OBJECT'
        op = row.operator("nomad.outliner_asset", text="Clear Asset")
        op.action, op.what = 'CLEAR', 'OBJECT'
        if ad is None:
            body.label(text="This object is not an asset", icon='INFO')
            return

        prev = getattr(obj, "preview", None)
        if prev is not None and prev.icon_id:
            body.template_icon(icon_value=prev.icon_id, scale=6.0)
        col = body.column()
        col.scale_y = 1.3
        col.context_pointer_set("id", obj)
        _act(col, ("ed.lib_id_generate_preview_from_object",
                   "ed.lib_id_generate_preview"), "Generate Preview",
             icon='RENDER_STILL')
        _dialog_button(col, "Load Custom Preview",
                       "ed.lib_id_load_custom_icon", icon='FILE_IMAGE')
        _act(col, "ed.lib_id_remove_preview", "Remove Preview", icon='X')

        for name in ("description", "author", "license", "copyright"):
            _p(body, ad, name)
        if hasattr(ad, "tags"):
            body.label(text="Tags")
            row = body.row()
            try:
                row.template_list("ASSETBROWSER_UL_metadata_tags", "", ad,
                                   "tags", ad, "active_tag", rows=3)
            except (TypeError, RuntimeError):
                row.label(text="Tag list not available")
            col = row.column(align=True)
            _act(col, "asset.tag_add", "", icon='ADD')
            _act(col, "asset.tag_remove", "", icon='REMOVE')


CLASSES = (NOMAD_PT_assets, NOMAD_OT_material_new)



def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass