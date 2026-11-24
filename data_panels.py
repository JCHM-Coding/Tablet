# Object Data popups for: metaball, point cloud, lattice, text, volume,
# empty (image / force field / collection instance), light, light probe,
# camera, speaker. Plus the edit-mode header menu and the collapsible
# Options (orientation, pivot, snapping, falloff) for those edit modes.
import traceback

import bpy
from .sculpt_popups import _p, _section
from .sculpt_panels import _act, _safe
from .pose_panels import _props_where
from .texture_panels import _dialog_button, image_buttons
from .curve_panels import SHAPE, TEXSPACE, GEOM
from .object_panels import _popover

_warned = set()
_NOISE = {"name", "name_full", "use_fake_user", "use_extra_user",
          "is_evaluated", "is_embedded_data", "is_library_indirect", "tag",
          "is_runtime_data", "session_uid", "preview", "asset_data",
          "library", "library_weak_reference", "override_library",
          "original", "users", "type", "id_type"}


def _names(layout, owner, names):
    for n in names:
        _p(layout, owner, n)


def _sec(l, key, title, closed=True):
    return _section(l, "nomad_d_" + key, title, closed=closed)


# ----------------------------------------------------------------------
# Edit-mode objects
# ----------------------------------------------------------------------

def _metaball(l, context, obj):
    mb = obj.data
    body = _sec(l, "meta", "Metaball", False)
    if body is not None:
        _names(body, mb, ("resolution", "render_resolution", "threshold",
                          "update_method"))
    body = _sec(l, "elem", "Active Element", False)
    if body is not None:
        elem = getattr(mb.elements, "active", None)
        if elem is None:
            body.label(text="No active element", icon='INFO')
        else:
            _names(body, elem, ("type", "co", "radius", "stiffness",
                                "use_negative", "use_scale_stiffness",
                                "hide", "size_x", "size_y", "size_z"))
    body = _sec(l, "mtex", "Texture Space")
    if body is not None:
        _names(body, mb, TEXSPACE)


def _pointcloud(l, context, obj):
    pc = obj.data
    body = _sec(l, "pcattr", "Attributes", False)
    if body is None:
        return
    row = body.row()
    for lst in ("MESH_UL_attributes", "UI_UL_list"):
        try:
            row.template_list(lst, "nomad_pc_attrs", pc, "attributes",
                              pc.attributes, "active_index", rows=4)
            break
        except (TypeError, RuntimeError):
            continue
    col = row.column(align=True)
    _dialog_button(col, "", "geometry.attribute_add", icon='ADD')
    _act(col, "geometry.attribute_remove", "", icon='REMOVE')


def _lattice(l, context, obj):
    lat = obj.data
    body = _sec(l, "lat", "Lattice", False)
    if body is None:
        return
    _names(body, lat, ("points_u", "points_v", "points_w",
                       "interpolation_type_u", "interpolation_type_v",
                       "interpolation_type_w", "use_outside"))
    if hasattr(lat, "vertex_group"):
        body.prop_search(lat, "vertex_group", obj, "vertex_groups")


def _text(l, context, obj):
    txt = obj.data
    body = _sec(l, "tshape", "Shape")
    if body is not None:
        _names(body, txt, SHAPE)
    body = _sec(l, "ttex", "Texture Space")
    if body is not None:
        _names(body, txt, TEXSPACE)
    body = _sec(l, "tgeo", "Geometry")
    if body is not None:
        for title, names in GEOM:
            body.label(text=title)
            _names(body, txt, names)

    body = _sec(l, "tfont", "Font")
    if body is not None:
        _p(body, txt, "font", text="Regular")
        _p(body, txt, "font_bold", text="Bold")
        _p(body, txt, "font_italic", text="Italic")
        _p(body, txt, "font_bold_italic", text="Bold & Italic")
        _dialog_button(body, "Open Font", "font.open", icon='FILE_FOLDER')
        _names(body, txt, ("size", "shear", "small_caps_scale",
                           "underline_position", "underline_height"))
        fmt = getattr(txt, "edit_format", None)
        if fmt is not None and context.mode == 'EDIT_TEXT':
            row = body.row(align=True)
            for name, text in (("use_bold", "Bold"),
                               ("use_italic", "Italic"),
                               ("use_underline", "Underline"),
                               ("use_small_caps", "Small Caps")):
                _p(row, fmt, name, text=text, toggle=True)

    body = _sec(l, "tpara", "Paragraph")
    if body is not None:
        _names(body, txt, ("align_x", "align_y", "overflow",
                           "space_character", "space_word", "space_line",
                           "offset_x", "offset_y"))

    body = _sec(l, "tboxes", "Text Boxes")
    if body is not None:
        row = body.row()
        row.scale_y = 1.3
        _act(row, "font.textbox_add", "Add Text Box", icon='ADD')
        for i, tb in enumerate(txt.text_boxes):
            box = body.box()
            row = box.row()
            row.label(text=f"Text Box {i + 1}")
            _act(row, "font.textbox_remove", "", icon='X', index=i)
            _names(box, tb, ("x", "y", "width", "height"))


# ----------------------------------------------------------------------
# Objects without an edit mode
# ----------------------------------------------------------------------

def _volume(l, context, obj):
    vol = obj.data
    body = _sec(l, "vol", "Volume", False)
    if body is not None:
        _props_where(body, vol, lambda i: i not in _NOISE)
    for name, title in (("render", "Render"), ("display", "Display")):
        sub = getattr(vol, name, None)
        if sub is not None:
            b = _sec(l, "vol_" + name, title)
            if b is not None:
                _props_where(b, sub, lambda i: i not in _NOISE)


def _empty(l, context, obj):
    body = _sec(l, "empty", "Empty", False)
    if body is not None:
        _names(body, obj, ("empty_display_type", "empty_display_size"))
    if getattr(obj, "empty_display_type", "") == 'IMAGE':
        body = _sec(l, "eimg", "Image", False)
        if body is not None:
            body.template_ID(obj, "data")
            image_buttons(body, f"EMPTY:{obj.name}")
            _names(body, obj, ("use_empty_image_alpha", "color",
                               "empty_image_depth", "empty_image_side",
                               "empty_image_offset",
                               "show_empty_image_perspective",
                               "show_empty_image_orthographic",
                               "show_empty_image_only_axis_aligned"))
    if (getattr(obj, "instance_collection", None) is not None
            or getattr(obj, "instance_type", "") == 'COLLECTION'):
        body = _sec(l, "einst", "Instancing", False)
        if body is not None:
            _names(body, obj, ("instance_type", "instance_collection"))


_LIGHT_COMMON = ("color", "energy", "exposure", "use_temperature",
                 "temperature", "specular_factor", "diffuse_factor",
                 "volume_factor", "use_soft_falloff")
_LIGHT_TYPE = {
    'POINT': ("shadow_soft_size",),
    'SUN': ("angle",),
    'SPOT': ("shadow_soft_size", "spot_size", "spot_blend", "show_cone"),
    'AREA': ("shape", "size", "size_y", "spread"),
}


def _light(l, context, obj):
    light = obj.data
    body = _sec(l, "light", "Light", False)
    if body is not None:
        _p(body, light, "type", expand=True)
        _names(body, light, _LIGHT_COMMON)
        _names(body, light, _LIGHT_TYPE.get(light.type, ()))
    body = _sec(l, "lshadow", "Shadow")
    if body is not None:
        _props_where(body, light, lambda i: (
            i.startswith(("use_shadow", "shadow_", "use_contact",
                          "contact_shadow")) and i != "shadow_soft_size"))
    body = _sec(l, "ldist", "Custom Distance")
    if body is not None:
        _names(body, light, ("use_custom_distance", "cutoff_distance"))


def _probe(l, context, obj):
    pr = obj.data
    cap = ("grid_", "visibility_", "invert_visibility", "resolution",
           "capture_")
    par = ("parallax", "use_custom_parallax")
    body = _sec(l, "probe", "Probe", False)
    if body is not None:
        _props_where(body, pr, lambda i: (
            i not in _NOISE and not i.startswith(cap + par)))
    body = _sec(l, "pcap", "Capture")
    if body is not None:
        _props_where(body, pr, lambda i: i.startswith(cap))
    body = _sec(l, "ppar", "Custom Parallax")
    if body is not None:
        _props_where(body, pr, lambda i: i.startswith(par))


def _camera(l, context, obj):
    cam = obj.data
    body = _sec(l, "clens", "Lens", False)
    if body is not None:
        _p(body, cam, "type", text="Type")
        if cam.type == 'ORTHO':
            _p(body, cam, "ortho_scale")
        else:
            _p(body, cam, "lens_unit")
            _p(body, cam, "angle" if getattr(cam, "lens_unit", "")
               == 'FOV' else "lens")
            if cam.type == 'PANO':
                _p(body, cam, "panorama_type")
        _names(body, cam, ("shift_x", "shift_y", "clip_start",
                           "clip_end"))

    body = _sec(l, "cdof", "Depth of Field")
    dof = getattr(cam, "dof", None)
    if body is not None and dof is not None:
        _p(body, dof, "use_dof", text="Depth of Field", toggle=True)
        sub = body.column()
        sub.active = bool(getattr(dof, "use_dof", False))
        _names(sub, dof, ("focus_object", "focus_distance",
                          "aperture_fstop", "aperture_blades",
                          "aperture_rotation", "aperture_ratio"))

    body = _sec(l, "ccam", "Camera")
    if body is not None:
        _names(body, cam, ("sensor_fit", "sensor_width", "sensor_height",
                           "display_size", "show_limits", "show_mist",
                           "show_sensor", "show_name", "show_passepartout",
                           "passepartout_alpha"))

    body = _sec(l, "csafe", "Safe Areas")
    if body is not None:
        _names(body, cam, ("show_safe_areas", "show_safe_center"))
        sa = getattr(context.scene, "safe_areas", None)
        if sa is not None:
            _names(body, sa, ("title", "action", "title_center",
                              "action_center"))

    body = _sec(l, "cbg", "Background Images")
    if body is None:
        return
    _p(body, cam, "show_background_images", text="Show Background Images",
       toggle=True)
    col = body.column()
    try:
        col.context_pointer_set("camera", cam)
    except (AttributeError, TypeError):
        pass
    _act(col, "view3d.camera_background_image_add", "Add Image", icon='ADD')
    for i, bg in enumerate(cam.background_images):
        box = body.box()
        row = box.row()
        _p(row, bg, "show_background_image", text="", icon='HIDE_OFF')
        row.label(text=f"Image {i + 1}")
        rc = row.column()
        try:
            rc.context_pointer_set("camera", cam)
        except (AttributeError, TypeError):
            pass
        _act(rc, "view3d.camera_background_image_remove", "", icon='X',
             index=i)
        _p(box, bg, "source")
        if getattr(bg, "source", 'IMAGE') == 'IMAGE':
            box.template_ID(bg, "image")
            image_buttons(box, f"CAMBG:{cam.name}:{i}")
        else:
            box.template_ID(bg, "clip")
        _names(box, bg, ("alpha", "display_depth", "frame_method",
                         "offset", "rotation", "scale", "use_flip_x",
                         "use_flip_y"))


def _speaker(l, context, obj):
    spk = obj.data
    body = _sec(l, "ssound", "Sound", False)
    if body is not None:
        body.template_ID(spk, "sound")
        _dialog_button(body, "Open Sound", "sound.open",
                       icon='FILE_FOLDER')
        _names(body, spk, ("volume", "pitch", "muted"))
    body = _sec(l, "sdist", "Distance")
    if body is not None:
        _names(body, spk, ("volume_min", "volume_max", "attenuation",
                           "distance_max", "distance_reference"))
    body = _sec(l, "scone", "Cone")
    if body is not None:
        _names(body, spk, ("cone_angle_outer", "cone_angle_inner",
                           "cone_volume_outer"))


_DRAW = {'META': _metaball, 'POINTCLOUD': _pointcloud,
         'LATTICE': _lattice, 'FONT': _text, 'VOLUME': _volume,
         'EMPTY': _empty, 'LIGHT': _light, 'LIGHT_PROBE': _probe,
         'CAMERA': _camera, 'SPEAKER': _speaker}


class NOMAD_PT_object_data(bpy.types.Panel):
    bl_label = "Data"
    bl_idname = "NOMAD_PT_object_data"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        obj = context.active_object
        if obj is None:
            l.label(text="No active object", icon='INFO')
            return
        fn = _DRAW.get(obj.type)
        if fn is None:
            l.label(text=f"No data options for {obj.type}", icon='INFO')
            return
        try:
            fn(l, context, obj)
        except Exception as exc:
            l.label(text=f"{type(exc).__name__}", icon='ERROR')
            if obj.type not in _warned:
                _warned.add(obj.type)
                print(f"NomadUI data panel ({obj.type}):")
                traceback.print_exc()


# ----------------------------------------------------------------------
# Edit-mode header menu (Metaball / Point Cloud / Lattice / Text)
# ----------------------------------------------------------------------

_EDIT_KEYS = {'EDIT_METABALL': ("Metaball", ("metaball",)),
              'EDIT_POINTCLOUD': ("Point Cloud",
                                  ("pointcloud", "point_cloud")),
              'EDIT_LATTICE': ("Lattice", ("lattice",)),
              'EDIT_TEXT': ("Text", ("font", "text"))}


def _find_edit_menu(keys):
    found, every = [], []
    for cls in bpy.types.Menu.__subclasses__():
        ident = getattr(cls, "bl_idname", cls.__name__)
        low = ident.lower()
        if low.startswith("view3d_mt_edit"):
            every.append(ident)
            if any(k in low for k in keys) and "context" not in low:
                found.append(ident)
    if not found:
        if keys not in _warned:
            _warned.add(keys)
            print(f"NomadUI: no edit menu for {keys}. Edit menus: {every}")
        return None
    return min(found, key=len)


class NOMAD_PT_edit_menu(bpy.types.Panel):
    bl_label = "Menu"
    bl_idname = "NOMAD_PT_edit_menu"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        title, keys = _EDIT_KEYS.get(context.mode, (None, ()))
        if title is None:
            l.label(text="No header menu for this mode", icon='INFO')
            return
        ident = _find_edit_menu(keys)
        l.label(text=title)
        if ident:
            l.menu_contents(ident)
        else:
            l.label(text=f"{title} menu not found", icon='INFO')


# ----------------------------------------------------------------------
# Options with collapsible sections
# ----------------------------------------------------------------------

class NOMAD_PT_options_c(bpy.types.Panel):
    bl_label = "Options"
    bl_idname = "NOMAD_PT_options_c"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        sc = context.scene
        ts = context.tool_settings

        body = _sec(l, "o_orient", "Transform Orientations")
        if body is not None:
            row = body.row(align=True)
            try:
                row.prop(sc.transform_orientation_slots[0], "type",
                         text="")
            except (IndexError, AttributeError, TypeError):
                row.label(text="n/a")
            _popover(row, "VIEW3D_PT_transform_orientations", "",
                     'PREFERENCES')

        body = _sec(l, "o_pivot", "Transform Pivot Point")
        if body is not None:
            _p(body, ts, "transform_pivot_point", text="")

        body = _sec(l, "o_snap", "Snapping")
        if body is not None:
            row = body.row(align=True)
            row.scale_y = 1.3
            row.prop(ts, "use_snap", text="Snap", toggle=True,
                     icon='SNAP_ON' if ts.use_snap else 'SNAP_OFF')
            _popover(row, "VIEW3D_PT_snapping", "", 'DOWNARROW_HLT')

        body = _sec(l, "o_tools", "Cursor, Move & Rotate")
        if body is not None:
            from . import edit_ops
            edit_ops.tool_buttons(body)

        body = _sec(l, "o_fall", "Falloff")
        if body is not None:
            attr = ("use_proportional_edit_objects"
                    if context.mode in {'OBJECT', 'POSE'}
                    else "use_proportional_edit")
            if hasattr(ts, attr):
                body.prop(ts, attr, text="Proportional Editing",
                          toggle=True,
                          icon='PROP_ON' if getattr(ts, attr)
                          else 'PROP_OFF')
            _p(body, ts, "proportional_edit_falloff", text="Falloff")
            _p(body, ts, "proportional_size", text="Size")


CLASSES = (NOMAD_PT_object_data, NOMAD_PT_edit_menu, NOMAD_PT_options_c)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass