# Movie Clip Editor (also used for masks): what the Video Sequencer got.
#   - a "Render" tab in the sidebar (N panel) with Render and Output,
#   - a "View" tab to switch the mode (Tracking / Mask) and the view
#     (Clip / Graph / Dope Sheet),
#   - the view selector in the header while the mask mode is active, where
#     Blender does not offer it.
# The editor itself is swapped in by editors.py ("Movie Clip Editor" and
# "Mask Editor" in the Editors popup, with the "back to 3D" button).
import bpy

from .sequencer_panels import _native


class NOMAD_PT_clip_render(bpy.types.Panel):
    bl_label = "Render"
    bl_idname = "NOMAD_PT_clip_render"
    bl_space_type = 'CLIP_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Render"

    def draw(self, context):
        l = self.layout
        l.use_property_split = True
        l.prop(context.scene.render, "engine", text="Engine")
        if not _native(l, context, "render", (("Film",),
                                              ("Color Management",))):
            l.label(text="Film / Color Management not found", icon='INFO')


class NOMAD_PT_clip_output(bpy.types.Panel):
    bl_label = "Output"
    bl_idname = "NOMAD_PT_clip_output"
    bl_space_type = 'CLIP_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Render"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        l = self.layout
        l.use_property_split = True
        drew = _native(l, context, "output", (
            ("Format",), ("Frame Range",), ("Stereoscopy",), ("Output",),
            ("Metadata",), ("Post Processing",)))
        drew = _native(l, context, "scene", (("Audio",),)) or drew
        if not drew:
            l.label(text="Output panels not found", icon='INFO')


class NOMAD_PT_clip_view(bpy.types.Panel):
    bl_label = "View"
    bl_idname = "NOMAD_PT_clip_view"
    bl_space_type = 'CLIP_EDITOR'
    bl_region_type = 'UI'
    bl_category = "View"

    def draw(self, context):
        sc = context.space_data
        l = self.layout
        if sc is None:
            return
        col = l.column()
        col.scale_y = 1.3
        col.label(text="Mode")
        col.prop(sc, "mode", expand=True)
        col.separator()
        col.label(text="View")
        col.prop(sc, "view", expand=True)
        if sc.view == 'DOPESHEET':
            l.label(text="Keyframes of the tracks", icon='INFO')


def _header_view(self, context):
    """Header: the view selector (Clip / Graph / Dope Sheet) in mask mode."""
    sc = context.space_data
    if sc is None or sc.type != 'CLIP_EDITOR' or sc.mode != 'MASK':
        return
    row = self.layout.row(align=True)
    row.prop(sc, "view", text="", expand=True)


CLASSES = (NOMAD_PT_clip_render, NOMAD_PT_clip_output, NOMAD_PT_clip_view)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    header = getattr(bpy.types, "CLIP_HT_header", None)
    if header is None:
        print("NomadUI clip: CLIP_HT_header not found")
        return
    try:
        header.append(_header_view)
    except (AttributeError, RuntimeError) as exc:
        print(f"NomadUI clip: header: {exc!r}")


def unregister():
    header = getattr(bpy.types, "CLIP_HT_header", None)
    if header is not None:
        try:
            header.remove(_header_view)
        except (AttributeError, ValueError, RuntimeError):
            pass
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass