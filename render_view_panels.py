# Render popup (top bar ▶) and View popup (top bar ◫).
# Render groups reuse Blender's own Properties-editor panels, found by
# label, so they follow the active engine automatically.
import inspect
import types

import bpy
from .sculpt_popups import _section

_logged = set()
_idx = {"n": -1, "by_ctx": {}, "children": {}}


# ----------------------------------------------------------------------
# Native panel embedding
# ----------------------------------------------------------------------

class _Proxy:
    """Stands in for `self` when calling a native panel's draw()."""

    def __init__(self, cls, layout):
        self._cls = cls
        self.layout = layout

    def __getattr__(self, name):
        cls = self.__dict__["_cls"]
        static = inspect.getattr_static(cls, name)
        if isinstance(static, (staticmethod, classmethod)):
            return getattr(cls, name)
        if inspect.isfunction(static):
            return types.MethodType(static, self)
        return getattr(cls, name)


def _index():
    subs = bpy.types.Panel.__subclasses__()
    if _idx["n"] == len(subs):
        return _idx
    by_ctx, children = {}, {}
    for cls in subs:
        if getattr(cls, "bl_space_type", None) != 'PROPERTIES':
            continue
        parent = getattr(cls, "bl_parent_id", "")
        if parent:
            children.setdefault(parent, []).append(cls)
        else:
            by_ctx.setdefault(getattr(cls, "bl_context", ""), []).append(cls)
    _idx.update(n=len(subs), by_ctx=by_ctx, children=children)
    return _idx


def _usable(cls, engine, context):
    compat = getattr(cls, "COMPAT_ENGINES", None)
    if compat is not None and engine not in compat:
        return False
    try:
        return bool(cls.poll(context))
    except Exception:
        return True   # no poll / context member missing: trust COMPAT


def _find(ctx_name, labels, engine, context):
    wanted = {s.lower() for s in labels}
    return [c for c in _index()["by_ctx"].get(ctx_name, ())
            if getattr(c, "bl_label", "").lower() in wanted
            and _usable(c, engine, context)]


def _children(cls, engine, context):
    pid = getattr(cls, "bl_idname", cls.__name__)
    return [c for c in _index()["children"].get(pid, ())
            if _usable(c, engine, context)]


def _call(fn, cls, layout, context):
    try:
        fn(_Proxy(cls, layout), context)
    except Exception as exc:
        layout.label(text=type(exc).__name__, icon='ERROR')
        key = (cls.__name__, type(exc).__name__)
        if key not in _logged:
            _logged.add(key)
            print(f"NomadUI native panel {cls.__name__}: {exc!r}")


def _draw_native(layout, cls, context, engine, flat=False):
    label = getattr(cls, "bl_label", cls.__name__)
    key = "nomad_" + getattr(cls, "bl_idname", cls.__name__)
    kids = _children(cls, engine, context)
    if flat:
        body = layout
    elif hasattr(layout, "panel"):
        header, body = layout.panel(key, default_closed=True)
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
    for kid in kids:
        _draw_native(body, kid, context, engine)


def _group(layout, key, title, context, ctx_name, items):
    body = _section(layout, key, title, closed=True)
    if body is None:
        return
    engine = context.scene.render.engine
    drew = False
    for labels in items:
        for cls in _find(ctx_name, labels, engine, context):
            _draw_native(body, cls, context, engine)
            drew = True
    if not drew:
        body.label(text="Nothing available for this engine", icon='INFO')


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _op(layout, idname, text, icon='NONE', props=None):
    try:
        op = layout.operator(idname, text=text, icon=icon)
    except (TypeError, RuntimeError, KeyError):
        try:
            op = layout.operator(idname, text=text)
        except (TypeError, RuntimeError, KeyError):
            layout.label(text=f"{text} (n/a)")
            return
    for k, v in (props or {}).items():
        try:
            setattr(op, k, v)
        except (AttributeError, TypeError):
            pass


def _view3d_space(context):
    sp = getattr(context, "space_data", None)
    if sp is not None and getattr(sp, "type", None) == 'VIEW_3D':
        return sp
    area = getattr(context, "area", None)
    if area is not None and area.type == 'VIEW_3D':
        return area.spaces.active
    for win in context.window_manager.windows:
        for a in win.screen.areas:
            if a.type == 'VIEW_3D':
                return a.spaces.active
    return None


# ----------------------------------------------------------------------
# Render popup
# ----------------------------------------------------------------------

_RENDER_ROWS = (
    (("Render Image", "render.render", 'RENDER_STILL', {}),
     ("Render Animation", "render.render", 'RENDER_ANIMATION',
      {"animation": True})),
    (("Viewport Render", "render.opengl", 'SHADING_RENDERED', {}),
     ("Save Screenshot", "screen.screenshot", 'FILE_IMAGE', {})),
    (("View Render", "render.view_show", 'IMAGE_DATA', {}),
     ("View Animation", "render.play_rendered_anim", 'FILE_MOVIE', {})),
    (("Render Audio", "sound.mixdown", 'SOUND', {}),),
)

_RENDER_ITEMS = (("Sampling",), ("Light Paths",), ("Raytracing",),
                 ("Volumes",), ("Curves",), ("Simplify",),
                 ("Depth of Field", "DOF"), ("Motion Blur",), ("Film",),
                 ("Performance",), ("Grease Pencil",), ("Freestyle",))
_OUTPUT_ITEMS = (("Format",), ("Frame Range",), ("Stereoscopy",),
                 ("Post Processing",), ("Output",))
_VIEWLAYER_ITEMS = (("View Layer",), ("Passes",), ("Filter",),
                    ("Override",))


def _find_compositor_menus():
    out = []
    for m in bpy.types.Menu.__subclasses__():
        ident = getattr(m, "bl_idname", m.__name__)
        text = (ident + " " + getattr(m, "bl_label", "")).lower()
        if "compos" in text and "effect" in text:
            out.append(ident)
    return out


def _compositor(layout, context):
    engine = context.scene.render.engine
    panels = [c for c in _index()["by_ctx"].get(
        "", []) + sum(_index()["by_ctx"].values(), [])
        if "compositor" in getattr(c, "bl_label", "").lower()]
    menus = _find_compositor_menus()

    if "compositor" not in _logged:
        _logged.add("compositor")
        print("NomadUI compositor panels:",
              [c.__name__ for c in panels], "menus:", menus)

    drew = False
    for ident in menus:
        layout.menu(ident, text="Add Effect", icon='ADD')
        drew = True
    for cls in panels:
        _draw_native(layout, cls, context, engine, flat=True)
        drew = True
    if not drew:
        layout.label(text="Compositor effects not found in this build",
                     icon='INFO')


class NOMAD_PT_render(bpy.types.Panel):
    bl_label = "Render"
    bl_idname = "NOMAD_PT_render"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        rd = context.scene.render

        for pair in _RENDER_ROWS:
            row = l.row(align=True)
            row.scale_y = 1.5
            for text, idname, icon, props in pair:
                _op(row, idname, text, icon, props)
            if len(pair) == 1:
                # Hueco para que el botón ocupe solo la mitad
                row.label(text="")

        l.separator()
        l.prop(rd, "engine", text="")
        l.operator("nomad.editor_switch", text="Compositor",
                   icon='NODE_COMPOSITING').which = 'COMPOSITOR'

        for key, title, ctx, items in (
                ("nomad_r_render", "Render", "render", _RENDER_ITEMS),
                ("nomad_r_output", "Output", "output", _OUTPUT_ITEMS),
                ("nomad_r_vlayer", "View Layer", "view_layer",
                 _VIEWLAYER_ITEMS)):
            try:
                _group(l, key, title, context, ctx, items)
            except Exception as exc:
                l.label(text=f"{title}: {type(exc).__name__}", icon='ERROR')
                print(f"NomadUI render group {title}: {exc!r}")

        body = _section(l, "nomad_r_comp", "Compositor", closed=True)
        if body is not None:
            try:
                _compositor(body, context)
            except Exception as exc:
                body.label(text=type(exc).__name__, icon='ERROR')
                print(f"NomadUI compositor: {exc!r}")


# ----------------------------------------------------------------------
# View popup
# ----------------------------------------------------------------------
def _pp(layout, owner, name, **kw):
    if owner is not None and hasattr(owner, name):
        layout.prop(owner, name, **kw)

class NOMAD_OT_open_popup(bpy.types.Operator):
    """Open another of our popups (the View popup closes first)."""
    bl_idname = "nomad.open_popup"
    bl_label = "Open"
    bl_options = {'INTERNAL'}

    panel: bpy.props.StringProperty()

    def execute(self, context):
        from .sculpt_popups import open_panel_deferred
        open_panel_deferred(self.panel)
        return {'FINISHED'}


class NOMAD_PT_armature_display(bpy.types.Panel):
    bl_label = "Armature"
    bl_idname = "NOMAD_PT_armature_display"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 10
        obj = context.active_object
        if obj is None or obj.type != 'ARMATURE':
            l.label(text="Select an armature", icon='INFO')
            return
        arm = obj.data
        space = _view3d_space(context)
        ov = space.overlay if space is not None else None

        if ov is not None:
            _pp(l, ov, "show_xray_bone", text="Fade Geometry",
                toggle=True)
            if getattr(ov, "show_xray_bone", False):
                _pp(l, ov, "xray_alpha_bone", text="Opacity")

        l.label(text="Display As")
        _pp(l, arm, "display_type", text="")

        row = l.row(align=True)
        _pp(row, arm, "show_names", text="Names", toggle=True)
        _pp(row, arm, "show_axes", text="Axes", toggle=True)
        row = l.row(align=True)
        _pp(row, arm, "show_bone_custom_shapes", text="Custom Shapes",
            toggle=True)
        _pp(row, obj, "show_in_front", text="In Front", toggle=True)

def _view_extras(l, context, mode):
    """Overlay popovers that live in View: Weight Paint, Grease Pencil."""
    def pop(panel, text, icon):
        row = l.row()
        row.scale_y = 1.5
        try:
            row.popover(panel=panel, text=text, icon=icon)
        except (TypeError, RuntimeError, KeyError):
            l.label(text=f"{text} (n/a)")

    if mode == 'PAINT_WEIGHT':
        pop("VIEW3D_PT_overlay_weight_paint", "Weight Paint Overlays",
            'OVERLAY')
    obj = context.active_object
    if obj is not None and obj.type in {'GREASEPENCIL', 'GPENCIL'}:
        pop("VIEW3D_PT_overlay_grease_pencil_options", "Grease Pencil",
            'GREASEPENCIL')

class NOMAD_PT_view(bpy.types.Panel):
    bl_label = "View"
    bl_idname = "NOMAD_PT_view"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    PICKER_MODES = {'SCULPT', 'PAINT_VERTEX', 'PAINT_TEXTURE',
                    'PAINT_GREASE_PENCIL', 'VERTEX_GREASE_PENCIL'}

    def draw(self, context):
        from . import top_bar
        from .brush_shelf import MODES as BRUSH_MODES
        from .viewport_ui import info_state

        l = self.layout
        l.ui_units_x = 12
        space = _view3d_space(context)
        if space is None:
            l.label(text="No 3D viewport", icon='INFO')
            return
        sc = context.scene
        mode = context.mode
        obj = context.active_object

        # Shading: four equal buttons (25 % each), one block
        grid = l.grid_flow(row_major=True, columns=4, even_columns=True,
                           even_rows=True, align=True)
        grid.scale_y = 1.6
        for value, icon in (('WIREFRAME', 'SHADING_WIRE'),
                            ('SOLID', 'SHADING_SOLID'),
                            ('MATERIAL', 'MATERIAL'),
                            ('RENDERED', 'SHADING_RENDERED')):
            grid.prop_enum(space.shading, "type", value, text="", icon=icon)
        row = l.row()
        try:
            row.popover(panel="VIEW3D_PT_shading",
                        text="Shading Settings", icon='SHADING_RENDERED')
        except (TypeError, RuntimeError, KeyError):
            pass

        # Overlays and gizmos: toggle + its dropdown
        for owner, name, text, icon, panel in (
                (space.overlay, "show_overlays", "Show Overlays",
                 'OVERLAY', "VIEW3D_PT_overlay"),
                (space, "show_gizmo", "Show Gizmos", 'GIZMO',
                 "VIEW3D_PT_gizmo_display")):
            row = l.row(align=True)
            row.scale_y = 1.5
            row.prop(owner, name, text=text, toggle=True, icon=icon)
            try:
                row.popover(panel=panel, text="", icon='DOWNARROW_HLT')
            except (TypeError, RuntimeError, KeyError):
                pass

        # Viewport text (ours: Blender's is hidden in tablet mode)
        row = l.row(align=True)
        row.scale_y = 1.3
        for which, text in (("text", "Info Text"), ("stats", "Statistics")):
            op = row.operator("nomad.info_toggle", text=text,
                              depress=info_state(context, which))
            op.which = which

        l.separator()
        # Our overlays, only where they apply
        row = l.row(align=True)
        row.scale_y = 1.5
        if mode in self.PICKER_MODES:
            row.prop(sc, "nomad_color_overlay", text="Color Picker",
                     toggle=True, icon='COLOR')
        row.prop(sc, "nomad_nav_gizmo", text="Navigate Gizmo",
                 toggle=True, icon='ORIENTATION_VIEW')
        if mode in self.PICKER_MODES and sc.nomad_color_overlay:
            col = l.column(align=True)
            col.prop(sc, "nomad_picker_corner", text="Picker Position")
            col.prop(sc, "nomad_picker_palette", text="Palette")
        row = l.row()
        row.scale_y = 1.5
        row.prop(sc, "nomad_sidebar_left", text="Tool Sidebar on Left",
                 toggle=True, icon='ARROW_LEFTRIGHT')

        if mode in BRUSH_MODES:
            row = l.row()
            row.scale_y = 1.5
            row.prop(sc, "nomad_fav_bar", text="Favorites Bar", toggle=True,
                     icon='SOLO_ON')
            if sc.nomad_fav_bar:
                l.prop(sc, "nomad_fav_side", text="Position")

        if top_bar._scrub_modes(context):
            row = l.row()
            row.scale_y = 1.5
            row.prop(sc, "nomad_scrub_visible", text="Timeline",
                     toggle=True, icon='TIME')
            if sc.nomad_scrub_visible:
                l.prop(sc, "nomad_tl_mode", text="Mode")

        if obj is not None and obj.type == 'ARMATURE':
            row = l.row()
            row.scale_y = 1.5
            op = row.operator("nomad.open_popup", text="Armature",
                              icon='ARMATURE_DATA')
            op.panel = "NOMAD_PT_armature_display"

        _view_extras(l, context, mode)

        l.separator()
        row = l.row()
        row.scale_y = 1.5
        row.operator("view3d.view_all", text="Frame All",
                     icon='VIEWZOOM').center = False

        row = l.row(align=True)
        row.scale_y = 1.5
        row.operator("view3d.localview", text="Local View",
                     icon='ZOOM_SELECTED',
                     depress=getattr(space, "local_view", None) is not None)
        quad = False
        try:
            quad = len(space.region_quadviews) > 0
        except (AttributeError, TypeError):
            pass
        row.operator("screen.region_quadview", text="Quad View",
                     icon='GRID', depress=quad)

        l.separator()
        row = l.row()
        row.scale_y = 1.5
        row.operator("nomad.toggle_off", text="Exit Tablet Mode", icon='X')



CLASSES = (NOMAD_PT_render, NOMAD_OT_open_popup,
           NOMAD_PT_armature_display, NOMAD_PT_view)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)