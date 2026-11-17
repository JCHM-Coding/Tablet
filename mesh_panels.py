# Edit Mesh popups: mode, Add (static / dynamic), Mesh Tools groups,
# quick actions (select, delete, UV, fill, separate), the top-bar
# Operators menu, and the Knife double-click-to-confirm keymap tweak.
import bpy
from . import tool_sidebar as ts
from .sculpt_popups import _section, defer_op, open_panel_deferred
from .sculpt_panels import _act, _actions, _tool_grid


def _add_button(layout, text, idname, icon):
    """Operator button that survives a wrong icon or operator name."""
    for kw in ({"icon": icon}, {}):
        try:
            layout.operator(idname, text=text, **kw)
            return
        except Exception:
            continue
    layout.label(text=f"{text} (n/a)")


def _need_edit_mesh(layout, context):
    if context.mode != 'EDIT_MESH':
        layout.label(text="Edit Mesh mode only", icon='INFO')
        return True
    return False


# ----------------------------------------------------------------------
# Selection mode (vertex / edge / face), multi-select, never empty
# ----------------------------------------------------------------------

class NOMAD_OT_mesh_mode(bpy.types.Operator):
    bl_idname = "nomad.mesh_mode"
    bl_label = "Selection Mode"
    bl_options = {'INTERNAL'}

    index: bpy.props.IntProperty()

    def execute(self, context):
        cur = tuple(context.tool_settings.mesh_select_mode)
        i = self.index
        if cur[i] and sum(cur) == 1:
            return {'CANCELLED'}        # at least one mode stays on
        try:
            bpy.ops.mesh.select_mode(
                use_extend=True, use_expand=False,
                type=('VERT', 'EDGE', 'FACE')[i], action='TOGGLE')
        except RuntimeError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}


class NOMAD_PT_mesh_mode(bpy.types.Panel):
    bl_label = "Mode"
    bl_idname = "NOMAD_PT_mesh_mode"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 8
        if _need_edit_mesh(l, context):
            return
        mode = tuple(context.tool_settings.mesh_select_mode)
        for i, (label, icon) in enumerate((("Vertex", 'VERTEXSEL'),
                                           ("Edge", 'EDGESEL'),
                                           ("Face", 'FACESEL'))):
            row = l.row()
            row.scale_y = 1.5
            op = row.operator("nomad.mesh_mode", text=label, icon=icon,
                              depress=bool(mode[i]))
            op.index = i


# ----------------------------------------------------------------------
# Add: Static (header, at the 3D cursor) / Dynamic (toolbar tools)
# ----------------------------------------------------------------------

STATIC_ADDS = [
    ("Plane", "mesh.primitive_plane_add", 'MESH_PLANE'),
    ("Cube", "mesh.primitive_cube_add", 'MESH_CUBE'),
    ("Circle", "mesh.primitive_circle_add", 'MESH_CIRCLE'),
    ("UV Sphere", "mesh.primitive_uv_sphere_add", 'MESH_UVSPHERE'),
    ("Ico Sphere", "mesh.primitive_ico_sphere_add", 'MESH_ICOSPHERE'),
    ("Cone", "mesh.primitive_cone_add", 'MESH_CONE'),
    ("Cylinder", "mesh.primitive_cylinder_add", 'MESH_CYLINDER'),
    ("Torus", "mesh.primitive_torus_add", 'MESH_TORUS'),
    ("Quad Sphere", "mesh.primitive_round_cube_add", 'MESH_CUBESPHERE'),
    ("Suzanne", "mesh.primitive_monkey_add", 'MESH_MONKEY'),
]


class NOMAD_PT_mesh_add(bpy.types.Panel):
    bl_label = "Add"
    bl_idname = "NOMAD_PT_mesh_add"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        if _need_edit_mesh(l, context):
            return
        body = _section(l, "nomad_add_static", "Static (at 3D cursor)",
                        closed=False)
        if body is not None:
            grid = body.grid_flow(row_major=True, columns=2,
                                  even_columns=True, align=True)
            grid.scale_y = 1.3
            for text, idname, icon in STATIC_ADDS:
                _add_button(grid, text, idname, icon)
        body = _section(l, "nomad_add_dynamic", "Dynamic (toolbar tools)",
                        closed=False)
        if body is not None:
            _tool_grid(body, context, ("add",))


# ----------------------------------------------------------------------
# Mesh Tools: your groups. Each variant = toolbar tool ids / labels,
# plus an optional operator used when the tool isn't in the toolbar.
# ----------------------------------------------------------------------

def _v(label, ids, op=None, labels=None, icon=None):
    return {"label": label, "ids": tuple(ids), "op": op, "icon": icon,
            "labels": tuple(s.casefold() for s in (labels or (label,)))}


# (key, title, glyph for the sidebar button, variants)
MESH_GROUPS = [
    ("extrude", "Extrude", "⇧", [
        _v("Extrude Region", ["builtin.extrude_region"]),
        _v("Extrude Manifold", ["builtin.extrude_manifold"]),
        _v("Extrude Along Normals",
           ["builtin.extrude_along_normals", "builtin.extrude_normals"]),
        _v("Extrude Individual", ["builtin.extrude_individual"]),
        _v("Extrude to Cursor",
           ["builtin.extrude_to_cursor", "builtin.extrude_cursor"],
           labels=["Extrude to Cursor", "Extrude Cursor"]),
    ]),
    ("inset", "Inset Faces", "◲", [
        _v("Inset Faces", ["builtin.inset_faces", "builtin.inset"],
           op="mesh.inset", labels=["Inset Faces", "Inset"],
           icon="ops.mesh.inset"),
    ]),
    ("bevel", "Bevel", "◢", [
        _v("Bevel", ["builtin.bevel"], op="mesh.bevel",
           icon="ops.mesh.bevel"),
    ]),
    ("loopcut", "Loop Cut", "≡", [
        _v("Loop Cut", ["builtin.loop_cut"]),
        _v("Offset Edge Loop Cut",
           ["builtin.offset_edge_loop_cut", "builtin.offset_edge_slide"],
           labels=["Offset Edge Loop Cut", "Offset Edge Slide"]),
    ]),
    ("cut", "Cut", "✂", [
        _v("Knife", ["builtin.knife"]),
        _v("Bisect", ["builtin.bisect"]),
    ]),
    ("polybuild", "Poly Build", "▦", [
        _v("Poly Build", ["builtin.poly_build", "builtin.polybuild"],
           op="mesh.polybuild_extrude_at_cursor_move",
           labels=["Poly Build", "Polybuild"],
           icon="ops.mesh.polybuild_hover"),
    ]),
    ("spin", "Spin", "↻", [
        _v("Spin", ["builtin.spin"], op="mesh.spin", icon="ops.mesh.spin"),
    ]),
    ("smooth", "Smooth", "≈", [
        _v("Smooth", ["builtin.smooth"]),
        _v("Randomize", ["builtin.randomize"]),
    ]),
    ("slide", "Slide", "⇄", [
        _v("Edge Slide", ["builtin.edge_slide"]),
        _v("Vertex Slide", ["builtin.vertex_slide"]),
    ]),
    ("shrink", "Shrink/Fatten", "⇕", [
        _v("Shrink/Fatten", ["builtin.shrink_fatten"],
           op="transform.shrink_fatten"),
        _v("Push/Pull", ["builtin.push_pull"], op="transform.push_pull"),
    ]),
    ("shear", "Shear", "▱", [
        _v("Shear", ["builtin.shear"]),
        _v("To Sphere", ["builtin.to_sphere"]),
    ]),
    ("rip", "Rip", "⌇", [
        _v("Rip Region", ["builtin.rip_region"]),
        _v("Rip Edge", ["builtin.rip_edge"]),
    ]),
]
_GROUPS = {g[0]: g for g in MESH_GROUPS}
_last = {}                      # group key -> last variant used
_state = {"open": None}         # group shown in the variants popup



def _find_tool(context, v):
    """The real ToolDef for a variant, or None if the toolbar lacks it."""
    known = ts._tooldefs(context)
    for i in v["ids"]:
        if i in known:
            return known[i]
    for t in known.values():
        if str(t.label).casefold() in v["labels"]:
            return t
    return None


def _icon_for(t, v):
    if t is not None:
        return ts._icon_kw(t)
    if v["icon"]:
        return ts._icon_kw(ts._Fake(None, None, v["icon"]))
    return {}


def _is_active(context, v, active):
    if not active:
        return False
    if active in v["ids"]:
        return True
    t = _find_tool(context, v)
    return t is not None and t.idname == active


def _variant_state(context, gkey, variants):
    """(index to show, is one of this group's tools active)."""
    active = ts._active_idname(context)
    for i, v in enumerate(variants):
        if _is_active(context, v, active):
            return i, True
    return _last.get(gkey, 0), False


def active_group(context):
    """((group tuple), variant index) of the active tool, or None."""
    active = ts._active_idname(context)
    if not active:
        return None
    for g in MESH_GROUPS:
        for i, v in enumerate(g[3]):
            if _is_active(context, v, active):
                return g, i
    return None


class NOMAD_OT_mesh_tool(bpy.types.Operator):
    """Activate a Mesh Tools variant as a real (modal, repeatable) tool."""
    bl_idname = "nomad.mesh_tool"
    bl_label = "Mesh Tool"
    bl_options = {'INTERNAL'}

    group: bpy.props.StringProperty()
    index: bpy.props.IntProperty()

    def execute(self, context):
        g = _GROUPS.get(self.group)
        if g is None or not (0 <= self.index < len(g[3])):
            return {'CANCELLED'}
        v = g[3][self.index]
        _last[self.group] = self.index
        t = _find_tool(context, v)
        if t is not None:
            ts._defer_tool(t.idname)
        else:
            # not in Blender's list: try each id, verify, operator last
            ts.activate_any(v["ids"], v["op"])
        return {'FINISHED'}


class NOMAD_OT_mesh_group(bpy.types.Operator):
    """Open the popup to choose a variant of a group."""
    bl_idname = "nomad.mesh_group"
    bl_label = "Mesh Tool Group"
    bl_options = {'INTERNAL'}

    group: bpy.props.StringProperty()

    def execute(self, context):
        _state["open"] = self.group
        open_panel_deferred("NOMAD_PT_mesh_group")
        return {'FINISHED'}


class NOMAD_PT_mesh_tools(bpy.types.Panel):
    bl_label = "Mesh Tools"
    bl_idname = "NOMAD_PT_mesh_tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        if _need_edit_mesh(l, context):
            return
        grid = l.grid_flow(row_major=True, columns=2, even_columns=True,
                           align=True)
        grid.scale_y = 1.4
        for gkey, title, glyph, variants in MESH_GROUPS:
            idx, on = _variant_state(context, gkey, variants)
            v = variants[idx]
            kw = _icon_for(_find_tool(context, v), v)
            if len(variants) == 1:
                op = grid.operator("nomad.mesh_tool", text=v["label"],
                                   depress=on, **kw)
                op.group, op.index = gkey, 0
            else:
                op = grid.operator("nomad.mesh_group", text=v["label"],
                                   depress=on, **kw)
                op.group = gkey


class NOMAD_PT_mesh_group(bpy.types.Panel):
    bl_label = "Mesh Tool Group"
    bl_idname = "NOMAD_PT_mesh_group"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 10
        g = _GROUPS.get(_state["open"])
        if g is None:
            l.label(text="No group selected", icon='INFO')
            return
        gkey, title, glyph, variants = g
        l.label(text=title)
        active = ts._active_idname(context)
        grid = l.grid_flow(row_major=True, columns=2, even_columns=True,
                           align=True)
        grid.scale_y = 1.4
        for i, v in enumerate(variants):
            t = _find_tool(context, v)
            op = grid.operator(
                "nomad.mesh_tool", text=v["label"],
                depress=_is_active(context, v, active),
                **_icon_for(t, v))
            op.group, op.index = gkey, i


# ----------------------------------------------------------------------
# Quick actions (right bar)
# ----------------------------------------------------------------------

SELECT_ACTIONS = [
    ("Select All", "mesh.select_all", {"action": 'SELECT'}),
    ("Select None", "mesh.select_all", {"action": 'DESELECT'}),
    ("Select Invert", "mesh.select_all", {"action": 'INVERT'}),
    ("Select More", "mesh.select_more", {}),
    ("Select Less", "mesh.select_less", {}),
    ("Edge Loops", "mesh.loop_multi_select", {"ring": False}),
    ("Edge Rings", "mesh.loop_multi_select", {"ring": True}),
    ("Shortest Path", "mesh.shortest_path_select", {}),
    ("Region to Loop", "mesh.region_to_loop", {}),
    ("Loop to Region", "mesh.loop_to_region", {}),
    ("Select Linked", "mesh.select_linked", {}),
]

DELETE_ACTIONS = [
    ("Delete Vertex", "mesh.delete", {"type": 'VERT'}),
    ("Delete Edges", "mesh.delete", {"type": 'EDGE'}),
    ("Delete Faces", "mesh.delete", {"type": 'FACE'}),
    ("Delete Edges Faces", "mesh.delete", {"type": 'EDGE_FACE'}),
    ("Only Faces", "mesh.delete", {"type": 'ONLY_FACE'}),
    ("Delete Loops", "mesh.delete_edgeloop", {}),
    ("Dissolve Vertices", "mesh.dissolve_verts", {}),
    ("Dissolve Edges", "mesh.dissolve_edges", {}),
    ("Dissolve Faces", "mesh.dissolve_faces", {}),
    ("Limited Dissolve", "mesh.dissolve_limited", {}),
    ("Edge Collapse", "mesh.edge_collapse", {}),
]

FILL_ACTIONS = [
    ("Fill", "mesh.fill", {}),
    ("Grid Fill", "mesh.fill_grid", {}),
    ("Bridge Edge Loops", "mesh.bridge_edge_loops", {}),
]

SEPARATE_ACTIONS = [
    ("Separate Selection", "mesh.separate", {"type": 'SELECTED'}),
    ("Separate By Material", "mesh.separate", {"type": 'MATERIAL'}),
    ("Separate Loose Parts", "mesh.separate", {"type": 'LOOSE'}),
]


def _simple_panel(cls_name, label, units, items, cols=2):
    def draw(self, context):
        l = self.layout
        l.ui_units_x = units
        if _need_edit_mesh(l, context):
            return
        _actions(l, items, cols=cols)
    return type(cls_name, (bpy.types.Panel,), {
        "bl_label": label, "bl_idname": cls_name,
        "bl_space_type": 'VIEW_3D', "bl_region_type": 'WINDOW',
        "draw": draw})


NOMAD_PT_mesh_select = _simple_panel(
    "NOMAD_PT_mesh_select", "Select", 12, SELECT_ACTIONS)
NOMAD_PT_mesh_delete = _simple_panel(
    "NOMAD_PT_mesh_delete", "Delete", 8, DELETE_ACTIONS, cols=1)
NOMAD_PT_mesh_fill = _simple_panel(
    "NOMAD_PT_mesh_fill", "Fill", 8, FILL_ACTIONS, cols=1)
NOMAD_PT_mesh_separate = _simple_panel(
    "NOMAD_PT_mesh_separate", "Separate", 8, SEPARATE_ACTIONS, cols=1)


class NOMAD_PT_mesh_uv(bpy.types.Panel):
    bl_label = "UV"
    bl_idname = "NOMAD_PT_mesh_uv"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 10
        if _need_edit_mesh(l, context):
            return
        col = l.column()
        col.scale_y = 1.3
        _act(col, "mesh.mark_seam", "Mark Seam", clear=False)
        _act(col, "mesh.mark_seam", "Clear Seam", clear=True)
        body = _section(l, "nomad_uv_unwrap", "Unwrap", closed=False)
        if body is not None:
            col = body.column()
            col.scale_y = 1.3
            _act(col, "uv.unwrap", "Unwrap")
            _act(col, "uv.smart_project", "Smart UV Project")
            _act(col, "uv.project_from_view", "Project from View")


# ----------------------------------------------------------------------
# Top bar: Operators (native Mesh / Vertex / Edge / Face menus)
# ----------------------------------------------------------------------

EDIT_MENUS = {
    'EDIT_MESH': [("Mesh", "VIEW3D_MT_edit_mesh"),
                  ("Vertex", "VIEW3D_MT_edit_mesh_vertices"),
                  ("Edge", "VIEW3D_MT_edit_mesh_edges"),
                  ("Face", "VIEW3D_MT_edit_mesh_faces")],
}
UV_MENU = {'EDIT_MESH': "VIEW3D_MT_uv_map"}


class NOMAD_PT_edit_operators(bpy.types.Panel):
    bl_label = "Operators"
    bl_idname = "NOMAD_PT_edit_operators"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        menus = EDIT_MENUS.get(context.mode)
        if not menus:
            l.label(text="No operators for this mode yet", icon='INFO')
            return
        for label, menu in menus:
            body = _section(l, f"nomad_ops_{menu}", label, closed=True)
            if body is None:
                continue
            if hasattr(bpy.types, menu):
                body.menu_contents(menu)
            else:
                body.label(text=f"{menu} not found", icon='INFO')


# ----------------------------------------------------------------------
# Knife: double click = confirm (instead of "close loop")
# ----------------------------------------------------------------------

def _knife_map():
    kc = bpy.context.window_manager.keyconfigs.user
    if kc is None:
        return None
    for km in kc.keymaps:
        if km.is_modal and "knife" in km.name.lower():
            return km
    return None


def apply_knife_confirm(enable):
    """Double click = confirm in the Knife modal map. Returns True if it
    ends up in the requested state."""
    km = _knife_map()
    if km is None:
        print("NomadUI knife: modal keymap not found")
        return False
    src, dst = (('ADD_CUT_CLOSED', 'CONFIRM') if enable
                else ('CONFIRM', 'ADD_CUT_CLOSED'))
    changed = present = False
    for kmi in km.keymap_items:
        try:
            if kmi.type == 'LEFTMOUSE' and kmi.value == 'DOUBLE_CLICK':
                if kmi.propvalue == dst:
                    present = True
                elif kmi.propvalue == src:
                    kmi.propvalue = dst
                    changed = True
        except (AttributeError, TypeError, RuntimeError):
            pass
    return changed or present


def _knife_update(self, context):
    apply_knife_confirm(bool(self.nomad_knife_confirm))


def _apply_knife_default():
    try:
        apply_knife_confirm(
            bool(getattr(bpy.context.scene, "nomad_knife_confirm", True)))
    except Exception as exc:
        print(f"NomadUI knife default: {exc!r}")
    return None


CLASSES = (NOMAD_OT_mesh_mode, NOMAD_PT_mesh_mode, NOMAD_PT_mesh_add,
           NOMAD_OT_mesh_tool, NOMAD_OT_mesh_group, NOMAD_PT_mesh_tools,
           NOMAD_PT_mesh_group, NOMAD_PT_mesh_select, NOMAD_PT_mesh_fill,
           NOMAD_PT_mesh_separate, NOMAD_PT_mesh_delete, NOMAD_PT_mesh_uv,
           NOMAD_PT_edit_operators)


# mesh_panels.py
def register():
    bpy.types.Scene.nomad_knife_confirm = bpy.props.BoolProperty(
        name="Double Click to Confirm", default=True,
        description="Knife: double click confirms the cut "
                    "(instead of closing the loop)",
        update=_knife_update)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    try:
        apply_knife_confirm(False)      # give the original binding back
    except Exception:
        pass
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    if hasattr(bpy.types.Scene, "nomad_knife_confirm"):
        del bpy.types.Scene.nomad_knife_confirm