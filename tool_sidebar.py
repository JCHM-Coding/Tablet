# Tool bars. Main bar (left): Object / Edit Mesh / Pose tools (Sculpt's
# lives in panels.py). Secondary bar (right, or next to the left one):
# quick actions.
import bpy
from . import drawing, panels
from .top_bar import BAR_H

ACTIVE_MODES = {'SCULPT', 'OBJECT', 'EDIT_MESH', 'POSE',
                'PAINT_GREASE_PENCIL', 'EDIT_GREASE_PENCIL',
                'VERTEX_GREASE_PENCIL', 'SCULPT_GREASE_PENCIL',
                'WEIGHT_GREASE_PENCIL', 'EDIT_CURVE', 'EDIT_SURFACE',
                'EDIT_ARMATURE', 'EDIT_METABALL', 'EDIT_POINTCLOUD',
                'EDIT_LATTICE', 'EDIT_TEXT',
                'PAINT_TEXTURE', 'PAINT_VERTEX', 'PAINT_WEIGHT'}

COL_ACTIVE = panels.FILL_COL


def _is(*ids):
    return lambda t: t.idname in ids
def _lab(t):
    return str(getattr(t, "label", "")).casefold()


# Which tools belong to each group (matched on the real tool list).
GROUPS = {
    # sculpt
    "brush": _is("builtin.brush"),
    "wp_gradient": _is("builtin.gradient"),
    "hide": lambda t: t.idname.endswith("_hide"),
    "trim": lambda t: t.idname.endswith(("_trim", "_project")),
    "filter": lambda t: t.idname.endswith("_filter"),
    "xform": _is("builtin.move", "builtin.rotate", "builtin.scale",
                 "builtin.transform"),
    # object / edit / pose
    "select": _is("builtin.select", "builtin.select_box",
                  "builtin.select_circle", "builtin.select_lasso"),
    "cursor": _is("builtin.cursor"),
    "xform_obj": _is("builtin.move", "builtin.rotate", "builtin.scale",
                     "builtin.scale_cage", "builtin.transform"),
    "measure": _is("builtin.measure"),
    "breakdown": lambda t: any(k in t.idname for k in
                               ("breakdown", "_push", "_relax")),
    # shared
    "annot": lambda t: t.idname.startswith("builtin.annotate"),
    "add": lambda t: t.idname.startswith("builtin.primitive_"),
    # Mask / Face Sets dropdowns (see sculpt_panels.py)
    "mask_gest": lambda t: (t.idname.startswith("builtin.")
                            and t.idname.endswith("_mask")),
    "mask_color": _is("builtin.mask_by_color"),
    "fs_gest": lambda t: (t.idname.startswith("builtin.")
                          and t.idname.endswith("_face_set")),
    "fs_edit": _is("builtin.face_set_edit"),
    "expand_mask": _is("sculpt.nomad_expand_mask"),
    "expand_fs": _is("sculpt.nomad_expand_facesets"),
    # Draw mode (Grease Pencil)
    "gp_select": _is("builtin.select_lasso"),
    "gp_draw": lambda t: (_lab(t) == "draw" or t.idname in (
        "builtin.brush", "builtin_brush.draw", "builtin_brush.Draw")),
    "gp_erase": lambda t: (_lab(t) == "erase"
                           or t.idname.casefold().endswith(".erase")),
    "gp_fill": lambda t: (_lab(t) == "fill"
                          or t.idname.casefold().endswith(".fill")),
    "gp_trim": lambda t: (t.idname in ("builtin.cutter", "builtin.trim")
                          or _lab(t) in ("cutter", "trim")),
    "gp_eyedrop": lambda t: "eyedropper" in t.idname,
    "gp_interp": lambda t: "interpolate" in t.idname,
    "gp_shapes": lambda t: (
        t.idname in ("builtin.box", "builtin.circle", "builtin.line",
                     "builtin.polyline", "builtin.arc", "builtin.curve")
        or _lab(t) in ("box", "circle", "line", "polyline", "arc",
                       "arch", "curve")),
    # Grease Pencil edit mode
    "gp_pen": lambda t: _lab(t) == "pen" or t.idname.endswith(".pen"),
    "gp_radius": lambda t: "radius" in t.idname or _lab(t) == "radius",
    "gp_bend": lambda t: "bend" in t.idname or _lab(t) == "bend",
    "gp_shear": lambda t: ("shear" in t.idname or "to_sphere" in t.idname
                           or _lab(t) in ("shear", "to sphere")),
    "gp_gradient": lambda t: "gradient" in t.idname,
    # Curve / Surface edit mode
    "cv_draw": lambda t: t.idname == "builtin.draw" or _lab(t) == "draw",
    "cv_pen": lambda t: (t.idname == "builtin.pen"
                         or _lab(t) in ("curve pen", "pen")),
    "cv_extrude": lambda t: "extrude" in t.idname,
    "cv_radius": lambda t: "radius" in t.idname,
    "cv_tilt": lambda t: "tilt" in t.idname,
    "cv_random": lambda t: "randomize" in t.idname,
    "cv_shear": lambda t: "shear" in t.idname,
    # Armature edit mode
    "ar_roll": lambda t: "roll" in t.idname or _lab(t) == "roll",
    "ar_bone": lambda t: (any(k in t.idname for k in
                              ("bone_size", "bone_envelope"))
                          or _lab(t) in ("bone size", "b-bone size",
                                         "bone envelope")),
}

# Known ids, used when Blender doesn't list a tool.
# (idname, label, icon handle: optional, no icon if it doesn't exist)
FALLBACK = {
    "brush": [("builtin.brush", "Brush", None)],
    "hide": [
        ("builtin.box_hide", "Box Hide", "ops.sculpt.border_hide"),
        ("builtin.lasso_hide", "Lasso Hide", "ops.sculpt.lasso_hide"),
        ("builtin.line_hide", "Line Hide", "ops.sculpt.line_hide"),
        ("builtin.polyline_hide", "Polyline Hide",
         "ops.sculpt.polyline_hide"),
    ],
    "wp_gradient": [("builtin.gradient", "Gradient", None)],
    "trim": [
        ("builtin.box_trim", "Box Trim", "ops.sculpt.box_trim"),
        ("builtin.lasso_trim", "Lasso Trim", "ops.sculpt.lasso_trim"),
        ("builtin.line_trim", "Line Trim", "ops.sculpt.line_trim"),
        ("builtin.polyline_trim", "Polyline Trim",
         "ops.sculpt.polyline_trim"),
        ("builtin.line_project", "Line Project",
         "ops.sculpt.line_project"),
    ],
    "filter": [
        ("builtin.mesh_filter", "Mesh Filter", "ops.sculpt.mesh_filter"),
        ("builtin.cloth_filter", "Cloth Filter",
         "ops.sculpt.cloth_filter"),
        ("builtin.color_filter", "Color Filter",
         "ops.sculpt.color_filter"),
    ],
    "xform": [
        ("builtin.move", "Move", "ops.transform.translate"),
        ("builtin.rotate", "Rotate", "ops.transform.rotate"),
        ("builtin.scale", "Scale", "ops.transform.resize"),
        ("builtin.transform", "Transform", "ops.transform.transform"),
    ],
    "select": [
        ("builtin.select", "Tweak", "ops.generic.select"),
        ("builtin.select_box", "Select Box", "ops.generic.select_box"),
        ("builtin.select_circle", "Select Circle",
         "ops.generic.select_circle"),
        ("builtin.select_lasso", "Select Lasso",
         "ops.generic.select_lasso"),
    ],
    "cursor": [
        ("builtin.cursor", "Cursor", "ops.generic.cursor"),
    ],
    "xform_obj": [
        ("builtin.move", "Move", "ops.transform.translate"),
        ("builtin.rotate", "Rotate", "ops.transform.rotate"),
        ("builtin.scale", "Scale", "ops.transform.resize"),
        ("builtin.scale_cage", "Scale Cage", "ops.transform.resize_cage"),
        ("builtin.transform", "Transform", "ops.transform.transform"),
    ],
    "measure": [
        ("builtin.measure", "Measure", "ops.view3d.ruler"),
    ],
    "breakdown": [
        ("builtin.pose_breakdowner", "Breakdowner",
         "ops.pose.breakdowner"),
        ("builtin.pose_push", "Push", "ops.pose.push"),
        ("builtin.pose_relax", "Relax", "ops.pose.relax"),
    ],
    "annot": [
        ("builtin.annotate", "Annotate", "ops.gpencil.draw"),
        ("builtin.annotate_line", "Annotate Line", "ops.gpencil.draw.line"),
        ("builtin.annotate_polygon", "Annotate Polygon",
         "ops.gpencil.draw.poly"),
        ("builtin.annotate_eraser", "Annotate Eraser",
         "ops.gpencil.draw.eraser"),
    ],
    "add": [
        ("builtin.primitive_cube_add", "Add Cube",
         "ops.mesh.primitive_cube_add_gizmo"),
        ("builtin.primitive_cone_add", "Add Cone",
         "ops.mesh.primitive_cone_add_gizmo"),
        ("builtin.primitive_cylinder_add", "Add Cylinder",
         "ops.mesh.primitive_cylinder_add_gizmo"),
        ("builtin.primitive_uv_sphere_add", "Add UV Sphere",
         "ops.mesh.primitive_uv_sphere_add_gizmo"),
    ],
    "mask_gest": [
        ("builtin.box_mask", "Box Mask", "ops.sculpt.border_mask"),
        ("builtin.lasso_mask", "Lasso Mask", "ops.sculpt.lasso_mask"),
        ("builtin.line_mask", "Line Mask", "ops.sculpt.line_mask"),
        ("builtin.polyline_mask", "Polyline Mask",
         "ops.sculpt.polyline_mask"),
    ],
    "mask_color": [
        ("builtin.mask_by_color", "Mask by Color",
         "ops.sculpt.mask_by_color"),
    ],
    "fs_gest": [
        ("builtin.box_face_set", "Box Face Set",
         "ops.sculpt.border_face_set"),
        ("builtin.lasso_face_set", "Lasso Face Set",
         "ops.sculpt.lasso_face_set"),
        ("builtin.line_face_set", "Line Face Set",
         "ops.sculpt.line_face_set"),
        ("builtin.polyline_face_set", "Polyline Face Set",
         "ops.sculpt.polyline_face_set"),
    ],
    "fs_edit": [
        ("builtin.face_set_edit", "Edit Face Set",
         "ops.sculpt.face_set_edit"),
    ],
    "gp_select": [("builtin.select_lasso", "Select Lasso",
                   "ops.generic.select_lasso")],
    "gp_draw": [("builtin_brush.draw", "Draw", None),
                ("builtin.brush", "Draw", None)],
    "gp_erase": [("builtin_brush.erase", "Erase", None)],
    "gp_fill": [("builtin_brush.fill", "Fill", None)],
    "gp_trim": [("builtin.trim", "Trim", None),
                ("builtin.stroke_trim", "Trim", None),
                ("builtin.cutter", "Cutter", None)],
    "gp_eyedrop": [("builtin.eyedropper", "Eyedropper", None)],
    "gp_interp": [("builtin.interpolate", "Interpolate", None)],
    "gp_shapes": [("builtin.box", "Box", None),
                  ("builtin.circle", "Circle", None),
                  ("builtin.line", "Line", None),
                  ("builtin.polyline", "Polyline", None),
                  ("builtin.arc", "Arc", None),
                  ("builtin.curve", "Curve", None)],
    "expand_mask": [("sculpt.nomad_expand_mask", "Expand Mask",
                     "brush.sculpt.mask")],
    "expand_fs": [("sculpt.nomad_expand_facesets", "Expand Face Sets",
                   "brush.sculpt.draw_face_sets")],
    "gp_pen": [("builtin.pen", "Pen", None)],
    "gp_radius": [("builtin.radius", "Radius", None)],
    "gp_bend": [("builtin.bend", "Bend", None)],
    "gp_shear": [("builtin.shear", "Shear", None),
                 ("builtin.to_sphere", "To Sphere", None)],
    "gp_gradient": [("builtin.gradient", "Gradient", None)],
    "cv_draw": [("builtin.draw", "Draw", None)],
    "cv_pen": [("builtin.pen", "Curve Pen", None)],
    "cv_extrude": [("builtin.extrude", "Extrude", None),
                   ("builtin.extrude_cursor", "Extrude to Cursor", None)],
    "cv_radius": [("builtin.radius", "Radius", None)],
    "cv_tilt": [("builtin.tilt", "Tilt", None)],
    "cv_random": [("builtin.randomize", "Randomize", None)],
    "cv_shear": [("builtin.shear", "Shear", None)],
    "ar_roll": [("builtin.roll", "Roll", None)],
    "ar_bone": [("builtin.bone_size", "B-Bone Size", None),
                ("builtin.bone_envelope", "Bone Envelope", None)],                  
}


# Secondary bar: right edge (or next to the main bar if "on left").
# (key, glyph, tooltip, popup panel; None = direct action)
_SEC_STD = [
    ("qf", "Q", "Quick Favorites (Q)", None),
    ("cv_shear", "▱", "Shear", None),
]

BUTTONS_BY_MODE = {
    'SCULPT': [
        ("qf", "Q", "Quick Favorites (Q)", None),
        ("fav", "★", "Favorite brushes", "NOMAD_PT_favorites"),
        ("hide", "◌", "Hide gestures", "NOMAD_PT_tools_hide"),
        ("trim", "✂", "Trim / Line Project", "NOMAD_PT_tools_trim"),
        ("filter", "≋", "Filters", "NOMAD_PT_tools_filter"),
        ("xform", "✥", "Transform", "NOMAD_PT_tools_xform"),
        ("add", "✚", "Add primitives", "NOMAD_PT_tools_add"),
        ("stencil", "▧", "Stencil controls", "NOMAD_PT_tp_stencil"),
    ],
    'OBJECT': [
        ("qf", "Q", "Quick Favorites (Q)", None),
        ("qf_select", "☑", "Select / Deselect All", None),
        ("qf_delete", "⌫", "Delete", None),
        ("qf_dup", "❐", "Duplicate", "NOMAD_PT_obj_duplicate"),
        ("qf_join", "⊕", "Join / Parenting", "NOMAD_PT_obj_join"),
        ("qf_hide", "◉", "Show / Hide", "NOMAD_PT_obj_hide"),
    ],
    'EDIT_MESH': [
        ("qf", "Q", "Quick Favorites (Q)", None),
        ("me_select", "☑", "Select", "NOMAD_PT_mesh_select"),
        ("me_delete", "⌫", "Delete", "NOMAD_PT_mesh_delete"),
        ("me_uv", "▥", "UV", "NOMAD_PT_mesh_uv"),
        ("me_fill", "◼", "Fill", "NOMAD_PT_mesh_fill"),
        ("me_separate", "⧉", "Separate", "NOMAD_PT_mesh_separate"),
    ],
    'POSE': [
        ("qf", "Q", "Quick Favorites (Q)", None),
        ("po_hide", "◉", "Show / Hide", "NOMAD_PT_pose_hide"),
        ("annot", "✐", "Annotate", "NOMAD_PT_tools_annot"),
        ("measure", "↔", "Measure", None),
    ],
    'PAINT_GREASE_PENCIL': [
        ("qf", "Q", "Quick Favorites (Q)", None),
        ("fav", "★", "Favorite brushes", "NOMAD_PT_favorites"),
        ("gp_strokemode", "◍", "Stroke mode (stroke / fill / both)",
         "NOMAD_PT_gp_strokemode"),
        ("gp_placement", "⌖", "Stroke placement",
         "NOMAD_PT_gp_placement"),
        ("gp_mode", "◧", "Mode (material / color attribute / pin)",
         "NOMAD_PT_gp_mode"),
        ("gp_caps", "◖", "Caps (round / flat)", "NOMAD_PT_gp_caps"),
    ],
    'PAINT_TEXTURE': [
        ("qf", "Q", "Quick Favorites (Q)", None),
        ("fav", "★", "Favorite brushes", "NOMAD_PT_favorites"),
        ("bk_DRAW", "✎", "Brush", "brush:DRAW"),
        ("bk_SOFTEN", "◔", "Blur", "brush:SOFTEN"),
        ("bk_SMEAR", "≈", "Smear", "brush:SMEAR"),
        ("bk_CLONE", "⎘", "Clone", "brush:CLONE"),
        ("bk_FILL", "◼", "Fill", "brush:FILL"),
        ("bk_MASK", "⊘", "Mask", "brush:MASK"),
        ("tp_select", "☑", "Select (face selection masking)",
         "NOMAD_PT_tp_select"),
    ],
    'PAINT_VERTEX': [
        ("qf", "Q", "Quick Favorites (Q)", None),
        ("fav", "★", "Favorite brushes", "NOMAD_PT_favorites"),
        ("bk_DRAW", "✎", "Brush", "brush:DRAW"),
        ("bk_BLUR", "◔", "Blur", "brush:BLUR"),
        ("bk_AVERAGE", "◍", "Average", "brush:AVERAGE"),
        ("bk_SMEAR", "≈", "Smear", "brush:SMEAR"),
    ],
    'PAINT_WEIGHT': [
        ("qf", "Q", "Quick Favorites (Q)", None),
        ("fav", "★", "Favorite brushes", "NOMAD_PT_favorites"),
        ("bk_DRAW", "✎", "Brush", "brush:DRAW"),
        ("bk_BLUR", "◔", "Blur", "brush:BLUR"),
        ("bk_AVERAGE", "◍", "Average", "brush:AVERAGE"),
        ("bk_SMEAR", "≈", "Smear", "brush:SMEAR"),
        ("wp_gradient", "▤", "Gradient", None),
    ],
    'VERTEX_GREASE_PENCIL': [
        ("qf", "Q", "Quick Favorites (Q)", None),
        ("fav", "★", "Favorite brushes", "NOMAD_PT_favorites"),
    ],
    'SCULPT_GREASE_PENCIL': [
        ("qf", "Q", "Quick Favorites (Q)", None),
        ("fav", "★", "Favorite brushes", "NOMAD_PT_favorites"),
    ],
    'WEIGHT_GREASE_PENCIL': [
        ("qf", "Q", "Quick Favorites (Q)", None),
        ("fav", "★", "Favorite brushes", "NOMAD_PT_favorites"),
    ],
    'EDIT_GREASE_PENCIL': [
        ("qf", "Q", "Quick Favorites (Q)", None),
        ("gp_shear", "▱", "Shear / To Sphere", "NOMAD_PT_tools_gp_shear"),
        ("gp_gradient", "▤", "Gradient", None),
        ("gp_interp", "⇌", "Interpolate", None),
        ("annot", "✐", "Annotate", "NOMAD_PT_tools_annot"),
    ],
    'EDIT_CURVE': [
        ("qf", "Q", "Quick Favorites (Q)", None),
        ("cv_tilt", "↺", "Tilt", None),
        ("cv_random", "∿", "Randomize", None),
        ("cv_shear", "▱", "Shear", None),
    ],
    'EDIT_SURFACE': list(_SEC_STD),
    'EDIT_ARMATURE': list(_SEC_STD),
    'EDIT_METABALL': list(_SEC_STD),
    'EDIT_POINTCLOUD': list(_SEC_STD),
    'EDIT_LATTICE': list(_SEC_STD),
    'EDIT_TEXT': [("qf", "Q", "Quick Favorites (Q)", None)],
}

_EDIT_STD = [
    ("select", "▭", "Select", "NOMAD_PT_tools_select"),
    ("cursor", "⌖", "Cursor", None),
    ("xform_obj", "✥", "Transform", "NOMAD_PT_tools_xform_obj"),
    ("annot", "✐", "Annotate", "NOMAD_PT_tools_annot"),
    ("measure", "↔", "Measure", None),
]

# Main bar (left edge). In Sculpt, Draw, Texture / Vertex / Weight Paint
# and the Grease Pencil paint modes it belongs to panels.py (sliders...).
MAIN_BUTTONS_BY_MODE = {
    'OBJECT': [
        ("select", "▭", "Select", "NOMAD_PT_tools_select"),
        ("cursor", "⌖", "Cursor", None),
        ("xform_obj", "✥", "Transform", "NOMAD_PT_tools_xform_obj"),
        ("add", "✚", "Add primitives", "NOMAD_PT_tools_add"),
        ("breakdown", "◐", "Breakdowner", "NOMAD_PT_tools_breakdown"),
        ("annot", "✐", "Annotate", "NOMAD_PT_tools_annot"),
        ("measure", "↔", "Measure", None),
    ],
    'EDIT_MESH': [
        ("me_mode", "◈", "Selection mode (vertex / edge / face)",
         "NOMAD_PT_mesh_mode"),
        ("select", "▭", "Select", "NOMAD_PT_tools_select"),
        ("cursor", "⌖", "Cursor", None),
        ("xform_obj", "✥", "Transform", "NOMAD_PT_tools_xform_obj"),
        ("me_add", "✚", "Add (static / dynamic)", "NOMAD_PT_mesh_add"),
        ("me_tools", "✦", "Mesh tools", "NOMAD_PT_mesh_tools"),
        ("annot", "✐", "Annotate", "NOMAD_PT_tools_annot"),
        ("measure", "↔", "Measure", None),
    ],
    'POSE': [
        ("select", "▭", "Select", "NOMAD_PT_tools_select"),
        ("cursor", "⌖", "Cursor", None),
        ("xform_obj", "✥", "Transform", "NOMAD_PT_tools_xform_obj"),
        ("breakdown", "◐", "Breakdowner", "NOMAD_PT_tools_breakdown"),
    ],
    'EDIT_GREASE_PENCIL': [
        ("gp_selmode", "◈", "Select mode (point / stroke / segment)",
         "NOMAD_PT_gp_selmode"),
        ("select", "▭", "Select", "NOMAD_PT_tools_select"),
        ("cursor", "⌖", "Cursor", None),
        ("xform_obj", "✥", "Transform", "NOMAD_PT_tools_xform_obj"),
        ("gp_pen", "✎", "Pen", None),
        ("gp_radius", "◎", "Radius", None),
        ("gp_bend", "⌒", "Bend", None),
    ],
    'EDIT_CURVE': [
        ("select", "▭", "Select", "NOMAD_PT_tools_select"),
        ("cursor", "⌖", "Cursor", None),
        ("xform_obj", "✥", "Transform", "NOMAD_PT_tools_xform_obj"),
        ("cv_draw", "✎", "Draw", None),
        ("cv_pen", "✒", "Curve Pen", None),
        ("cv_extrude", "⇧", "Extrude", "NOMAD_PT_tools_cv_extrude"),
        ("cv_radius", "◎", "Radius", None),
        ("annot", "✐", "Annotate", "NOMAD_PT_tools_annot"),
        ("measure", "↔", "Measure", None),
    ],
    'EDIT_SURFACE': list(_EDIT_STD),
    'EDIT_ARMATURE': [
        ("select", "▭", "Select", "NOMAD_PT_tools_select"),
        ("xform_obj", "✥", "Transform", "NOMAD_PT_tools_xform_obj"),
        ("ar_roll", "↺", "Roll", None),
        ("ar_bone", "◖", "B-Bone size / Bone envelope",
         "NOMAD_PT_tools_ar_bone"),
        ("cv_extrude", "⇧", "Extrude", "NOMAD_PT_tools_cv_extrude"),
        ("annot", "✐", "Annotate", "NOMAD_PT_tools_annot"),
        ("measure", "↔", "Measure", None),
    ],
    'EDIT_METABALL': list(_EDIT_STD),
    'EDIT_POINTCLOUD': list(_EDIT_STD),
    'EDIT_LATTICE': list(_EDIT_STD),
    'EDIT_TEXT': [
        ("select", "▭", "Select", "NOMAD_PT_tools_select"),
        ("cursor", "⌖", "Cursor", None),
        ("annot", "✐", "Annotate", "NOMAD_PT_tools_annot"),
        ("measure", "↔", "Measure", None),
    ],
}


# Main bar (left edge): in Sculpt it belongs to panels.py (sliders, mask...)


_tools_cache = {}
_warned = set()
_diag_done = set()


class _Fake:
    """Minimal stand-in for a ToolDef that Blender didn't list."""
    def __init__(self, idname, label, icon):
        self.idname, self.label, self.icon = idname, label, icon


# ----------------------------------------------------------------------
# Tool discovery
# ----------------------------------------------------------------------

def _flatten(item, out):
    """A ToolDef is a namedtuple: look for its idname BEFORE iterating."""
    if item is None:
        return
    idname = getattr(item, "idname", None)
    if isinstance(idname, str) and idname:
        out[idname] = item
        return
    if isinstance(item, (tuple, list)):
        for sub in item:
            _flatten(sub, out)


def _toolbar_class():
    from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
    return ToolSelectPanelHelper._tool_class_from_space_type('VIEW_3D')


def _eval_items(cls, key, context, out):
    from bl_ui.space_toolsystem_common import ToolDef
    for item in cls._tools.get(key, ()):
        try:
            if type(item) is not ToolDef and callable(item):
                _flatten(list(item(context)), out)
            else:
                _flatten(item, out)
        except Exception as exc:
            tag = repr(item)[:60]
            if tag not in _warned:
                _warned.add(tag)
                print(f"NomadUI tools: skipped {tag}: {exc!r}")


def _tool_key(context):
    """The toolbar changes with the mode, the object type and the
    face / vertex selection masking: cache per combination."""
    obj = context.active_object
    me = getattr(obj, "data", None) if obj is not None else None
    return (context.mode, obj.type if obj is not None else "",
            bool(getattr(me, "use_paint_mask", False)),
            bool(getattr(me, "use_paint_mask_vertex", False)))


def _tooldefs(context):
    """idname -> ToolDef for the current mode. Blender's own iterator
    first, then entry by entry to fill in whatever it missed."""
    key = _tool_key(context)
    if key in _tools_cache:
        return _tools_cache[key]
    mode = context.mode
    out = {}
    try:
        cls = _toolbar_class()
        try:
            for item in cls.tools_from_context(context):
                _flatten(item, out)
        except Exception as exc:
            if "iter" not in _warned:
                _warned.add("iter")
                print(f"NomadUI tools: tools_from_context stopped: "
                      f"{exc!r}")
        for k in (None, mode):
            _eval_items(cls, k, context, out)
    except Exception as exc:
        if "discovery" not in _warned:
            _warned.add("discovery")
            print(f"NomadUI tools: discovery failed: {exc!r}")
    if out:
        _tools_cache[key] = out
        print(f"NomadUI tools {key} ({len(out)}): {sorted(out)}")
    return out

def _desc(item):
    idname = getattr(item, "idname", None)
    if isinstance(idname, str):
        return idname
    if isinstance(item, (tuple, list)):
        return [_desc(i) for i in item]
    return "callable " + str(getattr(item, "__name__", repr(item)[:30]))


def dump_all_tools(context):
    """Diagnostic: what the toolbar structure really looks like."""
    try:
        cls = _toolbar_class()
        mode = context.mode
        for key in (None, mode):
            items = list(cls._tools.get(key, ()))
            print(f"NomadUI toolbar [{key}]: {len(items)} entries")
            for item in items[:60]:
                print("    ", _desc(item))
        print("NomadUI workspace tools:",
              [(t.mode, t.idname) for t in context.workspace.tools])
    except Exception as exc:
        print(f"NomadUI dump_all_tools: {exc!r}")


def _active_idname(context):
    try:
        t = context.workspace.tools.from_space_view3d_mode(
            context.mode, create=False)
        return t.idname if t else ""
    except Exception:
        return ""


def _members(context, key):
    match = GROUPS.get(key)
    known = _tooldefs(context)
    found = [t for t in known.values() if match and match(t)]
    have = {t.idname for t in found}
    order = {}
    for i, (idname, label, icon) in enumerate(FALLBACK.get(key, ())):
        order[idname] = i
        if idname not in have and not known:      # discovery failed only
            found.append(_Fake(idname, label, icon))
    found.sort(key=lambda t: order.get(t.idname, 99))
    return found


def _icon_kw(t):
    icon = getattr(t, "icon", None)
    if icon:
        try:
            from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
            return {"icon_value":
                    ToolSelectPanelHelper._icon_value_from_icon_handle(icon)}
        except Exception:
            pass
    return {}


# ----------------------------------------------------------------------
# Tool activation (never trusts the discovered list)
# ----------------------------------------------------------------------

def _view3d_override():
    C = bpy.context
    for win in C.window_manager.windows:
        for a in win.screen.areas:
            if a.type != 'VIEW_3D':
                continue
            r = next((r for r in a.regions if r.type == 'WINDOW'), None)
            if r is not None:
                return win, a, r
    return None, None, None


def activate_any(ids, op=None):
    """Activate the first tool in `ids` that Blender accepts, verified
    through the active tool afterwards. If none works, run `op` once
    (a non-modal fallback) and dump every toolbar id to the console."""
    ids = tuple(ids)

    def _run():
        try:
            C = bpy.context
            win, area, region = _view3d_override()
            if area is None:
                return None
            with C.temp_override(window=win, area=area, region=region):
                for i in ids:
                    try:
                        bpy.ops.wm.tool_set_by_id(name=i,
                                                  space_type='VIEW_3D')
                    except Exception:
                        continue
                    if _active_idname(C) == i:
                        return None
                print(f"NomadUI: none of {ids} could be activated "
                      f"(active tool: {_active_idname(C)!r})")
                if ids not in _diag_done:
                    _diag_done.add(ids)
                    dump_all_tools(C)
                if op:
                    mod, name = op.split(".")
                    getattr(getattr(bpy.ops, mod), name)('INVOKE_DEFAULT')
        except Exception as exc:
            print(f"NomadUI activate_any {ids}: {exc!r}")
        return None
    try:
        bpy.app.timers.register(_run, first_interval=0.01)
    except RuntimeError:
        pass


def _defer_tool(idname):
    activate_any((idname,))


class NOMAD_OT_tool_set(bpy.types.Operator):
    """Activate a toolbar tool; failures are reported, never raised."""
    bl_idname = "nomad.tool_set"
    bl_label = "Set Tool"
    bl_options = {'INTERNAL'}

    name: bpy.props.StringProperty()

    def execute(self, context):
        try:
            bpy.ops.wm.tool_set_by_id(name=self.name, space_type='VIEW_3D')
        except Exception as exc:
            print(f"NomadUI tool_set '{self.name}': {exc!r}")
            return {'CANCELLED'}
        if _active_idname(context) != self.name:
            print(f"NomadUI tool '{self.name}' could not be activated "
                  f"(known: {sorted(_tooldefs(context))})")
            dump_all_tools(context)
            return {'CANCELLED'}
        return {'FINISHED'}


def tool_buttons(layout, context, tools, cols=1):
    """Tool buttons for a popup (1 column list, or a grid)."""
    active = _active_idname(context)
    parent = None
    if cols > 1:
        parent = layout.grid_flow(row_major=True, columns=cols,
                                  even_columns=True, align=True)
        parent.scale_y = 1.4
    for t in tools:
        if parent is not None:
            target = parent
        else:
            target = layout.row()
            target.scale_y = 1.4
        op = target.operator("nomad.tool_set", text=str(t.label),
                             depress=(t.idname == active), **_icon_kw(t))
        op.name = t.idname


# ----------------------------------------------------------------------
# GPU bars
# ----------------------------------------------------------------------

def _column(buttons, x1, h):
    y = h - BAR_H - panels.TOP_GAP
    out = []
    for b in buttons:
        out.append((x1, y - panels.BTN, x1 + panels.BTN, y, b))
        y -= panels.BTN + panels.PAD
    return out





def draw(context, w, h, mx, my):
    if context.mode not in ACTIVE_MODES:
        return
    active = _active_idname(context)
    for x1, y1, x2, y2, (key, glyph, tip, panel) in _layout(context, w, h):
        on = _is_on(context, key, active)
        if key == "me_tools" and on:
            from .mesh_panels import active_group
            ag = active_group(context)
            if ag:
                glyph = ag[0][2]
                tip = f"Mesh tools: {ag[0][3][ag[1]]['label']}"
        inside = x1 <= mx <= x2 and y1 <= my <= y2
        if inside or on:                 # at rest only the capsule shows
            drawing.rrect(x1 + 2, y1 + 2, x2 - 2, y2 - 2, drawing.BEVEL,
                          panels.COL_SIDE_ON)
        drawing.text(x1 + panels.BTN / 2, (y1 + y2) / 2 - 9, glyph,
                     size=18, color=panels.COL_GLYPH, align='CENTER')
        if inside:
            panels.hover_tip = tip





def _toggle_facemask():
    def _run():
        try:
            obj = bpy.context.active_object
            if obj is not None and obj.type == 'MESH':
                obj.data.use_paint_mask = not obj.data.use_paint_mask
            from .modal import tag_all_view3d_redraw
            tag_all_view3d_redraw()
        except (RuntimeError, AttributeError, ReferenceError) as exc:
            print(f"NomadUI face mask: {exc}")
        return None
    try:
        bpy.app.timers.register(_run, first_interval=0.01)
    except RuntimeError:
        pass


def _layout(context, w, h):
    """Buttons of the secondary bar and, outside Sculpt, of the main."""
    mode = context.mode
    main_x = panels.MARGIN + 4
    if getattr(context.scene, "nomad_sidebar_left", False):
        sec_x = main_x + panels.BTN + panels.PAD      # next to the left bar
    else:
        sec_x = w - panels.MARGIN - 4 - panels.BTN
    main = [b for b in MAIN_BUTTONS_BY_MODE.get(mode, ())
            if _visible(b[0], context)]
    sec = [b for b in BUTTONS_BY_MODE.get(mode, ())
           if _visible(b[0], context)]
    return _column(main, main_x, h) + _column(sec, sec_x, h)



def _visible(key, context):
    if key == "fav" and getattr(context.scene, "nomad_fav_bar", False):
        return False                    # the favorites strip replaces it
    if key == "tp_stencil":
        from .color_overlay import stencil_available
        return stencil_available(context)
    return True


def _is_on(context, key, active):
    if key == "me_mode":
        return False                    # never stays lit
    if key in ("pm_mode", "sym", "gp_selmode"):
        return False
    if key == "me_tools":
        from .mesh_panels import active_group
        return active_group(context) is not None
    if key == "tp_facemask":
        obj = context.active_object
        return bool(obj is not None and obj.type == 'MESH'
                    and obj.data.use_paint_mask)
    if key == "stencil":
        from .color_overlay import stencil_mode
        return stencil_mode is not None
    if key.startswith("bk_"):
        from .brush_shelf import is_kind
        return is_kind(context, key[3:])
    return any(t.idname == active for t in _members(context, key))


def press(context, w, h, mx, my):
    """True if the click hit a bar button."""
    if context.mode not in ACTIVE_MODES:
        return False
    for x1, y1, x2, y2, (key, glyph, tip, panel) in _layout(context, w, h):
        if not (x1 <= mx <= x2 and y1 <= my <= y2):
            continue
        print(f"NomadUI tools: '{tip}'")
        if key == "qf":
            from .sculpt_popups import open_menu_deferred
            open_menu_deferred("SCREEN_MT_user_menu")     # the Q menu
        elif key == "qf_select":
            from .sculpt_popups import defer_op
            defer_op("object", "select_all", action='TOGGLE')
        elif key == "tp_facemask":
            _toggle_facemask()
        elif panel is not None and panel.startswith("brush:"):
            from .brush_shelf import activate_kind
            activate_kind(panel[6:])
        elif panel is None:
            ids = [m.idname for m in _members(context, key)]
            if ids:
                activate_any(ids)
        elif key == "fav":
            from .brush_shelf import open_popup
            open_popup(panel)
        else:
            from .sculpt_popups import open_panel_deferred
            open_panel_deferred(panel)
        return True
    return False


# ----------------------------------------------------------------------
# Group popups
# ----------------------------------------------------------------------

def _draw_group(layout, context, key):
    layout.ui_units_x = 8
    members = _members(context, key)
    if not members:
        layout.label(text="No tools in this mode", icon='INFO')
        return
    tool_buttons(layout, context, members)


def _make_group_panel(key, label):
    def draw(self, context):
        _draw_group(self.layout, context, key)
    return type(f"NOMAD_PT_tools_{key}", (bpy.types.Panel,), {
        "bl_label": label,
        "bl_idname": f"NOMAD_PT_tools_{key}",
        "bl_space_type": 'VIEW_3D',
        "bl_region_type": 'WINDOW',
        "draw": draw,
    })


CLASSES = tuple(_make_group_panel(k, lbl) for k, lbl in (
    ("hide", "Hide"), ("trim", "Trim / Project"), ("filter", "Filters"),
    ("xform", "Transform"), ("annot", "Annotate"), ("add", "Add"),
    ("select", "Select"), ("xform_obj", "Transform"),
    ("breakdown", "Breakdowner"), ("gp_shapes", "Predefined Strokes"),
    ("gp_shear", "Shear / To Sphere"), ("cv_extrude", "Extrude"),
    ("ar_bone", "B-Bone Size / Envelope"))) + (NOMAD_OT_tool_set,)


def register():
    bpy.types.Scene.nomad_sidebar_left = bpy.props.BoolProperty(
        name="Tool Sidebar on Left", default=False)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    if hasattr(bpy.types.Scene, "nomad_sidebar_left"):
        del bpy.types.Scene.nomad_sidebar_left
    _tools_cache.clear()