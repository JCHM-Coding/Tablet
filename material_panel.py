# Popup de materiales (botón ◈ de la barra superior).
import bpy
from .sculpt_popups import _p, _section, open_panel_deferred  # noqa: F401


def _node_input(layout, mat, name):
    """Dibuja una entrada del nodo Material Output (Surface, Volume,
    Displacement, Thickness) con el selector de shader nativo."""
    nt = getattr(mat, "node_tree", None)
    if nt is None:
        if hasattr(mat, "use_nodes"):
            layout.prop(mat, "use_nodes", text="Usar nodos", toggle=True)
        else:
            layout.label(text="Sin nodos", icon='INFO')
        return
    node = None
    for target in ('EEVEE', 'ALL'):
        try:
            node = nt.get_output_node(target)
        except (RuntimeError, TypeError):
            node = None
        if node is not None:
            break
    inp = node.inputs.get(name) if node is not None else None
    if inp is None:
        layout.label(text=f"Sin entrada «{name}»", icon='INFO')
        return
    try:
        layout.template_node_view(nt, node, inp)
    except (TypeError, RuntimeError) as exc:
        layout.label(text=f"{name}: {exc}", icon='ERROR')


class NOMAD_PT_material(bpy.types.Panel):
    bl_label = "Material"
    bl_idname = "NOMAD_PT_material"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        obj = context.active_object
        if obj is None or obj.type in {'EMPTY', 'CAMERA', 'LIGHT',
                                       'ARMATURE', 'LIGHT_PROBE',
                                       'SPEAKER'}:
            l.label(text="No compatible object", icon='INFO')
            return

        mat = obj.active_material

        # --- Slots + actions ---
        row = l.row()
        row.template_list("MATERIAL_UL_matslots", "", obj,
                          "material_slots", obj, "active_material_index",
                          rows=4)
        col = row.column(align=True)
        col.scale_y = 1.3
        col.operator("object.material_slot_add", icon='ADD', text="")
        col.operator("object.material_slot_remove", icon='REMOVE', text="")
        col.separator()
        col.context_pointer_set("material", mat)
        col.operator("material.copy", icon='COPYDOWN', text="")
        col.operator("material.paste", icon='PASTEDOWN', text="")
        col.separator()
        op = col.operator("object.material_slot_move", icon='TRIA_UP',
                          text="")
        op.direction = 'UP'
        op = col.operator("object.material_slot_move", icon='TRIA_DOWN',
                          text="")
        op.direction = 'DOWN'
        col.separator()
        col.menu("MATERIAL_MT_context_menu", icon='DOWNARROW_HLT', text="")

        if obj.mode == 'EDIT':
            r = l.row(align=True)
            r.operator("object.material_slot_assign", text="Assign")
            r.operator("object.material_slot_select", text="Select")
            r.operator("object.material_slot_deselect", text="Deselect")
        l.operator("nomad.editor_switch", text="Shader Editor",
                   icon='NODE_MATERIAL').which = 'SHADER'
        row = l.row(align=True)
        row.template_ID(obj, "active_material")
        op = row.operator("nomad.material_new",
                          text="New" if mat is None else "",
                          icon='ADD' if mat is None else 'DUPLICATE')
        op.duplicate = mat is not None

        if mat is None:
            l.label(text="No material in this slot", icon='MATERIAL')
            return

        if getattr(mat, "is_grease_pencil", False):
            self._grease_pencil(l, mat)
            return

        # --- Surface (no preview) ---
        l.label(text="Surface")
        _node_input(l, mat, "Surface")

        more = _section(l, "nomad_mat_more", "More Settings", closed=True)
        if more is None:
            return

        b = _section(more, "nomad_mat_volume", "Volume", closed=True)
        if b is not None:
            _node_input(b, mat, "Volume")

        b = _section(more, "nomad_mat_disp", "Displacement", closed=True)
        if b is not None:
            _node_input(b, mat, "Displacement")
            _p(b, mat, "displacement_method", text="Method")

        b = _section(more, "nomad_mat_thick", "Thickness", closed=True)
        if b is not None:
            _node_input(b, mat, "Thickness")
            _p(b, mat, "thickness_mode", text="Mode")

        b = _section(more, "nomad_mat_settings", "Settings", closed=True)
        if b is not None:
            for name in ("surface_render_method", "blend_method",
                         "use_backface_culling",
                         "use_backface_culling_shadow",
                         "use_backface_culling_lightprobe_volume",
                         "use_transparency_overlap",
                         "use_transparent_shadow",
                         "volume_intersection_method", "pass_index"):
                _p(b, mat, name)

        b = _section(more, "nomad_mat_lineart", "Line Art", closed=True)
        if b is not None:
            la = getattr(mat, "lineart", None)
            if la is None:
                b.label(text="No Line Art", icon='INFO')
            else:
                _p(b, la, "use_material_mask", text="Mask")
                if getattr(la, "use_material_mask", False):
                    r = b.row(align=True)
                    for i in range(8):
                        r.prop(la, "use_material_mask_bits", index=i,
                               text="", toggle=True)
                _p(b, la, "mat_occlusion", text="Occlusion")
                _p(b, la, "use_intersection_priority",
                   text="Intersection Priority")
                if getattr(la, "use_intersection_priority", False):
                    _p(b, la, "intersection_priority", text="Priority")

        b = _section(more, "nomad_mat_viewport", "Viewport Display",
                     closed=True)
        if b is not None:
            _p(b, mat, "diffuse_color", text="Color")
            _p(b, mat, "metallic", text="Metallic")
            _p(b, mat, "roughness", text="Roughness")

    def _grease_pencil(self, l, mat):
        gp = getattr(mat, "grease_pencil", None)
        if gp is None:
            l.label(text="No Grease Pencil settings", icon='INFO')
            return

        body = _section(l, "nomad_mat_gp_stroke", "Stroke", closed=False)
        if body is not None:
            _p(body, gp, "show_stroke", text="Show Stroke", toggle=True)
            _p(body, gp, "mode", text="Line Type")
            _p(body, gp, "stroke_style", text="Style")
            if getattr(gp, "stroke_style", 'SOLID') == 'TEXTURE':
                _p(body, gp, "stroke_image", text="Image")
                _p(body, gp, "use_stroke_pattern", text="Use As Pattern")
                _p(body, gp, "mix_stroke_factor", text="Mix Factor")
            _p(body, gp, "color", text="Color")
            _p(body, gp, "use_stroke_holdout", text="Holdout")

        body = _section(l, "nomad_mat_gp_fill", "Fill", closed=False)
        if body is not None:
            _p(body, gp, "show_fill", text="Show Fill", toggle=True)
            style = getattr(gp, "fill_style", 'SOLID')
            _p(body, gp, "fill_style", text="Style")
            if style == 'GRADIENT':
                _p(body, gp, "gradient_type", text="Type")
                _p(body, gp, "fill_color", text="Color")
                _p(body, gp, "mix_color", text="Secondary")
                _p(body, gp, "mix_factor", text="Mix Factor")
            elif style == 'TEXTURE':
                _p(body, gp, "fill_image", text="Image")
                _p(body, gp, "texture_offset", text="Offset")
                _p(body, gp, "texture_scale", text="Scale")
                _p(body, gp, "texture_angle", text="Rotation")
            else:
                _p(body, gp, "fill_color", text="Color")
            _p(body, gp, "use_fill_holdout", text="Holdout")

        body = _section(l, "nomad_mat_gp_settings", "Settings",
                        closed=True)
        if body is not None:
            for name in ("alignment_mode", "pass_index",
                         "use_overlap_strokes", "pixel_size"):
                _p(body, gp, name)


CLASSES = (NOMAD_PT_material,)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)