# Mask / Face Sets dropdowns (left bar), tool-properties popup, and a
# "click on the mesh" helper for cursor-driven operators.
import bpy
import traceback
from . import brush_shelf
from . import tool_sidebar as ts
from .sculpt_popups import _section, open_panel_deferred

# Essentials brush asset names (change here if your build names differ)
MASK_BRUSH = "Mask"
FACESET_BRUSH = "Face Set Paint"
MASK_BRUSH_NAMES = ("Mask",)
FACESET_BRUSH_NAMES = ("Face Set Paint", "Draw Face Sets", "Face Sets", "Face Set")

_ESS = "brushes/essentials_brushes-mesh_sculpt.blend/Brush/"

_warned = set()


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _op_exists(idname):
    try:
        mod, name = idname.split(".", 1)
        getattr(getattr(bpy.ops, mod), name).get_rna_type()
        return True
    except Exception:
        return False


def _similar_ops(candidates):
    """Operators that look like the missing ones (for the console)."""
    words = {w for c in candidates
             for w in c.split(".", 1)[-1].split("_") if len(w) > 3}
    out = []
    for modname in ("mesh", "paint", "sculpt", "object", "image"):
        mod = getattr(bpy.ops, modname, None)
        if mod is None:
            continue
        for n in dir(mod):
            if any(w in n for w in words):
                out.append(f"{modname}.{n}")
    return sorted(out)


def _act(layout, idname, text, icon='NONE', **props):
    """Operator button. `idname` may be a list of candidates (first one
    that exists wins). Props that don't exist in this build are skipped
    (and logged once) instead of breaking the popup."""
    if isinstance(idname, (tuple, list)):
        found = next((i for i in idname if _op_exists(i)), None)
        if found is None:
            layout.label(text=f"{text} (n/a)")
            key = ("noop", tuple(idname))
            if key not in _warned:
                _warned.add(key)
                print(f"NomadUI: none of {list(idname)} exists. "
                      f"Similar operators: {_similar_ops(idname)}")
            return
        idname = found
    try:
        op = layout.operator(idname, text=text, icon=icon)
    except Exception:
        layout.label(text=f"{text} (n/a)")
        return
    for k, v in props.items():
        try:
            setattr(op, k, v)
        except (AttributeError, TypeError) as exc:
            if (idname, k) not in _warned:
                _warned.add((idname, k))
                print(f"NomadUI action {idname}.{k}={v!r}: {exc}")


def _safe(layout, label, fn):
    """Draw one block; a failure shows a line and a traceback in the
    console instead of cutting everything below it."""
    try:
        fn(layout)
    except Exception as exc:
        layout.label(text=f"{label}: {type(exc).__name__}", icon='ERROR')
        key = ("section", label)
        if key not in _warned:
            _warned.add(key)
            print(f"NomadUI popup block '{label}' failed:")
            traceback.print_exc()


def _actions(layout, items, cols=2):
    grid = layout.grid_flow(row_major=True, columns=cols,
                            even_columns=True, align=True)
    grid.scale_y = 1.3
    for text, idname, props in items:
        _act(grid, idname, text, **props)


def _brush_button(layout, context, text, names, icon):
    """Activate a sculpt brush asset by name (several names tried)."""
    # Si la brocha solicitada corresponde a las de Face Sets, forzamos la ruta nativa de Blender 5.x
    if any("face" in n.casefold() for n in names):
        row = layout.row()
        row.scale_y = 1.5
        
        # Comprobamos si la brocha actual de escultura contiene "face" en su nombre para marcar el botón presionado
        sculpt_settings = getattr(context.tool_settings, "sculpt", None)
        b_act = getattr(sculpt_settings, "brush", None) if sculpt_settings else None
        is_depressed = b_act is not None and "face" in b_act.name.casefold()
        
        # Creamos el botón llamando al operador nativo de assets de Blender 5.x
        op = row.operator("brush.asset_activate", text=text, icon=icon, depress=is_depressed)
        op.asset_library_type = 'ESSENTIALS'
        op.asset_library_identifier = ""
        op.relative_asset_identifier = "brushes/essentials_brushes-mesh_sculpt.blend/Brush/Face Set Paint"
        return

    # --- El resto de la función se queda igual para las demás brochas ---
    entries = brush_shelf._cache.get(context.mode) or []
    wanted = [n.casefold() for n in names]
    entry = None
    for w in wanted:
        entry = next((e for e in entries if e["name"].casefold() == w), None)
        if entry is not None:
            break
            
    row = layout.row()
    row.scale_y = 1.5
    if entry is not None:
        ak = brush_shelf._active_key(context)
        op = row.operator("nomad.brush_activate", text=text, icon=icon,
                          depress=(ak == (entry["name"], entry["fnorm"])))
        op.lib_type, op.lib_id, op.rel = (entry["type"], entry["lib_id"], entry["rel"])
        return
        
    b = brush_shelf.active_brush(context)
    op = row.operator("nomad.brush_activate", text=text, icon=icon,
                      depress=(b is not None and b.name.casefold() in wanted))
    op.lib_type, op.lib_id, op.rel = 'ESSENTIALS', "", _ESS + names[0]




def _tool_grid(layout, context, keys):
    tools = [t for k in keys for t in ts._members(context, k)]
    if not tools:
        layout.label(text="No tools found in this mode", icon='INFO')
        return
    active = ts._active_idname(context)
    grid = layout.grid_flow(row_major=True, columns=2,
                            even_columns=True, align=True)
    grid.scale_y = 1.4
    for t in tools:
        op = grid.operator("wm.tool_set_by_id", text=t.label,
                           depress=(t.idname == active), **ts._icon_kw(t))
        op.name = t.idname
        try:
            op.space_type = 'VIEW_3D'
        except (AttributeError, TypeError):
            pass


# (toggle, label, value props shown while it is on)
_AUTOMASK = [
    ("use_automasking_topology", "Topology", ()),
    ("use_automasking_face_sets", "Face Sets", ()),
    ("use_automasking_boundary_edges", "Mesh Boundary",
     ("boundary_edges_propagation_steps",)),
    ("use_automasking_boundary_face_sets", "Face Sets Boundary",
     ("boundary_edges_propagation_steps",)),
    ("use_automasking_cavity", "Cavity",
     ("cavity_factor", "cavity_blur_steps")),
    ("use_automasking_start_normal", "Area Normal",
     ("start_normal_limit", "start_normal_falloff")),
    ("use_automasking_view_normal", "View Normal",
     ("view_normal_limit", "view_normal_falloff")),
    ("use_automasking_view_occlusion", "View Occlusion", ()),
]
_SKIP_PTR = {"rna_type", "id_data", "original", "evaluated"}


def _pointers(owner):
    for prop in owner.bl_rna.properties:
        if prop.type != 'POINTER' or prop.identifier in _SKIP_PTR:
            continue
        try:
            yield prop, getattr(owner, prop.identifier)
        except (AttributeError, RuntimeError):
            continue


def _is_automask(prop):
    return getattr(prop.fixed_type, "identifier", "") \
        == "MeshAutomaskingSettings"


def _find_automasking(context):
    """The MeshAutomaskingSettings struct, wherever this build keeps it."""
    ts_ = context.tool_settings
    attr = brush_shelf.MODES.get(context.mode, (None, None, "sculpt"))[2]
    roots = [brush_shelf.active_brush(context), getattr(ts_, attr, None),
             ts_.sculpt, ts_]
    for root in roots:
        if root is None:
            continue
        for prop, value in _pointers(root):
            if value is not None and _is_automask(prop):
                return value
    for root in roots:                      # one level deeper
        if root is None:
            continue
        for prop, value in _pointers(root):
            if value is None:
                continue
            try:
                for p2, v2 in _pointers(value):
                    if v2 is not None and _is_automask(p2):
                        return v2
            except Exception:
                continue
    return None


def _automasking(layout, context):
    am = _find_automasking(context)
    if am is None:
        layout.label(text="Automasking settings not found", icon='INFO')
        if "automask" not in _warned:
            _warned.add("automask")
            roots = {"brush": brush_shelf.active_brush(context),
                     "sculpt": context.tool_settings.sculpt}
            report = {k: [p.identifier for p, _v in _pointers(r)]
                      for k, r in roots.items() if r is not None}
            print(f"NomadUI: MeshAutomaskingSettings not found. "
                  f"Pointer properties: {report}")
        return
    drawn = set()
    for flag, label, values in _AUTOMASK:
        if not hasattr(am, flag):
            continue
        layout.prop(am, flag, text=label, toggle=True)
        if not getattr(am, flag, False):
            continue
        sub = layout.column(align=True)
        for v in values:
            if hasattr(am, v) and v not in drawn:
                drawn.add(v)
                sub.prop(am, v)
        if flag == "use_automasking_cavity":
            for extra, etext in (
                    ("use_automasking_cavity_inverted", "Inverted"),
                    ("use_automasking_custom_cavity_curve",
                     "Custom Curve")):
                if hasattr(am, extra):
                    sub.prop(am, extra, text=etext, toggle=True)
            if (getattr(am, "use_automasking_custom_cavity_curve", False)
                    and hasattr(am, "cavity_curve")):
                try:
                    sub.template_curve_mapping(am, "cavity_curve")
                except (TypeError, RuntimeError):
                    pass


# ----------------------------------------------------------------------
# Click-on-the-mesh operator (cursor-driven native operators)
# ----------------------------------------------------------------------

_CLICK_OPS = {
    'FS_HIDE': ("sculpt.face_set_change_visibility",
                {"mode": 'HIDE_ACTIVE'}),
    'FS_ISOLATE': ("sculpt.face_set_change_visibility",
                   {"mode": 'TOGGLE'}),
    'FS_GROW': ("sculpt.face_set_edit", {"mode": 'GROW'}),
    'FS_SHRINK': ("sculpt.face_set_edit", {"mode": 'SHRINK'}),
    'FS_EXTRACT': ("mesh.face_set_extract", {}),
    'MASK_BY_COLOR': ("sculpt.mask_by_color", {}),
    'SAMPLE_COLOR': ("paint.sample_color", {}),
    'WEIGHT_SAMPLE': ("paint.weight_sample", {}),
    'WEIGHT_SAMPLE_GROUP': ("paint.weight_sample_group", {}),
    'GP_WEIGHT_SAMPLE': ("grease_pencil.weight_sample", {}),
}


class NOMAD_OT_click_action(bpy.types.Operator):
    """Arm an action that needs a point on the mesh, then click it."""
    bl_idname = "nomad.click_action"
    bl_label = "Click on the mesh"
    bl_options = {'INTERNAL'}

    action: bpy.props.EnumProperty(
        items=[(k, k, "") for k in _CLICK_OPS])

    def _end(self, context):
        try:
            context.window.cursor_modal_restore()
        except (AttributeError, RuntimeError):
            pass

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        try:
            context.window.cursor_modal_set('EYEDROPPER')
        except (AttributeError, TypeError, ValueError):
            pass
        print(f"NomadUI click action armed: {self.action} (Esc cancels)")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'ESC', 'RIGHTMOUSE'} and event.value == 'PRESS':
            self._end(context)
            return {'CANCELLED'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            idname, props = _CLICK_OPS[self.action]
            mod, name = idname.split(".")
            self._end(context)
            try:
                getattr(getattr(bpy.ops, mod), name)(
                    'INVOKE_DEFAULT', **props)
            except Exception as exc:
                print(f"NomadUI click action {idname}: {exc}")
            return {'FINISHED'}
        return {'PASS_THROUGH'}


# ----------------------------------------------------------------------
# Action lists
# ----------------------------------------------------------------------

_VALUE = 'VALUE'
_MASK_EXTRACT = ("sculpt.paint_mask_extract", "paint.mask_extract",
                 "sculpt.mask_extract")
_MASK_SLICE = ("sculpt.paint_mask_slice", "paint.mask_slice",
               "sculpt.mask_slice")

MASK_ACTIONS = [
    ("Fill", "paint.mask_flood_fill", {"mode": _VALUE, "value": 1.0}),
    ("Clear", "paint.mask_flood_fill", {"mode": _VALUE, "value": 0.0}),
    ("Invert", "paint.mask_flood_fill", {"mode": 'INVERT'}),
    ("Smooth", "sculpt.mask_filter", {"filter_type": 'SMOOTH'}),
    ("Sharpen", "sculpt.mask_filter", {"filter_type": 'SHARPEN'}),
    ("Extract", _MASK_EXTRACT, {}),
    ("Slice", _MASK_SLICE, {"fill_holes": False, "new_object": False}),
    ("Slice + Fill Holes", _MASK_SLICE,
     {"fill_holes": True, "new_object": False}),
    ("Slice to New Object", _MASK_SLICE, {"new_object": True}),
    ("From Cavity", "sculpt.mask_from_cavity",
     {"settings_source": 'OPERATOR'}),
    ("From Mesh Boundary", "sculpt.mask_from_boundary",
     {"settings_source": 'OPERATOR', "boundary_mode": 'MESH'}),
    ("From Face Sets Boundary", "sculpt.mask_from_boundary",
     {"settings_source": 'OPERATOR', "boundary_mode": 'FACE_SETS'}),
    ("By Color (click)", "nomad.click_action", {"action": 'MASK_BY_COLOR'}),
    ("Hide Masked", "paint.hide_show_masked", {"action": 'HIDE'}),
    ("Show All", "paint.hide_show_all", {"action": 'SHOW'}),
]

FS_ACTIONS = [
    ("From Masked", "sculpt.face_sets_create", {"mode": 'MASKED'}),
    ("From Visible", "sculpt.face_sets_create", {"mode": 'VISIBLE'}),
    ("From Edit Mode Selection", "sculpt.face_sets_create",
     {"mode": 'SELECTION'}),
    ("Grow (click)", "nomad.click_action", {"action": 'FS_GROW'}),
    ("Shrink (click)", "nomad.click_action", {"action": 'FS_SHRINK'}),
    ("Extract (click)", "nomad.click_action", {"action": 'FS_EXTRACT'}),
    ("Hide (click)", "nomad.click_action", {"action": 'FS_HIDE'}),
    ("Isolate (click)", "nomad.click_action", {"action": 'FS_ISOLATE'}),
    ("Show All", "paint.hide_show_all", {"action": 'SHOW'}),
]

FS_INIT = [
    ("Loose Parts", 'LOOSE_PARTS'),
    ("Face Set Boundaries", 'FACE_SET_BOUNDARIES'),
    ("Materials", 'MATERIALS'),
    ("Normals", 'NORMALS'),
    ("UV Seams", 'UV_SEAMS'),
    ("Edge Creases", 'CREASES'),
    ("Bevel Weight", 'BEVEL_WEIGHT'),
    ("Sharp Edges", 'SHARP_EDGES'),
]


# ----------------------------------------------------------------------
# Panels
# ----------------------------------------------------------------------

class NOMAD_PT_mask(bpy.types.Panel):
    bl_label = "Mask"
    bl_idname = "NOMAD_PT_mask"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        if context.mode != 'SCULPT':
            l.label(text="Sculpt mode only", icon='INFO')
            return
        _safe(l, "mask brush", lambda lay: _brush_button(
            lay, context, "Mask Brush", MASK_BRUSH_NAMES, 'MOD_MASK'))
        _safe(l, "mask tools", lambda lay: _tool_grid(
            lay, context, ("mask_gest", "mask_color", "expand_mask")))

        body = _section(l, "nomad_mask_auto", "Automasking", closed=True)
        if body is not None:
            _safe(body, "automasking",
                  lambda lay: _automasking(lay, context))
        body = _section(l, "nomad_mask_actions", "Mask Actions",
                        closed=True)
        if body is not None:
            _safe(body, "mask actions",
                  lambda lay: _actions(lay, MASK_ACTIONS))


class NOMAD_PT_facesets(bpy.types.Panel):
    bl_label = "Face Sets"
    bl_idname = "NOMAD_PT_facesets"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        if context.mode != 'SCULPT':
            l.label(text="Sculpt mode only", icon='INFO')
            return
        # Busca algo parecido a esto en tu script original:
        _safe(l, "face sets brush", lambda lay: _brush_button(
            lay, context, "Face Sets Brush", FACESET_BRUSH_NAMES, 'FACESEL'))


        _safe(l, "face sets tools", lambda lay: _tool_grid(
            lay, context, ("fs_gest", "fs_edit", "expand_fs")))

        body = _section(l, "nomad_fs_actions", "Face Set Actions",
                        closed=True)
        if body is not None:
            _safe(body, "face set actions",
                  lambda lay: _actions(lay, FS_ACTIONS))

        body = _section(l, "nomad_fs_init", "Initialize Face Sets",
                        closed=True)
        if body is not None:
            def _init(lay):
                grid = lay.grid_flow(row_major=True, columns=2,
                                     even_columns=True, align=True)
                grid.scale_y = 1.3
                for text, mode in FS_INIT:
                    _act(grid, "sculpt.face_sets_init", text, mode=mode)
            _safe(body, "initialize", _init)


class NOMAD_PT_tool_props(bpy.types.Panel):
    """Settings of the active tool (what Blender shows in the tool header)."""
    bl_label = "Tool Properties"
    bl_idname = "NOMAD_PT_tool_props"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        try:
            from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
            ToolSelectPanelHelper.draw_active_tool_header(context, l)
        except Exception as exc:
            l.label(text=f"No tool settings: {type(exc).__name__}",
                    icon='INFO')
            print(f"NomadUI tool props: {exc!r}")

        active = ts._active_idname(context)
        if "knife" in active and hasattr(context.scene,
                                         "nomad_knife_confirm"):
            l.separator()
            l.prop(context.scene, "nomad_knife_confirm",
                   text="Double Click to Confirm")
        if (hasattr(context.scene, "nomad_gp_confirm") and active and any(
                m.idname == active for m in ts._members(context,
                                                        "gp_shapes"))):
            l.separator()
            l.prop(context.scene, "nomad_gp_confirm",
                   text="Double Click to Confirm")





def open_tool_props():
    """Brush tool in a paint mode -> brush settings; any other tool ->
    its own settings (what Blender shows in the tool header)."""
    mode = bpy.context.mode
    if mode.endswith("GREASE_PENCIL") and mode != 'EDIT_GREASE_PENCIL':
        open_panel_deferred("NOMAD_PT_gp_tool")
        return
    active = ts._active_idname(bpy.context)
    brush_tool = (mode in {'SCULPT', 'PAINT_VERTEX', 'PAINT_TEXTURE',
                           'PAINT_WEIGHT'}
                  and (not active or active == "builtin.brush"
                       or active.startswith("builtin_brush.")))
    open_panel_deferred("VIEW3D_PT_tools_brush_settings" if brush_tool
                        else "NOMAD_PT_tool_props")


CLASSES = (NOMAD_OT_click_action, NOMAD_PT_mask, NOMAD_PT_facesets,
           NOMAD_PT_tool_props)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass