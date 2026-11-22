# Floating GPU asset browser: type filter, libraries (dropdown with create /
# remove), collapsible catalog folders, preview tiles, drag & drop into the
# viewport (Object mode) and a Pose Library mode (Pose mode).
import array
import math
import os
import time
import uuid
from pathlib import Path

import bpy
import gpu
from bpy_extras import view3d_utils

from . import drawing, panels, safety, style
from .top_bar import BAR_H
from .sculpt_popups import open_panel_deferred, _view3d_override, defer_op
from .brush_shelf import _read_cats, _parse_cats
from .fav_bar import _draw_tex

W = 340
HEAD = 34
ROW = 26
NAME_H = 14
GAP = 6
TREE_W = 112
PAD = 6

COL_BG = (0.06, 0.06, 0.07, 0.96)
COL_ROW = (0.13, 0.13, 0.15, 1.0)
COL_SEL = (0.22, 0.48, 0.85, 0.55)
COL_TXT = (0.9, 0.9, 0.92, 1.0)
COL_DIM = (0.6, 0.6, 0.65, 1.0)

TYPES = (("ALL", "All", None), ("OBJECT", "Obj", "objects"),
         ("COLLECTION", "Coll", "collections"),
         ("MATERIAL", "Mat", "materials"),
         ("NODETREE", "Node", "node_groups"), ("WORLD", "World", "worlds"),
         ("LIGHT", "Light", "lights"))
_ATTR = {k: a for k, _l, a in TYPES if a}
_ATTR["ACTION"] = "actions"                 # poses (Pose mode only)

visible = False
_all = []                  # asset dicts
_raw = {}                  # key -> (w, h, array) until the first draw
_gpu = {}                  # key -> GPUTexture or None
_scan = {"queue": [], "total": 0, "done": 0, "active": False}
_cats = {}
_ui = {"type": "ALL", "lib": "ALL", "folder": "", "sel": None,
       "fold": set(), "st": 0.0, "sg": 0.0}
_st = {"mode": None, "src": None, "last": (0, 0), "moved": 0.0,
       "raw": (0, 0), "inside": True, "mouse": (0, 0)}
_pending = {"asset": None}


def _in(r, mx, my):
    return r[0] <= mx <= r[2] and r[1] <= my <= r[3]


def _tile():
    try:
        p = bpy.context.preferences.addons[__package__].preferences
        return int(max(40, min(160, p.asset_tile)))
    except (KeyError, AttributeError):
        return 62


def _pose_mode():
    return bpy.context.mode == 'POSE'


def selected_asset():
    return next((a for a in _all if a["key"] == _ui["sel"]), None)


# ----------------------------------------------------------------------
# Scanning (one file per timer tick; previews are kept as raw pixels)
# ----------------------------------------------------------------------

def _pixels(pv, size_attr, px_attr):
    w, h = getattr(pv, size_attr)
    if w <= 0 or h <= 0:
        return None
    buf = array.array('f', bytes(4 * w * h * 4))
    getattr(pv, px_attr).foreach_get(buf)
    step = max(1, math.ceil(w / 64))
    out = array.array('f')
    for y in range(0, h, step):
        row = y * w * 4
        for x in range(0, w, step):
            i = row + x * 4
            out.extend(buf[i:i + 4])
    return (len(range(0, w, step)), len(range(0, h, step)), out)


def _grab(idb):
    try:
        pv = idb.preview
        if pv is None:
            return None
        for a, b in (("image_size", "image_pixels_float"),
                     ("icon_size", "icon_pixels_float")):
            try:
                got = _pixels(pv, a, b)
            except Exception:
                got = None
            if got:
                return got
    except Exception:
        pass
    return None


def _add(idb, kind, attr, file, lib, path, ltype):
    key = (file, kind, idb.name)
    _all.append({"key": key, "name": idb.name, "kind": kind, "attr": attr,
                 "file": file, "lib": lib, "path": path, "ltype": ltype})
    raw = _grab(idb)
    if raw:
        _raw[key] = raw


def _local_cats():
    """Catalogs of the current file: the catalog file next to the .blend
    (or in its parent folder). Only those two files are read, not a tree."""
    cats = {}
    if bpy.data.filepath:
        here = Path(bpy.data.filepath).parent
        for folder in (here.parent, here):          # the nearest one wins
            f = folder / "blender_assets.cats.txt"
            if f.is_file():
                try:
                    _parse_cats(f, cats)
                except (OSError, UnicodeDecodeError):
                    pass
    return cats


def _local_path(ad, cats):
    """Catalog path of a local asset. A catalog that was just created is
    not in the file yet: fall back to the simple name (path with '/' -> '-')."""
    path = cats.get(str(ad.catalog_id).casefold(), "")
    if not path:
        simple = getattr(ad, "catalog_simple_name", "") or ""
        path = simple.replace("-", "/").strip("/")
    return path


def _scan_local(context):
    cats = _local_cats()
    for kind, attr in _ATTR.items():
        for idb in getattr(bpy.data, attr, ()):
            try:
                if idb.library is None and idb.asset_data is not None:
                    _add(idb, kind, attr, "", "Current File",
                         _local_path(idb.asset_data, cats), 'LOCAL')
            except (ReferenceError, RuntimeError, AttributeError):
                pass


def _files(context):
    out, mine = [], str(Path(bpy.data.filepath)) if bpy.data.filepath else ""
    try:
        libs = list(context.preferences.filepaths.asset_libraries)
    except (AttributeError, RuntimeError):
        libs = []
    for lib in libs:
        root = Path(bpy.path.abspath(lib.path))
        if root.is_dir():
            for f in sorted(root.rglob("*.blend")):
                if str(f) != mine:
                    out.append((lib.name, root, f))
    try:
        assets = Path(bpy.utils.system_resource('DATAFILES')) / "assets"
        if assets.is_dir():
            for f in sorted(assets.rglob("*.blend")):
                parts = [p.casefold() for p in
                         f.relative_to(assets).parts[:-1]]
                if "brushes" not in parts:
                    out.append(("Essentials", assets, f))
    except Exception as exc:
        print(f"NomadUI assets: essentials: {exc!r}")
    return out


def _scan_file(lib, root, f):
    if root not in _cats:
        _cats[root] = _read_cats(root)
    cats = _cats[root]
    ltype = 'ESSENTIALS' if lib == "Essentials" else 'CUSTOM'
    try:
        with bpy.data.libraries.load(str(f), link=True,
                                     assets_only=True) as (src, dst):
            for attr in _ATTR.values():
                names = list(getattr(src, attr, ()))
                if names:
                    setattr(dst, attr, names)
    except Exception as exc:
        print(f"NomadUI assets: {f.name}: {exc!r}")
        return
    fallback = "/".join(f.relative_to(root).parent.parts)
    libs = set()
    for kind, attr in _ATTR.items():
        for idb in list(getattr(dst, attr, ()) or ()):
            if idb is None:
                continue
            try:
                ad = idb.asset_data
                path = (cats.get(str(ad.catalog_id).casefold(), "")
                        if ad is not None else "") or fallback
                _add(idb, kind, attr, str(f), lib, path, ltype)
                if idb.library is not None:
                    libs.add(idb.library)
            except (ReferenceError, RuntimeError, AttributeError):
                pass
    for l in libs:
        try:
            bpy.data.libraries.remove(l)
        except (RuntimeError, ReferenceError, ValueError):
            pass


def _step():
    if safety.exiting() or not _scan["queue"]:
        _scan["active"] = False
        return None
    lib, root, f = _scan["queue"].pop(0)
    try:
        _scan_file(lib, root, f)
    except Exception as exc:
        print(f"NomadUI assets: {f.name}: {exc!r}")
    _scan["done"] += 1
    if not _scan["queue"]:
        _scan["active"] = False
        print(f"NomadUI assets: {len(_all)} assets")
        return None
    return 0.03


def refresh():
    _catcache.update(t=0.0, lib=None, paths=[])
    _all.clear()
    _raw.clear()
    _gpu.clear()
    _cats.clear()
    ctx = bpy.context
    _scan_local(ctx)
    _scan["queue"] = _files(ctx)
    _scan["total"] = len(_scan["queue"])
    _scan["done"] = 0
    if _scan["queue"] and not _scan["active"]:
        _scan["active"] = True
        try:
            bpy.app.timers.register(_step, first_interval=0.05)
        except RuntimeError:
            _scan["active"] = False


def toggle():
    global visible
    visible = not visible
    if visible and not _all and not _scan["active"]:
        refresh()


# ----------------------------------------------------------------------
# Model
# ----------------------------------------------------------------------

def _kind_ok(kind):
    return (kind == 'ACTION') if _pose_mode() else (kind != 'ACTION')


def _match(a, folder=True):
    if not _kind_ok(a["kind"]):
        return False
    if (not _pose_mode() and _ui["type"] != "ALL"
            and a["kind"] != _ui["type"]):
        return False
    if _ui["lib"] != "ALL" and a["lib"] != _ui["lib"]:
        return False
    f = _ui["folder"]
    if folder and f and not (a["path"] == f or a["path"].startswith(f + "/")):
        return False
    return True


def _libs():
    labs = ["Current File", "Essentials"]
    try:
        labs += [l.name for l in bpy.context.preferences.filepaths
                 .asset_libraries]
    except (AttributeError, RuntimeError):
        pass
    for a in _all:
        if a["lib"] not in labs:
            labs.append(a["lib"])
    return ["ALL"] + labs


_catcache = {"t": 0.0, "lib": None, "paths": []}


def _catalog_paths():
    """Catalogs of the shown library(ies) read from their catalog files, so
    that empty catalogs also appear. Cached: this runs while drawing."""
    now = time.time()
    lib = _ui["lib"]
    if _catcache["lib"] == lib and now - _catcache["t"] < 2.0:
        return _catcache["paths"]
    names = _writable_libs()
    names = names if lib == "ALL" else [n for n in names if n == lib]
    paths = set()
    for n in names:
        try:
            paths.update(_cat_paths(n))
        except (OSError, ReferenceError, RuntimeError):
            pass
    _catcache.update(t=now, lib=lib, paths=sorted(paths))
    return _catcache["paths"]


def _tree_rows():
    counts, total = {}, 0
    for path in _catalog_paths():
        parts = [p for p in path.split("/") if p]
        for i in range(1, len(parts) + 1):
            counts.setdefault("/".join(parts[:i]), 0)
    for a in _all:
        if not _match(a, folder=False):
            continue
        total += 1
        parts = [p for p in a["path"].split("/") if p]
        for i in range(1, len(parts) + 1):
            k = "/".join(parts[:i])
            counts[k] = counts.get(k, 0) + 1
    rows = [("", "All", 0, False, total)]
    for k in sorted(counts, key=str.casefold):
        depth = k.count("/")
        anc = ["/".join(k.split("/")[:i]) for i in range(1, depth + 1)]
        if any(x in _ui["fold"] for x in anc):
            continue
        has_child = any(o.startswith(k + "/") for o in counts)
        rows.append((k, k.rsplit("/", 1)[-1], depth + 1, has_child,
                     counts[k]))
    return rows


def _texture(key):
    if key in _gpu:
        return _gpu[key]
    raw = _raw.pop(key, None)
    if raw is None:
        return None
    w, h, arr = raw
    try:
        buf = gpu.types.Buffer('FLOAT', len(arr), list(arr))
        tex = gpu.types.GPUTexture((w, h), format='RGBA32F', data=buf)
    except Exception:
        tex = None
    _gpu[key] = tex
    return tex


# ----------------------------------------------------------------------
# Geometry
# ----------------------------------------------------------------------

def _rects(context, w, h):
    x2 = w - (panels.MARGIN + 4 + panels.BTN + panels.PAD + 8)
    if getattr(context.scene, "nomad_sidebar_left", False):
        x2 = w - panels.MARGIN - 8
    x1 = x2 - W
    y2 = h - BAR_H - 10
    if getattr(context.scene, "nomad_nav_gizmo", True):
        from . import color_overlay
        y2 = min(y2, color_overlay._nav_geometry(context, w, h)[3] - 10)
    y1 = style._stack_top(context)
    chips = (x1 + PAD, y2 - HEAD - ROW, x2 - PAD, y2 - HEAD - 2)
    libr = (x1 + PAD, chips[1] - ROW - 2, x2 - PAD, chips[1] - 2)
    foot = (x1 + PAD, y1 + PAD, x2 - PAD, y1 + PAD + 30)
    top, bot = libr[1] - 4, foot[3] + 4
    tree = (x1 + PAD, bot, x1 + PAD + TREE_W, top)
    grid = (tree[2] + GAP, bot, x2 - PAD, top)
    return {"panel": (x1, y1, x2, y2), "head": (x1, y2 - HEAD, x2, y2),
            "chips": chips, "lib": libr, "foot": foot, "tree": tree,
            "grid": grid}


def _head_buttons(R):
    x2, y2 = R["panel"][2], R["panel"][3]
    keys = (("close", "✕"), ("refresh", "⟳")) if _pose_mode() else (
        ("close", "✕"), ("more", "≡"), ("refresh", "⟳"))
    out, x = [], x2 - PAD
    for key, glyph in keys:
        out.append((key, glyph, (x - 26, y2 - HEAD + 4, x, y2 - 4)))
        x -= 30
    return out


def _chip_rects(R):
    x1, y1, x2, y2 = R["chips"]
    n = len(TYPES)
    cw = (x2 - x1) / n
    return [(t[0], t[1], (x1 + i * cw + 1, y1, x1 + (i + 1) * cw - 1, y2))
            for i, t in enumerate(TYPES)]


def _grid_layout(R):
    gx1, gy1, gx2, gy2 = R["grid"]
    tile = _tile()
    cols = max(1, int((gx2 - gx1 + GAP) // (tile + GAP)))
    return cols, tile + NAME_H + GAP


def _snap(v, step):
    return int(round(v / step)) * step


def _max_scroll(n_rows, row_h, area):
    extra = max(0.0, n_rows * row_h - (area[3] - area[1]))
    return math.ceil(extra / row_h) * row_h


def _pose_ready():
    ob = bpy.context.active_object
    return bool(ob is not None and ob.type == 'ARMATURE'
                and bpy.context.mode == 'POSE')


def _local_assets_count():
    return sum(1 for a in bpy.data.actions if a.asset_data is not None)


def _watch_new_pose():
    """poselib saves the pose when its dialog is accepted, which we do not
    see: poll for the new asset and refresh the browser."""
    start = _local_assets_count()
    left = [90]

    def _tick():
        left[0] -= 1
        try:
            if _local_assets_count() != start:
                refresh()
                return None
        except (ReferenceError, RuntimeError):
            return None
        return 1.0 if left[0] > 0 else None
    try:
        bpy.app.timers.register(_tick, first_interval=1.0)
    except (RuntimeError, ValueError):
        pass


def _prepare_new_pose(context):
    """Create Pose Asset only keeps the selected bones and silently does
    nothing when none is selected: in that case use every bone."""
    from .anim_options import bone_selected, set_bone_selected
    ob = context.active_object
    if ob is None or ob.type != 'ARMATURE':
        return
    names = [b.name for b in ob.data.bones]
    try:
        if not any(bone_selected(ob, n) for n in names):
            for n in names:
                set_bone_selected(ob, n, True)
    except (AttributeError, KeyError, RuntimeError):
        pass


def _foot_buttons(R):
    """[(key, label, rect, tip, enabled)] for the footer."""
    f = R["foot"]
    sel = selected_asset()
    if _pose_mode():
        from . import requirements
        ready = sel is not None and _pose_ready()
        keys = [("apply", "Apply", "Apply the pose to the selected bones "
                 "(or every bone)", ready),
                ("flip", "Flip", "Apply the pose mirrored", ready),
                ("blend", "Blend", "Blend the pose in with a slider", ready),
                ("new", "New", "Create a pose asset from the current pose "
                 "(selected bones, or all if none)",
                 requirements.enabled("pose_library") and _pose_ready()),
                ("del", "Del", "Delete the selected asset", sel is not None)]
        n = len(keys)
        wb = (f[2] - f[0] - (n - 1) * 3) / n
        return [(k, lbl, (f[0] + i * (wb + 3), f[1], f[0] + i * (wb + 3)
                          + wb, f[3]), tip, en)
                for i, (k, lbl, tip, en) in enumerate(keys)]
    keys = [("add", "Add", "Add the selected asset at the 3D cursor",
             sel is not None),
            ("del", "Del", "Delete the selected asset", sel is not None)]
    out, x = [], f[2]
    for k, lbl, tip, en in reversed(keys):
        out.insert(0, (k, lbl, (x - 56, f[1], x, f[3]), tip, en))
        x -= 59
    return out


# ----------------------------------------------------------------------
# Draw
# ----------------------------------------------------------------------

def draw(context, w, h, mx, my):
    if not visible:
        return
    R = _rects(context, w, h)
    x1, y1, x2, y2 = R["panel"]
    pose = _pose_mode()
    drawing.rect(x1, y1, x2, y2, COL_BG)

    title = "Pose Library" if pose else "Assets"
    if _scan["active"]:
        title += f"  (scanning {_scan['done']}/{_scan['total']})"
    drawing.text(x1 + PAD + 2, y2 - HEAD / 2 - 6, title, size=14,
                 color=COL_TXT)
    for key, glyph, r in _head_buttons(R):
        inside = _in(r, mx, my)
        drawing.rect(r[0], r[1], r[2], r[3],
                     panels.COL_HOVER if inside else panels.COL_BTN)
        drawing.text((r[0] + r[2]) / 2, (r[1] + r[3]) / 2 - 7, glyph,
                     size=15, color=COL_TXT, align='CENTER')

    if pose:
        c = R["chips"]
        drawing.text(c[0] + 4, (c[1] + c[3]) / 2 - 6,
                     "Poses (actions marked as assets)", size=12,
                     color=COL_DIM)
    else:
        for tkey, label, r in _chip_rects(R):
            on = _ui["type"] == tkey
            drawing.rect(r[0], r[1], r[2], r[3],
                         panels.FILL_COL if on else panels.COL_BTN)
            drawing.text((r[0] + r[2]) / 2, (r[1] + r[3]) / 2 - 6, label,
                         size=11, color=COL_TXT, align='CENTER')

    lr = R["lib"]
    drawing.rect(lr[0], lr[1], lr[2], lr[3],
                 panels.COL_HOVER if _in(lr, mx, my) else panels.COL_BTN)
    lib = "All Libraries" if _ui["lib"] == "ALL" else _ui["lib"]
    drawing.text(lr[0] + 8, (lr[1] + lr[3]) / 2 - 6, f"▾ {lib}", size=12,
                 color=COL_TXT)

    # --- folders tree ---
    t = R["tree"]
    rows = _tree_rows()
    _ui["st"] = max(0.0, min(_ui["st"], _max_scroll(len(rows), ROW, t)))
    off = _snap(_ui["st"], ROW)
    for i, (path, name, depth, has_child, n) in enumerate(rows):
        ry2 = t[3] - i * ROW + off
        ry1 = ry2 - ROW
        if ry1 < t[1] - 0.5 or ry2 > t[3] + 0.5:
            continue
        sel = _ui["folder"] == path
        drawing.rect(t[0], ry1 + 1, t[2], ry2 - 1,
                     COL_SEL if sel else COL_ROW)
        tx = t[0] + 4 + depth * 10
        cy = (ry1 + ry2) / 2 - 6
        if has_child:
            drawing.text(tx, cy, "▸" if path in _ui["fold"] else "▾",
                         size=12, color=COL_TXT)
        maxc = max(3, int((t[2] - tx - 36) / 6.5))
        drawing.text(tx + 12, cy, name[:maxc], size=11, color=COL_TXT)
        drawing.text(t[2] - 4, cy, str(n), size=10, color=COL_DIM,
                     align='RIGHT')

    # --- tiles ---
    g = R["grid"]
    tile = _tile()
    items = [a for a in _all if _match(a)]
    cols, row_h = _grid_layout(R)
    n_rows = math.ceil(len(items) / cols) if items else 0
    _ui["sg"] = max(0.0, min(_ui["sg"], _max_scroll(n_rows, row_h, g)))
    goff = _snap(_ui["sg"], row_h)
    for i, a in enumerate(items):
        r_, c_ = divmod(i, cols)
        tx = g[0] + c_ * (tile + GAP)
        ty2 = g[3] - r_ * row_h + goff
        ty1 = ty2 - tile - NAME_H
        if ty1 < g[1] - 0.5 or ty2 > g[3] + 0.5:
            continue
        sel = _ui["sel"] == a["key"]
        drawing.rect(tx - 2, ty1 - 2, tx + tile + 2, ty2 + 2,
                     COL_SEL if sel else COL_ROW)
        tex = _texture(a["key"])
        img = (tx, ty2 - tile, tx + tile, ty2)
        if tex is not None:
            _draw_tex(tex, *img)
        else:
            drawing.rect(*img, (0.2, 0.2, 0.22, 1.0))
            drawing.text(tx + tile / 2, ty2 - tile / 2 - 8,
                         a["kind"][:1], size=20, color=COL_DIM,
                         align='CENTER')
        drawing.text(tx + 1, ty1 + 1, a["name"][:int(tile / 5.6)],
                     size=10, color=COL_TXT)
        if _in((tx, ty1, tx + tile, ty2), mx, my):
            panels.hover_tip = a["name"]
    if not items:
        msg = ("Scanning..." if _scan["active"] else
               "No poses yet: use New, then refresh" if pose else
               "No assets")
        drawing.text(g[0] + 6, g[3] - 24, msg, size=12, color=COL_DIM)

    # --- footer ---
    sel = selected_asset()
    f = R["foot"]
    if sel is not None and not pose:
        drawing.text(f[0] + 2, (f[1] + f[3]) / 2 - 6, sel["name"][:18],
                     size=12, color=COL_TXT)
    for key, label, rect, tip, en in _foot_buttons(R):
        hot = _in(rect, mx, my) and en
        drawing.rect(*rect, panels.COL_HOVER if hot else panels.COL_BTN)
        drawing.text((rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2 - 6,
                     label, size=12 if not pose else 11,
                     color=COL_TXT if en else COL_DIM, align='CENTER')
        if _in(rect, mx, my):
            panels.hover_tip = tip

    if _st["mode"] == 'tile' and _st["moved"] > 10 and not pose:  # ghost
        gx, gy = _st["mouse"]
        key = _st["src"]
        tex = _texture(key) if key else None
        if tex is not None:
            _draw_tex(tex, gx - 24, gy - 24, gx + 24, gy + 24)
        else:
            drawing.rect(gx - 24, gy - 24, gx + 24, gy + 24, COL_SEL)


# ----------------------------------------------------------------------
# Interaction
# ----------------------------------------------------------------------

def _tile_at(R, mx, my):
    g = R["grid"]
    if not _in(g, mx, my):
        return None
    tile = _tile()
    cols, row_h = _grid_layout(R)
    items = [a for a in _all if _match(a)]
    goff = _snap(_ui["sg"], row_h)
    for i, a in enumerate(items):
        r_, c_ = divmod(i, cols)
        tx = g[0] + c_ * (tile + GAP)
        ty2 = g[3] - r_ * row_h + goff
        ty1 = ty2 - tile - NAME_H
        if ty1 < g[1] - 0.5 or ty2 > g[3] + 0.5:
            continue
        if _in((tx, ty1, tx + tile, ty2), mx, my):
            return a
    return None


def _head_action(key):
    global visible
    if key == "close":
        visible = False
    elif key == "more":
        open_panel_deferred("NOMAD_PT_assets")
    elif key == "refresh":
        refresh()


def _foot_action(context, key):
    sel = selected_asset()
    if key == "add" and sel is not None:
        _defer_drop(sel, None)
    elif key == "del" and sel is not None:
        _pending["asset"] = sel
        open_panel_deferred("NOMAD_PT_asset_delete")
    elif key == "apply":
        defer_op("nomad", "pose_apply", 'EXEC_DEFAULT', flipped=False,
                 use_blend=False)
    elif key == "flip":
        defer_op("nomad", "pose_apply", 'EXEC_DEFAULT', flipped=True,
                 use_blend=False)
    elif key == "blend":
        open_panel_deferred("NOMAD_PT_pose_blend")
    elif key == "new":
        _prepare_new_pose(context)
        defer_op("poselib", "create_pose_asset", 'INVOKE_DEFAULT')
        _watch_new_pose()


def press(context, w, h, mx, my):
    """False | True | 'as_tile' | 'as_scroll'."""
    if not visible:
        return False
    R = _rects(context, w, h)
    if not _in(R["panel"], mx, my):
        return False
    for key, glyph, r in _head_buttons(R):
        if _in(r, mx, my):
            _head_action(key)
            return True
    if not _pose_mode():
        for tkey, label, r in _chip_rects(R):
            if _in(r, mx, my):
                _ui.update(type=tkey, folder="", st=0.0, sg=0.0)
                return True
    if _in(R["lib"], mx, my):
        open_panel_deferred("NOMAD_PT_asset_libs")
        return True

    for key, label, rect, tip, en in _foot_buttons(R):
        if _in(rect, mx, my):
            if en:
                _foot_action(context, key)
            return True

    t = R["tree"]
    if _in(t, mx, my):
        rows = _tree_rows()
        off = _snap(_ui["st"], ROW)
        for i, (path, name, depth, has_child, n) in enumerate(rows):
            ry2 = t[3] - i * ROW + off
            ry1 = ry2 - ROW
            if ry1 < t[1] - 0.5 or ry2 > t[3] + 0.5:
                continue
            if ry1 <= my <= ry2:
                tx = t[0] + 4 + depth * 10
                if has_child and mx <= tx + 14:
                    _ui["fold"] ^= {path}
                else:
                    _ui["folder"] = path
                    _ui["sg"] = 0.0
                return True
        _st.update(mode='scroll_t', last=(mx, my), moved=0.0)
        return 'as_scroll'

    a = _tile_at(R, mx, my)
    _st.update(last=(mx, my), moved=0.0, mouse=(mx, my), inside=True)
    if a is not None:
        _st.update(mode='tile', src=a["key"])
        return 'as_tile'
    _st.update(mode='scroll_g', src=None)
    return 'as_scroll'


def update(context, w, h, mx, my, kind):
    lx, ly = _st["last"]
    dy = my - ly
    _st["last"] = (mx, my)
    _st["mouse"] = (mx, my)
    _st["moved"] += abs(mx - lx) + abs(dy)
    R = _rects(context, w, h)
    _st["inside"] = _in(R["panel"], mx, my)
    mode = _st["mode"]
    if mode == 'scroll_t' and _st["moved"] > 8:
        rows = _tree_rows()
        _ui["st"] = max(0.0, min(_ui["st"] + dy,
                                 _max_scroll(len(rows), ROW, R["tree"])))
    elif mode == 'scroll_g' and _st["moved"] > 8:
        items = [a for a in _all if _match(a)]
        cols, row_h = _grid_layout(R)
        n_rows = math.ceil(len(items) / cols) if items else 0
        _ui["sg"] = max(0.0, min(_ui["sg"] + dy,
                                 _max_scroll(n_rows, row_h, R["grid"])))


def wheel(area, region, mx, my, direction):
    if not visible:
        return False
    context = bpy.context
    w, h = style.region_size(region)
    R = _rects(context, w, h)
    if not _in(R["panel"], mx, my):
        return False
    if _in(R["tree"], mx, my):
        rows = _tree_rows()
        _ui["st"] = max(0.0, min(_ui["st"] - direction * ROW,
                                 _max_scroll(len(rows), ROW, R["tree"])))
    else:
        items = [a for a in _all if _match(a)]
        cols, row_h = _grid_layout(R)
        n_rows = math.ceil(len(items) / cols) if items else 0
        _ui["sg"] = max(0.0, min(_ui["sg"] - direction * row_h,
                                 _max_scroll(n_rows, row_h, R["grid"])))
    return True


def release(context):
    mode, key, moved = _st["mode"], _st["src"], _st["moved"]
    inside, raw = _st["inside"], _st["raw"]
    _st.update(mode=None, src=None)
    if mode != 'tile' or key is None:
        return
    asset = next((a for a in _all if a["key"] == key), None)
    if asset is None:
        return
    if moved <= 10:
        if _pose_mode() and _ui["sel"] == key:
            _foot_action(context, "apply")       # a second tap applies
        _ui["sel"] = key
    elif not inside and not _pose_mode():
        _defer_drop(asset, raw)                  # dropped into the viewport


# ----------------------------------------------------------------------
# Drop into the scene
# ----------------------------------------------------------------------

def _load(asset):
    if not asset["file"]:
        return getattr(bpy.data, asset["attr"]).get(asset["name"])
    with bpy.data.libraries.load(asset["file"], link=False) as (src, dst):
        setattr(dst, asset["attr"], [asset["name"]])
    got = getattr(dst, asset["attr"])
    return got[0] if got else None


def _select(context, obj):
    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj


def _target(context, raw):
    """(location, object under the point). raw = region coords or None."""
    sc = context.scene
    if raw is None:
        return sc.cursor.location.copy(), None
    win, area, region = _view3d_override()
    if area is None:
        return sc.cursor.location.copy(), None
    rv3d = area.spaces.active.region_3d
    view = view3d_utils.region_2d_to_vector_3d(region, rv3d, raw)
    origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, raw)
    try:
        hit, loc, _n, _i, obj, _m = sc.ray_cast(
            context.evaluated_depsgraph_get(), origin, view)
        if hit:
            return loc, obj
    except RuntimeError:
        pass
    return view3d_utils.region_2d_to_location_3d(
        region, rv3d, raw, sc.cursor.location), None


def _do_drop(asset, raw):
    context = bpy.context
    sc = context.scene
    loc, target = _target(context, raw)
    idb = _load(asset)
    if idb is None:
        print(f"NomadUI assets: could not load {asset['name']}")
        return
    kind = asset["kind"]
    coll = context.view_layer.active_layer_collection.collection
    if kind == 'OBJECT':
        obj = idb.copy() if not asset["file"] else idb
        if not asset["file"] and obj.data is not None:
            obj.data = obj.data.copy()
        try:
            obj.asset_clear()
        except (AttributeError, RuntimeError, TypeError):
            pass
        obj.location = loc
        coll.objects.link(obj)
        _select(context, obj)
    elif kind == 'COLLECTION':
        inst = bpy.data.objects.new(idb.name, None)
        inst.instance_type = 'COLLECTION'
        inst.instance_collection = idb
        inst.location = loc
        coll.objects.link(inst)
        _select(context, inst)
    elif kind == 'MATERIAL':
        ob = target or context.active_object
        if ob is not None and hasattr(ob.data, "materials"):
            empty = next((i for i, s in enumerate(ob.material_slots)
                          if s.material is None), None)
            if empty is not None:                 # fill an empty slot
                ob.active_material_index = empty
                ob.active_material = idb
            else:                                 # otherwise a new slot
                ob.data.materials.append(idb)
                ob.active_material_index = len(ob.material_slots) - 1
    elif kind == 'NODETREE':
        ob = target or context.active_object
        if ob is not None and idb.bl_idname == 'GeometryNodeTree':
            ob.modifiers.new(idb.name, 'NODES').node_group = idb
    elif kind == 'WORLD':
        sc.world = idb
    elif kind == 'LIGHT':
        obj = bpy.data.objects.new(idb.name, idb)
        obj.location = loc
        coll.objects.link(obj)
        _select(context, obj)
    try:
        bpy.ops.ed.undo_push(message=f"Add asset {asset['name']}")
    except RuntimeError:
        pass


def _defer_drop(asset, raw):
    def _run():
        try:
            _do_drop(asset, raw)
        except Exception as exc:
            print(f"NomadUI asset drop: {exc!r}")
        return None
    try:
        bpy.app.timers.register(_run, first_interval=0.01)
    except RuntimeError:
        pass


# ----------------------------------------------------------------------
# Delete an asset
# ----------------------------------------------------------------------

def _library_roots():
    out = []
    try:
        for lib in bpy.context.preferences.filepaths.asset_libraries:
            out.append(Path(bpy.path.abspath(lib.path)))
    except (AttributeError, RuntimeError):
        pass
    return out


def delete_check(a):
    """(ok, message): can this asset be deleted, and what will happen."""
    if a["ltype"] == 'LOCAL':
        return True, "Removes the asset from this file."
    if a["ltype"] == 'ESSENTIALS':
        return False, "Essentials assets are read-only."
    path = Path(a["file"])
    if not any(root in path.parents for root in _library_roots()):
        return False, "This file is not inside one of your libraries."
    n = sum(1 for x in _all if x["file"] == a["file"])
    if n > 1:
        return False, (f"This file holds {n} assets. Delete the asset by "
                       f"opening the file in Blender, or remove the file "
                       f"from the file manager.")
    return True, f"Deletes the file {path.name} (it holds only this asset)."


def delete_asset(a):
    ok, msg = delete_check(a)
    if not ok:
        return False, msg
    if a["ltype"] == 'LOCAL':
        coll = getattr(bpy.data, a["attr"], None)
        idb = coll.get(a["name"]) if coll is not None else None
        if idb is None or idb.library is not None:
            return False, "The asset is no longer in this file."
        coll.remove(idb)
    else:
        path = Path(a["file"])
        try:
            path.unlink()
            backup = path.with_suffix(".blend1")
            if backup.exists():
                backup.unlink()
        except OSError as exc:
            return False, f"Could not delete the file: {exc}"
    _all[:] = [x for x in _all if x["key"] != a["key"]]
    _raw.pop(a["key"], None)
    _gpu.pop(a["key"], None)
    if _ui["sel"] == a["key"]:
        _ui["sel"] = None
    return True, "Deleted."


class NOMAD_OT_asset_delete(bpy.types.Operator):
    bl_idname = "nomad.asset_delete"
    bl_label = "Delete Asset"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        a = _pending["asset"]
        if a is None:
            return {'CANCELLED'}
        ok, msg = delete_asset(a)
        _pending["asset"] = None
        self.report({'INFO'} if ok else {'WARNING'}, msg)
        return {'FINISHED'} if ok else {'CANCELLED'}


class NOMAD_PT_asset_delete(bpy.types.Panel):
    bl_label = "Delete Asset"
    bl_idname = "NOMAD_PT_asset_delete"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 13
        a = _pending["asset"]
        if a is None:
            l.label(text="Nothing to delete", icon='INFO')
            return
        ok, msg = delete_check(a)
        l.label(text=a["name"], icon='ASSET_MANAGER')
        l.label(text=f"Library: {a['lib']}")
        col = l.column()
        col.alert = not ok
        for part in [msg[i:i + 46] for i in range(0, len(msg), 46)]:
            col.label(text=part)
        row = l.row(align=True)
        row.scale_y = 1.5
        sub = row.row(align=True)
        sub.enabled = ok
        sub.operator("nomad.asset_delete", text="Delete", icon='TRASH')


# ----------------------------------------------------------------------
# Libraries: select, create, remove
# ----------------------------------------------------------------------

def _save_prefs():
    try:
        if bpy.context.preferences.use_preferences_save:
            bpy.ops.wm.save_userpref()
    except (AttributeError, RuntimeError):
        pass


class NOMAD_OT_asset_lib_select(bpy.types.Operator):
    bl_idname = "nomad.asset_lib_select"
    bl_label = "Select Library"
    bl_options = {'INTERNAL'}

    lib: bpy.props.StringProperty()

    def execute(self, context):
        _ui.update(lib=self.lib, folder="", st=0.0, sg=0.0)
        return {'FINISHED'}


class NOMAD_OT_asset_lib_new(bpy.types.Operator):
    bl_idname = "nomad.asset_lib_new"
    bl_label = "Create Library"
    bl_description = ("Create the folder and register it as an asset "
                      "library")
    bl_options = {'INTERNAL'}

    def execute(self, context):
        wm = context.window_manager
        name = wm.nomad_newlib_name.strip()
        path = bpy.path.abspath(wm.nomad_newlib_dir.strip())
        if not name or not path:
            self.report({'WARNING'}, "Give the library a name and a folder")
            return {'CANCELLED'}
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as exc:
            self.report({'ERROR'}, f"Could not create the folder: {exc}")
            return {'CANCELLED'}
        libs = context.preferences.filepaths.asset_libraries
        try:
            libs.new(name=name, directory=path)
        except (AttributeError, TypeError, RuntimeError):
            try:
                bpy.ops.preferences.asset_library_add(directory=path)
            except RuntimeError as exc:
                self.report({'ERROR'}, f"Could not add the library: {exc}")
                return {'CANCELLED'}
        _save_prefs()
        _ui.update(lib=name, folder="")
        refresh()
        self.report({'INFO'}, f"Library '{name}' created")
        return {'FINISHED'}


class NOMAD_OT_asset_lib_remove(bpy.types.Operator):
    bl_idname = "nomad.asset_lib_remove"
    bl_label = "Remove Library"
    bl_description = "Remove the library from the list (files stay on disk)"
    bl_options = {'INTERNAL'}

    name: bpy.props.StringProperty()

    def execute(self, context):
        libs = context.preferences.filepaths.asset_libraries
        lib = libs.get(self.name)
        if lib is None:
            return {'CANCELLED'}
        libs.remove(lib)
        _save_prefs()
        if _ui["lib"] == self.name:
            _ui["lib"] = "ALL"
        refresh()
        return {'FINISHED'}


# ----------------------------------------------------------------------
# Libraries and catalogs: shared by the asset browser, the pose library
# and the brush popups
# ----------------------------------------------------------------------

_CATS = "blender_assets.cats.txt"
_CATS_HEAD = (
    "# This is an Asset Catalog Definition file for Blender.\n#\n"
    "# Empty lines and lines starting with `#` will be ignored.\n"
    "# The first non-ignored line should be the version indicator.\n"
    "# Other lines are of the format "
    "\"UUID:catalog/path/for/assets:simple catalog name\"\n\nVERSION 1\n\n")
_keep = {}              # enum item lists must stay alive (Blender keeps refs)


def _stable(tag, items):
    _keep[tag] = items
    return items


def _lib_root(name):
    if name == "Current File":
        return Path(bpy.data.filepath).parent if bpy.data.filepath else None
    lib = bpy.context.preferences.filepaths.asset_libraries.get(name)
    return Path(bpy.path.abspath(lib.path)) if lib is not None else None


def _writable_libs():
    out = ["Current File"] if bpy.data.filepath else []
    out += [lib.name for lib in bpy.context.preferences.filepaths.asset_libraries]
    return out


def _cat_entries(root):
    """[(uuid, path)] from the library's catalog file."""
    try:
        lines = (root / _CATS).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#") or ln.startswith("VERSION"):
            continue
        parts = ln.split(":", 2)
        if len(parts) == 3:
            out.append((parts[0], parts[1]))
    return out


def _cat_paths(lib_name):
    root = _lib_root(lib_name)
    if root is None:
        return []
    return sorted({p for _u, p in _cat_entries(root)}, key=str.casefold)


def _catlib_items(self, context):
    names = _writable_libs()
    return _stable("catlib", [(n, n, "") for n in names]
                   or [("NONE", "Save the file first", "")])


def _catparent_items(self, context):
    items = [("/", "(Top level)", "Create it at the top level")]
    for p in _cat_paths(context.window_manager.nomad_newcat_lib):
        items.append((p, p, ""))
    return _stable("catparent", items)


def _delcat_items(self, context):
    paths = _cat_paths(context.window_manager.nomad_newcat_lib)
    return _stable("delcat", [(p, p, "") for p in paths]
                   or [("NONE", "No catalogs in this library", "")])


class NOMAD_OT_asset_cat_new(bpy.types.Operator):
    bl_idname = "nomad.asset_cat_new"
    bl_label = "Create Catalog"
    bl_description = "Create an asset catalog (folder) in the chosen library"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        wm = context.window_manager
        root = _lib_root(wm.nomad_newcat_lib)
        name = wm.nomad_newcat_name.strip().strip("/").replace(":", "-")
        if root is None or not name:
            self.report({'WARNING'}, "Choose a library and give the "
                                     "catalog a name")
            return {'CANCELLED'}
        parent = wm.nomad_newcat_parent
        path = name if parent in ("/", "") else f"{parent}/{name}"
        if path in {p for _u, p in _cat_entries(root)}:
            self.report({'INFO'}, f"'{path}' already exists")
            return {'CANCELLED'}
        try:
            root.mkdir(parents=True, exist_ok=True)
            f = root / _CATS
            fresh = not f.exists()
            with open(f, "a", encoding="utf-8") as fh:
                if fresh:
                    fh.write(_CATS_HEAD)
                fh.write(f"{uuid.uuid4()}:{path}:{path.replace('/', '-')}\n")
        except OSError as exc:
            self.report({'ERROR'}, f"Could not write the catalog: {exc}")
            return {'CANCELLED'}
        try:
            bpy.ops.asset.library_refresh()
        except (RuntimeError, AttributeError):
            pass
        wm.nomad_newcat_name = ""
        refresh()
        self.report({'INFO'}, f"Catalog '{path}' created")
        return {'FINISHED'}


class NOMAD_OT_asset_cat_delete(bpy.types.Operator):
    bl_idname = "nomad.asset_cat_delete"
    bl_label = "Delete Catalog"
    bl_description = ("Delete the catalog and its sub-catalogs (the assets "
                      "stay, they just become unassigned)")
    bl_options = {'INTERNAL'}

    def execute(self, context):
        wm = context.window_manager
        root = _lib_root(wm.nomad_newcat_lib)
        path = wm.nomad_delcat
        if root is None or path in ("", "NONE"):
            return {'CANCELLED'}
        f = root / _CATS
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
            keep = []
            for ln in lines:
                parts = ln.strip().split(":", 2)
                p = parts[1] if len(parts) == 3 and not ln.startswith("#") else None
                if p is not None and (p == path or p.startswith(path + "/")):
                    continue
                keep.append(ln)
            f.write_text("\n".join(keep) + "\n", encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            self.report({'ERROR'}, f"Could not edit the catalogs: {exc}")
            return {'CANCELLED'}
        try:
            bpy.ops.asset.library_refresh()
        except (RuntimeError, AttributeError):
            pass
        refresh()
        self.report({'INFO'}, f"Catalog '{path}' deleted")
        return {'FINISHED'}


def _section(layout, idname, text):
    """A collapsible dropdown (Blender 4.2+); a flat block as fallback."""
    if hasattr(layout, "panel"):
        header, body = layout.panel(idname, default_closed=True)
        header.label(text=text)
        return body
    layout.label(text=text)
    return layout


def draw_manage(l, context):
    """New Library / Catalogs dropdowns. Used by the library popup of the
    asset browser and the pose library, and by the brush popup."""
    wm = context.window_manager
    body = _section(l, "nomad_man_lib", "New Library")
    if body is not None:
        body.prop(wm, "nomad_newlib_name", text="Name")
        body.prop(wm, "nomad_newlib_dir", text="Folder")
        row = body.row()
        row.scale_y = 1.3
        row.operator("nomad.asset_lib_new", text="Create Library",
                     icon='ADD')
        user = list(context.preferences.filepaths.asset_libraries)
        if user:
            body.label(text="Delete library (files stay on disk)")
            col = body.column(align=True)
            for lib in user:
                op = col.operator("nomad.asset_lib_remove", text=lib.name,
                                  icon='TRASH')
                op.name = lib.name
    body = _section(l, "nomad_man_cat", "Catalogs")
    if body is not None:
        body.prop(wm, "nomad_newcat_lib", text="Library")
        body.prop(wm, "nomad_newcat_parent", text="Folder")
        body.prop(wm, "nomad_newcat_name", text="Name")
        row = body.row()
        row.scale_y = 1.3
        row.operator("nomad.asset_cat_new", text="Create Catalog", icon='ADD')
        body.separator()
        body.prop(wm, "nomad_delcat", text="")
        row = body.row()
        row.scale_y = 1.3
        row.operator("nomad.asset_cat_delete", text="Delete Catalog",
                     icon='TRASH')


class NOMAD_PT_asset_libs(bpy.types.Panel):
    bl_label = "Libraries"
    bl_idname = "NOMAD_PT_asset_libs"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 13
        wm = context.window_manager
        l.label(text="Library")
        col = l.column(align=True)
        col.scale_y = 1.3
        for lib in _libs():
            name = "All Libraries" if lib == "ALL" else lib
            icon = ('ASSET_MANAGER' if lib == "ALL" else
                    'FILE_BLEND' if lib == "Current File" else
                    'PACKAGE' if lib == "Essentials" else 'FILE_FOLDER')
            op = col.operator("nomad.asset_lib_select", text=name,
                              icon=icon, depress=(_ui["lib"] == lib))
            op.lib = lib

        l.separator()
        draw_manage(l, context)


CLASSES = (NOMAD_OT_asset_delete, NOMAD_PT_asset_delete,
           NOMAD_OT_asset_lib_select, NOMAD_OT_asset_lib_new,
           NOMAD_OT_asset_lib_remove, NOMAD_OT_asset_cat_new,
           NOMAD_OT_asset_cat_delete, NOMAD_PT_asset_libs)


def register():
    wm = bpy.types.WindowManager
    wm.nomad_newlib_name = bpy.props.StringProperty(
        name="Name", default="My Library", options={'SKIP_SAVE'})
    wm.nomad_newlib_dir = bpy.props.StringProperty(
        name="Folder", default="", subtype='DIR_PATH',
        options={'SKIP_SAVE'})
    wm.nomad_newcat_name = bpy.props.StringProperty(
        name="Name", default="", options={'SKIP_SAVE'})
    wm.nomad_newcat_lib = bpy.props.EnumProperty(
        name="Library", items=_catlib_items, options={'SKIP_SAVE'})
    wm.nomad_newcat_parent = bpy.props.EnumProperty(
        name="Folder", items=_catparent_items, options={'SKIP_SAVE'})
    wm.nomad_delcat = bpy.props.EnumProperty(
        name="Catalog", items=_delcat_items, options={'SKIP_SAVE'})
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    global visible
    visible = False
    _scan["queue"] = []
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    for name in ("nomad_newlib_name", "nomad_newlib_dir",
                 "nomad_newcat_name", "nomad_newcat_lib",
                 "nomad_newcat_parent", "nomad_delcat"):
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)