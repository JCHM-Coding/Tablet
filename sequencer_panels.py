# Video sequencer: a "Render" tab in the sidebar with two panels,
# Render (engine, Film, Color Management) and Output.
import bpy
from .render_view_panels import _find, _draw_native


def _native(layout, context, ctx_name, items):
    engine = context.scene.render.engine
    drew = False
    for labels in items:
        for cls in _find(ctx_name, labels, engine, context):
            _draw_native(layout, cls, context, engine)
            drew = True
    return drew


class NOMAD_PT_seq_render(bpy.types.Panel):
    bl_label = "Render"
    bl_idname = "NOMAD_PT_seq_render"
    bl_space_type = 'SEQUENCE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Render"

    def draw(self, context):
        l = self.layout
        l.use_property_split = True
        l.prop(context.scene.render, "engine", text="Engine")
        if not _native(l, context, "render", (("Film",),
                                              ("Color Management",))):
            l.label(text="Film / Color Management not found", icon='INFO')


class NOMAD_PT_seq_output(bpy.types.Panel):
    bl_label = "Output"
    bl_idname = "NOMAD_PT_seq_output"
    bl_space_type = 'SEQUENCE_EDITOR'
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


CLASSES = (NOMAD_PT_seq_render, NOMAD_PT_seq_output)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass