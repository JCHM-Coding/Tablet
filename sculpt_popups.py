# Sculpt sidebar popups: Symmetry and Dyntopo/Remesh.
# Paneles VIEW_3D/WINDOW, se abren con call_panel desde un timer.
import bpy


def _p(layout, owner, name, **kw):
    """layout.prop solo si la propiedad existe en esta build."""
    if owner is not None and hasattr(owner, name):
        layout.prop(owner, name, **kw)
        return True
    return False

def _mesh(context):
    obj = context.active_object
    if obj is not None and obj.type == 'MESH':
        return obj, obj.data
    return None, None

def _section(layout, key, title, closed=False):
    """Sección plegable (layout.panel, 4.1+). Devuelve el layout del
    cuerpo, o None si está plegada. Fallback a box en builds sin panel()."""
    if hasattr(layout, "panel"):
        header, body = layout.panel(key, default_closed=closed)
        header.label(text=title)
        return body
    box = layout.box()
    box.label(text=title)
    return box


def open_panel_deferred(panel_name, keep_open=True):
    """Abre un panel popup FUERA del modal. Re-busca el área al momento
    (nunca usa referencias guardadas). keep_open=False: el popup se cierra
    al pulsar un botón (el siguiente toque ya llega al viewport)."""
    def _run():
        try:
            C = bpy.context
            area = region = None
            for win in C.window_manager.windows:
                for a in win.screen.areas:
                    if a.type == 'VIEW_3D':
                        r = next((r for r in a.regions
                                  if r.type == 'WINDOW'), None)
                        if r is not None:
                            area, region = a, r
                            break
                if area:
                    break
            if area is None:
                return None
            with C.temp_override(window=win, area=area, region=region):
                bpy.ops.wm.call_panel('INVOKE_DEFAULT', name=panel_name,
                                      keep_open=keep_open)
        except (RuntimeError, AttributeError, ReferenceError) as exc:
            print(f"NomadUI popup {panel_name}: {exc}")
        return None
    try:
        bpy.app.timers.register(_run, first_interval=0.01)
    except RuntimeError:
        pass




class NOMAD_PT_symmetry(bpy.types.Panel):
    bl_label = "Symmetry"
    bl_idname = "NOMAD_PT_symmetry"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        obj, me = _mesh(context)
        if me is None:
            l.label(text="No active mesh", icon='INFO')
            return

        if context.mode != 'SCULPT':
            l.label(text="Mirror")
            row = l.row(align=True)
            row.scale_y = 1.4
            _p(row, me, "use_mirror_x", text="X", toggle=True)
            _p(row, me, "use_mirror_y", text="Y", toggle=True)
            _p(row, me, "use_mirror_z", text="Z", toggle=True)
            if context.mode == 'PAINT_WEIGHT':
                _p(l, me, "use_mirror_vertex_groups",
                   text="Mirror Vertex Groups", toggle=True)
            _p(l, me, "use_mirror_topology", text="Topology Mirror",
               toggle=True)
            return

        sc = context.tool_settings.sculpt
        cls = getattr(bpy.types, "VIEW3D_PT_sculpt_symmetry", None)
        if cls is not None:
            from .render_view_panels import _draw_native
            _draw_native(l, cls, context, "", flat=True)
        else:
            l.label(text="Mirror")
            row = l.row(align=True)
            _p(row, me, "use_mirror_x", text="X", toggle=True)
            _p(row, me, "use_mirror_y", text="Y", toggle=True)
            _p(row, me, "use_mirror_z", text="Z", toggle=True)
            l.label(text="Lock")
            row = l.row(align=True)
            _p(row, sc, "lock_x", text="X", toggle=True)
            _p(row, sc, "lock_y", text="Y", toggle=True)
            _p(row, sc, "lock_z", text="Z", toggle=True)
            l.label(text="Tiling")
            row = l.row(align=True)
            _p(row, sc, "tile_x", text="X", toggle=True)
            _p(row, sc, "tile_y", text="Y", toggle=True)
            _p(row, sc, "tile_z", text="Z", toggle=True)
            _p(l, sc, "tile_offset", text="Tile Offset")
            _p(l, sc, "radial_symmetry", text="Radial")
            _p(l, sc, "use_symmetry_feather", text="Feather")

        l.separator()
        _p(l, sc, "symmetrize_direction", text="Symmetrize")
        l.operator("sculpt.symmetrize", text="Symmetrize", icon='MOD_MIRROR')


class NOMAD_PT_dyntopo(bpy.types.Panel):
    bl_label = "Dyntopo / Remesh"
    bl_idname = "NOMAD_PT_dyntopo"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        obj, me = _mesh(context)
        if me is None:
            l.label(text="No active mesh", icon='INFO')
            return
        sc = context.tool_settings.sculpt

        # ------------------------------------------------ DYNTOPO
        on = bool(getattr(obj, "use_dynamic_topology_sculpting", False))
        if hasattr(l, "panel"):
            header, body = l.panel("nomad_dyntopo", default_closed=False)
            header.operator("sculpt.dynamic_topology_toggle",
                            text="Dyntopo", icon='MOD_REMESH', depress=on)
        else:
            body = l.box()
            body.operator("sculpt.dynamic_topology_toggle",
                          text="Dyntopo", icon='MOD_REMESH', depress=on)

        if body is not None and on:
            method = getattr(sc, "detail_type_method", None)

            # Refine method + Detailing
            _p(body, sc, "detail_refine_method", text="Refine")
            _p(body, sc, "detail_type_method", text="Detailing")

            # Tamaño de detalle: número + gotero según el método
            row = body.row(align=True)
            if method in {'CONSTANT', 'MANUAL'}:
                _p(row, sc, "constant_detail_resolution", text="Resolución")
                row.operator("sculpt.sample_detail_size", text="",
                             icon='EYEDROPPER')
            elif method == 'BRUSH':
                _p(row, sc, "detail_percent", text="Detalle %")
            else:  # RELATIVE
                _p(row, sc, "detail_size", text="Detail Size")
                row.operator("sculpt.dyntopo_detail_size_edit", text="",
                             icon='EYEDROPPER')

            # Flood fill solo en Constant
            if method == 'CONSTANT':
                r = body.row()
                r.scale_y = 1.3
                r.operator("sculpt.detail_flood_fill",
                           text="Detail Flood Fill")

        # ------------------------------------------------ REMESH
        body = _section(l, "nomad_remesh", "Remesh")
        if body is not None:
            row = body.row(align=True)
            _p(row, me, "remesh_voxel_size", text="Voxel Size")
            row.operator("object.voxel_size_edit", text="",
                         icon='EYEDROPPER')
            _p(body, me, "remesh_voxel_adaptivity", text="Adaptividad")
            _p(body, me, "use_remesh_fix_poles", text="Fix Poles")
            _p(body, me, "use_remesh_preserve_volume", text="Volumen")
            _p(body, me, "use_remesh_preserve_attributes",
               text="Atributos")

            r = body.row()
            r.scale_y = 1.4
            r.operator("object.voxel_remesh", text="Voxel Remesh")

            r = body.row()
            r.scale_y = 1.4
            r.operator("object.quadriflow_remesh", text="Quad Remesher")

# Opciones por tipo de textura (las que expone Blender para cada una).
_TEX_OPTIONS = {
    'CLOUDS': ("noise_basis", "noise_type", "noise_scale",
               "noise_depth", "nabla"),
    'WOOD': ("wood_type", "noise_basis_2", "noise_type", "noise_scale",
             "turbulence", "nabla"),
    'MARBLE': ("marble_type", "noise_basis_2", "noise_type",
               "noise_scale", "noise_depth", "turbulence", "nabla"),
    'MAGIC': ("noise_depth", "turbulence"),
    'BLEND': ("progression", "use_flip_axis"),
    'STUCCI': ("stucci_type", "noise_basis", "noise_type",
               "noise_scale", "turbulence"),
    'NOISE': (),
    'MUSGRAVE': ("musgrave_type", "dimension_max", "lacunarity",
                 "octaves", "noise_intensity", "noise_basis",
                 "noise_scale", "offset", "gain"),
    'VORONOI': ("distance_metric", "color_mode", "minkowski_exponent",
                "noise_intensity", "feature_weight_1", "feature_weight_2",
                "feature_weight_3", "feature_weight_4", "noise_scale"),
    'DISTORTED_NOISE': ("noise_basis", "noise_distortion", "distortion",
                        "noise_scale", "nabla"),
}

_TEX_SETS = {
    'TEXTURE': {"tex": "texture", "slot": "texture_slot",
                "map": ("tex_paint_map_mode", "map_mode"),
                "bias": "texture_sample_bias"},
    'MASK': {"tex": "mask_texture", "slot": "mask_texture_slot",
             "map": ("mask_map_mode",), "bias": None},
}


def _paint_settings(context):
    from . import brush_shelf
    attr = brush_shelf.MODES.get(context.mode, (None, None, "sculpt"))[2]
    return getattr(context.tool_settings, attr, None)


class NOMAD_OT_texture_new(bpy.types.Operator):
    """New texture on the active brush (on a local copy if it's linked)."""
    bl_idname = "nomad.texture_new"
    bl_label = "New Texture"
    bl_options = {'REGISTER', 'UNDO'}

    target: bpy.props.EnumProperty(
        items=[('TEXTURE', "Texture", ""), ('MASK', "Mask", "")],
        default='TEXTURE')

    def execute(self, context):
        sc = _paint_settings(context)
        src = getattr(sc, "brush", None)
        if src is None:
            self.report({'WARNING'}, "No active brush")
            return {'CANCELLED'}
        attr = "mask_texture" if self.target == 'MASK' else "texture"

        if src.library is None:
            local = src
        else:
            local = src.copy()
            local.name = "Nomad " + src.name
        local.use_fake_user = True

        tex = bpy.data.textures.new("Texture", 'IMAGE')
        try:
            setattr(local, attr, tex)
        except Exception as exc:
            print(f"NomadUI texture: {attr} failed: {exc!r}")

        if sc.brush != local or sc.brush.library is not None:
            try:
                local.asset_mark()
            except Exception as exc:
                print(f"NomadUI texture: asset_mark failed: {exc!r}")
            for ident in (f"Brush/{local.name}", local.name,
                          f"brushes/{local.name}"):
                try:
                    bpy.ops.brush.asset_activate(
                        asset_library_type='LOCAL',
                        asset_library_identifier="",
                        relative_asset_identifier=ident)
                except Exception:
                    continue
                if (sc.brush is not None and sc.brush.library is None
                        and sc.brush.name == local.name):
                    break
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


def _texture_block(l, context, brush, which):
    cfg = _TEX_SETS[which]
    tex = getattr(brush, cfg["tex"], None)
    try:
        l.template_ID_preview(brush, cfg["tex"], rows=3, cols=6)
    except (TypeError, RuntimeError):
        l.template_ID(brush, cfg["tex"])
    row = l.row()
    row.scale_y = 1.4
    op = row.operator("nomad.texture_new", text="New Texture", icon='ADD')
    op.target = which

    if tex is None:
        l.label(text="Choose or create a texture", icon='TEXTURE')
        return
    _p(l, tex, "type", text="Type")
    ttype = getattr(tex, "type", 'NONE')
    if ttype == 'IMAGE':
        try:
            l.template_ID(tex, "image")
        except (TypeError, RuntimeError):
            pass
        from .texture_panels import image_buttons
        image_buttons(l, 'TEXTURE' if which == 'TEXTURE'
                      else 'MASK_TEXTURE')
    else:
        for name in _TEX_OPTIONS.get(ttype, ()):
            _p(l, tex, name)
    _p(l, tex, "intensity", text="Intensity")
    _p(l, tex, "contrast", text="Contrast")

    slot = getattr(brush, cfg["slot"], None)
    body = _section(l, f"nomad_tex_map_{which}", "Mapping", closed=True)
    if body is None or slot is None:
        return
    names = cfg["map"]
    if which == 'TEXTURE' and context.mode != 'PAINT_TEXTURE':
        names = ("map_mode", "tex_paint_map_mode")
    mname = next((n for n in names if hasattr(slot, n)), None)
    if mname:
        _p(body, slot, mname, text="Mapping")
    if mname and getattr(slot, mname, None) == 'STENCIL':
        body.label(text="Stencil: use the Stencil button (right bar)",
                   icon='INFO')
    else:
        _p(body, slot, "angle", text="Angle")
        if getattr(slot, "has_texture_angle_source", True):
            _p(body, slot, "use_rake", text="Rake")
            _p(body, slot, "use_random", text="Random")
            if getattr(slot, "use_random", False):
                _p(body, slot, "random_angle", text="Random Range")
    _p(body, slot, "offset", text="Offset")
    _p(body, slot, "scale", text="Size")
    if cfg["bias"]:
        _p(body, brush, cfg["bias"], text="Sample Bias", slider=True)
    if which == 'TEXTURE':
        _p(body, brush, "use_color_as_displacement",
           text="Vector Displacement")


class NOMAD_PT_texture(bpy.types.Panel):
    bl_label = "Texture"
    bl_idname = "NOMAD_PT_texture"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        from . import brush_shelf
        brush = brush_shelf.active_brush(context)
        if brush is None:
            l.label(text="No active brush", icon='INFO')
            return
        body = _section(l, "nomad_tex_main", "Texture", closed=False)
        if body is not None:
            _texture_block(body, context, brush, 'TEXTURE')
        body = _section(l, "nomad_tex_mask", "Mask Texture", closed=True)
        if body is not None:
            _texture_block(body, context, brush, 'MASK')

def _view3d_override():
    C = bpy.context
    for win in C.window_manager.windows:
        for a in win.screen.areas:
            if a.type != 'VIEW_3D':
                continue
            r = next((r for r in a.regions if r.type == 'WINDOW'), None)
            if r is not None:
                return win, a, r
    return None, None, None


def defer_op(module, name, ctx='EXEC_DEFAULT', **kw):
    """Run an operator outside the modal, with a viewport override."""
    def _run():
        try:
            win, area, region = _view3d_override()
            if area is None:
                return None
            with bpy.context.temp_override(window=win, area=area,
                                           region=region):
                getattr(getattr(bpy.ops, module), name)(ctx, **kw)
        except (RuntimeError, AttributeError, TypeError,
                ReferenceError) as exc:
            print(f"NomadUI {module}.{name}: {exc}")
        return None
    try:
        bpy.app.timers.register(_run, first_interval=0.01)
    except RuntimeError:
        pass


def open_menu_deferred(menu_name):
    """Open a native menu (VIEW3D_MT_add, ...) outside the modal."""
    def _run():
        try:
            win, area, region = _view3d_override()
            if area is None:
                return None
            with bpy.context.temp_override(window=win, area=area,
                                           region=region):
                bpy.ops.wm.call_menu('INVOKE_DEFAULT', name=menu_name)
        except (RuntimeError, AttributeError, ReferenceError) as exc:
            print(f"NomadUI menu {menu_name}: {exc}")
        return None
    try:
        bpy.app.timers.register(_run, first_interval=0.01)
    except RuntimeError:
        pass           
           
CLASSES = (NOMAD_OT_texture_new, NOMAD_PT_symmetry, NOMAD_PT_dyntopo,
           NOMAD_PT_texture)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)