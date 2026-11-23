# Real Blender editors in place of our 3D viewport (Image, UV, Shader,
# Geometry Nodes, Compositor, Video Sequencer, Movie Clip). The editor-type selector of
# their header is covered by a "back to 3D" button.
import bpy

from . import drawing, safety

COVER = 1.9      # width of the covered selector, in header heights

EDITORS = (
    ("IMAGE", "Image Editor", 'IMAGE_DATA',
     {"type": 'IMAGE_EDITOR', "ui_mode": 'VIEW'}),
    ("UV", "UV Editor", 'UV',
     {"type": 'IMAGE_EDITOR', "ui_mode": 'UV'}),
    ("SHADER", "Shader Editor", 'NODE_MATERIAL',
     {"type": 'NODE_EDITOR', "tree_type": 'ShaderNodeTree'}),
    ("GEOMETRY", "Geometry Nodes", 'GEOMETRY_NODES',
     {"type": 'NODE_EDITOR', "tree_type": 'GeometryNodeTree'}),
    ("COMPOSITOR", "Compositor", 'NODE_COMPOSITING',
     {"type": 'NODE_EDITOR', "tree_type": 'CompositorNodeTree'}),
    ("VIDEO", "Video Sequencer", 'SEQUENCE', {"type": 'SEQUENCE_EDITOR'}),
    ("CLIP", "Movie Clip Editor", 'TRACKING',
     {"type": 'CLIP_EDITOR', "mode": 'TRACKING'}),
    ("MASK", "Mask Editor", 'MOD_MASK',
     {"type": 'CLIP_EDITOR', "mode": 'MASK'}),
)

_ptr = [None]         # pointer of the area we switched (when not fullscreen)
_handles = []


# ----------------------------------------------------------------------
# Finding "our" area
# ----------------------------------------------------------------------

def find_area():
    """(window, area) of the tablet viewport, whatever editor it shows."""
    try:
        wm = bpy.context.window_manager
        for win in wm.windows:
            scr = win.screen
            if scr.show_fullscreen and len(scr.areas):
                return win, scr.areas[0]
        if _ptr[0] is not None:
            for win in wm.windows:
                for a in win.screen.areas:
                    if a.as_pointer() == _ptr[0]:
                        return win, a
        for win in wm.windows:
            for a in win.screen.areas:
                if a.type == 'VIEW_3D':
                    return win, a
    except (AttributeError, RuntimeError, ReferenceError):
        pass
    return None, None


def active():
    """True while a real editor replaces our 3D viewport."""
    win, area = find_area()
    return area is not None and area.type != 'VIEW_3D'


# ----------------------------------------------------------------------
# Switching
# ----------------------------------------------------------------------

def _apply(area, spec):
    area.type = spec["type"]
    sp = area.spaces.active
    for key in ("ui_mode", "tree_type", "mode"):
        if key in spec:
            try:
                setattr(sp, key, spec[key])
            except (AttributeError, TypeError, ValueError,
                    RuntimeError) as exc:
                print(f"NomadUI editors: {key}: {exc!r}")


def _later(fn, delay=0.08):
    def _run():
        try:
            fn()
        except Exception as exc:
            print(f"NomadUI editors: {exc!r}")
        return None
    try:
        bpy.app.timers.register(_run, first_interval=delay)
    except RuntimeError:
        pass


def switch_deferred(which):
    spec = next((e[3] for e in EDITORS if e[0] == which), None)
    if spec is None:
        return

    def _go():
        win, area = find_area()
        if area is None or area.type != 'VIEW_3D':
            return
        _ptr[0] = area.as_pointer()
        with bpy.context.temp_override(window=win, screen=win.screen,
                                       area=area):
            _apply(area, spec)
            area.tag_redraw()
    _later(_go)


def back_to_3d_deferred(after=None):
    def _go():
        win, area = find_area()
        if area is not None and area.type != 'VIEW_3D':
            with bpy.context.temp_override(window=win, screen=win.screen,
                                           area=area):
                area.type = 'VIEW_3D'
                area.tag_redraw()
        if after is not None:
            win, area = find_area()
            if win is not None and area is not None:
                with bpy.context.temp_override(window=win,
                                               screen=win.screen,
                                               area=area):
                    after()
            else:
                after()
    _later(_go)


# ----------------------------------------------------------------------
# Back button over the editor-type selector
# ----------------------------------------------------------------------

def _draw_header():
    if safety.exiting():
        return
    from . import modal
    ctx = bpy.context
    reg, scr, area = ctx.region, ctx.screen, ctx.area
    if (reg is None or scr is None or area is None or not modal.running
            or not scr.show_fullscreen or area.type == 'VIEW_3D'):
        return
    w = int(reg.height * COVER)
    drawing.begin_2d()
    drawing.rect(0, 0, w, reg.height, (0.14, 0.14, 0.15, 1.0))
    drawing.rect(3, 3, w - 3, reg.height - 3, (0.22, 0.48, 0.85, 1.0))
    drawing.text(w / 2, reg.height / 2 - 7, "◀ 3D", size=13,
                 color=(1, 1, 1, 1), align='CENTER')
    drawing.end_2d()


def back_hit(context, event):
    """True if the click lands on our back button (editors only)."""
    scr = context.screen
    if scr is None or not scr.show_fullscreen:
        return False
    for area in scr.areas:
        if area.type == 'VIEW_3D':
            continue
        for r in area.regions:
            if r.type == 'HEADER' and r.height > 0:
                w = int(r.height * COVER)
                if (r.x <= event.mouse_x <= r.x + w
                        and r.y <= event.mouse_y <= r.y + r.height):
                    return True
    return False


def corner_hit(context, event, size):
    """True if the click is in the top-right corner of the area (Blender's
    own "Back to Previous" button lives there)."""
    scr = context.screen
    if scr is None or not scr.show_fullscreen:
        return False
    from . import style
    for area in scr.areas:
        r = style.ui_region(area)
        if r is None:
            continue
        if (r.x <= event.mouse_x <= r.x + r.width
                and event.mouse_x > r.x + r.width - size
                and event.mouse_y > r.y + r.height - size
                and event.mouse_y <= r.y + r.height):
            return True
    return False


# ----------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------

class NOMAD_OT_editor_switch(bpy.types.Operator):
    bl_idname = "nomad.editor_switch"
    bl_label = "Switch Editor"
    bl_description = "Replace the 3D viewport with this editor"
    bl_options = {'INTERNAL'}

    which: bpy.props.StringProperty()

    def execute(self, context):
        if self.which == 'VIEW3D':
            back_to_3d_deferred()
        else:
            switch_deferred(self.which)
        return {'FINISHED'}


class NOMAD_PT_editors(bpy.types.Panel):
    bl_label = "Editors"
    bl_idname = "NOMAD_PT_editors"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 10
        col = l.column()
        col.scale_y = 1.6
        for key, label, icon, _spec in EDITORS:
            col.operator("nomad.editor_switch", text=label,
                         icon=icon).which = key
        l.label(text="Use the 3D button at the top left to come back")


CLASSES = (NOMAD_OT_editor_switch, NOMAD_PT_editors)
def _uv_menu_extra(self, context):
    self.layout.separator()
    self.layout.operator("nomad.editor_switch", text="UV Editor",
                         icon='UV').which = 'UV'


def _image_button(self, context):
    self.layout.operator("nomad.editor_switch", text="Image Editor",
                         icon='IMAGE_DATA').which = 'IMAGE'


def _gn_button(self, context):
    obj = context.active_object
    if obj is not None and any(m.type == 'NODES' for m in obj.modifiers):
        self.layout.separator()
        self.layout.operator("nomad.editor_switch",
                             text="Open Geometry Nodes Editor",
                             icon='GEOMETRY_NODES').which = 'GEOMETRY'


def _hook_buttons(add):
    """Editor buttons injected into popups that live in other modules."""
    for name, fn, first in (("NOMAD_PT_tp_options", _image_button, True),
                            ("NOMAD_PT_modifiers", _gn_button, False)):
        cls = getattr(bpy.types, name, None)
        if cls is None:
            print(f"NomadUI editors: {name} not found")
            continue
        try:
            if add:
                (cls.prepend if first else cls.append)(fn)
            else:
                cls.remove(fn)
        except (AttributeError, ValueError, RuntimeError) as exc:
            print(f"NomadUI editors: hook {name}: {exc!r}")


def ensure_file_browser_header():
    try:
        for window in bpy.context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'FILE_BROWSER':
                    for space in area.spaces:
                        if space.type == 'FILE_BROWSER':
                            space.show_header = True
    except Exception:
        pass


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _hook_buttons(True)
    try:
        bpy.types.VIEW3D_MT_uv_map.append(_uv_menu_extra)
    except (AttributeError, RuntimeError):
        pass
    for name in ("SpaceImageEditor", "SpaceNodeEditor",
                 "SpaceSequenceEditor", "SpaceClipEditor"):
        space = getattr(bpy.types, name, None)
        if space is None:
            continue
        try:
            _handles.append((space, space.draw_handler_add(
                _draw_header, (), 'HEADER', 'POST_PIXEL')))
        except (TypeError, ValueError, RuntimeError, AttributeError) as exc:
            print(f"NomadUI editors: header handler {name}: {exc!r}")


def unregister():
    _hook_buttons(False)
    try:
        bpy.types.VIEW3D_MT_uv_map.remove(_uv_menu_extra)
    except (AttributeError, ValueError, RuntimeError):
        pass
    for space, handle in _handles:
        try:
            space.draw_handler_remove(handle, 'HEADER')
        except (ValueError, RuntimeError):
            pass
    _handles.clear()
    if active():
        back_to_3d_deferred()
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass