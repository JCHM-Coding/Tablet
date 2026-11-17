# Draw mode (Grease Pencil, context.mode 'PAINT_GREASE_PENCIL'):
# right-bar popups, Layer popup, Options, primitive double-click confirm.
import bpy
from .sculpt_popups import _p, _section
from .sculpt_panels import _act
from . import brush_shelf
from . import tool_sidebar as ts
from .render_view_panels import _call

_warned = set()


def _gp_owners(context):
    """Every struct where a Grease Pencil setting may live in this build."""
    ts = context.tool_settings
    owners = [ts]
    for name in ("gpencil_paint", "gpencil_sculpt", "gpencil_sculpt_paint",
                 "gpencil_vertex_paint", "gpencil_weight_paint"):
        o = getattr(ts, name, None)
        if o is not None:
            owners.append(o)
    brush = brush_shelf.active_brush(context)
    if brush is not None:
        owners.append(brush)
        gs = getattr(brush, "gpencil_settings", None)
        if gs is not None:
            owners.append(gs)
    obj = context.active_object
    if obj is not None and obj.type in {'GREASEPENCIL', 'GPENCIL'}:
        owners.append(obj.data)
    return owners


def _gp_prop(context, *names):
    for owner in _gp_owners(context):
        for name in names:
            if hasattr(owner, name):
                return owner, name
    return None, None


def _draw_prop(layout, owner, name, label):
    try:
        ptype = owner.bl_rna.properties[name].type
    except (KeyError, AttributeError):
        ptype = 'ENUM'
    if ptype == 'BOOLEAN':
        row = layout.row()
        row.scale_y = 1.4
        row.prop(owner, name, text=label, toggle=True)
    else:
        layout.label(text=label)
        col = layout.column(align=True)
        col.scale_y = 1.4
        col.prop(owner, name, expand=True)


def _settings_panel(idname, title, items, units=8):
    def draw(self, context):
        l = self.layout
        l.ui_units_x = units
        for label, names in items:
            owner, name = _gp_prop(context, *names)
            if owner is None:
                l.label(text=f"{label}: not available", icon='INFO')
                if names[0] not in _warned:
                    _warned.add(names[0])
                    print(f"NomadUI GP: none of {names} found")
                continue
            _draw_prop(l, owner, name, label)
    return type(idname, (bpy.types.Panel,), {
        "bl_label": title, "bl_idname": idname,
        "bl_space_type": 'VIEW_3D', "bl_region_type": 'WINDOW',
        "draw": draw})


NOMAD_PT_gp_placement = _settings_panel(
    "NOMAD_PT_gp_placement", "Stroke Placement",
    [("Stroke Placement", ("gpencil_stroke_placement_view3d",))])
NOMAD_PT_gp_selmode = _settings_panel(
    "NOMAD_PT_gp_selmode", "Select Mode",
    [("Select Mode", ("gpencil_selectmode_edit",))])
NOMAD_PT_gp_selmode_sculpt = _settings_panel(
    "NOMAD_PT_gp_selmode_sculpt", "Select Mode",
    [("Select Mode", ("gpencil_selectmode_sculpt",))])
NOMAD_PT_gp_mf = _settings_panel(
    "NOMAD_PT_gp_mf", "Multiframe",
    [("Multiframe Editing", ("use_grease_pencil_multi_frame_editing",
                             "use_gpencil_multiframe_editing")),
     ("Use Falloff", ("use_multiframe_falloff",
                      "use_gpencil_multiframe_falloff"))], units=10)


def _find_menu(suffix):
    """Native Grease Pencil edit menu: '' = main, 'point', 'stroke'..."""
    seen = []
    for cls in bpy.types.Menu.__subclasses__():
        ident = getattr(cls, "bl_idname", cls.__name__)
        low = ident.lower()
        if not low.startswith("view3d_mt_edit"):
            continue
        for key in ("greasepencil", "grease_pencil"):
            if key in low:
                seen.append(ident)
                if low.split(key)[-1].strip("_") == suffix:
                    return ident
    if suffix not in _warned:
        _warned.add(suffix)
        print(f"NomadUI GP: edit menu '{suffix}' not found. "
              f"Grease Pencil edit menus: {seen}")
    return None


class NOMAD_PT_gp_edit_ops(bpy.types.Panel):
    bl_label = "Operators"
    bl_idname = "NOMAD_PT_gp_edit_ops"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        for key, title, suffix in (("main", "Grease Pencil", ""),
                                   ("point", "Point", "point"),
                                   ("stroke", "Stroke", "stroke")):
            body = _section(l, f"nomad_gpe_{key}", title, closed=True)
            if body is None:
                continue
            ident = _find_menu(suffix)
            if ident:
                body.menu_contents(ident)
            else:
                body.label(text=f"{title} menu not found", icon='INFO')

        body = _section(l, "nomad_gpe_multi", "Multiframe", closed=True)
        if body is None:
            return
        owner, name = _gp_prop(context,
                               "use_grease_pencil_multi_frame_editing",
                               "use_gpencil_multiframe_editing")
        if owner is not None:
            body.prop(owner, name, text="Multiframe Editing", toggle=True)
        else:
            body.label(text="Multiframe editing: not available",
                       icon='INFO')
        fo, fn = _gp_prop(context, "use_multiframe_falloff",
                          "use_gpencil_multiframe_falloff")
        if fo is not None:
            body.prop(fo, fn, text="Use Falloff", toggle=True)
            if getattr(fo, fn, False):
                co, cn = _gp_prop(context, "multiframe_falloff_curve")
                if co is not None:
                    try:
                        body.template_curve_mapping(co, cn)
                    except (TypeError, RuntimeError):
                        pass
NOMAD_PT_gp_mode = _settings_panel(
    "NOMAD_PT_gp_mode", "Mode",
    [("Mode", ("brush_draw_mode",)),
     ("Pin Material", ("use_material_pin",))])
NOMAD_PT_gp_caps = _settings_panel(
    "NOMAD_PT_gp_caps", "Caps",
    [("Caps", ("caps_type",))])
NOMAD_PT_gp_options = _settings_panel(
    "NOMAD_PT_gp_options", "Options",
    [("Multiframe Editing",
      ("use_grease_pencil_multi_frame_editing",
       "use_gpencil_multiframe_editing")),
     ("Additive Drawing", ("use_gpencil_draw_additive",)),
     ("Auto-Merge Strokes", ("use_gpencil_automerge_strokes",)),
     ("Add Weight Data", ("use_gpencil_weight_data_add",)),
     ("Draw Strokes on Back", ("use_gpencil_draw_onback",))], units=10)


NOMAD_PT_gp_strokemode = _settings_panel(
    "NOMAD_PT_gp_strokemode", "Stroke Mode",
    [("Stroke Mode", ("stroke_type",))])


def _onion(layout, gpd, layer):
    shown = False
    if layer is not None and hasattr(layer, "use_onion_skinning"):
        layout.prop(layer, "use_onion_skinning",
                    text="Onion Skinning (this layer)", toggle=True)
        shown = True
    for prop in gpd.bl_rna.properties:
        ident = prop.identifier
        if (ident == "rna_type" or prop.is_hidden or prop.is_readonly
                or not (ident.startswith(("onion", "ghost", "use_onion",
                                          "use_ghost"))
                        or ident in ("before_color", "after_color"))):
            continue
        try:
            layout.prop(gpd, ident)
            shown = True
        except (TypeError, RuntimeError):
            pass
    if not shown:
        layout.label(text="Onion skinning settings not found", icon='INFO')


class NOMAD_PT_gp_layers(bpy.types.Panel):
    bl_label = "Layer"
    bl_idname = "NOMAD_PT_gp_layers"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        obj = context.active_object
        if obj is None or obj.type not in {'GREASEPENCIL', 'GPENCIL'}:
            l.label(text="No Grease Pencil object", icon='INFO')
            return
        gpd = obj.data

        col = l.column()
        try:
            col.context_pointer_set("grease_pencil", gpd)
        except (AttributeError, TypeError):
            pass
        row = col.row()
        drawn = False
        for name in ("template_grease_pencil_layer_tree",
                     "template_grease_pencil_layers"):
            fn = getattr(row, name, None)
            if fn is None:
                continue
            for args in ((), (gpd,), (gpd, 6)):
                try:
                    fn(*args)
                    drawn = True
                    break
                except (TypeError, RuntimeError, AttributeError):
                    continue
            if drawn:
                break
        if not drawn:
            row.label(text="Layer list not available", icon='INFO')

        side = row.column(align=True)
        _act(side, "grease_pencil.layer_add", "", icon='ADD')
        _act(side, "grease_pencil.layer_group_add", "", icon='NEWFOLDER')
        _act(side, "grease_pencil.layer_remove", "", icon='REMOVE')
        side.separator()
        try:
            side.menu("GREASE_PENCIL_MT_grease_pencil_add_layer_extra",
                      icon='DOWNARROW_HLT', text="")
        except (TypeError, RuntimeError, KeyError):
            pass
        side.separator()
        _act(side, "grease_pencil.layer_move", "", icon='TRIA_UP',
             direction='UP')
        _act(side, "grease_pencil.layer_move", "", icon='TRIA_DOWN',
             direction='DOWN')

        layer = getattr(gpd.layers, "active", None)
        if layer is not None:
            box = l.box()
            _p(box, layer, "opacity", text="Opacity", slider=True)
            _p(box, layer, "blend_mode", text="Blend")
            r = box.row(align=True)
            _p(r, layer, "hide", text="Hide", toggle=True)
            _p(r, layer, "lock", text="Lock", toggle=True)

        body = _section(l, "nomad_gp_plane", "Drawing Plane", closed=True)
        if body is not None:
            owner, name = _gp_prop(context, "lock_axis")
            if owner is None:
                body.label(text="Drawing plane not available", icon='INFO')
            else:
                c = body.column(align=True)
                c.scale_y = 1.4
                c.prop(owner, name, expand=True)

        body = _section(l, "nomad_gp_onion", "Onion Skinning", closed=True)
        if body is not None:
            _onion(body, gpd, layer)


# ----------------------------------------------------------------------
# Tool (options): Properties > Tool > Brush Settings, every panel that
# applies to the active brush (Draw, Fill, Erase...)
# ----------------------------------------------------------------------

_GP_CTX = {'PAINT_GREASE_PENCIL': "paint",
           'VERTEX_GREASE_PENCIL': "vertex",
           'SCULPT_GREASE_PENCIL': "sculpt",
           'WEIGHT_GREASE_PENCIL': "weight",
           'EDIT_GREASE_PENCIL': "edit"}


def _collect_tool_panels(context):
    """Native 'Tool' tab panels for the current Grease Pencil mode, in
    Blender's order, with their sub-panels."""
    want = _GP_CTX.get(context.mode, "paint")
    others = {"paint", "vertex", "sculpt", "weight", "edit"} - {want}
    tops, kids = [], {}
    for cls in bpy.types.Panel.__subclasses__():
        if (getattr(cls, "bl_space_type", None) != 'VIEW_3D'
                or getattr(cls, "bl_region_type", None) != 'UI'
                or getattr(cls, "bl_category", "") != "Tool"):
            continue
        parent = getattr(cls, "bl_parent_id", "")
        if parent:
            kids.setdefault(parent, []).append(cls)
            continue
        ident = getattr(cls, "bl_idname", cls.__name__).casefold()
        ctx = str(getattr(cls, "bl_context", "")).casefold()
        if "grease_pencil" not in ident and "gpencil" not in ident:
            continue
        if want not in ctx or any(o in ctx for o in others):
            continue
        if not _poll_ok(cls, context):
            continue
        tops.append(cls)
    return tops, kids


def _poll_ok(cls, context):
    try:
        return bool(cls.poll(context))
    except AttributeError:
        return True             # no poll defined
    except Exception:
        return True


def _draw_tool_panel(layout, cls, kids, context):
    opts = getattr(cls, "bl_options", set())
    ident = getattr(cls, "bl_idname", cls.__name__)
    label = getattr(cls, "bl_label", cls.__name__)
    if 'HIDE_HEADER' in opts:
        body = layout
    elif hasattr(layout, "panel"):
        header, body = layout.panel("nomad_tp_" + ident,
                                    default_closed=('DEFAULT_CLOSED' in opts))
        row = header.row(align=True)
        if hasattr(cls, "draw_header"):
            _call(cls.draw_header, cls, row, context)
        row.label(text=label)
    else:
        body = layout.box()
        body.label(text=label)
    if body is None:
        return
    body.use_property_split = True
    body.use_property_decorate = False
    _call(cls.draw, cls, body, context)
    for kid in kids.get(ident, ()):
        if _poll_ok(kid, context):
            _draw_tool_panel(body, kid, kids, context)


class NOMAD_PT_gp_tool(bpy.types.Panel):
    bl_label = "Tool"
    bl_idname = "NOMAD_PT_gp_tool"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        active = ts._active_idname(context)

        # A non-brush tool (predefined strokes, ...): its own options first
        if active and active != "builtin.brush":
            body = _section(l, "nomad_gpt_tool", "Active Tool",
                            closed=False)
            if body is not None:
                try:
                    from bl_ui.space_toolsystem_common import (
                        ToolSelectPanelHelper)
                    ToolSelectPanelHelper.draw_active_tool_header(
                        context, body)
                except Exception as exc:
                    body.label(text=f"No tool settings: "
                                    f"{type(exc).__name__}", icon='INFO')
                if hasattr(context.scene, "nomad_gp_confirm") and any(
                        m.idname == active
                        for m in ts._members(context, "gp_shapes")):
                    body.prop(context.scene, "nomad_gp_confirm",
                              text="Double Click to Confirm")

        tops, kids = _collect_tool_panels(context)
        if not tops:
            l.label(text="Brush settings panels not found", icon='INFO')
            if "toolpanels" not in _warned:
                _warned.add("toolpanels")
                names = [getattr(c, "bl_idname", c.__name__)
                         for c in bpy.types.Panel.__subclasses__()
                         if getattr(c, "bl_space_type", None) == 'VIEW_3D'
                         and getattr(c, "bl_category", "") == "Tool"]
                print(f"NomadUI GP tool panels not found. Tool tab "
                      f"panels: {names}")
            return
        for cls in tops:
            _draw_tool_panel(l, cls, kids, context)


# ----------------------------------------------------------------------
# Predefined strokes: double click = confirm (on by default)
# ----------------------------------------------------------------------

_confirm_items = []        # (keymap name, kmi) added by us


def _primitive_maps():
    kc = bpy.context.window_manager.keyconfigs.user
    if kc is None:
        return []
    return [km for km in kc.keymaps
            if km.is_modal and "primitive" in km.name.lower()]


def apply_gp_confirm(enable):
    maps = _primitive_maps()
    if not maps:
        kc = bpy.context.window_manager.keyconfigs.user
        names = [km.name for km in kc.keymaps if km.is_modal] if kc else []
        print(f"NomadUI GP confirm: primitive modal keymap not found. "
              f"Modal maps: {names}")
        return False
    for km in maps:
        if enable:
            has = any(
                k.type == 'LEFTMOUSE' and k.value == 'DOUBLE_CLICK'
                and k.propvalue == 'CONFIRM' for k in km.keymap_items)
            if not has:
                try:
                    kmi = km.keymap_items.new_modal(
                        'CONFIRM', 'LEFTMOUSE', 'DOUBLE_CLICK')
                    _confirm_items.append((km.name, kmi))
                except (TypeError, RuntimeError) as exc:
                    print(f"NomadUI GP confirm: {exc!r}")
        else:
            for name, kmi in list(_confirm_items):
                if name != km.name:
                    continue
                try:
                    km.keymap_items.remove(kmi)
                except (RuntimeError, ReferenceError):
                    pass
                _confirm_items.remove((name, kmi))
    return True


def _confirm_update(self, context):
    apply_gp_confirm(bool(self.nomad_gp_confirm))


def _apply_confirm_default():
    try:
        apply_gp_confirm(bool(getattr(bpy.context.scene,
                                      "nomad_gp_confirm", True)))
    except Exception as exc:
        print(f"NomadUI GP confirm default: {exc!r}")
    return None


CLASSES = (NOMAD_PT_gp_strokemode, NOMAD_PT_gp_placement, NOMAD_PT_gp_mode,
           NOMAD_PT_gp_caps, NOMAD_PT_gp_options, NOMAD_PT_gp_layers,
           NOMAD_PT_gp_tool, NOMAD_PT_gp_selmode, NOMAD_PT_gp_edit_ops,
           NOMAD_PT_gp_selmode_sculpt, NOMAD_PT_gp_mf)


# gp_panels.py
def register():
    bpy.types.Scene.nomad_gp_confirm = bpy.props.BoolProperty(
        name="Double Click to Confirm", default=True,
        description="Predefined strokes: double click confirms the shape",
        update=_confirm_update)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    try:
        apply_gp_confirm(False)
    except Exception:
        pass
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    if hasattr(bpy.types.Scene, "nomad_gp_confirm"):
        del bpy.types.Scene.nomad_gp_confirm