# Sculpt Expand for Mask / Face Sets. One tool for each target; the
# falloff (incl. Snap) is chosen in the tool properties.
# Replaces sculpt_mode.py: disable that one to avoid duplicate scene props.
import bpy
import bpy_extras.view3d_utils

_KM_NAME = "Sculpt Expand Modal"

# Runtime state of the injected modal-keymap timer events.
_st = {
    "timers": [], "kmis": [], "handler": None,
    "frames": 0, "target": 0, "phase": 'NONE',
    "loop": 0, "distort": 0,
    "kmi_loop": None, "kmi_dist": None, "snap": None,
    "step_timer": None, "step_kmi": None,
}
_hidden_tools = None


# ----------------------------------------------------------------------
# Native toolbar entries (hidden while the addon is on)
# ----------------------------------------------------------------------

def _hide_native_expand_tools():
    global _hidden_tools
    try:
        from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active
        tools = VIEW3D_PT_tools_active._tools
        original = tools.get('SCULPT')
        if not isinstance(original, list):
            return

        def strip(items):
            out = []
            for item in items:
                if isinstance(item, (list, tuple)):
                    out.append(type(item)(strip(item)))
                elif getattr(item, 'operator', '') != 'sculpt.expand':
                    out.append(item)
            return out

        _hidden_tools = list(original)
        tools['SCULPT'] = strip(original)
    except Exception:
        _hidden_tools = None


def _restore_native_expand_tools():
    global _hidden_tools
    if _hidden_tools is None:
        return
    try:
        from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active
        VIEW3D_PT_tools_active._tools['SCULPT'] = _hidden_tools
    except Exception:
        pass
    _hidden_tools = None


# ----------------------------------------------------------------------
# Modal-keymap events (Loop / Distortion / Snap / recursion Step)
# ----------------------------------------------------------------------

def _expand_keymap():
    wm = bpy.context.window_manager
    for kc in (wm.keyconfigs.active, wm.keyconfigs.user,
               wm.keyconfigs.addon):
        km = kc.keymaps.get(_KM_NAME) if kc else None
        if km:
            return km
    return None


def _try(fn, *args):
    try:
        fn(*args)
    except Exception:
        pass


def _set_active(kmi, value):
    if kmi is not None:
        try:
            kmi.active = value
        except Exception:
            pass


def stop_step():
    """Stop the recursion timer and its modal-keymap item."""
    s = _st
    if s["step_kmi"] is not None:
        km = _expand_keymap()
        if km:
            _try(km.keymap_items.remove, s["step_kmi"])
        s["step_kmi"] = None
    if s["step_timer"] is not None:
        _try(bpy.context.window_manager.event_timer_remove,
             s["step_timer"])
        s["step_timer"] = None


def cleanup_internal_events():
    s = _st
    if s["handler"] is not None:
        _try(bpy.types.SpaceView3D.draw_handler_remove,
             s["handler"], 'WINDOW')
        s["handler"] = None
    wm = bpy.context.window_manager
    for t in s["timers"]:
        _try(wm.event_timer_remove, t)
    s["timers"].clear()
    km = _expand_keymap()
    if km:
        for kmi in s["kmis"] + [s["snap"]]:
            if kmi is not None:
                _try(km.keymap_items.remove, kmi)
    s["kmis"].clear()
    s["snap"] = None
    stop_step()
    s.update(frames=0, target=0, phase='NONE', loop=0, distort=0,
             kmi_loop=None, kmi_dist=None)


def _on_draw_step():
    s = _st
    s["frames"] += 1
    if s["snap"] is not None and s["frames"] == 6:
        _set_active(s["snap"], False)      # snap fires only once
    if (s["phase"] == 'LOOP' and s["frames"] >= s["loop"]
            and s["distort"] > 0):
        _set_active(s["kmi_loop"], False)
        _set_active(s["kmi_dist"], True)
        s["phase"] = 'DISTORTION'
    if s["frames"] >= s["target"]:
        cleanup_internal_events()


def setup_internal_events(loop_count=1, texture_distortion=0,
                          is_snap=False):
    s = _st
    cleanup_internal_events()
    km = _expand_keymap()
    window = bpy.context.window
    if not km or not window:
        return False
    s["frames"] = 0
    try:
        if is_snap:
            s["target"] = 20
            s["snap"] = km.keymap_items.new_modal(
                "SNAP_TOGGLE", 'TIMER', 'ANY')
            s["snap"].active = True
        else:
            loops = max(0, loop_count - 1)
            dist = max(0, texture_distortion)
            if loops == 0 and dist == 0:
                return True
            s.update(loop=loops, distort=dist, target=loops + dist + 1)
            if loops:
                s["kmi_loop"] = km.keymap_items.new_modal(
                    "LOOP_COUNT_INCREASE", 'TIMER', 'ANY')
                s["kmi_loop"].active = True
                s["kmis"].append(s["kmi_loop"])
            if dist:
                s["kmi_dist"] = km.keymap_items.new_modal(
                    "TEXTURE_DISTORTION_INCREASE", 'TIMER', 'ANY')
                s["kmi_dist"].active = not loops
                s["kmis"].append(s["kmi_dist"])
            s["phase"] = 'LOOP' if loops else 'DISTORTION'
        wm = bpy.context.window_manager
        s["timers"].append(wm.event_timer_add(
            0.05 if is_snap else 0.02, window=window))
        s["handler"] = bpy.types.SpaceView3D.draw_handler_add(
            _on_draw_step, (), 'WINDOW', 'POST_VIEW')
    except Exception as exc:
        print("EXPAND - event setup failed:", exc)
        cleanup_internal_events()
        return False
    return True


def setup_step(seconds, topology=False):
    """Repeating timer for native Geodesic/Topology recursion.
    0 disables it (and removes any previous one)."""
    s = _st
    stop_step()
    if seconds <= 0:
        return True
    km = _expand_keymap()
    window = bpy.context.window
    if not km or not window:
        print("EXPAND - Sculpt Expand Modal keymap/window not found")
        return False
    try:
        event = ("RECURSION_STEP_TOPOLOGY" if topology
                 else "RECURSION_STEP_GEODESIC")
        s["step_kmi"] = km.keymap_items.new_modal(event, 'TIMER', 'ANY')
        s["step_kmi"].active = True
        s["step_timer"] = bpy.context.window_manager.event_timer_add(
            float(seconds), window=window)
        return True
    except Exception as exc:
        print("EXPAND - step timer failed:", exc)
        stop_step()
        return False


def _update_step(scene, context):
    if scene.expand_helper_geodesic_step <= 0:
        stop_step()


def raycast_from_event(context, event):
    coord = (event.mouse_region_x, event.mouse_region_y)
    region, rv3d = context.region, context.region_data
    obj = context.active_object
    if not region or not rv3d or not obj or obj.type != 'MESH':
        return False, None, None, None
    view = bpy_extras.view3d_utils.region_2d_to_vector_3d(
        region, rv3d, coord)
    origin = bpy_extras.view3d_utils.region_2d_to_origin_3d(
        region, rv3d, coord)
    inv = obj.matrix_world.inverted()
    o = inv @ origin
    d = ((inv @ (origin + view)) - o).normalized()
    return obj.ray_cast(o, d)


# ----------------------------------------------------------------------
# Operator (Mask and Face Sets)
# ----------------------------------------------------------------------

class SCULPT_OT_nomad_expand(bpy.types.Operator):
    bl_idname = "sculpt.nomad_expand"
    bl_label = "Expand"

    target: bpy.props.EnumProperty(
        name="Target",
        items=[('MASK', "Mask", ""), ('FACE_SETS', "Face Sets", "")],
        default='MASK')
    falloff: bpy.props.EnumProperty(
        name="Falloff",
        items=[
            ('GEODESIC', "Geodesic", ""),
            ('TOPOLOGY', "Topology", ""),
            ('TOPOLOGY_DIAGONALS', "Topology Diagonals", ""),
            ('SPHERICAL', "Spherical", ""),
            ('SNAP', "Snap", "Geodesic, repositioning the pivot"),
        ],
        default='TOPOLOGY')
    preserve: bpy.props.BoolProperty(name="Preserve", default=False)
    invert: bpy.props.BoolProperty(name="Invert", default=False)
    gradient_falloff: bpy.props.BoolProperty(
        name="Gradient Falloff", default=False)              # mask only
    expand_by_normals: bpy.props.BoolProperty(
        name="Expand by Normals", default=False)             # mask only
    texture_distortion: bpy.props.IntProperty(
        name="Distortion", default=0, min=0, soft_max=32)    # mask only
    active_faceset: bpy.props.BoolProperty(
        name="Active Face Set", default=False)               # face sets only
    loop_count: bpy.props.IntProperty(
        name="Loop", default=1, min=1, soft_max=16)

    def modal(self, context, event):
        if event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            hit = raycast_from_event(context, event)[0]
            if not hit:
                cleanup_internal_events()
                return {'FINISHED'}
        return {'RUNNING_MODAL'}

    def invoke(self, context, event):
        sc = context.scene
        step = getattr(sc, "expand_helper_geodesic_step", 0)
        topology = getattr(sc, "expand_helper_recursion_topology", False)
        mask = self.target == 'MASK'

        if self.falloff == 'SNAP':
            if not setup_internal_events(is_snap=True):
                return {'CANCELLED'}
            extra = dict(falloff_type='GEODESIC', use_reposition_pivot=True)
        else:
            if not setup_step(step, topology):
                return {'CANCELLED'}
            # With Step active the TIMER belongs to the recursion map;
            # with Step=0 Loop/Distortion keep working.
            if step <= 0:
                setup_internal_events(
                    self.loop_count,
                    self.texture_distortion if mask else 0)
            if mask:
                extra = dict(
                    falloff_type=('NORMALS' if self.expand_by_normals
                                  else self.falloff),
                    use_falloff_gradient=self.gradient_falloff)
            elif self.active_faceset:
                extra = dict(falloff_type='BOUNDARY_FACE_SET',
                             use_modify_active=True)
            else:
                extra = dict(falloff_type=self.falloff)

        return bpy.ops.sculpt.expand(
            'INVOKE_DEFAULT', target=self.target, invert=self.invert,
            use_mask_preserve=self.preserve, **extra)


# ----------------------------------------------------------------------
# Tools
# ----------------------------------------------------------------------

def _draw_settings(context, layout, tool, mask):
    p = tool.operator_properties("sculpt.nomad_expand")
    layout.prop(p, "falloff", text="Falloff")
    layout.prop(p, "preserve", text="Preserve")
    layout.prop(p, "invert", text="Invert")
    if mask:
        layout.prop(p, "gradient_falloff", text="Gradient")
        layout.prop(p, "expand_by_normals", text="Normals")
        layout.prop(p, "texture_distortion", text="Distortion")
        layout.popover(panel="NOMAD_PT_texture", text="Texture",
                       icon='TEXTURE')
    else:
        layout.prop(p, "active_faceset", text="Active Face Set")
    layout.prop(p, "loop_count", text="Loop")
    layout.prop(context.scene, "expand_helper_geodesic_step", text="Step")
    layout.prop(context.scene, "expand_helper_recursion_topology",
                text="Topology Recursion", toggle=True)


class SCULPT_WST_expand_mask(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'SCULPT'
    bl_idname = "sculpt.nomad_expand_mask"
    bl_label = "Expand Mask"
    bl_description = "Expand the mask from the clicked point"
    bl_icon = "brush.sculpt.mask"
    bl_operator = "sculpt.nomad_expand"
    bl_keymap = ((
        "sculpt.nomad_expand",
        {"type": 'LEFTMOUSE', "value": 'PRESS'},
        {"properties": [("target", 'MASK')]},
    ),)

    @staticmethod
    def draw_settings(context, layout, tool):
        _draw_settings(context, layout, tool, True)


class SCULPT_WST_expand_facesets(bpy.types.WorkSpaceTool):
    bl_space_type = 'VIEW_3D'
    bl_context_mode = 'SCULPT'
    bl_idname = "sculpt.nomad_expand_facesets"
    bl_label = "Expand Face Sets"
    bl_description = "Expand face sets from the clicked point"
    bl_icon = "brush.sculpt.draw_face_sets"
    bl_operator = "sculpt.nomad_expand"
    bl_keymap = ((
        "sculpt.nomad_expand",
        {"type": 'LEFTMOUSE', "value": 'PRESS'},
        {"properties": [("target", 'FACE_SETS')]},
    ),)

    @staticmethod
    def draw_settings(context, layout, tool):
        _draw_settings(context, layout, tool, False)


CLASSES = (SCULPT_OT_nomad_expand,)
TOOLS = (
    (SCULPT_WST_expand_mask, {"builtin.annotate"}, True),
    (SCULPT_WST_expand_facesets,
     {SCULPT_WST_expand_mask.bl_idname}, False),
)


def register():
    _hide_native_expand_tools()
    bpy.types.Scene.expand_helper_geodesic_step = bpy.props.IntProperty(
        name="Geodesic Step", default=0, min=0, soft_max=9,
        update=_update_step)
    bpy.types.Scene.expand_helper_recursion_topology = \
        bpy.props.BoolProperty(name="Topology Recursion", default=False)
    for cls in CLASSES:
        try:
            bpy.utils.register_class(cls)
        except ValueError:
            pass
    for tool_cls, after, sep in TOOLS:
        try:
            bpy.utils.register_tool(tool_cls, after=after,
                                    separator=sep, group=False)
        except Exception as exc:
            print(f"NomadUI expand tool {tool_cls.bl_idname}: {exc}")


def unregister():
    cleanup_internal_events()
    _restore_native_expand_tools()
    for tool_cls, _, _ in reversed(TOOLS):
        try:
            bpy.utils.unregister_tool(tool_cls)
        except Exception:
            pass
    for name in ("expand_helper_recursion_topology",
                 "expand_helper_geodesic_step"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass