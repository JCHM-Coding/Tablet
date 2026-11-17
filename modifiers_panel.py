# Modifiers compacto: pila + opciones esenciales por tipo.
# Panel VIEW_3D: funciona en popup con override de viewport.
import bpy


# Opciones esenciales por tipo (None = "ver en Properties")
# Opciones esenciales por tipo (None = "ver en Properties")
_OPTIONS = {
    'MIRROR': ("use_axis", "mirror_object", "merge_threshold"),
    'SUBSURF': ("subdivision_type", "levels", "render_levels"),
    'MULTIRES': ("levels", "sculpt_levels", "render_levels"),
    'BEVEL': ("offset_type", "width", "segments", "limit_method",
              "profile"),
    'BOOLEAN': ("operation", "solver", "operand_type", "object",
                "collection"),
    'SOLIDIFY': ("thickness", "offset", "use_rim"),
    'ARRAY': ("fit_type", "count", "use_constant_offset",
              "constant_offset_displace", "use_merge_vertices"),
    'REMESH': ("mode", "octree_depth", "scale", "sharpness"),
    'DECIMATE': ("decimate_type", "ratio", "iterations",
                 "angle_limit"),
    'ARMATURE': ("object", "vertex_group", "use_deform_preserve_volume"),
    'LATTICE': ("object", "strength"),
    'CURVE': ("object", "deform_axis"),
    'SHRINKWRAP': ("wrap_method", "target", "offset"),
    'SIMPLE_DEFORM': ("deform_method", "deform_axis", "angle",
                      "factor"),
    'SCREW': ("angle", "screw_offset", "iterations", "steps"),
    'HOOK': ("object", "strength", "falloff_radius"),
    'DISPLACE': ("texture", "strength", "mid_level", "direction"),
    'NODES': ("node_group",),
    'SKIN': ("use_smooth_shade",),
    'MASK': ("mode", "texture", "vertex_group"),
    'SMOOTH': ("factor", "iterations", "vertex_group"),
    'WELD': ("mode", "merge_threshold"),
    'WIREFRAME': ("thickness", "offset", "use_replace"),
    'WAVE': ("use_x", "use_y", "time_offset", "width", "height",
             "speed"),
    'WARP': ("object_from", "object_to", "strength",
             "falloff_radius"),
    'WEIGHTED_NORMAL': ("mode", "weight", "keep_sharp"),
    'UV_WARP': ("axis_u", "axis_v", "object", "center"),
    'UV_PROJECT': ("uv_layer", "aspect", "scale_x", "scale_y"),
    'CAST': ("cast_type", "factor", "radius", "size"),
    'CORRECTIVE_SMOOTH': ("factor", "iterations", "smooth_type"),
    'BUILD': ("frame_start", "frame_duration", "use_reverse"),
    'COLLISION': ("permeability", "damping"),
    'EXPLODE': ("particle_uv", "show_unborn", "show_alive"),
    'LAPLACIANDEFORM': ("iterations", "lambda_factor"),
    'LAPLACIANSMOOTH': ("lambda_factor", "iterations"),
    'MESH_CACHE': ("cache_format", "filepath", "frame_start"),
    'MESH_DEFORM': ("object", "precision", "use_dynamic_bind"),
    'MESH_SEQUENCE_CACHE': ("cache_format", "filepath"),
    'NORMAL_EDIT': ("mode", "target", "mix_mode", "mix_factor"),
    'OCEAN': ("geometry_mode", "size", "chop_amount", "wind_velocity"),
    'PARTICLE_INSTANCE': ("object", "particle_system_index", "axis"),
    'SURFACE_DEFORM': ("target", "falloff_radius", "strength"),
    'TRIANGULATE': ("quad_method", "ngon_method", "min_vertices"),
    'VERTEX_WEIGHT_EDIT': ("mode", "default_weight",
                           "falloff_type"),
    'VERTEX_WEIGHT_MIX': ("mode", "default_weight", "falloff_type"),
    'VERTEX_WEIGHT_PROXIMITY': ("proximity_mode", "min_dist",
                                "max_dist"),
    # Fisica y simualciones: sin opciones compactas por ahora
    # (CLOTH, FLUID, SOFT_BODY, PARTICLE_SYSTEM, DYNAMIC_PAINT)
    # -> muestran "Mas opciones en Properties".
}

_MOD_TYPES = {'MESH', 'CURVE', 'FONT', 'SURFACE', 'LATTICE',
              'GREASEPENCIL', 'GPENCIL', 'CURVES', 'POINTCLOUD', 'VOLUME'}
_MOD_SKIP = {"rna_type", "name", "type", "is_override_data",
             "persistent_uid", "show_expanded", "show_viewport",
             "show_render", "show_in_editmode", "show_on_cage"}


def _generic(layout, mod):
    """Every editable property, for modifier types without a table."""
    for prop in mod.bl_rna.properties:
        ident = prop.identifier
        if ident in _MOD_SKIP or prop.is_readonly or prop.is_hidden:
            continue
        try:
            layout.prop(mod, ident)
        except (TypeError, RuntimeError):
            pass


def _with_object_mode(context, obj, fn):
    """Ejecuta fn() en Object Mode y restaura modo/seleccion."""
    mode = context.mode
    selected = list(context.selected_objects)
    try:
        if mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for s in context.selected_objects:
            s.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        fn()
    finally:
        try:
            if mode != 'OBJECT':
                bpy.ops.object.mode_set(
                    mode='EDIT' if mode.startswith('EDIT_') else mode)
            for s in selected:
                s.select_set(True)
        except RuntimeError:
            pass


class NOMAD_OT_modifier_action(bpy.types.Operator):
    bl_idname = "nomad.modifier_action"
    bl_label = "Modifier Action"
    bl_options = {'REGISTER', 'UNDO'}

    index: bpy.props.IntProperty()
    action: bpy.props.EnumProperty(items=[
        ('UP', "Up", ""), ('DOWN', "Down", ""),
        ('REMOVE', "Remove", ""), ('APPLY', "Apply", ""),
        ('TOGGLE', "Toggle Viewport", "")])
    select: bpy.props.BoolProperty(default=False)

    def execute(self, context):
        obj = context.active_object
        if obj is None:
            return {'CANCELLED'}
        mods = obj.modifiers
        i = self.index
        if i < 0 or i >= len(mods):
            return {'CANCELLED'}
        mod = mods[i]
        name = mod.name

        if self.select:
            context.scene.nomad_mod_index = i
        elif self.action == 'TOGGLE':
            mod.show_viewport = not mod.show_viewport
        elif self.action == 'REMOVE':
            mods.remove(mod)
            context.scene.nomad_mod_index = min(i, len(mods) - 1)
        else:
            def _run():
                if self.action == 'APPLY':
                    bpy.ops.object.modifier_apply(modifier=name)
                elif self.action == 'UP' and i > 0:
                    bpy.ops.object.modifier_move_up(modifier=name)
                elif self.action == 'DOWN' and i < len(mods) - 1:
                    bpy.ops.object.modifier_move_down(modifier=name)
            _with_object_mode(context, obj, _run)
        return {'FINISHED'}


def _modifiers(op, area):
    from .sculpt_popups import open_panel_deferred
    open_panel_deferred("NOMAD_PT_modifiers")
def vertex_groups_ui(layout, context, obj):
    from .sculpt_panels import _act
    if obj is None or obj.type not in {'MESH', 'LATTICE',
                                       'GREASEPENCIL', 'GPENCIL'}:
        layout.label(text="No vertex groups for this object", icon='INFO')
        return
    vg = obj.vertex_groups
    row = layout.row()
    row.template_list("MESH_UL_vgroups", "", obj, "vertex_groups", vg,
                      "active_index", rows=4)
    col = row.column(align=True)
    _act(col, "object.vertex_group_add", "", icon='ADD')
    _act(col, "object.vertex_group_remove", "", icon='REMOVE')
    col.separator()
    try:
        col.menu("MESH_MT_vertex_group_context_menu",
                 icon='DOWNARROW_HLT', text="")
    except (TypeError, RuntimeError, KeyError):
        pass
    col.separator()
    _act(col, "object.vertex_group_move", "", icon='TRIA_UP',
         direction='UP')
    _act(col, "object.vertex_group_move", "", icon='TRIA_DOWN',
         direction='DOWN')

    if obj.mode == 'EDIT' and len(vg):
        row = layout.row(align=True)
        _act(row, "object.vertex_group_assign", "Assign")
        _act(row, "object.vertex_group_remove_from", "Remove")
        row = layout.row(align=True)
        _act(row, "object.vertex_group_select", "Select")
        _act(row, "object.vertex_group_deselect", "Deselect")
        layout.prop(context.tool_settings, "vertex_group_weight",
                    text="Weight")


class NOMAD_PT_modifiers(bpy.types.Panel):
    bl_label = "Modifiers"
    bl_idname = "NOMAD_PT_modifiers"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        layout = self.layout
        layout.ui_units_x = 12
        obj = context.active_object
        if obj is not None and obj.type in _MOD_TYPES:
            self._modifiers(layout, context, obj)
        else:
            layout.label(text="No compatible object for modifiers",
                         icon='INFO')

        from .sculpt_popups import _section
        body = _section(layout, "nomad_mod_vgroups", "Vertex Groups",
                        closed=True)
        if body is not None:
            vertex_groups_ui(body, context, obj)

    def _modifiers(self, layout, context, obj):
        layout.operator("wm.call_menu", text="Add",
                        icon='ADD').name = "OBJECT_MT_modifier_add"
        layout.separator()

        mods = obj.modifiers
        if not mods:
            layout.label(text="No modifiers", icon='INFO')
            return

        idx = min(context.scene.nomad_mod_index, len(mods) - 1)

        box = layout.box()
        for i, mod in enumerate(mods):
            row = box.row(align=True)
            row.alert = not mod.show_viewport
            op = row.operator("nomad.modifier_action", text=mod.name,
                              depress=(i == idx))
            op.select = True
            op.index = i
            for action, icon in (
                    ('UP', 'TRIA_UP'), ('DOWN', 'TRIA_DOWN'),
                    ('TOGGLE', 'HIDE_OFF' if mod.show_viewport
                     else 'HIDE_ON'),
                    ('APPLY', 'CHECKMARK'), ('REMOVE', 'X')):
                op = row.operator("nomad.modifier_action", text="",
                                  icon=icon)
                op.action = action
                op.index = i

        mod = mods[idx]
        layout.separator()
        box = layout.box()
        box.label(text=mod.name, icon='MODIFIER')
        props = _OPTIONS.get(mod.type)
        if props:
            for p in props:
                try:
                    box.prop(mod, p)
                except (TypeError, RuntimeError):
                    pass
        else:
            _generic(box, mod)

CLASSES = (NOMAD_OT_modifier_action, NOMAD_PT_modifiers)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    if not hasattr(bpy.types.Scene, "nomad_mod_index"):
        bpy.types.Scene.nomad_mod_index = bpy.props.IntProperty(
            name="Modifier Index", default=0, min=0)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, "nomad_mod_index"):
        del bpy.types.Scene.nomad_mod_index