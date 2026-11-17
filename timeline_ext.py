# Dope Sheet mode of the timeline (objects and bones only): Summary >
# Object > Bone > F-curves in a collapsible channel list and keyframe rows.
# Its controls are two rows added to the control bar (nothing is drawn over
# the editor): menus and settings on the first row, drag tools on the
# second. The Graph Editor is in graph_ext.py, NLA and Drivers have their
# own modules.
#
# SAFETY RULE: F-curve / keyframe wrappers are never kept between events.
# Cached wrappers are only used for READING while drawing; every edit
# re-resolves its curves with fresh_map() and checks that a keyframe is
# still the one it expects before writing to it.
import bisect
import math
import time

import bpy
from bpy.app.handlers import persistent

from . import drawing, panels, style
from .anim_options import _fcurves, _bone_ok

CH_W = 200
ROWH = 24
RULER_H = 26
TB_H = 30                # old toolbar height (NLA and Drivers still use it)
ROW_H = 30               # height of each added control row
EXP_SCRUB_H = 282        # strip height when expanded: 4x the timeline (308 px)
PAD_X = 30
INDENT = 14
MAX_OBJECTS = 8
KEY_R = 5.5
CACHE_TTL = 0.25
UPDATE_EVERY = 0.06      # min seconds between fc.update() while dragging

MODE_LABEL = {'TIMELINE': "Timeline", 'DOPESHEET': "Dope Sheet",
              'GRAPH': "Graph Editor", 'NLA': "NLA", 'DRIVERS': "Drivers"}
DS_MODE_LABEL = {'DOPESHEET': "Dope Sheet", 'ACTION': "Action Editor",
                 'SHAPEKEY': "Shape Key Editor", 'GPENCIL': "Grease Pencil",
                 'MASK': "Mask", 'CACHE': "Cache File"}
_SOON = {}

COL_ROW_A = (0.17, 0.17, 0.20, 1.0)
COL_ROW_B = (0.14, 0.14, 0.17, 1.0)
COL_GRP = (0.22, 0.26, 0.34, 1.0)
COL_OBJ = (0.27, 0.31, 0.40, 1.0)
COL_SUM = (0.31, 0.35, 0.45, 1.0)
COL_SEL = (0.22, 0.48, 0.85, 0.45)
COL_KEY = (0.9, 0.9, 0.92, 1.0)
COL_KEY_SEL = (1.0, 0.65, 0.15, 1.0)
COL_GHOST = (1.0, 0.65, 0.15, 0.5)
COL_HEAD = (0.11, 0.11, 0.13, 1.0)
COL_LINE = (0.35, 0.35, 0.40, 1.0)
COL_PLAY = (0.22, 0.48, 0.85, 1.0)
COL_START = (0.35, 0.65, 1.0, 0.9)
COL_END = (1.0, 0.55, 0.35, 0.9)
COL_BOX = (1.0, 1.0, 1.0, 0.9)
COL_BTN = (0.20, 0.20, 0.23, 1.0)
COL_MARK = (0.95, 0.85, 0.35, 1.0)
_AXIS_COL = ((0.93, 0.25, 0.32, 1.0), (0.55, 0.80, 0.20, 1.0),
             (0.25, 0.55, 0.95, 1.0), (0.65, 0.65, 0.70, 1.0))
_BASE = {"sum": COL_SUM, "obj": COL_OBJ, "bone": COL_GRP}
_FOLDABLE = ("sum", "obj", "bone")

_PROP = {"location": "Location", "rotation_euler": "Euler Rotation",
         "rotation_quaternion": "Quaternion Rotation", "scale": "Scale",
         "rotation_axis_angle": "Axis-Angle Rotation"}
_TRANSFORM = {"location", "rotation_euler", "rotation_quaternion",
              "rotation_axis_angle", "scale", "delta_location",
              "delta_rotation_euler", "delta_rotation_quaternion",
              "delta_scale"}
_BONE_PREFIX = 'pose.bones["'
SHARED_KEYS = ("search", "sfield", "filter")

# Dope Sheet menu buttons -> popup panel
_DS_PANELS = {"mode": "NOMAD_PT_ds_mode", "view": "NOMAD_PT_ds_view",
              "select": "NOMAD_PT_gr_select", "marker": "NOMAD_PT_gr_marker",
              "channel": "NOMAD_PT_gr_channel", "key": "NOMAD_PT_ds_key",
              "filters": "NOMAD_PT_gr_filters",
              "pivot": "NOMAD_PT_ds_pivot", "snap_o": "NOMAD_PT_ds_snap",
              "prop_o": "NOMAD_PT_ds_prop"}

_fold = set()
_scroll = 0.0
_diag_seen = set()
_last_up = [0.0]
_req = {"name": None}
_v = {"f0": 0.0, "ppf": 10.0, "init": False}          # time view
_tool = {"box": False, "scale": False, "dup": False}
_st = {"mode": None, "op": None, "row": None, "last": (0, 0), "moved": 0.0,
       "x0": 0.0, "y0": 0.0, "w": 0, "snap": [], "d": 0.0, "box": None,
       "piv": None, "noupd": False}
_cache = {"rows": None, "rows_t": 0.0, "items": None, "items_t": 0.0}
_kcache = {}
_fcache = {}


def _in(r, mx, my):
    return r[0] <= mx <= r[2] and r[1] <= my <= r[3]


def _sp(name, default):
    return getattr(bpy.context.scene, name, default)


def _flush():
    _cache["rows"] = None
    _cache["items"] = None
    _kcache.clear()
    _fcache.clear()


def drop_caches():
    """Forget every cached F-curve wrapper (here and in the Graph)."""
    _flush()
    try:
        from . import graph_ext
        graph_ext._flush()
    except Exception:
        pass


def _changed(self, context):
    """A filter or the search text changed."""
    drop_caches()


@persistent
def _on_depsgraph(scene, depsgraph=None):
    try:
        if depsgraph is not None and not depsgraph.id_type_updated('ACTION'):
            return                       # only edits of actions matter
    except Exception:
        pass
    drop_caches()


@persistent
def _on_undo_load(*_args):
    drop_caches()


def request(name):
    """View requests from the popups (applied while drawing)."""
    _req["name"] = name


def _mode(context):
    return getattr(context.scene, "nomad_tl_mode", 'TIMELINE')


def expanded(context):
    from . import top_bar
    sc = context.scene
    return bool(_mode(context) != 'TIMELINE'
                and getattr(sc, "nomad_scrub_visible", False)
                and top_bar._scrub_modes(context))


def graph_on(context):
    return bool(expanded(context) and _mode(context) == 'GRAPH')


def dope_on(context):
    return bool(expanded(context) and _mode(context) == 'DOPESHEET')


def has_rows(context):
    """Graph Editor and Dope Sheet add rows to the control bar."""
    return graph_on(context) or dope_on(context)


def ext_module(context):
    """NLA and Drivers have their own modules."""
    m = _mode(context)
    if m == 'NLA':
        from . import nla_ext
        return nla_ext
    if m == 'DRIVERS':
        from . import driver_ext
        return driver_ext
    return None


def _factor(mode):
    """Height of a mode, in times the compact timeline (add-on prefs)."""
    try:
        p = bpy.context.preferences.addons[__package__].preferences
        return float({'DOPESHEET': p.tl_h_dope, 'GRAPH': p.tl_h_graph,
                      'NLA': p.tl_h_nla,
                      'DRIVERS': p.tl_h_drivers}.get(mode, 4.0))
    except (KeyError, AttributeError):
        return 4.0


def extra(context):
    from . import top_bar
    if not expanded(context):
        return 0
    total = top_bar.SCRUB_H - 4 + top_bar.CTRL_H
    strip = _factor(_mode(context)) * total - top_bar.CTRL_H + 4
    area = context.area
    if area is not None and area.type == 'VIEW_3D':
        strip = min(strip, area.height / style.ui_scale() * 0.72)
    return max(0.0, strip - top_bar.SCRUB_H)


def rows_n(context):
    """Rows added to the control bar: one row of menus (Graph Editor and
    Dope Sheet)."""
    return 1 if has_rows(context) else 0


def rows_h(context):
    return rows_n(context) * ROW_H


# ----------------------------------------------------------------------
# Popups: filters and search text
# ----------------------------------------------------------------------

class NOMAD_PT_tl_filters(bpy.types.Panel):
    bl_label = "Filters"
    bl_idname = "NOMAD_PT_tl_filters"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 10
        sc = context.scene
        l.label(text="Show")
        col = l.column(align=True)
        col.scale_y = 1.3
        col.prop(sc, "nomad_tl_f_sel", toggle=True,
                 icon='RESTRICT_SELECT_OFF')
        col.prop(sc, "nomad_tl_f_bones", toggle=True, icon='BONE_DATA')
        l.label(text="Channel types")
        row = l.row(align=True)
        row.scale_y = 1.3
        row.prop(sc, "nomad_tl_f_loc", text="Location", toggle=True)
        row.prop(sc, "nomad_tl_f_rot", text="Rotation", toggle=True)
        row.prop(sc, "nomad_tl_f_scale", text="Scale", toggle=True)


class NOMAD_PT_tl_search(bpy.types.Panel):
    bl_label = "Search"
    bl_idname = "NOMAD_PT_tl_search"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 10
        row = l.row()
        row.activate_init = True
        row.prop(context.scene, "nomad_tl_search", text="",
                 icon='VIEWZOOM')


CLASSES = (NOMAD_PT_tl_filters, NOMAD_PT_tl_search)
_PROPS = ("nomad_tl_mode", "nomad_tl_search_on", "nomad_tl_search",
          "nomad_tl_f_sel", "nomad_tl_f_bones", "nomad_tl_f_loc",
          "nomad_tl_f_rot", "nomad_tl_f_scale")


def register():
    S = bpy.types.Scene
    S.nomad_tl_mode = bpy.props.EnumProperty(
        name="Timeline Mode", default='TIMELINE',
        items=[('TIMELINE', "Timeline", "Compact timeline"),
               ('DOPESHEET', "Dope Sheet", "Channels and keyframes"),
               ('GRAPH', "Graph Editor", "F-curves and handles"),
               ('NLA', "NLA", "Tracks and strips"),
               ('DRIVERS', "Drivers", "Drivers of objects and bones")])
    S.nomad_tl_search_on = bpy.props.BoolProperty(
        name="Search", default=False, update=_changed)
    S.nomad_tl_search = bpy.props.StringProperty(
        name="Search", default="", update=_changed,
        options={'TEXTEDIT_UPDATE'})
    S.nomad_tl_f_sel = bpy.props.BoolProperty(
        name="Only Selected Objects", default=True, update=_changed)
    S.nomad_tl_f_bones = bpy.props.BoolProperty(
        name="Only Selected Bones", default=True, update=_changed)
    S.nomad_tl_f_loc = bpy.props.BoolProperty(default=True, update=_changed)
    S.nomad_tl_f_rot = bpy.props.BoolProperty(default=True, update=_changed)
    S.nomad_tl_f_scale = bpy.props.BoolProperty(default=True,
                                                update=_changed)
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    h = bpy.app.handlers
    h.depsgraph_update_post.append(_on_depsgraph)
    h.undo_post.append(_on_undo_load)
    h.redo_post.append(_on_undo_load)
    h.load_post.append(_on_undo_load)


def unregister():
    h = bpy.app.handlers
    for lst, fn in ((h.depsgraph_update_post, _on_depsgraph),
                    (h.undo_post, _on_undo_load),
                    (h.redo_post, _on_undo_load),
                    (h.load_post, _on_undo_load)):
        if fn in lst:
            lst.remove(fn)
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    for name in _PROPS:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)


# ----------------------------------------------------------------------
# Data: objects and bones, transform channels only
# ----------------------------------------------------------------------

def _bone_of(fc):
    dp = fc.data_path
    if dp.startswith(_BONE_PREFIX):
        return dp[len(_BONE_PREFIX):].split('"]', 1)[0]
    return None


def _prop_of(fc):
    return fc.data_path.rsplit(".", 1)[-1].split("[")[0]


def _is_transform(fc):
    return _prop_of(fc) in _TRANSFORM


def _type_of(fc):
    base = _prop_of(fc)
    if base.endswith("location"):
        return 'LOC'
    if "rotation" in base:
        return 'ROT'
    return 'SCALE'


def _label(fc):
    dp = fc.data_path
    base = _prop_of(fc)
    idx = fc.array_index
    if base in _PROP:
        axes = ("WXYZ" if base in ("rotation_quaternion",
                                   "rotation_axis_angle") else "XYZ")
        ax = axes[idx] if 0 <= idx < len(axes) else str(idx)
        return f"{ax} {_PROP[base]}"
    if not base:
        return f"{dp} [{idx}]"
    return f"{base.replace('_', ' ').title()} [{idx}]"


def transform_curves(obj, filtered=True):
    """Object / bone transform curves. filtered=True also applies the
    type filters and the search text (Dope Sheet and Graph Editor)."""
    sc = bpy.context.scene
    bones_only = getattr(sc, "nomad_tl_f_bones", True)
    allowed = set()
    if getattr(sc, "nomad_tl_f_loc", True):
        allowed.add('LOC')
    if getattr(sc, "nomad_tl_f_rot", True):
        allowed.add('ROT')
    if getattr(sc, "nomad_tl_f_scale", True):
        allowed.add('SCALE')
    words = []
    if filtered and getattr(sc, "nomad_tl_search_on", False):
        words = sc.nomad_tl_search.strip().lower().split()
    out = []
    for fc in _fcurves(obj):
        if not _is_transform(fc):
            continue
        if bones_only and not _bone_ok(obj, fc):
            continue
        if filtered:
            if _type_of(fc) not in allowed:
                continue
            if words:
                name = f"{obj.name} {_bone_of(fc) or ''} {_label(fc)}"
                name = name.lower()
                if not all(t in name for t in words):
                    continue
        out.append(fc)
    return out


def _objects(context):
    sc = context.scene
    if getattr(sc, "nomad_tl_f_sel", True):
        objs = {o.name: o for o in context.selected_objects}
        ao = context.active_object
        if ao is not None:
            objs.setdefault(ao.name, ao)
        return list(objs.values())[:MAX_OBJECTS]
    return [o for o in sc.objects
            if o.animation_data and o.animation_data.action][:MAX_OBJECTS * 4]


def _fk(obj, fc):
    """Stable identity of a curve: (object, data_path, array_index)."""
    return (obj.name, fc.data_path, fc.array_index)


def _shown(sc, fc):
    """Show Hidden / Only Show Errors (shared with the Graph Editor)."""
    if fc.hide and not getattr(sc, "nomad_gr_hidden", False):
        return False
    if getattr(sc, "nomad_gr_errors", False) and fc.is_valid:
        return False
    return True


def fresh_items(context, filtered=True):
    """[(key, fcurve)] read straight from the data, never cached. USE THIS
    for every edit."""
    sc = context.scene
    out = []
    for obj in _objects(context):
        for fc in transform_curves(obj, filtered):
            if filtered and not _shown(sc, fc):
                continue
            out.append((_fk(obj, fc), fc))
    return out


def fresh_map(context, filtered=True):
    return dict(fresh_items(context, filtered))


def curve_items(context):
    """Cached [(key, fcurve)] (READ ONLY: for drawing)."""
    now = time.time()
    if (_cache["items"] is not None
            and now - _cache["items_t"] < CACHE_TTL):
        return _cache["items"]
    out = fresh_items(context)
    _cache["items"], _cache["items_t"] = out, now
    return out


def curve_list(context):
    return [fc for _k, fc in curve_items(context)]


def object_frames(obj):
    """Sorted integer frames with a key (compact timeline), cached.
    Not affected by the search and filters of the Dope Sheet."""
    if obj is None:
        return []
    now = time.time()
    ent = _fcache.get(obj.name)
    if ent is not None and now - ent[0] < 0.3:
        return ent[1]
    frames = set()
    for fc in transform_curves(obj, filtered=False):
        kps = fc.keyframe_points
        n = len(kps)
        if not n:
            continue
        co = [0.0] * (2 * n)
        kps.foreach_get("co", co)
        frames.update(int(round(x)) for x in co[0::2])
    out = sorted(frames)
    _fcache[obj.name] = (now, out)
    return out


def _axis_color(fc):
    base = _prop_of(fc)
    if base in _PROP:
        idx = fc.array_index
        if base in ("rotation_quaternion", "rotation_axis_angle"):
            idx -= 1
        if 0 <= idx < 3:
            return _AXIS_COL[idx]
    return _AXIS_COL[3]


def _diag(context):
    """Print once why an object shows no channels."""
    for obj in _objects(context):
        ad = getattr(obj, "animation_data", None)
        act = getattr(ad, "action", None)
        sig = (obj.name, act.name if act else None)
        if sig in _diag_seen:
            continue
        _diag_seen.add(sig)
        slot = getattr(ad, "action_slot", None)
        layers = len(act.layers) if act is not None and hasattr(
            act, "layers") else "-"
        print(f"NomadUI timeline: {obj.name}: "
              f"action={act.name if act else None} "
              f"slot={getattr(slot, 'name_display', slot)} "
              f"layers={layers} all_fcurves={len(_fcurves(obj))} "
              f"transform_fcurves={len(transform_curves(obj, False))}")


def _build_rows(context):
    sc = context.scene
    rows, per_obj = [], []
    for obj in _objects(context):
        fcs = [fc for fc in transform_curves(obj) if _shown(sc, fc)]
        if fcs:
            per_obj.append((obj, fcs))
    if not per_obj:
        _diag(context)
        return rows

    allf = [fc for _o, fcs in per_obj for fc in fcs]
    allk = [_fk(o, fc) for o, fcs in per_obj for fc in fcs]
    sfold = "s:all" in _fold
    rows.append({"kind": "sum", "key": "s:all", "label": "Summary",
                 "level": 0, "fold": sfold, "fcs": allf, "fks": allk})
    if sfold:
        return rows

    def fc_row(obj, fc, level):
        return {"kind": "fc", "level": level, "fc": fc, "fcs": [fc],
                "fks": [_fk(obj, fc)],
                "key": f"f:{obj.name}:{fc.data_path}:{fc.array_index}",
                "label": _label(fc)}

    for obj, fcs in per_obj:
        okey = "o:" + obj.name
        ofold = okey in _fold
        rows.append({"kind": "obj", "key": okey, "label": obj.name,
                     "level": 1, "fold": ofold, "fcs": fcs,
                     "fks": [_fk(obj, fc) for fc in fcs]})
        if ofold:
            continue
        own, bones = [], {}
        for fc in sorted(fcs, key=lambda f: (f.data_path, f.array_index)):
            b = _bone_of(fc)
            if b is None:
                own.append(fc)
            else:
                bones.setdefault(b, []).append(fc)
        for fc in own:
            rows.append(fc_row(obj, fc, 2))
        for bname, lst in bones.items():
            bkey = f"b:{obj.name}:{bname}"
            bfold = bkey in _fold
            rows.append({"kind": "bone", "key": bkey, "label": bname,
                         "level": 2, "fold": bfold, "fcs": lst,
                         "fks": [_fk(obj, fc) for fc in lst]})
            if bfold:
                continue
            for fc in lst:
                rows.append(fc_row(obj, fc, 3))
    return rows


def _rows(context):
    now = time.time()
    if _cache["rows"] is not None and now - _cache["rows_t"] < CACHE_TTL:
        return _cache["rows"]
    rows = _build_rows(context)
    _cache["rows"], _cache["rows_t"] = rows, now
    return rows


def _keys(row):
    """(frames, selected flags) of a row; summary rows merge their
    children. Read with foreach_get and cached."""
    now = time.time()
    ent = _kcache.get(row["key"])
    if ent is not None and now - ent[0] < CACHE_TTL:
        return ent[1]
    frames, sels = [], []
    for fc in row["fcs"]:
        kps = fc.keyframe_points
        n = len(kps)
        if not n:
            continue
        co = [0.0] * (2 * n)
        kps.foreach_get("co", co)
        sel = [False] * n
        kps.foreach_get("select_control_point", sel)
        frames += co[0::2]
        sels += sel
    out = (frames, sels)
    _kcache[row["key"]] = (now, out)
    return out


# ----------------------------------------------------------------------
# Geometry and time mapping
# ----------------------------------------------------------------------

def _geom(context, w):
    from . import top_bar
    ty1 = top_bar.SCRUB_Y
    ty2 = top_bar.SCRUB_Y + top_bar.SCRUB_H + extra(context) - 6
    rows = has_rows(context)
    nrows = rows_n(context)
    rows_top = ty2 + nrows * ROW_H
    tbh = 0 if rows else TB_H
    top = ty2 - tbh
    rt = top - RULER_H
    return {"panel": (0, ty1, w, rows_top),
            "tb": (0, ty2, w, rows_top) if rows else (0, top, w, ty2),
            "head": (0, rt, CH_W, top), "ruler": (CH_W, rt, w, top),
            "chan": (0, ty1, CH_W, rt), "keys": (CH_W, ty1, w, rt),
            "rows": [(0, rows_top - (i + 1) * ROW_H, w, rows_top - i * ROW_H)
                     for i in range(nrows)]}


def _range(sc):
    fs, fe = sc.frame_start, sc.frame_end
    return fs, (fe if fe > fs else fs + 1)


def _fit_view(sc, w):
    fs, fe = _range(sc)
    _v["ppf"] = max(0.05, (w - CH_W - 2 * PAD_X) / (fe - fs))
    _v["f0"] = fs - PAD_X / _v["ppf"]
    _v["init"] = True


def _ensure_view(sc, w):
    if not _v["init"]:
        _fit_view(sc, w)


def _fx(f):
    return CH_W + (f - _v["f0"]) * _v["ppf"]


def _xf(x):
    return _v["f0"] + (x - CH_W) / _v["ppf"]


def _zoom_time(mx, k):
    f = _xf(mx)
    _v["ppf"] = max(0.05, min(2000.0, _v["ppf"] * k))
    _v["f0"] = f - (mx - CH_W) / _v["ppf"]


def _tick_step(ppf):
    for s in (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000):
        if s * ppf >= 46:
            return s
    return 1000


def _max_scroll(n, G):
    extra_px = max(0.0, n * ROWH - (G["chan"][3] - G["chan"][1]))
    return math.ceil(extra_px / ROWH) * ROWH


def snap_frame(sc, f, mode):
    """Snap a frame to whole frames, seconds or the nearest marker."""
    if mode == 'SECOND':
        fps = max(1.0, sc.render.fps / sc.render.fps_base)
        return round(f / fps) * fps
    if mode == 'MARKER':
        ms = [m.frame for m in sc.timeline_markers]
        if ms:
            near = min(ms, key=lambda x: abs(x - f))
            if abs(near - f) <= 3:
                return float(near)
    return float(round(f))


def _falloff(name, t):
    t = max(0.0, min(1.0, t))
    if name == 'LINEAR':
        return t
    if name == 'SHARP':
        return t * t
    if name == 'SPHERE':
        return math.sqrt(max(0.0, 1 - (1 - t) ** 2))
    if name == 'ROOT':
        return math.sqrt(t)
    if name == 'CONSTANT':
        return 1.0
    return t * t * (3 - 2 * t)


def draw_ruler(sc, rl, fx, f_left, f_right, ppf, span=None, grid=None,
               show_range=True, seconds=False):
    """Ticks and numbers, with the start and end frames always shown
    (unless the frame-range overlay is off)."""
    fs, fe = sc.frame_start, sc.frame_end
    fps = max(1.0, sc.render.fps / sc.render.fps_base)

    def name(f):
        return f"{f / fps:.1f}s" if seconds else str(f)

    xs, xe = fx(fs), fx(fe)
    step = _tick_step(ppf)
    f = int(math.ceil(f_left / step) * step)
    while f <= f_right:
        x = fx(f)
        if not show_range or (abs(x - xs) > 34 and abs(x - xe) > 34):
            drawing.rect(x, rl[1], x + 1, rl[1] + 7, COL_LINE)
            drawing.text(x + 3, rl[1] + 9, name(f), size=10,
                         color=panels.COL_TIP)
            if grid is not None and span:
                drawing.rect(x, span[0], x + 1, span[1], grid)
        f += step
    if not show_range:
        return
    for f, col, right in ((fs, COL_START, False), (fe, COL_END, True)):
        x = fx(f)
        if not (rl[0] - 1 <= x <= rl[2] + 1):
            continue
        drawing.rect(x - 1, rl[1], x + 1, rl[3], col)
        if span:
            drawing.rect(x, span[0], x + 1, span[1], col)
        drawing.text(x - 5 if right else x + 5, rl[1] + 9, name(f), size=11,
                     color=col, align='RIGHT' if right else 'LEFT')


def _row_at(rows, G, my):
    top = G["chan"][3]
    off = int(round(_scroll / ROWH)) * ROWH
    for i, row in enumerate(rows):
        y2 = top - i * ROWH + off
        y1 = y2 - ROWH
        if y1 < G["chan"][1] - 0.5 or y2 > top + 0.5:
            continue
        if y1 <= my <= y2:
            return row
    return None


# ----------------------------------------------------------------------
# Control rows (Dope Sheet)
# ----------------------------------------------------------------------

def _w(label, kind):
    if kind == 'field':
        return 140
    return max(30, int(len(label) * 6.8) + (24 if kind == 'menu' else 16))


def _place(rect, specs, left):
    total = sum(10 if s is None else _w(s[1], s[2]) + 3 for s in specs)
    x = rect[0] + 8 if left else rect[2] - 8 - total + 3
    out = []
    for s in specs:
        if s is None:
            x += 10
            continue
        key, label, kind, tip = s
        wb = _w(label, kind)
        out.append((key, label, kind,
                    (x, rect[1] + 3, x + wb, rect[3] - 3), tip))
        x += wb + 3
    return out


def _dope_items(context, G):
    sc = context.scene
    ds = _sp("nomad_ds_mode", 'DOPESHEET')
    r0 = G["rows"][0]
    mode_item = ("mode", DS_MODE_LABEL.get(ds, "Dope Sheet"), 'menu',
                 "Dope Sheet mode")
    if ds != 'DOPESHEET':
        return _place(r0, [mode_item], True)
    left = [mode_item,
            ("view", "View", 'menu', "View options"),
            ("select", "Select", 'menu', "Select keyframes"),
            ("marker", "Marker", 'menu', "Markers"),
            ("channel", "Channel", 'menu', "Channels"),
            ("key", "Key", 'menu', "Keyframes")]
    right = [("search", "Search", 'toggle', "Search channels by name")]
    if sc.nomad_tl_search_on:
        right.append(("sfield", (sc.nomad_tl_search
                                 or "type to search...")[:18], 'field',
                      "Edit the search text"))
    right += [("filters", "Filters", 'menu',
               "Filters (objects, bones, channel types)"),
              ("pivot", "Pivot", 'menu', "Pivot point (Scale)"),
              ("snap", "Snap", 'toggle', "Snapping on / off"),
              ("snap_o", "", 'menu', "Snapping options"),
              ("prop", "Prop. Edit", 'toggle',
               "Proportional editing on / off"),
              ("prop_o", "", 'menu', "Proportional editing options")]
    return _place(r0, left, True) + _place(r0, right, False)


def _dope_is_on(context, key):
    sc = context.scene
    if key in ("box", "scale", "dup"):
        return _tool[key]
    if key == "snap":
        return bool(_sp("nomad_ds_snap", True))
    if key == "prop":
        return bool(_sp("nomad_ds_prop", False))
    if key == "search":
        return bool(sc.nomad_tl_search_on)
    return False


def _draw_buttons(context, items, mx, my, is_on):
    for key, label, kind, rect, tip in items:
        hot = _in(rect, mx, my)
        on = is_on(context, key)
        drawing.rrect(rect[0], rect[1], rect[2], rect[3], 6,
                      panels.COL_HOVER if hot
                      else COL_PLAY if on else COL_BTN)
        cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        if kind == 'menu':
            if label:
                drawing.text(rect[0] + 8, cy - 4, label, size=11,
                             color=panels.COL_GLYPH)
                drawing.glyph(rect[2] - 10, cy, "▾", 10, panels.COL_GLYPH)
            else:
                drawing.glyph(cx, cy, "▾", 11, panels.COL_GLYPH)
        else:
            drawing.text(cx, cy - 4, label, size=11,
                         color=panels.COL_GLYPH, align='CENTER')
        if hot:
            panels.hover_tip = tip


# ----------------------------------------------------------------------
# Toolbar of the NLA and Drivers editors (search / filter buttons)
# ----------------------------------------------------------------------

def shared_buttons(context, x, tb):
    sc = context.scene
    out = []
    x += 12
    out.append(("search", "Search", (x, tb[1] + 3, x + 48, tb[3] - 3),
                "Search channels by name"))
    x += 51
    if sc.nomad_tl_search_on:
        text = sc.nomad_tl_search or "type to search..."
        out.append(("sfield", text[:18],
                    (x, tb[1] + 3, x + 140, tb[3] - 3),
                    "Edit the search text"))
        x += 143
    out.append(("filter", "Filter", (x, tb[1] + 3, x + 48, tb[3] - 3),
                "Filters (objects, bones, channel types)"))
    return out


def shared_on(context, key):
    sc = context.scene
    if key == "search":
        return bool(sc.nomad_tl_search_on)
    if key == "filter":
        return not (sc.nomad_tl_f_sel and sc.nomad_tl_f_bones
                    and sc.nomad_tl_f_loc and sc.nomad_tl_f_rot
                    and sc.nomad_tl_f_scale)
    return False


def shared_action(context, key):
    from .sculpt_popups import open_panel_deferred
    sc = context.scene
    if key == "search":
        sc.nomad_tl_search_on = not sc.nomad_tl_search_on
        if sc.nomad_tl_search_on:
            open_panel_deferred("NOMAD_PT_tl_search")
        else:
            sc.nomad_tl_search = ""
    elif key == "sfield":
        open_panel_deferred("NOMAD_PT_tl_search")
    elif key == "filter":
        open_panel_deferred("NOMAD_PT_tl_filters")
    drop_caches()


def _push(msg):
    try:
        bpy.ops.ed.undo_push(message=msg)
    except RuntimeError:
        pass


def _tb_action(context, key, w):
    """Actions of the Dope Sheet rows."""
    from .sculpt_popups import open_panel_deferred
    sc = context.scene
    if key in _DS_PANELS:
        open_panel_deferred(_DS_PANELS[key])
        return
    if key in SHARED_KEYS:
        shared_action(context, key)
        return
    if key == "snap":
        sc.nomad_ds_snap = not sc.nomad_ds_snap
    elif key == "prop":
        sc.nomad_ds_prop = not sc.nomad_ds_prop
    elif key == "fit":
        _fit_view(sc, w)
    elif key in ("hz+", "hz-"):
        _zoom_time((CH_W + w) / 2, 1.25 if key == "hz+" else 0.8)
    elif key in ("box", "scale", "dup"):
        on = not _tool[key]
        _tool.update(box=False, scale=False, dup=False)
        _tool[key] = on
    _flush()


def _apply_request(context, w):
    """View requests (Frame All / Selected / Current) from the popups."""
    name = _req["name"]
    _req["name"] = None
    if name is None:
        return
    sc = context.scene
    if name == 'fit':
        _fit_view(sc, w)
    elif name == 'cur':
        _v["f0"] = sc.frame_current - (w - CH_W) / 2 / _v["ppf"]
    elif name == 'fit_sel':
        xs = [kp.co[0] for fc in curve_list(context)
              for kp in fc.keyframe_points if kp.select_control_point]
        if len(xs) >= 1:
            lo, hi = min(xs), max(xs)
            if hi - lo < 1.0:
                lo, hi = lo - 0.5, hi + 0.5
            _v["ppf"] = max(0.05, (w - CH_W - 2 * PAD_X) / (hi - lo))
            _v["f0"] = lo - PAD_X / _v["ppf"]


# ----------------------------------------------------------------------
# Draw
# ----------------------------------------------------------------------

def draw(context, w, mx, my):
    global _scroll
    sc = context.scene
    mode = _mode(context)
    ext = ext_module(context)
    if ext is not None:
        ext.draw(context, w, mx, my)
        return
    if mode in _SOON:
        p = _geom(context, w)["panel"]
        drawing.rect(p[0], p[1], p[2], p[3], COL_ROW_B)
        drawing.text((p[0] + p[2]) / 2, (p[1] + p[3]) / 2 - 7, _SOON[mode],
                     size=15, color=panels.COL_TIP, align='CENTER')
        return

    graph = graph_on(context)
    dope = dope_on(context)
    G = _geom(context, w)
    cx1, cy1, cx2, cy2 = G["chan"]
    kx1, ky1, kx2, ky2 = G["keys"]
    hd, rl = G["head"], G["ruler"]

    ds = _sp("nomad_ds_mode", 'DOPESHEET')
    if dope and ds != 'DOPESHEET':
        drawing.rect(0, cy1, w, rl[3], COL_ROW_B)
        drawing.text(w / 2, (cy1 + rl[3]) / 2 - 7,
                     f"{DS_MODE_LABEL.get(ds, ds)}: coming soon", size=15,
                     color=panels.COL_TIP, align='CENTER')
        _draw_buttons(context, _dope_items(context, G), mx, my,
                      _dope_is_on)
        return

    rows = _rows(context)
    _scroll = max(0.0, min(_scroll, _max_scroll(len(rows), G)))
    off = int(round(_scroll / ROWH)) * ROWH

    drawing.rect(hd[0], hd[1], hd[2], hd[3], COL_HEAD)
    drawing.text(hd[0] + 10, (hd[1] + hd[3]) / 2 - 5, "Channels", size=12,
                 color=panels.COL_TIP)
    overlays = bool(_sp("nomad_ds_overlays", True))
    if not graph:
        _ensure_view(sc, w)
        _apply_request(context, w)
        drawing.rect(rl[0], rl[1], rl[2], rl[3], COL_HEAD)
        draw_ruler(sc, rl, _fx, _xf(rl[0]), _xf(rl[2]), _v["ppf"],
                   span=(ky1, ky2),
                   show_range=overlays and bool(_sp("nomad_ds_ov_range",
                                                    True)),
                   seconds=overlays and bool(_sp("nomad_ds_ov_seconds",
                                                 False)))
        if not rows:
            drawing.text(CH_W + 16, (ky1 + ky2) / 2 - 5,
                         "No channels: select an object or bone with "
                         "animation (or check the filters)", size=13,
                         color=panels.COL_TIP)

    bg, sep, visible = {}, [], []
    for i, row in enumerate(rows):
        y2 = cy2 - i * ROWH + off
        y1 = y2 - ROWH
        if y1 < cy1 - 0.5 or y2 > cy2 + 0.5:
            continue
        base = _BASE.get(row["kind"], COL_ROW_A if i % 2 else COL_ROW_B)
        bg.setdefault(base, []).append((0, y1, CH_W if graph else w, y2 - 1))
        fc = row.get("fc")
        if fc is not None and fc.select:
            bg.setdefault(COL_SEL, []).append((0, y1, CH_W, y2 - 1))
        sep.append((CH_W, y1, CH_W + 1, y2 - 1))
        visible.append((row, y1, y2))
    for col, rs in bg.items():
        drawing.rects(rs, col)
    drawing.rects(sep, COL_LINE)

    norm_pts, sel_pts = [], []
    for row, y1, y2 in visible:
        kind = row["kind"]
        fc = row.get("fc")
        cy = (y1 + y2) / 2
        x = 8 + row["level"] * INDENT
        if kind in _FOLDABLE:
            drawing.glyph(x + 5, cy, "▸" if row["fold"] else "▾", 12,
                          panels.COL_GLYPH)
            x += 16
        else:
            drawing.rect(x, cy - 5, x + 4, cy + 5, _axis_color(fc))
            x += 10
        label = row["label"]
        maxc = max(4, int((CH_W - x - 30) / 6.6))
        if len(label) > maxc:
            label = label[:maxc - 1] + "…"
        drawing.text(x, cy - 4, label, size=12, color=panels.COL_GLYPH)
        if fc is not None:
            drawing.glyph(CH_W - 16, cy, "○" if fc.mute else "◉", 12,
                          panels.COL_TIP if fc.mute else panels.COL_GLYPH)
        if not graph:
            frames, sels = _keys(row)
            for f, s in zip(frames, sels):
                kxp = _fx(f)
                if kx1 - 6 <= kxp <= kx2 + 6:
                    (sel_pts if s else norm_pts).append((kxp, cy))

    if graph:
        from . import graph_ext
        graph_ext.draw(context, w, mx, my)
        return

    drawing.diamonds(norm_pts, KEY_R, COL_KEY)
    drawing.diamonds(sel_pts, KEY_R, COL_KEY_SEL)

    if overlays and _sp("nomad_ds_ov_markers", True):
        pts = []
        for mk in sc.timeline_markers:
            mxp = _fx(mk.frame)
            if kx1 <= mxp <= kx2:
                pts.append((mxp, ky1 + 9))
                drawing.text(mxp + 7, ky1 + 4, mk.name[:14], size=10,
                             color=COL_MARK)
        drawing.diamonds(pts, 5, COL_MARK)

    if _st["mode"] == 'edit' and _st["op"] == 'DUP' and _st["d"]:
        ghost = {}
        for e in _st["snap"]:
            ghost.setdefault(e["fk"], []).append(e["x"] + _st["d"])
        pts = []
        for row, y1, y2 in visible:
            for fk in row["fks"]:
                for f in ghost.get(fk, ()):
                    pts.append((_fx(f), (y1 + y2) / 2))
        drawing.diamonds(pts, KEY_R, COL_GHOST)

    if _st["mode"] == 'box' and _st["box"]:
        x0, y0, x1, y1 = _st["box"]
        xa, xb = sorted((x0, x1))
        ya, yb = sorted((y0, y1))
        drawing.rects([(xa, ya, xb, ya + 1), (xa, yb - 1, xb, yb),
                       (xa, ya, xa + 1, yb), (xb - 1, ya, xb, yb)], COL_BOX)

    px = _fx(sc.frame_current)
    if kx1 <= px <= kx2:
        drawing.rect(px - 1, ky1, px + 1, ky2, COL_PLAY)
        drawing.glyph(px, rl[1] + 6, "▼", 10, COL_PLAY)

    _draw_buttons(context, _dope_items(context, G), mx, my, _dope_is_on)


# ----------------------------------------------------------------------
# Selection and editing helpers (always on FRESH data)
# ----------------------------------------------------------------------

def _deselect_all(context):
    for _k, fc in fresh_items(context):
        for kp in fc.keyframe_points:
            kp.select_control_point = False
            kp.select_left_handle = False
            kp.select_right_handle = False


def _select_at(context, row, frame):
    fm = fresh_map(context)
    near = []
    for fk in row["fks"]:
        fc = fm.get(fk)
        if fc is None:
            continue
        for kp in fc.keyframe_points:
            if abs(kp.co[0] - frame) < 0.01:
                near.append(kp)
    if near and all(kp.select_control_point for kp in near):
        return                                  # already selected: drag all
    _deselect_all(context)                      # (does not invalidate near)
    for kp in near:
        kp.select_control_point = True
        kp.select_left_handle = True
        kp.select_right_handle = True


def _nearest_key(row, mx):
    frames, _s = _keys(row)
    best, bd = None, 11.0
    for f in frames:
        d = abs(_fx(f) - mx)
        if d < bd:
            best, bd = f, d
    return best


def _entry(fk, i, kp, w=1.0):
    return {"fk": fk, "i": i, "x": kp.co[0], "y": kp.co[1],
            "cx": kp.co[0], "hl": tuple(kp.handle_left),
            "hr": tuple(kp.handle_right), "tl": kp.handle_left_type,
            "tr": kp.handle_right_type, "ip": kp.interpolation,
            "ea": kp.easing, "w": w}


def _snapshot(context, with_prop=False):
    """Selected keys as plain data (no Blender objects are kept); with
    proportional editing on, the neighbours follow with a weight."""
    out, sel_x = [], []
    items = fresh_items(context)
    for fk, fc in items:
        for i, kp in enumerate(fc.keyframe_points):
            if kp.select_control_point:
                out.append(_entry(fk, i, kp))
                sel_x.append(kp.co[0])
    if with_prop and out and _sp("nomad_ds_prop", False):
        radius = max(0.5, _sp("nomad_ds_prop_size", 10.0))
        fall = _sp("nomad_ds_falloff", 'SMOOTH')
        sel_x.sort()
        for fk, fc in items:
            for i, kp in enumerate(fc.keyframe_points):
                if kp.select_control_point:
                    continue
                x = kp.co[0]
                j = bisect.bisect_left(sel_x, x)
                d = 1e18
                if j < len(sel_x):
                    d = abs(sel_x[j] - x)
                if j > 0:
                    d = min(d, abs(sel_x[j - 1] - x))
                if d < radius:
                    wgt = _falloff(fall, 1.0 - d / radius)
                    if wgt > 0.001:
                        out.append(_entry(fk, i, kp, wgt))
    return out


def _dope_pivot(context, snap):
    """Pivot (in frames) for Scale: current frame, centre of the selection
    or the centre of each channel's selection."""
    mode = _sp("nomad_ds_pivot", 'CURRENT_FRAME')
    xs = [e["x"] for e in snap]
    centre = (min(xs) + max(xs)) / 2
    if mode == 'BOUNDING_BOX_CENTER':
        return {"all": centre, "per": {}}
    if mode == 'INDIVIDUAL_CENTERS':
        per = {}
        for fk in {e["fk"] for e in snap}:
            pts = [e["x"] for e in snap if e["fk"] == fk]
            per[fk] = (min(pts) + max(pts)) / 2
        return {"all": centre, "per": per}
    return {"all": float(context.scene.frame_current), "per": {}}


def _resolve(fm, e):
    """The keyframe an entry refers to, or None if it is not there / not
    the same any more (nothing is ever written to a stale keyframe)."""
    fc = fm.get(e["fk"])
    if fc is None:
        return None
    kps = fc.keyframe_points
    if e["i"] >= len(kps):
        return None
    kp = kps[e["i"]]
    if abs(kp.co[0] - e["cx"]) > 1e-3:
        return None
    return kp


def _touch(fm, fks, force=False):
    now = time.time()
    if not force and now - _last_up[0] < UPDATE_EVERY:
        return
    _last_up[0] = now
    for fk in fks:
        fc = fm.get(fk)
        if fc is not None:
            fc.update()


def _tap_row(context, key):
    row = next((r for r in _rows(context) if r["key"] == key), None)
    if row is None:
        return
    if row["kind"] in _FOLDABLE:
        _fold.symmetric_difference_update({key})
        return
    fm = fresh_map(context)
    fc = fm.get(row["fks"][0])
    if fc is None:
        return
    if _st["x0"] >= CH_W - 30:                  # the mute toggle
        fc.mute = not fc.mute
        return
    for other in fm.values():
        other.select = False
    fc.select = True
    try:
        context.scene.nomad_gr_active = "{}|{}|{}".format(*row["fks"][0])
    except (AttributeError, TypeError):
        pass


def _box_select(context, w, box):
    G = _geom(context, w)
    xa, xb = sorted((box[0], box[2]))
    ya, yb = sorted((box[1], box[3]))
    top = G["chan"][3]
    off = int(round(_scroll / ROWH)) * ROWH
    hit = []
    for i, row in enumerate(_rows(context)):
        ry2 = top - i * ROWH + off
        ry1 = ry2 - ROWH
        if ry2 < ya or ry1 > yb or ry1 < G["chan"][1] - 0.5:
            continue
        hit.extend(row["fks"])
    _deselect_all(context)
    fm = fresh_map(context)
    for fk in set(hit):
        fc = fm.get(fk)
        if fc is None:
            continue
        for kp in fc.keyframe_points:
            if xa <= _fx(kp.co[0]) <= xb:
                kp.select_control_point = True
                kp.select_left_handle = True
                kp.select_right_handle = True


def duplicate_keys(context, snap, d, dv=0.0):
    """Insert copies of the snapshot keys offset by (d, dv); the copies
    become the selection. Works only from plain data."""
    fm = fresh_map(context)
    affected = {e["fk"] for e in snap}
    for fk in affected:
        fc = fm.get(fk)
        if fc is None:
            continue
        for kp in fc.keyframe_points:
            kp.select_control_point = False
            kp.select_left_handle = False
            kp.select_right_handle = False
    for e in snap:
        fc = fm.get(e["fk"])
        if fc is None:
            continue
        try:
            new = fc.keyframe_points.insert(e["x"] + d, e["y"] + dv)
        except (RuntimeError, TypeError):
            continue
        try:
            new.interpolation = e["ip"]
            new.easing = e["ea"]
            new.handle_left_type = e["tl"]
            new.handle_right_type = e["tr"]
        except (TypeError, ValueError):
            pass
        new.handle_left = (e["hl"][0] + d, e["hl"][1] + dv)
        new.handle_right = (e["hr"][0] + d, e["hr"][1] + dv)
        new.select_control_point = True
        new.select_left_handle = True
        new.select_right_handle = True
    for fk in affected:
        fc = fm.get(fk)
        if fc is not None:
            fc.update()


def _edit_update(context, sc, mx):
    op, snap = _st["op"], _st["snap"]
    if not snap:
        return
    snap_on = bool(_sp("nomad_ds_snap", True))
    smode = _sp("nomad_ds_snap_mode", 'FRAME')
    if op in ('MOVE', 'DUP'):
        ref = snap[0]                          # a selected key
        raw = ref["x"] + (mx - _st["x0"]) / _v["ppf"]
        d = (snap_frame(sc, raw, smode) if snap_on else raw) - ref["x"]
        if d == _st["d"]:
            return
        _st["d"] = d
        if op == 'DUP':
            return                      # only a ghost until release
        fm = fresh_map(context)
        for e in snap:
            kp = _resolve(fm, e)
            if kp is None:
                _st["mode"] = None      # stale: cancel the gesture
                return
            wt = e["w"]
            nx = e["x"] + d * wt
            kp.co = (nx, e["y"])
            kp.handle_left = (e["hl"][0] + d * wt, e["hl"][1])
            kp.handle_right = (e["hr"][0] + d * wt, e["hr"][1])
            e["cx"] = nx
        if not _st["noupd"]:
            _touch(fm, {e["fk"] for e in snap})
    else:                                              # SCALE
        piv = _st["piv"] or {"all": float(sc.frame_current), "per": {}}
        base = _st["x0"] - _fx(piv["all"])
        if abs(base) < 12:
            base = 12.0 if base >= 0 else -12.0
        k = max(0.02, (mx - _fx(piv["all"])) / base)
        _st["d"] = k
        fm = fresh_map(context)
        for e in snap:
            kp = _resolve(fm, e)
            if kp is None:
                _st["mode"] = None
                return
            c = piv["per"].get(e["fk"], piv["all"])
            nx = c + (e["x"] - c) * k
            if snap_on:
                nx = snap_frame(sc, nx, smode)
            kp.co = (nx, e["y"])
            kp.handle_left = (c + (e["hl"][0] - c) * k, e["hl"][1])
            kp.handle_right = (c + (e["hr"][0] - c) * k, e["hr"][1])
            e["cx"] = nx
        _touch(fm, {e["fk"] for e in snap})
    _kcache.clear()


# ----------------------------------------------------------------------
# Interaction (called from top_bar.scrub_click / scrub_drag / scrub_release)
# ----------------------------------------------------------------------

def press(context, w, mx, my):
    G = _geom(context, w)
    if not _in(G["panel"], mx, my):
        return False
    if _mode(context) in _SOON:
        return True
    ext = ext_module(context)
    if ext is not None:
        _st.update(last=(mx, my), moved=0.0, mode=None, op=None, row=None,
                   snap=[], x0=mx, y0=my, w=w, d=0.0, box=None, piv=None,
                   noupd=False)
        if ext.press(context, w, mx, my):
            _st["mode"] = 'ext'
            return True
        return False
    sc = context.scene
    graph = graph_on(context)
    dope = dope_on(context)
    _st.update(last=(mx, my), moved=0.0, mode=None, op=None, row=None,
               snap=[], x0=mx, y0=my, w=w, d=0.0, box=None, piv=None,
               noupd=False)
    if (graph and not _in(G["chan"], mx, my)
            and not _in(G["head"], mx, my)):
        from . import graph_ext
        if graph_ext.press(context, w, mx, my):
            _st["mode"] = 'graph'
            return True
        return False

    _ensure_view(sc, w)
    if dope:
        for key, label, kind, rect, tip in _dope_items(context, G):
            if _in(rect, mx, my):
                _tb_action(context, key, w)
                return True
        if any(_in(r, mx, my) for r in G["rows"]):
            return True
        if _sp("nomad_ds_mode", 'DOPESHEET') != 'DOPESHEET':
            return True
    if _in(G["ruler"], mx, my):
        sc.frame_set(int(round(_xf(mx))))
        _st["mode"] = 'scrub'
        return True
    if _in(G["head"], mx, my):
        return True

    rows = _rows(context)
    row = _row_at(rows, G, my)
    if _in(G["chan"], mx, my):
        _st["mode"] = 'chan'
        _st["row"] = row["key"] if row else None
        return True

    if _tool["box"]:
        _st["mode"] = 'box'
        _st["box"] = (mx, my, mx, my)
        return True
    op = 'SCALE' if _tool["scale"] else 'DUP' if _tool["dup"] else 'MOVE'
    if row is not None:
        kf = _nearest_key(row, mx)
        if kf is not None:
            _select_at(context, row, kf)
            snap = _snapshot(context, with_prop=(op == 'MOVE'))
            _st.update(mode='edit', op=op, snap=snap,
                       noupd=any(e["w"] < 1.0 for e in snap))
            if op == 'SCALE' and snap:
                _st["piv"] = _dope_pivot(context, snap)
            return True
    if op == 'SCALE':                    # scale the current selection
        snap = _snapshot(context)
        if snap:
            _st.update(mode='edit', op=op, snap=snap,
                       piv=_dope_pivot(context, snap))
            return True
    _st["mode"] = 'bg'
    return True


def update(context, w, mx, my):
    global _scroll
    if _st["mode"] == 'ext':
        ext = ext_module(context)
        if ext is not None:
            ext.update(context, w, mx, my)
        return
    if _st["mode"] == 'graph':
        from . import graph_ext
        graph_ext.update(context, w, mx, my)
        return
    sc = context.scene
    _ensure_view(sc, w)
    lx, ly = _st["last"]
    dx, dy = mx - lx, my - ly
    _st["last"] = (mx, my)
    _st["moved"] += abs(dx) + abs(dy)
    mode = _st["mode"]
    if mode == 'scrub':
        sc.frame_set(int(round(_xf(mx))))
    elif mode == 'chan' and _st["moved"] > 8:
        G = _geom(context, w)
        _scroll = max(0.0, min(_scroll + dy,
                               _max_scroll(len(_rows(context)), G)))
    elif mode == 'bg' and _st["moved"] > 8:
        G = _geom(context, w)
        _v["f0"] -= dx / _v["ppf"]
        _scroll = max(0.0, min(_scroll + dy,
                               _max_scroll(len(_rows(context)), G)))
    elif mode == 'box':
        _st["box"] = (_st["x0"], _st["y0"], mx, my)
    elif mode == 'edit' and _st["moved"] > 4:
        _edit_update(context, sc, mx)


def release(context):
    mode, moved = _st["mode"], _st["moved"]
    _st["mode"] = None
    if mode == 'ext':
        ext = ext_module(context)
        if ext is not None:
            ext.release(context)
        return
    if mode == 'graph':
        from . import graph_ext
        graph_ext.release(context)
        return
    if mode == 'chan' and moved <= 8 and _st["row"]:
        _tap_row(context, _st["row"])
    elif mode == 'bg' and moved <= 8:
        _deselect_all(context)
    elif mode == 'box':
        if _st["box"] and moved > 6:
            _box_select(context, _st["w"], _st["box"])
    elif mode == 'edit':
        op, snap = _st["op"], _st["snap"]
        if op in ('MOVE', 'SCALE'):
            fm = fresh_map(context)
            _touch(fm, {e["fk"] for e in snap}, force=True)
            if moved > 4:
                _push("Edit keyframes")
        elif op == 'DUP' and _st["d"]:
            duplicate_keys(context, snap, _st["d"])
            _push("Duplicate keyframes")
    _st.update(snap=[], box=None, op=None, piv=None, noupd=False)
    drop_caches()


def wheel(area, region, mx, my, direction):
    global _scroll
    context = bpy.context
    if not expanded(context):
        return False
    w, h = style.region_size(region)
    G = _geom(context, w)
    if not _in(G["panel"], mx, my):
        return False
    if _mode(context) in _SOON:
        return True
    ext = ext_module(context)
    if ext is not None:
        return ext.wheel(context, w, mx, my, direction)
    if graph_on(context) and not _in(G["chan"], mx, my):
        from . import graph_ext
        return graph_ext.wheel(context, w, mx, my, direction)
    if _in(G["keys"], mx, my) and not graph_on(context):
        _ensure_view(context.scene, w)
        _zoom_time(mx, 1.15 ** direction)
        return True
    _scroll = max(0.0, min(_scroll - direction * ROWH,
                           _max_scroll(len(_rows(context)), G)))
    return True