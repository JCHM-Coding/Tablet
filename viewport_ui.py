# Viewport housekeeping for the tablet mode: our own info text (clear of
# the bars), Blender's text / statistics / HUD hidden meanwhile, and the
# frame-number entry popup.
import bpy
import time
import blf
import contextlib
from mathutils import Quaternion

from . import top_bar
from . import drawing, panels
from .top_bar import BAR_H
from . import safety

_saved = {}         # space pointer -> {"text", "stats", "hud"} originals
COL_INFO = (0.92, 0.93, 0.95, 0.9)

_VIEWS = (("Top", (1, 0, 0, 0)), ("Bottom", (0, 1, 0, 0)),
          ("Front", (0.7071, 0.7071, 0, 0)),
          ("Back", (0, 0, 0.7071, 0.7071)),
          ("Left", (0.5, -0.5, -0.5, -0.5)),
          ("Right", (0.5, -0.5, 0.5, 0.5)))


def _spaces(context):
    try:
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == 'VIEW_3D':
                    yield area.spaces.active
    except (AttributeError, RuntimeError, ReferenceError):
        return


_shelf_tries = {}


def _areas(context):
    try:
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == 'VIEW_3D':
                    yield win, area
    except (AttributeError, RuntimeError, ReferenceError):
        return


def _hide_shelf(context):
    """The asset shelf flag is read-only: toggle its region instead."""
    for win, area in _areas(context):
        key = area.as_pointer()
        try:
            shown = bool(area.spaces.active.show_region_asset_shelf)
        except (AttributeError, RuntimeError):
            return
        if not shown:
            _shelf_tries.pop(key, None)
            continue
        n = _shelf_tries.get(key, 0)
        if n >= 3:
            continue
        _shelf_tries[key] = n + 1

        def _go(key=key):
            try:
                for w2, a2 in _areas(bpy.context):
                    if a2.as_pointer() != key:
                        continue
                    region = next((r for r in a2.regions
                                   if r.type == 'WINDOW'), None)
                    with bpy.context.temp_override(window=w2, area=a2,
                                                   region=region):
                        bpy.ops.screen.region_toggle(
                            region_type='ASSET_SHELF')
            except (RuntimeError, TypeError, AttributeError) as exc:
                print(f"NomadUI asset shelf: {exc!r}")
            return None
        try:
            bpy.app.timers.register(_go, first_interval=0.05)
        except RuntimeError:
            pass


def _is_quad(sp):
    try:
        return len(sp.region_quadviews) > 0
    except (AttributeError, TypeError, RuntimeError):
        return False


def _hud_off(sp):
    """Write show_region_hud only when it is on, and never in Quad View:
    writing it with no HUD region makes Blender crash."""
    try:
        if not _is_quad(sp) and sp.show_region_hud:
            sp.show_region_hud = False
    except (AttributeError, RuntimeError):
        pass


def hide_native(context):
    """Hide Blender's text info, statistics and Adjust Last Operation HUD
    (and close the asset shelf) while the tablet mode is on."""
    if safety.no_window():
        return
    for sp in _spaces(context):
        key = sp.as_pointer()
        if key in _saved:
            continue
        try:
            ov = sp.overlay
            _saved[key] = {"text": bool(ov.show_text),
                           "stats": bool(ov.show_stats),
                           "hud": bool(sp.show_region_hud)}
            ov.show_text = False
            ov.show_stats = False
        except (AttributeError, RuntimeError) as exc:
            print(f"NomadUI hide native overlays: {exc!r}")
            continue
        _hud_off(sp)
    _hide_shelf(context)


def show_headers(context):
    """The File Browser that Blender opens for File > Open / Import (in a
    temporary window) and the Outliner in its Blender File view must always
    show their header, whatever hid it."""
    if safety.no_window():
        return
    try:
        for win in context.window_manager.windows:
            for area in win.screen.areas:
                if area.type == 'FILE_BROWSER':
                    pass
                elif area.type == 'OUTLINER':
                    if getattr(area.spaces.active, "display_mode",
                               None) != 'LIBRARIES':
                        continue
                else:
                    continue
                sp = area.spaces.active
                if sp is not None and not sp.show_region_header:
                    sp.show_region_header = True
                    area.tag_redraw()
    except (AttributeError, RuntimeError, ReferenceError):
        pass


def enforce(context):
    """Called every 0.1 s: switching mode can bring back the HUD or the
    mode's own asset shelf, so close them again."""
    if safety.no_window():
        return
    for sp in _spaces(context):
        _hud_off(sp)
    _hide_shelf(context)
    show_headers(context)


def restore_native(context):
    if safety.no_window():
        return                      # quitting: writing here would crash
    for sp in _spaces(context):
        saved = _saved.pop(sp.as_pointer(), None)
        if not saved:
            continue
        try:
            sp.overlay.show_text = saved["text"]
            sp.overlay.show_stats = saved["stats"]
            if (not _is_quad(sp)
                    and bool(sp.show_region_hud) != saved["hud"]):
                sp.show_region_hud = saved["hud"]
        except (AttributeError, RuntimeError):
            pass


def reset():
    _saved.clear()


def info_state(context, which):
    sp = getattr(context, "space_data", None)
    saved = _saved.get(sp.as_pointer()) if sp is not None else None
    return bool(saved and saved.get(which))


def _view_title(rv3d):
    if rv3d.view_perspective == 'CAMERA':
        return ("Camera Perspective" if rv3d.is_perspective
                else "Camera Orthographic")
    name = "User"
    q = rv3d.view_rotation
    for n, v in _VIEWS:
        if abs(q.dot(Quaternion(v))) > 0.9999:
            name = n
            break
    return f"{name} {'Perspective' if rv3d.is_perspective else 'Orthographic'}"


def _info_x(context):
    from . import tool_sidebar as ts
    from . import style
    x = (panels.MARGIN + 4 + panels.BTN + panels.PAD + 8
         + style.left_inset(context))
    if (getattr(context.scene, "nomad_sidebar_left", False)
            and ts.BUTTONS_BY_MODE.get(context.mode)):
        x += panels.BTN + panels.PAD
    return x


def draw_info(context, w, h):
    sp = context.space_data
    rv3d = sp.region_3d if sp is not None else None
    if sp is None or rv3d is None:
        return
    saved = _saved.get(sp.as_pointer())
    if not saved:
        return
    from . import style
    x = _info_x(context)
    y = h - BAR_H - 22 - style.top_inset(context)
    if saved.get("text"):
        drawing.text(x, y, _view_title(rv3d), size=15, color=COL_INFO)
        y -= 20
        coll = context.view_layer.active_layer_collection
        obj = context.active_object
        line = f"({context.scene.frame_current}) {coll.name if coll else ''}"
        if obj is not None:
            line += f" | {obj.name}"
        drawing.text(x, y, line, size=13, color=COL_INFO)
        y -= 22
    if saved.get("stats"):
        try:
            text = context.scene.statistics(context.view_layer)
        except (AttributeError, RuntimeError, TypeError):
            return
        for part in text.split(" | "):
            drawing.text(x, y, part, size=12, color=COL_INFO)
            y -= 17


class NOMAD_OT_info_toggle(bpy.types.Operator):
    bl_idname = "nomad.info_toggle"
    bl_label = "Viewport Info"
    bl_options = {'INTERNAL'}

    which: bpy.props.StringProperty()

    def execute(self, context):
        sp = getattr(context, "space_data", None)
        saved = _saved.get(sp.as_pointer()) if sp is not None else None
        if saved is None or self.which not in saved:
            return {'CANCELLED'}
        saved[self.which] = not saved[self.which]
        return {'FINISHED'}


class NOMAD_PT_frame_entry(bpy.types.Panel):
    bl_label = "Frame Range"
    bl_idname = "NOMAD_PT_frame_entry"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 8
        sc = context.scene
        col = l.column()
        col.scale_y = 1.5
        col.prop(sc, "frame_current", text="Current")
        col.prop(sc, "frame_start", text="Start")
        col.prop(sc, "frame_end", text="End")


_tip = {"text": None, "since": 0.0}


def draw_tooltip(context, w, h, mx, my):
    """Blender-style tooltip: small black box, white text, after 0.5 s."""
    text = top_bar.tip_now or panels.hover_tip
    now = time.time()
    if text != _tip["text"]:
        _tip["text"], _tip["since"] = text, now
        return
    if not text or now - _tip["since"] < 0.5:
        return
    blf.size(0, 13)
    tw, th = blf.dimensions(0, text)
    x = max(8.0, min(mx + 16, w - tw - 16))
    y = max(8.0, my - 34)
    drawing.rect(x - 6, y - 5, x + tw + 6, y + th + 6, (0, 0, 0, 0.92))
    drawing.text(x, y, text, size=13, color=(1, 1, 1, 1))


def _ov():
    from .sculpt_popups import _view3d_override
    win, area, region = _view3d_override()
    if win is None:
        return contextlib.nullcontext()
    return bpy.context.temp_override(window=win, area=area, region=region)


def _leave_and_quit(act):
    """Leave the tablet mode, then (a moment later) save and quit."""
    from . import modal
    if modal.running:
        modal.restore_ui(bpy.context)

    def _go():
        try:
            if act == 'SAVE':
                if bpy.data.filepath:
                    with _ov():
                        bpy.ops.wm.save_mainfile('EXEC_DEFAULT')
                else:
                    with _ov():
                        bpy.ops.wm.save_as_mainfile('INVOKE_DEFAULT')
                    return None          # the user picks a file first
            with _ov():
                bpy.ops.wm.quit_blender('EXEC_DEFAULT')   # no 2nd popup
        except Exception as exc:
            print(f"NomadUI quit: {exc!r}")
        return None
    try:
        bpy.app.timers.register(_go, first_interval=1.2)
    except RuntimeError:
        pass


class NOMAD_OT_quit(bpy.types.Operator):
    bl_idname = "nomad.quit"
    bl_label = "Quit Blender"
    bl_description = "Exit the tablet mode first, then close Blender"
    bl_options = {'INTERNAL'}

    action: bpy.props.EnumProperty(items=[
        ('ASK', "Ask", ""), ('SAVE', "Save", ""),
        ('DISCARD', "Don't Save", ""), ('CANCEL', "Cancel", "")],
        default='ASK')

    def execute(self, context):
        act = self.action
        if act == 'CANCEL':
            return {'FINISHED'}
        if act == 'ASK':
            use_prompt = bool(bpy.context.preferences.view.use_save_prompt)
            if use_prompt and bpy.data.is_dirty:
                from .sculpt_popups import open_panel_deferred
                open_panel_deferred("NOMAD_PT_quit")
                return {'FINISHED'}
            act = 'DISCARD'        # prompt off, or nothing to save 
        _leave_and_quit(act)
        return {'FINISHED'}


class NOMAD_PT_quit(bpy.types.Panel):
    bl_label = "Quit"
    bl_idname = "NOMAD_PT_quit"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 10
        l.label(text="Save changes before closing?", icon='QUESTION')
        col = l.column()
        col.scale_y = 1.5
        for act, text, icon in (('SAVE', "Save", 'FILE_TICK'),
                                ('DISCARD', "Don't Save", 'TRASH'),
                                ('CANCEL', "Cancel", 'X')):
            col.operator("nomad.quit", text=text, icon=icon).action = act


_keymaps = []


def _register_keys():
    try:
        kc = bpy.context.window_manager.keyconfigs.addon
        if kc is None:
            return
        km = kc.keymaps.new(name="Window", space_type='EMPTY')
        kmi = km.keymap_items.new("nomad.quit", 'Q', 'PRESS', ctrl=True)
        kmi.properties.action = 'ASK'
        _keymaps.append((km, kmi))
    except Exception as exc:
        print(f"NomadUI keymap: {exc!r}")


def _unregister_keys():
    for km, kmi in _keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _keymaps.clear()


CLASSES = (NOMAD_OT_info_toggle, NOMAD_PT_frame_entry, NOMAD_OT_quit,
           NOMAD_PT_quit)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _register_keys()


def unregister():
    _unregister_keys()
    try:
        restore_native(bpy.context)
    except Exception:
        pass
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass