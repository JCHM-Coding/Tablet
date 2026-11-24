bl_info = {
    "name": "Tablet",
    "author": "",
    "version": (0, 5, 0),
    "blender": (5, 3, 0),
    "location": "View3D > Sidebar > Nomad",
    "description": "Tablet-style custom viewport interface",
    "category": "Interface",
}

import time
import traceback

import bpy
import gpu
from bpy.app.handlers import persistent

from . import (safety, drawing, top_bar, modal, panels, modifiers_panel,
               outliner_panel, sculpt_popups, material_panel,
               render_view_panels, color_overlay, brush_shelf, tool_sidebar,
               expand, sculpt_panels, object_panels, mesh_panels,
               pose_panels, gp_panels, texture_panels, paint_panels,
               curve_panels, data_panels, sequencer_panels, clip_panels, viewport_ui,
               outliner_gpu, fav_bar, asset_gpu, assets_panels, editors, anim_options,
               style, fav_bar, nav_gizmo, timeline_ext, graph_ext, nla_ext, driver_ext,
               requirements, pose_assets, requirements, pose_assets, graph_panels, ds_panels, dope_gp, edit_ops,
               graph_ext)

MODULES = (modifiers_panel, outliner_panel, sculpt_popups, material_panel,
           render_view_panels, color_overlay, brush_shelf, tool_sidebar,
           expand, sculpt_panels, object_panels, mesh_panels, pose_panels,
           gp_panels, texture_panels, paint_panels, curve_panels,
           data_panels, sequencer_panels, clip_panels, viewport_ui, outliner_gpu,
           asset_gpu, pose_assets, assets_panels, editors, timeline_ext,
           anim_options, fav_bar, nla_ext, driver_ext, graph_panels,
           ds_panels, dope_gp, edit_ops)

MODULES = tuple(dict.fromkeys(MODULES))
# ----------------------------------------------------------------------
# Operators, menus, preferences
# ----------------------------------------------------------------------

class NOMAD_OT_stub(bpy.types.Operator):
    """Placeholder for features that are not connected yet."""
    bl_idname = "nomad.stub"
    bl_label = "Placeholder"
    bl_options = {'REGISTER'}

    message: bpy.props.StringProperty(default="")

    def execute(self, context):
        self.report({'INFO'}, f"{self.message}: coming soon")
        return {'FINISHED'}


class NOMAD_OT_toggle_overlays(bpy.types.Operator):
    """Toggle the viewport overlays."""
    bl_idname = "nomad.toggle_overlays"
    bl_label = "Overlays on/off"
    bl_options = {'REGISTER'}

    def execute(self, context):
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                space = area.spaces.active
                space.overlay.show_overlays = not space.overlay.show_overlays
                area.tag_redraw()
        return {'FINISHED'}


class NOMAD_MT_modes(bpy.types.Menu):
    bl_idname = "NOMAD_MT_modes"
    bl_label = "Mode"

    FALLBACK = {
        'MESH': [('OBJECT', "Object Mode"), ('EDIT', "Edit Mode"),
                 ('SCULPT', "Sculpt Mode"),
                 ('VERTEX_PAINT', "Vertex Paint"),
                 ('WEIGHT_PAINT', "Weight Paint"),
                 ('TEXTURE_PAINT', "Texture Paint")],
        'ARMATURE': [('OBJECT', "Object Mode"), ('EDIT', "Edit Mode"),
                     ('POSE', "Pose Mode")],
    }

    def draw(self, context):
        l = self.layout
        obj = context.active_object
        if obj is None:
            l.label(text="No active object")
            return
        try:
            # Blender filters this list by the active object's type
            l.operator_enum("object.mode_set", "mode")
        except (TypeError, RuntimeError, KeyError):
            modes = self.FALLBACK.get(
                obj.type, [('OBJECT', "Object Mode"), ('EDIT', "Edit Mode")])
            for mode, label in modes:
                l.operator("object.mode_set", text=label).mode = mode


class NOMAD_PT_panel(bpy.types.Panel):
    bl_label = "Tablet"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tablet"

    def draw(self, context):
        layout = self.layout
        if context.scene.nomad_ui_active:
            layout.operator("nomad.toggle_off",
                            text="Exit Tablet Mode", icon='X')
        else:
            layout.operator("nomad.start",
                            text="Start Tablet Mode", icon='PLAY')


class NomadPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    autostart: bpy.props.BoolProperty(
        name="Start in tablet mode",
        description="Enter the tablet mode automatically when Blender "
                    "starts or a file is opened",
        default=False)
    tl_h_dope: bpy.props.FloatProperty(
        name="Dope Sheet", default=4.0, min=2.0, max=12.0,
        description="Height, as a multiple of the compact timeline")
    tl_h_graph: bpy.props.FloatProperty(
        name="Graph Editor", default=4.0, min=2.0, max=12.0,
        description="Height, as a multiple of the compact timeline")
    tl_h_nla: bpy.props.FloatProperty(
        name="NLA", default=4.0, min=2.0, max=12.0,
        description="Height, as a multiple of the compact timeline")
    tl_h_drivers: bpy.props.FloatProperty(
        name="Drivers", default=4.0, min=2.0, max=12.0,
        description="Height, as a multiple of the compact timeline")
    ui_scale_override: bpy.props.FloatProperty(
        name="Interface scale", default=0.0, min=0.0, max=8.0,
        description="Scale of the tablet interface. 0 = automatic: it "
                    "follows the DPI of the screen and Blender's "
                    "Resolution Scale, like Blender's own windows. Type a "
                    "value (for example 2.0) if the buttons look too small "
                    "or too large next to the native windows")
    asset_tile: bpy.props.IntProperty(
        name="Asset browser cell size", default=62, min=40, max=160,
        subtype='PIXEL',
        description="Size of the preview cells of the asset browser "
                    "(objects, materials, poses...)")
    brush_cell: bpy.props.FloatProperty(
        name="Brush browser cell size", default=5.0, min=3.0, max=10.0,
        description="Size of the thumbnails of the brush browser and the "
                    "favorites popup")

    def draw(self, context):
        from . import requirements
        l = self.layout
        l.prop(self, "autostart")

        box = l.box()
        box.label(text="Interface scale (0 = automatic)")
        box.prop(self, "ui_scale_override")
        box.label(text=f"In use: x{style.ui_scale():.2f}   "
                       f"(Blender: x{context.preferences.system.ui_scale:.2f})"
                  if hasattr(context.preferences.system, "ui_scale")
                  else f"In use: x{style.ui_scale():.2f}")

        box = l.box()
        box.label(text="Timeline editors height (x the compact timeline)")
        col = box.column(align=True)
        for name in ("tl_h_dope", "tl_h_graph", "tl_h_nla", "tl_h_drivers"):
            col.prop(self, name)

        box = l.box()
        box.label(text="Asset browsers")
        col = box.column(align=True)
        col.prop(self, "asset_tile")
        col.prop(self, "brush_cell")

        box = l.box()
        box.label(text="Required add-ons")
        for label, token in requirements.REQUIRED:
            row = box.row()
            if requirements.enabled(token):
                row.label(text=f"{label}: enabled", icon='CHECKMARK')
                continue
            row.alert = True
            row.label(text=f"{label} is not enabled", icon='ERROR')
            mod = requirements.module_name(token)
            if mod:
                row.alert = False
                op = row.operator("preferences.addon_enable", text="Enable")
                op.module = mod
            else:
                row.label(text="(not installed)")
        box.label(text="Without them, the related features are disabled "
                       "or hidden.")


CLASSES = (NomadPreferences, NOMAD_OT_stub, NOMAD_OT_toggle_overlays,
           modal.NOMAD_OT_modal, modal.NOMAD_OT_start,
           modal.NOMAD_OT_toggle_off, NOMAD_MT_modes, NOMAD_PT_panel)


_handle = None
_post_pending = [False]
_quad_log = [0]
_timers = []


# ----------------------------------------------------------------------
# Startup / load / save (nothing runs before the UI exists)
# ----------------------------------------------------------------------

def _ready():
    """True once Blender has a real window with a sized 3D viewport."""
    try:
        wm = bpy.context.window_manager
        if wm is None or not wm.windows:
            return False
        found = False
        for win in wm.windows:
            if win.screen is None:
                return False
            for a in win.screen.areas:
                if a.type == 'VIEW_3D':
                    r = next((r for r in a.regions
                              if r.type == 'WINDOW'), None)
                    if r is not None and r.width > 0 and r.height > 0:
                        found = True
        return found
    except Exception:
        return False


def _when_ready(fn, first=3.0, tries=30):
    count = [0]

    def _run():
        if safety.exiting():
            return None
        count[0] += 1
        if _ready():
            try:
                fn()
            except Exception:
                traceback.print_exc()
            return None
        return 0.5 if count[0] < tries else None
    _timers.append(_run)
    try:
        bpy.app.timers.register(_run, first_interval=first, persistent=True)
    except (RuntimeError, ValueError):
        pass


def _autostart_wanted():
    try:
        return bool(bpy.context.preferences.addons[
            __package__].preferences.autostart)
    except (KeyError, AttributeError):
        return False


def _start_modal():
    try:
        win, area, region = sculpt_popups._view3d_override()
        if area is None:
            return
        with bpy.context.temp_override(window=win, area=area,
                                       region=region):
            bpy.ops.nomad.modal('INVOKE_DEFAULT')
    except Exception as exc:
        print(f"NomadUI autostart: {exc!r}")


# The tablet mode does not start until the first click has been released
# (that click closes Blender's splash screen). Nothing else is considered.
_CLICKS = {'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE'}
_gate = {"click": False}         # True from register() until that click


def _start_after_wait():
    if not modal.running and _autostart_wanted():
        _start_modal()
    return None


class NOMAD_OT_wait_splash(bpy.types.Operator):
    """Passes every event through until the first click is released, then
    starts the tablet mode."""
    bl_idname = "nomad.wait_splash"
    bl_label = "Wait for the First Click"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if safety.exiting() or not _gate["click"]:
            return {'CANCELLED', 'PASS_THROUGH'}
        if event.type not in _CLICKS or event.value != 'RELEASE':
            return {'PASS_THROUGH'}
        _gate["click"] = False
        try:
            bpy.app.timers.register(_start_after_wait, first_interval=0.3)
        except (RuntimeError, ValueError):
            pass
        return {'FINISHED', 'PASS_THROUGH'}


def _wait_for_click():
    try:
        win, area, region = sculpt_popups._view3d_override()
        if area is None:
            raise RuntimeError("no 3D View")
        with bpy.context.temp_override(window=win, area=area, region=region):
            bpy.ops.nomad.wait_splash('INVOKE_DEFAULT')
    except Exception as exc:
        print(f"NomadUI first-click wait: {exc!r}")
        _gate["click"] = False
        _start_modal()


def _post_load():
    """After startup or a file load, once the UI exists."""
    _post_pending[0] = False
    modal.running = False
    modal._want_exit = False
    was_active = False
    try:
        for sc in bpy.data.scenes:
            if getattr(sc, "nomad_ui_active", False):
                was_active = True
            sc.nomad_ui_active = False
    except Exception:
        pass
    viewport_ui.reset()
    try:
        brush_shelf.purge_all()
    except Exception as exc:
        print(f"NomadUI purge: {exc!r}")
    if _autostart_wanted():
        if _gate["click"]:
            _wait_for_click()            # not before the first click
        else:
            _start_modal()
    elif was_active or modal.any_fullscreen():
        modal.exit_fullscreen_deferred()


def _schedule_post_load(first=3.0):
    if _post_pending[0]:
        return
    _post_pending[0] = True
    _when_ready(_post_load, first=first)


def _cancel_timers():
    for fn in _timers:
        try:
            bpy.app.timers.unregister(fn)
        except (ValueError, RuntimeError):
            pass
    _timers.clear()


@persistent
def _on_load(*_args):
    modal.running = False
    modal._want_exit = False
    if _gate["click"]:
        # still waiting for the first click: only make sure that a waiter
        # will exist (a file load removes the one that was running)
        _schedule_post_load(first=1.5)
        return
    # Loading a file (e.g. choosing 2D Animation / Sculpting / Storyboarding
    # on the splash screen) deletes the timers that were pending, but the
    # flag stayed True and blocked every later schedule: reset both.
    _cancel_timers()
    _post_pending[0] = False
    _schedule_post_load(first=1.5)


@persistent
def _on_save_pre(*_args):
    """Never write the hidden overlays / temporary brushes into a file."""
    try:
        viewport_ui.restore_native(bpy.context)
        brush_shelf.purge_all()
    except Exception:
        pass


@persistent
def _on_save_post(*_args):
    if modal.running and not safety.exiting():
        try:
            viewport_ui.hide_native(bpy.context)
        except Exception:
            pass



# ----------------------------------------------------------------------
# Drawing
# ----------------------------------------------------------------------

def _guard(fn):
    try:
        fn()
    except Exception:
        traceback.print_exc()


def _draw_all():
    """Draw handler: top bar, bars, pickers, browsers (scaled). In Quad
    View each of the 4 regions draws the whole UI shifted by its own
    offset, so every region shows only its part of one continuous UI."""
    if safety.exiting():
        return
    ctx = bpy.context
    area = ctx.area
    if not area or area.type != 'VIEW_3D':
        return
    if not getattr(ctx.scene, "nomad_ui_active", False) or not modal.running:
        return
    regs = [r for r in area.regions if r.type == 'WINDOW']
    if not regs:
        return

    s = style.ui_scale()
    drawing.SCALE = s                    # crisp text at any DPI (drawing.py)
    ox = oy = 0.0
    if len(regs) > 1:
        ux, uy, uw, uh = style.union(regs)
        w, h = uw / s, uh / s
        here = ctx.region
        if here is not None:
            ox, oy = here.x - ux, here.y - uy
        if _quad_log[0] < 4:
            _quad_log[0] += 1
            print(f"NomadUI quad draw: region=({here.x},{here.y},"
                  f"{here.width},{here.height}) union=({ux},{uy},{uw},{uh}) "
                  f"viewport={tuple(gpu.state.viewport_get())}")
    else:
        w, h = regs[0].width / s, regs[0].height / s
    mx, my = panels.mouse               # already in scaled units (modal)
    panels.hover_tip = None

    gpu.state.blend_set('ALPHA')
    gpu.state.depth_test_set('NONE')
    gpu.matrix.push()
    try:
        gpu.matrix.translate((-ox, -oy))
        gpu.matrix.scale((s, s))
        _guard(top_bar.draw)
        for fn in (lambda: style.draw_groups(ctx, w, h),
                   lambda: viewport_ui.draw_info(ctx, w, h),
                   lambda: panels.draw_bottom(ctx, w, h, mx, my),
                   lambda: panels.draw_side(ctx, w, h, mx, my),
                   lambda: color_overlay.draw(ctx, w, h, mx, my),
                   lambda: fav_bar.draw(ctx, w, h, mx, my),
                   lambda: asset_gpu.draw(ctx, w, h, mx, my),
                   lambda: outliner_gpu.draw(ctx, w, h, mx, my),
                   lambda: edit_ops.draw(ctx, w, h),
                   lambda: viewport_ui.draw_tooltip(ctx, w, h, mx, my)):
            _guard(fn)
    finally:
        gpu.matrix.pop()
        drawing.SCALE = 1.0              # other draw handlers do not scale
    gpu.state.blend_set('NONE')


# ----------------------------------------------------------------------
# Register
# ----------------------------------------------------------------------

def register():
    bpy.types.Scene.nomad_ui_active = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.nomad_scrub_visible = bpy.props.BoolProperty(
        default=False)
    bpy.types.Scene.nomad_color_overlay = bpy.props.BoolProperty(
        name="Color Picker", default=True)
    bpy.types.Scene.nomad_nav_gizmo = bpy.props.BoolProperty(
        name="Navigate Gizmo", default=True)
    bpy.types.Scene.nomad_fav_bar = bpy.props.BoolProperty(
        name="Favorites Bar", default=False)
    for cls in CLASSES + (NOMAD_OT_wait_splash,):
        bpy.utils.register_class(cls)

    for mod in MODULES:
        fn = getattr(mod, "register", None)
        if fn is None:
            continue
        try:
            fn()
        except Exception:
            print(f"NomadUI: register failed in {mod.__name__}")
            traceback.print_exc()

    global _handle
    _handle = bpy.types.SpaceView3D.draw_handler_add(
        _draw_all, (), 'WINDOW', 'POST_PIXEL')

    bpy.app.handlers.load_post.append(_on_load)
    bpy.app.handlers.load_factory_startup_post.append(_on_load)
    bpy.app.handlers.save_pre.append(_on_save_pre)
    bpy.app.handlers.save_post.append(_on_save_post)
    _gate["click"] = True
    _schedule_post_load(first=3.0)
    try:
        style.install()
    except Exception:
        traceback.print_exc()


def unregister():
    global _handle

    if safety.quitting():
        return          # Blender is closing: touch nothing at all

    _cancel_timers()

    for lst, fn in ((bpy.app.handlers.load_post, _on_load),
                    (bpy.app.handlers.load_factory_startup_post, _on_load),
                    (bpy.app.handlers.save_pre, _on_save_pre),
                    (bpy.app.handlers.save_post, _on_save_post)):
        if fn in lst:
            lst.remove(fn)



    if _handle:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_handle, 'WINDOW')
        except (ValueError, RuntimeError):
            pass
        _handle = None

    was_running = modal.running
    try:
        for sc in bpy.data.scenes:
            sc.nomad_ui_active = False
    except Exception:
        pass
    modal.running = False
    try:
        viewport_ui.restore_native(bpy.context)
    except Exception:
        pass
    if was_running or modal.any_fullscreen():
        modal.exit_fullscreen_deferred()

    for mod in reversed(MODULES):
        fn = getattr(mod, "unregister", None)
        if fn is None:
            continue
        try:
            fn()
        except Exception:
            traceback.print_exc()

    for cls in reversed(CLASSES + (NOMAD_OT_wait_splash,)):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    for name in ("nomad_ui_active", "nomad_scrub_visible",
                 "nomad_color_overlay", "nomad_nav_gizmo",
                 "nomad_fav_bar"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)


if __name__ == "__main__":
    register()