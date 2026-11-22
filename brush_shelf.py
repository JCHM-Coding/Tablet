# Brush picker for NomadUI.
# Every asset library is scanned once (Current File, Essentials, user
# libraries). A brush belongs to a mode through its CATALOG path
# (Brushes/<mode folder>/...), so custom sub-folders show up. Without a
# catalog, the brush flags decide. Explorer: library dropdown > folders.
import hashlib
import json
import os
from pathlib import Path

import bpy

TAG = "nomad_shelf"          # ID property on the temporary brushes we load
FAV = "FAV"                  # id of the favorites item in the library menu
SCALE = 5.0                  # big preview
SCALE_POPUP = 3.2            # thumbnails in the popup grid

# mode -> (brush flags, Essentials file stems, tool_settings attr)
MODES = {
    'SCULPT': (("use_paint_sculpt",),
               ("essentials_brushes-mesh_sculpt",), "sculpt"),
    'PAINT_TEXTURE': (("use_paint_image",),
                      ("essentials_brushes-mesh_texture",), "image_paint"),
    'PAINT_VERTEX': (("use_paint_vertex",),
                     ("essentials_brushes-mesh_vertex",), "vertex_paint"),
    'PAINT_WEIGHT': (("use_paint_weight",),
                     ("essentials_brushes-mesh_weight",), "weight_paint"),
    'PAINT_GREASE_PENCIL': (("use_paint_grease_pencil",
                             "use_paint_gpencil"),
                            ("essentials_brushes-gp_draw",),
                            "gpencil_paint"),
    'VERTEX_GREASE_PENCIL': (("use_vertex_grease_pencil",),
                             ("essentials_brushes-gp_vertex",
                              "essentials_brushes-gp_vertex_paint"),
                             "gpencil_vertex_paint"),
    'SCULPT_GREASE_PENCIL': (("use_sculpt_grease_pencil",),
                             ("essentials_brushes-gp_sculpt",
                              "essentials_brushes-gp_sculpt_paint"),
                             "gpencil_sculpt_paint"),
    'WEIGHT_GREASE_PENCIL': (("use_weight_grease_pencil",),
                             ("essentials_brushes-gp_weight",
                              "essentials_brushes-gp_weight_paint"),
                             "gpencil_weight_paint"),
}

# Catalog folder (under "Brushes") of each mode
MODE_FOLDER = {
    'SCULPT': "Mesh Sculpt",
    'PAINT_TEXTURE': "Mesh Texture Paint",
    'PAINT_VERTEX': "Mesh Vertex Paint",
    'PAINT_WEIGHT': "Mesh Weight Paint",
    'PAINT_GREASE_PENCIL': "Grease Pencil Draw",
    'VERTEX_GREASE_PENCIL': "Grease Pencil Paint",
    'SCULPT_GREASE_PENCIL': "Grease Pencil Sculpt",
    'WEIGHT_GREASE_PENCIL': "Grease Pencil Weight Paint",
}
_MODE_FOLDERS = {f.casefold() for f in MODE_FOLDER.values()} | {
    "curve sculpt"}

_TYPE_ATTRS = {
    'SCULPT': ("sculpt_brush_type", "sculpt_tool"),
    'PAINT_GREASE_PENCIL': ("gpencil_brush_type", "gpencil_tool"),
    'PAINT_TEXTURE': ("image_brush_type", "image_tool"),
    'PAINT_VERTEX': ("vertex_brush_type", "vertex_tool"),
    'PAINT_WEIGHT': ("weight_brush_type", "weight_tool"),
    'VERTEX_GREASE_PENCIL': ("gpencil_vertex_brush_type",
                             "gpencil_vertex_tool"),
    'SCULPT_GREASE_PENCIL': ("gpencil_sculpt_brush_type",
                             "gpencil_sculpt_tool"),
    'WEIGHT_GREASE_PENCIL': ("gpencil_weight_brush_type",
                             "gpencil_weight_tool"),
}
_KIND_NAMES = {
    "ERASE": ("eras",), "FILL": ("fill",),
    "DRAW": ("draw", "pencil", "pen", "paint", "airbrush"),
    "SOFTEN": ("soften", "blur"), "BLUR": ("blur", "soften"),
    "SMEAR": ("smear",), "AVERAGE": ("average",),
    "CLONE": ("clone",), "MASK": ("mask",), "REPLACE": ("replace",),
}

_all = None                  # every brush of every library (all modes)
_cache = {}                  # mode -> entries (with 'rel_path', 'btype')
_favs = None
_scan_log = []
_last_kind = {}
_pending = set()


# ----------------------------------------------------------------------
# Favorites (same file and keys as the old asset_shelf.py)
# ----------------------------------------------------------------------

def _fav_path():
    try:
        d = bpy.utils.user_resource(
            'CONFIG', path="touchscreen_asset_shelf", create=True)
        if d:
            return Path(d) / "favorites.json"
    except (AttributeError, RuntimeError, TypeError):
        pass
    return Path.home() / ".touchscreen_asset_shelf_favorites.json"


def favs():
    global _favs
    if _favs is None:
        _favs = set()
        try:
            data = json.loads(_fav_path().read_text(encoding="utf-8"))
            _favs = {str(v) for v in data.get("favorites", []) if v}
        except (OSError, ValueError, AttributeError, TypeError):
            pass
    return _favs


def save_favs():
    try:
        p = _fav_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"version": 1,
                                 "favorites": sorted(favs())},
                                ensure_ascii=False, indent=2),
                     encoding="utf-8")
    except (OSError, TypeError, ValueError):
        pass


def fav_key(e):
    return json.dumps([e["type"], e["lib_id"], e["rel"]],
                      ensure_ascii=False, separators=(",", ":"))


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _norm(p):
    return os.path.normcase(os.path.normpath(p)) if p else ""


def active_brush(context):
    info = MODES.get(context.mode)
    if info is None:
        return None
    try:
        return getattr(context.tool_settings, info[2]).brush
    except (AttributeError, RuntimeError):
        return None


def _active_key(context):
    """(name, library file) of the active brush, to highlight its tile."""
    b = active_brush(context)
    if b is None:
        return None
    path = ""
    try:
        if b.library is not None:
            path = _norm(bpy.path.abspath(b.library.filepath))
    except (AttributeError, ReferenceError, RuntimeError):
        pass
    return (b.name, path)


def _brush_named(key):
    try:
        return bpy.data.brushes.get(key)
    except (TypeError, KeyError):
        return bpy.data.brushes.get(key[0])


def _icon(e):
    b = _brush_named(e["local"])
    if b is None:
        return 0
    try:
        return b.preview.icon_id if b.preview else 0
    except (AttributeError, ReferenceError, RuntimeError):
        return 0


def _supports(brush, flag):
    flags = (flag,) if isinstance(flag, str) else tuple(flag)
    try:
        return any(bool(getattr(brush, f, False)) for f in flags)
    except (ReferenceError, RuntimeError):
        return False


def _brush_type(brush, mode=None):
    attrs = _TYPE_ATTRS.get(mode, ("gpencil_brush_type", "image_brush_type"))
    for attr in attrs:
        v = getattr(brush, attr, None)
        if isinstance(v, str):
            return v
    return ""


def _entry(name, local, kind, lib_id, rel, lib, blend, path, btypes,
           flag_modes):
    return {"name": name, "local": local, "type": kind, "lib_id": lib_id,
            "rel": rel, "lib": lib, "file": blend, "fnorm": _norm(blend),
            "path": path, "btypes": btypes, "flag_modes": flag_modes}


# ----------------------------------------------------------------------
# Scanning
# ----------------------------------------------------------------------

def _parse_cats(f, cats):
    try:
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if (not line or line.startswith("#")
                    or line.upper().startswith("VERSION")):
                continue
            parts = line.split(":", 2)
            if len(parts) == 3 and parts[0].strip():
                cats[parts[0].strip().casefold()] = \
                    parts[1].strip().strip("/")
    except (OSError, UnicodeError):
        pass


def _read_cats(root):
    """uuid (casefold) -> catalog path, from every cats file under root."""
    cats = {}
    for f in Path(root).rglob("blender_assets.cats.txt"):
        _parse_cats(f, cats)
    return cats


def _cat_path(brush, cats):
    try:
        return cats.get(str(brush.asset_data.catalog_id).casefold(), "")
    except (AttributeError, ReferenceError, RuntimeError):
        return ""


def _linked_brush(name, blend):
    """Brush already linked from this very file (Blender skips
    re-appending those and may return None for them)."""
    target = _norm(str(blend))
    for b in bpy.data.brushes:
        try:
            if (b.library is not None and b.name == name
                    and _norm(bpy.path.abspath(b.library.filepath))
                    == target):
                return b
        except (ReferenceError, RuntimeError):
            pass
    return None


def _purge(context):
    """Remove the temporary brushes this module loaded (never the active
    one, never user brushes)."""
    active = active_brush(context)
    for b in list(bpy.data.brushes):
        try:
            if b.get(TAG) is None or b == active:
                continue
            bpy.data.brushes.remove(b, do_unlink=True)
        except (ReferenceError, RuntimeError, TypeError):
            pass


def purge_all():
    _purge(bpy.context)


def _modes_of(brush, blend):
    out = set()
    stem = blend.stem.casefold() if blend else ""
    for mode, (flags, stems, _attr) in MODES.items():
        if _supports(brush, flags) or stem in [s.casefold()
                                               for s in stems]:
            out.add(mode)
    return out


def _scan_file(found, blend, root, kind, lib_id, lib_label, cats):
    try:
        with bpy.data.libraries.load(str(blend),
                                     assets_only=True) as (src, dst):
            names = [str(getattr(i, "name", i)) for i in src.brushes]
            dst.brushes = list(names)   # Blender mutates this list in place
    except Exception as exc:
        print(f"NomadUI shelf: {blend.name}: {exc}")
        return
    rel_file = os.path.relpath(str(blend), str(root)).replace("\\", "/")
    loaded = list(dst.brushes)
    kept = 0
    for name, brush in zip(names, loaded):
        try:
            if brush is None:
                brush = _linked_brush(name, blend)
            if brush is None:
                continue
            linked = brush.library is not None   # read-only, don't touch
            path = _cat_path(brush, cats)
            btypes = {m: _brush_type(brush, m) for m in MODES}
            flag_modes = _modes_of(brush, blend)
            ikey = (brush.name,
                    brush.library.filepath if linked else None)
            found.append(_entry(
                name, ikey, kind, lib_id, f"{rel_file}/Brush/{name}",
                lib_label, str(blend), path, btypes, flag_modes))
            kept += 1
            if not linked:
                brush[TAG] = 1
                try:
                    # not an asset in this file: Blender's own browser
                    # must not list the temporary copy
                    brush.asset_clear()
                except (AttributeError, RuntimeError, TypeError):
                    pass
        except (ReferenceError, RuntimeError, TypeError):
            pass
    _scan_log.append((blend.name, kept))


def scan_all(context):
    global _all
    _purge(context)
    _scan_log.clear()
    found = []

    # Brushes saved in this .blend
    cats_local = {}
    if bpy.data.filepath:
        f = Path(bpy.data.filepath).parent / "blender_assets.cats.txt"
        if f.is_file():
            _parse_cats(f, cats_local)
    for b in bpy.data.brushes:
        try:
            if (b.library is None and b.asset_data is not None
                    and b.get(TAG) is None):
                found.append(_entry(
                    b.name, (b.name, None), 'LOCAL', "",
                    f"Brush/{b.name}", "Current File", "",
                    _cat_path(b, cats_local),
                    {m: _brush_type(b, m) for m in MODES},
                    _modes_of(b, None)))
        except (ReferenceError, RuntimeError):
            pass

    # User asset libraries
    try:
        libs = list(context.preferences.filepaths.asset_libraries)
    except (AttributeError, RuntimeError):
        libs = []
    for lib in libs:
        try:
            root = Path(bpy.path.abspath(lib.path))
            if not root.is_dir():
                continue
            cats = _read_cats(root)
            for blend in sorted(root.rglob("*.blend")):
                _scan_file(found, blend, root, 'CUSTOM', lib.name,
                           lib.name, cats)
        except Exception as exc:
            print(f"NomadUI shelf: library {lib.name}: {exc}")

    # Blender Essentials
    try:
        assets = Path(bpy.utils.system_resource('DATAFILES')) / "assets"
        if (assets / "brushes").is_dir():
            cats = _read_cats(assets)
            for blend in sorted((assets / "brushes").rglob("*.blend")):
                _scan_file(found, blend, assets, 'ESSENTIALS', "",
                           "Essentials", cats)
    except Exception as exc:
        print(f"NomadUI shelf: essentials: {exc}")

    unique = {}
    for e in found:
        unique.setdefault((e["type"], e["lib_id"], e["rel"]), e)
    _all = sorted(unique.values(),
                  key=lambda e: (e["lib"].casefold(), e["path"].casefold(),
                                 e["name"].casefold()))
    _cache.clear()
    print(f"NomadUI shelf: {len(_all)} brushes. Files: {dict(_scan_log)}")
    if _all and all(_icon(e) == 0 for e in _all[:5]):
        print("NomadUI shelf: previews not available (the thumbnails "
              "may have been lost when clearing the asset data)")


def _mode_rel(e, mode):
    """Folder of the brush inside the mode's folder, or None if the
    brush doesn't belong to the mode."""
    parts = [p for p in e["path"].split("/") if p]
    if parts and parts[0].casefold() == "brushes":
        parts = parts[1:]
    if parts and parts[0].casefold() in _MODE_FOLDERS:
        if parts[0].casefold() == MODE_FOLDER[mode].casefold():
            return "/".join(parts[1:])
        return None
    if mode in e["flag_modes"]:         # no mode folder: trust the flags
        return "/".join(parts)
    return None


def _mode_entries(mode):
    out = []
    for e in _all or ():
        rel = _mode_rel(e, mode)
        if rel is None:
            continue
        c = dict(e)
        c["rel_path"] = rel
        c["btype"] = e["btypes"].get(mode, "")
        out.append(c)
    return out


def _stale():
    if _all is None:
        return True
    for e in _all[:4]:
        key = e["local"]
        if (e["type"] != 'LOCAL' and key[1] is None
                and _brush_named(key) is None):
            return True
    return False


def scan(context, mode, force=False):
    if force or _stale():
        scan_all(context)
    _cache[mode] = _mode_entries(mode)
    print(f"NomadUI shelf [{mode}]: {len(_cache[mode])} brushes")


def ensure(context, mode):
    if mode in MODES and (_all is None or _stale() or mode not in _cache):
        scan(context, mode)


def ensure_async(mode):
    """Scan from a timer (never inside a draw callback)."""
    if mode in _pending:
        return
    _pending.add(mode)

    def _run():
        try:
            ensure(bpy.context, mode)
        except Exception as exc:
            print(f"NomadUI shelf scan: {exc!r}")
        _pending.discard(mode)
        return None
    try:
        bpy.app.timers.register(_run, first_interval=0.05)
    except RuntimeError:
        _pending.discard(mode)


def favorite_entries(mode):
    entries = _cache.get(mode)
    if entries is None:
        return None
    fv = favs()
    return [e for e in entries if fav_key(e) in fv]


# ----------------------------------------------------------------------
# Brush kinds (Erase / Fill / Blur / ... as brush assets)
# ----------------------------------------------------------------------

def _activate(e):
    try:
        bpy.ops.brush.asset_activate(
            'EXEC_DEFAULT', asset_library_type=e["type"],
            asset_library_identifier=e["lib_id"],
            relative_asset_identifier=e["rel"], use_toggle=False)
    except Exception as exc:
        print(f"NomadUI activate: {exc}")
        return
    _record_kind(e)


def _record_kind(e):
    t = e.get("btype")
    if t:
        _last_kind[(bpy.context.mode, t)] = e["rel"]


def find_entry(mode, kind):
    """Brush asset of a kind, preferring the one used last."""
    entries = _cache.get(mode) or []
    of_kind = [e for e in entries if e.get("btype") == kind]
    if not of_kind:
        words = _KIND_NAMES.get(kind, ())
        of_kind = [e for e in entries
                   if any(w in e["name"].casefold() for w in words)]
    last = _last_kind.get((mode, kind))
    for e in of_kind:
        if e["rel"] == last:
            return e
    return of_kind[0] if of_kind else None


def is_kind(context, kind):
    b = active_brush(context)
    if b is None:
        return False
    t = _brush_type(b, context.mode)
    if t:
        return t == kind
    return any(w in b.name.casefold() for w in _KIND_NAMES.get(kind, ()))


def activate_kind(kind):
    """Scan if needed, then activate a brush of that kind."""
    from .sculpt_popups import _view3d_override

    def _run():
        try:
            C = bpy.context
            mode = C.mode
            ensure(C, mode)
            e = find_entry(mode, kind)
            if e is None:
                print(f"NomadUI: no {kind} brush found. Brushes: "
                      f"{[(x['name'], x['btype']) for x in _cache.get(mode, [])]}")
                return None
            win, area, region = _view3d_override()
            if area is None:
                return None
            with C.temp_override(window=win, area=area, region=region):
                _activate(e)
        except Exception as exc:
            print(f"NomadUI activate_kind {kind}: {exc!r}")
        return None
    try:
        bpy.app.timers.register(_run, first_interval=0.01)
    except RuntimeError:
        pass


# ----------------------------------------------------------------------
# Explorer model: library dropdown > folders > brushes
# ----------------------------------------------------------------------

def _listing(entries, lib, p, query):
    """-> (subfolders [(label, path, count)], brushes [entry])."""
    q = query.strip().casefold()
    fv = favs()
    if lib == FAV:
        scope = [e for e in entries if fav_key(e) in fv]
        if q:
            scope = [e for e in scope if q in e["name"].casefold()]
        return [], scope

    scope = [e for e in entries
             if lib in ("ALL", e["lib"]) and (
                 not p or e["rel_path"] == p
                 or e["rel_path"].startswith(p + "/"))]
    if q:
        return [], [e for e in scope if q in e["name"].casefold()]

    counts = {}
    for e in scope:
        rest = e["rel_path"][len(p):].lstrip("/")
        if rest:
            first = rest.split("/", 1)[0]
            counts[first] = counts.get(first, 0) + 1
    folders = [(name, f"{p + '/' if p else ''}{name}", counts[name])
               for name in sorted(counts, key=str.casefold)]
    return folders, scope


def _up(path):
    return path.rsplit("/", 1)[0] if "/" in path else ""


# ----------------------------------------------------------------------
# Operators
# ----------------------------------------------------------------------

class NOMAD_OT_brush_activate(bpy.types.Operator):
    bl_idname = "nomad.brush_activate"
    bl_label = "Activate Brush"
    bl_description = "Make this brush the active one"
    bl_options = {'INTERNAL'}

    lib_type: bpy.props.StringProperty()
    lib_id: bpy.props.StringProperty()
    rel: bpy.props.StringProperty()

    def execute(self, context):
        try:
            res = bpy.ops.brush.asset_activate(
                'EXEC_DEFAULT',
                asset_library_type=self.lib_type,
                asset_library_identifier=self.lib_id,
                relative_asset_identifier=self.rel,
                use_toggle=False)
        except Exception as exc:
            self.report({'WARNING'}, f"Activate failed: {exc}")
            return {'CANCELLED'}
        if 'FINISHED' not in res:
            return {'CANCELLED'}
        e = next((x for x in _cache.get(context.mode, ())
                  if x["rel"] == self.rel), None)
        if e is not None:
            _record_kind(e)
        return {'FINISHED'}


class NOMAD_OT_brush_fav(bpy.types.Operator):
    bl_idname = "nomad.brush_fav"
    bl_label = "Toggle Favorite"
    bl_description = "Add or remove this brush from the favorites"
    bl_options = {'INTERNAL'}

    lib_type: bpy.props.StringProperty()
    lib_id: bpy.props.StringProperty()
    rel: bpy.props.StringProperty()

    def execute(self, context):
        key = fav_key({"type": self.lib_type, "lib_id": self.lib_id,
                       "rel": self.rel})
        fv = favs()
        if key in fv:
            fv.discard(key)
        else:
            fv.add(key)
        save_favs()
        return {'FINISHED'}


class NOMAD_OT_shelf_nav(bpy.types.Operator):
    bl_idname = "nomad.shelf_nav"
    bl_label = "Open Folder"
    bl_description = "Open this folder"
    bl_options = {'INTERNAL'}

    path: bpy.props.StringProperty()

    def execute(self, context):
        context.window_manager.nomad_shelf_path = self.path
        return {'FINISHED'}


class NOMAD_OT_shelf_refresh(bpy.types.Operator):
    bl_idname = "nomad.shelf_refresh"
    bl_label = "Refresh Libraries"
    bl_description = "Scan the asset libraries again"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        if context.mode in MODES:
            scan(context, context.mode, force=True)
        return {'FINISHED'}


class NOMAD_OT_shelf_clean(bpy.types.Operator):
    bl_idname = "nomad.shelf_clean"
    bl_label = "Clean Temporary Brushes"
    bl_description = ("Delete the temporary brush copies this addon "
                      "loaded into the file")
    bl_options = {'INTERNAL'}

    def execute(self, context):
        before = len(bpy.data.brushes)
        _purge(context)
        self.report({'INFO'},
                    f"Removed {before - len(bpy.data.brushes)} brushes")
        return {'FINISHED'}


# ----------------------------------------------------------------------
# Asset-style icon views (preview with the name below)
# ----------------------------------------------------------------------

_enum = {"fav": ([], {}), "shelf": ([], {})}   # (items kept alive, id -> entry)
_last = {"fav": 0, "shelf": 0}
_lib_store = []
_item_cache = {}     # key -> (signature, items list)
_graveyard = []      # replaced lists, kept alive so Blender never reads
                     # freed strings from a dynamic enum


def _stable(key, out):
    sig = tuple((i[0], i[1], i[3], i[4]) for i in out)
    old = _item_cache.get(key)
    if old is not None and old[0] == sig:
        return old[1]
    if old is not None:
        _graveyard.append(old[1])
        del _graveyard[:-200]
    _item_cache[key] = (sig, out)
    return out



def _make_get(kind):
    """The preview follows the active brush (no writes inside draw)."""
    def get(self):
        items, mp = _enum[kind]
        ak = _active_key(bpy.context)
        if ak is not None:
            for ident, _n, _d, _i, num in items:
                e = mp.get(ident)
                if e is not None and (e["name"], e["fnorm"]) == ak:
                    return num
        return _last[kind] if _last[kind] < len(items) else 0
    return get


def _make_set(kind):
    def set_(self, value):
        items, mp = _enum[kind]
        for ident, _n, _d, _i, num in items:
            if num == value:
                e = mp.get(ident)
                if e is not None:
                    _last[kind] = num
                    _activate(e)
                return
    return set_


def current_path(wm):
    p = getattr(wm, "nomad_shelf_folder", "/")
    return "" if p in ("/", "") else p


def _visible_entries(kind, wm, mode):
    entries = _cache.get(mode) or []
    if kind == "fav":
        fv = favs()
        return [e for e in entries if fav_key(e) in fv]
    return _listing(entries, wm.nomad_shelf_lib, current_path(wm),
                    wm.nomad_shelf_search)[1]


def _make_items(kind):
    def items(self, context):
        try:
            ctx = context or bpy.context
            lst = _visible_entries(kind, ctx.window_manager, ctx.mode)
        except Exception:
            lst = []
        out, mp = [], {}
        for i, e in enumerate(lst):
            ident = "B" + hashlib.sha1(
                fav_key(e).encode("utf-8")).hexdigest()[:16]
            out.append((ident, e["name"], e["name"],
                        _icon(e) or 'BRUSH_DATA', i))
            mp[ident] = e
        if not out:
            out = [("NONE", "No brushes", "", 'INFO', 0)]
        out = _stable(kind, out)
        _enum[kind] = (out, mp)
        return out
    return items


def _lib_items(self, context):
    mode = (context or bpy.context).mode
    labs = sorted({e["lib"] for e in (_cache.get(mode) or [])},
                  key=str.casefold)
    first = [l for l in ("Current File", "Essentials") if l in labs]
    order = first + [l for l in labs if l not in first]
    items = [("ALL", "All Libraries", "", 'ASSET_MANAGER', 0)]
    for i, lab in enumerate(order, 1):
        icon = 'FILE_BLEND' if lab == "Current File" else (
            'PACKAGE' if lab == "Essentials" else 'FILE_FOLDER')
        items.append((lab, lab, "", icon, i))
    items.append((FAV, "★ Favorites", "", 'SOLO_ON', len(items)))
    return _stable("lib", items)


def _folder_items(self, context):
    ctx = context or bpy.context
    wm = ctx.window_manager
    entries = _cache.get(ctx.mode) or []
    lib = wm.nomad_shelf_lib or "ALL"
    counts = {}
    for e in entries:
        if lib not in ("ALL", e["lib"]):
            continue
        parts = [p for p in e["rel_path"].split("/") if p]
        for i in range(1, len(parts) + 1):
            key = "/".join(parts[:i])
            counts[key] = counts.get(key, 0) + 1
    items = [("/", "All Folders", "", 'FILE_FOLDER', 0)]
    for i, path in enumerate(sorted(counts, key=str.casefold), 1):
        depth = path.count("/")
        name = path.rsplit("/", 1)[-1]
        items.append((path, f"{'    ' * depth}{name}  ({counts[path]})",
                      path, 'FILE_FOLDER', i))
    return _stable("folder", items)


def _lib_update(self, context):
    try:
        self.nomad_shelf_folder = "/"
    except (TypeError, ValueError, AttributeError):
        pass


def _icon_view(layout, wm, prop):
    layout.template_icon_view(wm, prop, show_labels=wm.nomad_shelf_names,
                              scale=SCALE, scale_popup=SCALE_POPUP)


def _active_entry(context, entries):
    ak = _active_key(context)
    if ak is None:
        return None
    return next((e for e in entries
                 if (e["name"], e["fnorm"]) == ak), None)


class NOMAD_PT_brushes(bpy.types.Panel):
    bl_label = "Brushes"
    bl_idname = "NOMAD_PT_brushes"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        if context.mode not in MODES:
            l.label(text="Brushes: sculpt and paint modes only",
                    icon='INFO')
            return
        wm = context.window_manager
        l.prop(wm, "nomad_shelf_search", text="", icon='VIEWZOOM')
        row = l.row(align=True)
        row.prop(wm, "nomad_shelf_names", text="Names", icon='FONT_DATA',
                 toggle=True)
        row.operator("nomad.shelf_refresh", text="", icon='FILE_REFRESH')
        row.operator("nomad.shelf_clean", text="", icon='TRASH')

        from . import asset_gpu
        entries = _cache.get(context.mode)
        if entries is None:
            l.label(text="Press refresh to load brushes", icon='INFO')
            asset_gpu.draw_manage(l, context)
            return

        l.prop(wm, "nomad_shelf_lib", text="")           # library dropdown
        if wm.nomad_shelf_lib != FAV:
            l.prop(wm, "nomad_shelf_folder", text="")    # folder dropdown

        items = _visible_entries("shelf", wm, context.mode)
        if items:
            _icon_view(l, wm, "nomad_shelf_choice")
        else:
            l.label(text="No brushes here", icon='INFO')

        active = active_brush(context)
        if active is not None:
            l.label(text=f"Active: {active.name}", icon='BRUSH_DATA')
        entry = _active_entry(context, entries)
        if entry is not None:
            in_favs = fav_key(entry) in favs()
            op = l.operator(
                "nomad.brush_fav",
                text="Remove from Favorites" if in_favs
                else "Add to Favorites",
                icon='REMOVE' if in_favs else 'ADD')
            op.lib_type = entry["type"]
            op.lib_id = entry["lib_id"]
            op.rel = entry["rel"]
        l.label(text=f"{len(entries)} brushes", icon='BRUSH_DATA')
        asset_gpu.draw_manage(l, context)


class NOMAD_PT_favorites(bpy.types.Panel):
    """Toolbar favorites: pick only, no removing from here."""
    bl_label = "Favorite Brushes"
    bl_idname = "NOMAD_PT_favorites"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 12
        entries = _cache.get(context.mode)
        if entries is None:
            l.label(text="Open Brushes once to load the libraries",
                    icon='INFO')
            return
        wm = context.window_manager
        fv = favs()
        if any(fav_key(e) in fv for e in entries):
            l.prop(wm, "nomad_shelf_names", text="Names",
                   icon='FONT_DATA', toggle=True)
            _icon_view(l, wm, "nomad_fav_choice")
        else:
            l.label(text="No favorites yet", icon='INFO')


def open_popup(panel_name):
    """Scan (outside draw) if needed, then open the popup, all deferred."""
    from .sculpt_popups import open_panel_deferred

    def _prep():
        try:
            ensure(bpy.context, bpy.context.mode)
        except Exception as exc:
            print(f"NomadUI shelf scan: {exc!r}")
        open_panel_deferred(panel_name)
        return None
    try:
        bpy.app.timers.register(_prep, first_interval=0.01)
    except RuntimeError:
        pass


CLASSES = (NOMAD_OT_brush_activate, NOMAD_OT_brush_fav,
           NOMAD_OT_shelf_nav, NOMAD_OT_shelf_refresh,
           NOMAD_OT_shelf_clean, NOMAD_PT_brushes, NOMAD_PT_favorites)


def register():
    wm_t = bpy.types.WindowManager
    wm_t.nomad_shelf_path = bpy.props.StringProperty(
        default="", options={'SKIP_SAVE'})
    wm_t.nomad_shelf_search = bpy.props.StringProperty(
        default="", options={'SKIP_SAVE', 'TEXTEDIT_UPDATE'})
    wm_t.nomad_shelf_names = bpy.props.BoolProperty(
        name="Show Names", default=True,
        description="Show brush names below thumbnails")
    wm_t.nomad_shelf_lib = bpy.props.EnumProperty(
        name="Library", items=_lib_items, update=_lib_update,
        options={'SKIP_SAVE'})
    wm_t.nomad_shelf_folder = bpy.props.EnumProperty(
        name="Folder", items=_folder_items, options={'SKIP_SAVE'})
    wm_t.nomad_fav_choice = bpy.props.EnumProperty(
        name="Favorites", items=_make_items("fav"),
        get=_make_get("fav"), set=_make_set("fav"),
        options={'SKIP_SAVE'})
    wm_t.nomad_shelf_choice = bpy.props.EnumProperty(
        name="Brushes", items=_make_items("shelf"),
        get=_make_get("shelf"), set=_make_set("shelf"),
        options={'SKIP_SAVE'})
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    for name in ("nomad_shelf_path", "nomad_shelf_search",
                 "nomad_shelf_names", "nomad_shelf_lib",
                 "nomad_shelf_folder", "nomad_fav_choice",
                 "nomad_shelf_choice"):
        if hasattr(bpy.types.WindowManager, name):
            delattr(bpy.types.WindowManager, name)
    from .safety import quitting
    if not quitting():
        try:
            _purge(bpy.context)
        except Exception:
            pass
    _cache.clear()