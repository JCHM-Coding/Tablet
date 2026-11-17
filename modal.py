import bpy
from . import top_bar, panels, viewport_ui, editors, style
from .sculpt_popups import _view3d_override

running = False        # True only while the modal operator is alive
_want_exit = False     # True only when the user asked to leave
CORNER = 22            # px around Blender's "Back to Previous" corner


def tag_all_view3d_redraw(context=None):
    """Redibuja todos los viewport 3D buscándolos AL MOMENTO."""
    try:
        ctx = context or bpy.context
        for window in ctx.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    area.tag_redraw()
    except (ReferenceError, RuntimeError, AttributeError):
        pass


def defer_operator(*op_ids):
    """Run operators in the next cycle, OUTSIDE the modal callback."""
    def _run():
        last = None
        for op_id in op_ids:
            try:
                mod, name = op_id.split(".")
                getattr(getattr(bpy.ops, mod), name)('INVOKE_DEFAULT')
                return None
            except (RuntimeError, AttributeError) as exc:
                last = f"{op_id}: {exc}"
        if last:
            print(f"NomadUI deferred: {last}")
        return None
    try:
        bpy.app.timers.register(_run, first_interval=0.01)
    except RuntimeError:
        pass


def area_under_mouse(context, mouse_x, mouse_y):
    if not context.screen:
        return None, None
    for area in context.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        region = style.ui_region(area)
        if region and (
            region.x <= mouse_x <= region.x + region.width
            and region.y <= mouse_y <= region.y + region.height
        ):
            return area, region
    return None, None


def any_fullscreen():
    try:
        return any(win.screen.show_fullscreen
                   for win in bpy.context.window_manager.windows)
    except (AttributeError, RuntimeError, ReferenceError):
        return False


def _screen_full():
    win, area = editors.find_area()
    if area is None:
        return
    region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    with bpy.context.temp_override(window=win, screen=win.screen,
                                   area=area, region=region):
        bpy.ops.screen.screen_full_area('INVOKE_DEFAULT',
                                        use_hide_panels=True)


def _defer(fn, delay=0.05):
    def _run():
        try:
            fn()
        except Exception as exc:
            print(f"NomadUI deferred: {exc!r}")
        return None
    try:
        bpy.app.timers.register(_run, first_interval=delay)
    except RuntimeError:
        pass


def enter_fullscreen_deferred():
    def _go():
        if not any_fullscreen():
            _screen_full()
    _defer(_go)


def exit_fullscreen_deferred():
    def _go():
        if any_fullscreen():
            _screen_full()
    _defer(_go)


def _apply_keymap_defaults():
    """Knife / predefined-stroke double-click, applied after the UI is up
    (never while Blender is still loading)."""
    try:
        from . import mesh_panels, gp_panels
        mesh_panels._apply_knife_default()
        gp_panels._apply_confirm_default()
    except Exception as exc:
        print(f"NomadUI keymap defaults: {exc!r}")


def start_deferred(delay=0.05):
    """Start the tablet mode from a timer, with the main 3D area as the
    context. Starting it from the sidebar (N panel) region fails because
    the fullscreen hides that very region."""
    def _go():
        if running:
            return
        win, area, region = _view3d_override()
        if area is None:
            print("NomadUI: there is no 3D viewport to start in")
            return
        for sc in bpy.data.scenes:
            sc.nomad_ui_active = False         # stale flag from before
        with bpy.context.temp_override(window=win, area=area,
                                       region=region):
            bpy.ops.nomad.modal('INVOKE_DEFAULT')
    _defer(_go, delay)


def _finish_exit():
    viewport_ui.restore_native(bpy.context)
    exit_fullscreen_deferred()
    tag_all_view3d_redraw()


def restore_ui(context):
    global _want_exit
    _want_exit = running          # only meaningful if the modal is alive
    context.scene.nomad_ui_active = False
    if editors.active():
        # a real editor is showing: go back to 3D first, then restore
        editors.back_to_3d_deferred(after=_finish_exit)
    else:
        _finish_exit()


class NOMAD_OT_modal(bpy.types.Operator):
    bl_idname = "nomad.modal"
    bl_label = "Start Tablet Mode"
    bl_description = "Clean viewport with custom bars (tablet mode)"
    bl_options = {'REGISTER'}

    _timer = None
    _first = True

    def modal(self, context, event):
        if not context.scene.nomad_ui_active:
            if _want_exit:
                self.cancel(context)
                return {'CANCELLED'}
            # an undo step brought back an old value of the flag
            context.scene.nomad_ui_active = True

        if (event.type == 'ESC' and event.value == 'PRESS'
                and not editors.active()):
            restore_ui(context)
            self.cancel(context)
            return {'CANCELLED'}

        if event.type == 'TIMER':
            if self._first:
                self._first = False
                enter_fullscreen_deferred()
                _defer(_apply_keymap_defaults, 1.0)
                viewport_ui.hide_native(context)
                tag_all_view3d_redraw(context)
                return {'PASS_THROUGH'}
            viewport_ui.enforce(context)

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            # "Back to Previous" corner of Blender (any editor): never let
            # a tap reach it by accident
            if editors.corner_hit(context, event, CORNER):
                return {'RUNNING_MODAL'}
            # our "back to 3D" button over the editor-type selector
            if editors.back_hit(context, event):
                editors.back_to_3d_deferred()
                return {'RUNNING_MODAL'}

        area, region = area_under_mouse(context,
                                        event.mouse_x, event.mouse_y)

        if area is not None:
            s = style.ui_scale()
            mx = (event.mouse_x - region.x) / s
            my = (event.mouse_y - region.y) / s
            top_bar.mouse = (mx, my)
            panels.mouse = (mx, my)
            panels.hover_tip = None

            if event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
                from . import (outliner_gpu, asset_gpu, color_overlay,
                               timeline_ext)
                d = 1 if event.type == 'WHEELUPMOUSE' else -1
                if (timeline_ext.wheel(area, region, mx, my, d)
                        or asset_gpu.wheel(area, region, mx, my, d)
                        or outliner_gpu.wheel(area, region, mx, my, d)
                        or color_overlay.wheel(area, region, mx, my, d)
                        or style.wheel(area, region, mx, my, d)):
                    area.tag_redraw()
                    return {'RUNNING_MODAL'}

            if event.type == 'LEFTMOUSE':
                if event.value == 'PRESS':
                    area.tag_redraw()
                    consumed = top_bar.handle_click(area, mx, my, self)
                    if not consumed:
                        res = panels.handle_press(area, mx, my, self)
                        consumed = (res is not False)  # True o 'drag'
                    tag_all_view3d_redraw(context)
                    if consumed:
                        return {'RUNNING_MODAL'}
                    return {'PASS_THROUGH'}
                elif event.value == 'RELEASE':
                    panels.drag_release()
                    top_bar.scrub_release()
                    area.tag_redraw()

            if event.type == 'MOUSEMOVE':
                if panels.drag is not None:
                    panels.drag_update(area, mx, my)
                if top_bar.drag_state is not None:
                    top_bar.scrub_drag(area, mx, my)

            area.tag_redraw()

        return {'PASS_THROUGH'}

    def invoke(self, context, event):
        global running, _want_exit
        if context.scene.nomad_ui_active:
            return {'CANCELLED'}
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.1, window=context.window)
        wm.modal_handler_add(self)
        context.scene.nomad_ui_active = True
        running = True
        _want_exit = False
        try:
            from .panels import disable_unified
            disable_unified(context)
        except Exception:
            pass
        self._first = True
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        """Blender also calls this when it QUITS or loads a file: in that
        case touch nothing (windows and screens are being freed)."""
        global running, _want_exit
        running = False
        if not _want_exit:
            return
        _want_exit = False
        try:
            if self._timer:
                context.window_manager.event_timer_remove(self._timer)
            self._timer = None
            context.scene.nomad_ui_active = False
            tag_all_view3d_redraw(context)
        except (RuntimeError, AttributeError, ReferenceError):
            pass


class NOMAD_OT_start(bpy.types.Operator):
    """Start the tablet mode (used by the N panel button)."""
    bl_idname = "nomad.start"
    bl_label = "Start Tablet Mode"
    bl_description = "Clean viewport with custom bars (tablet mode)"

    @classmethod
    def poll(cls, context):
        return not running

    def execute(self, context):
        start_deferred()
        return {'FINISHED'}


class NOMAD_OT_toggle_off(bpy.types.Operator):
    """Exit the tablet mode and restore Blender's interface."""
    bl_idname = "nomad.toggle_off"
    bl_label = "Exit Tablet Mode"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        restore_ui(context)
        return {'FINISHED'}