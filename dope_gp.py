"""Grease Pencil mode of the Dope Sheet: the layers of the active Grease
Pencil object are the channels and its frames are the keys.

Plugged in through timeline_ext.ext_module (draw / press / update / release /
wheel). Nothing from Blender is kept between events: layers are looked up by
name every time they are touched."""

import bpy

from . import drawing, panels
from . import timeline_ext as tl
from .graph_panels import _panel

_s = {"mode": None, "last": (0, 0), "moved": 0.0, "x0": 0.0, "row": None,
      "scroll": 0.0, "d": 0, "move": [], "ref": 0}
_cache = {"t": 0.0, "rows": None}
_iso = {}                                  # isolate: layer name -> was hidden

KEY_TYPES = (("Keyframe", 'KEYFRAME'), ("Breakdown", 'BREAKDOWN'),
             ("Moving Hold", 'MOVING_HOLD'), ("Extreme", 'EXTREME'),
             ("Jitter", 'JITTER'))
# header keys that open a popup (the first four replace the generic ones)
PANELS = {"select": "NOMAD_PT_dsgp_select", "channel": "NOMAD_PT_dsgp_channel",
          "key": "NOMAD_PT_dsgp_key", "layer": "NOMAD_PT_dsgp_layer",
          "gp_extra": "NOMAD_PT_dsgp_extra"}
_API = (AttributeError, RuntimeError, TypeError, ValueError, ReferenceError)


# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------

def _gp(context):
    ob = context.active_object
    if ob is not None and ob.type == 'GREASEPENCIL':
        return ob.data
    return None


def _layer(gp, name):
    for layer in gp.layers:
        if layer.name == name:
            return layer
    return None


def _depth(layer):
    n, g = 0, getattr(layer, "parent_group", None)
    while g is not None and n < 8:
        n += 1
        g = getattr(g, "parent_group", None)
    return n


def _flush():
    _cache["rows"] = None


def rows(context):
    """[{name, level, hide, lock, active, frames[(frame, selected)]}] from the
    top layer to the bottom one. Cached for a moment (read while drawing)."""
    import time
    now = time.time()
    if _cache["rows"] is not None and now - _cache["t"] < 0.12:
        return _cache["rows"]
    gp = _gp(context)
    out = []
    if gp is not None:
        active = gp.layers.active
        aname = active.name if active is not None else None
        for layer in reversed(list(gp.layers)):
            frames = [(fr.frame_number, bool(getattr(fr, "select", False)))
                      for fr in layer.frames]
            out.append({"name": layer.name, "level": _depth(layer),
                        "hide": bool(getattr(layer, "hide", False)),
                        "lock": bool(getattr(layer, "lock", False)),
                        "active": layer.name == aname, "frames": frames})
    _cache["rows"], _cache["t"] = out, now
    return out


def isolated(context):
    return bool(_iso)


def _selected(context):
    return [(r["name"], f) for r in rows(context) for f, s in r["frames"] if s]


# ----------------------------------------------------------------------
# Actions (the header buttons and the popups)
# ----------------------------------------------------------------------

def _set_select(context, mode):
    gp = _gp(context)
    if gp is None:
        return
    cur = context.scene.frame_current
    for layer in gp.layers:
        for fr in layer.frames:
            f = fr.frame_number
            sel = bool(getattr(fr, "select", False))
            new = {'ALL': True, 'NONE': False, 'INVERT': not sel,
                   'BEFORE': f < cur, 'AFTER': f > cur}[mode]
            try:
                fr.select = new
            except _API:
                pass


def _move_selected(context, d):
    gp = _gp(context)
    entries = _selected(context)
    by_layer = {}
    for name, f in entries:
        by_layer.setdefault(name, []).append(f)
    for name, fs in by_layer.items():
        layer = _layer(gp, name)
        if layer is None:
            continue
        existing = {fr.frame_number for fr in layer.frames}
        moving = set(fs)
        for f in sorted(fs, reverse=d > 0):          # free targets first
            t = f + d
            if t in existing and t not in moving:
                continue                              # would overwrite
            try:
                layer.frames.move(f, t)
            except _API:
                continue
            existing.discard(f)
            existing.add(t)
            moving.discard(f)
            moving.add(t)


def run(context, key):
    """Data actions. Returns a message for the undo stack or None."""
    gp = _gp(context)
    sc = context.scene
    if gp is None:
        return None
    layer = gp.layers.active
    if key == "gp_add":
        gp.layers.new("Layer", set_active=True)
        return "Add layer"
    if key == "gp_del" and layer is not None:
        gp.layers.remove(layer)
        return "Remove layer"
    if key in ("gp_up", "gp_down") and layer is not None:
        gp.layers.move(layer, 'UP' if key == "gp_up" else 'DOWN')
        return "Move layer"
    if key == "gp_group":
        gp.layer_groups.new("Group")
        return "Add layer group"
    if key == "gp_dup":
        bpy.ops.grease_pencil.layer_duplicate()
        return "Duplicate layer"
    if key == "gp_showall":
        for ly in gp.layers:
            ly.hide = False
        _iso.clear()
        return "Show all layers"
    if key == "gp_hide" and layer is not None:
        layer.hide = not layer.hide
        return "Toggle layer visibility"
    if key == "gp_lock" and layer is not None:
        layer.lock = not layer.lock
        return "Toggle layer lock"
    if key == "gp_iso":
        if _iso:                                      # restore
            for ly in gp.layers:
                if ly.name in _iso:
                    ly.hide = _iso[ly.name]
            _iso.clear()
        elif layer is not None:
            for ly in gp.layers:
                _iso[ly.name] = bool(ly.hide)
                ly.hide = ly.name != layer.name
        return "Isolate layer"
    if key in ("sel_all", "sel_none", "sel_inv", "sel_before", "sel_after"):
        _set_select(context, {"sel_all": 'ALL', "sel_none": 'NONE',
                              "sel_inv": 'INVERT', "sel_before": 'BEFORE',
                              "sel_after": 'AFTER'}[key])
        return None
    if key == "k_insert" and layer is not None:
        if sc.frame_current not in {fr.frame_number for fr in layer.frames}:
            layer.frames.new(sc.frame_current)
        return "Insert keyframe"
    if key == "k_delete":
        for name, f in sorted(_selected(context), key=lambda e: -e[1]):
            ly = _layer(gp, name)
            if ly is not None:
                ly.frames.remove(f)
        return "Delete keyframes"
    if key in ("k_cur", "k_dup"):
        sel = _selected(context)
        if not sel:
            return None
        first = min(f for _n, f in sel)
        d = sc.frame_current - first
        if key == "k_dup":
            d = d or 1
            for name, f in sorted(sel, key=lambda e: -e[1] if d > 0 else e[1]):
                ly = _layer(gp, name)
                if ly is not None and (f + d) not in {
                        fr.frame_number for fr in ly.frames}:
                    ly.frames.copy(f, f + d)
            return "Duplicate keyframes"
        if d:
            _move_selected(context, d)
        return "Move keyframes"
    if key.startswith("kt:"):
        for name, f in _selected(context):
            ly = _layer(gp, name)
            if ly is None:
                continue
            for fr in ly.frames:
                if fr.frame_number == f:
                    fr.keyframe_type = key[3:]
        return "Set keyframe type"
    return None


def action(context, key, w):
    """Header click. True if handled here (False: timeline_ext handles it)."""
    from .sculpt_popups import open_panel_deferred
    if key in PANELS:
        open_panel_deferred(PANELS[key])
        return True
    if key.startswith("gp_"):
        try:
            msg = run(context, key)
            if msg:
                tl._push(msg)
        except _API as exc:
            print(f"NomadUI Grease Pencil {key}: {exc!r}")
        _flush()
        return True
    return False


class NOMAD_OT_dsgp_action(bpy.types.Operator):
    bl_idname = "nomad.dsgp_action"
    bl_label = "Grease Pencil"
    bl_options = {'REGISTER', 'UNDO'}

    key: bpy.props.StringProperty()

    def execute(self, context):
        try:
            run(context, self.key)
        except _API as exc:
            self.report({'WARNING'}, f"{self.key}: {exc}")
            return {'CANCELLED'}
        _flush()
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


# ----------------------------------------------------------------------
# Popups
# ----------------------------------------------------------------------

def _grid(l, items, cols=2):
    g = l.grid_flow(row_major=True, columns=cols, even_columns=True,
                    align=True)
    g.scale_y = 1.25
    for text, key in items:
        g.operator("nomad.dsgp_action", text=text).key = key
    return g


def _need(l, context):
    if _gp(context) is None:
        l.label(text="Select a Grease Pencil object", icon='INFO')
        return False
    return True


def _d_select(l, context):
    if _need(l, context):
        _grid(l, [("All", "sel_all"), ("None", "sel_none"),
                  ("Invert", "sel_inv"), ("Before Current", "sel_before"),
                  ("After Current", "sel_after")], 2)


def _d_channel(l, context):
    if not _need(l, context):
        return
    _grid(l, [("Add Layer", "gp_add"), ("Remove Layer", "gp_del"),
              ("Move Up", "gp_up"), ("Move Down", "gp_down"),
              ("Hide / Show", "gp_hide"), ("Lock / Unlock", "gp_lock"),
              ("Isolate Layer", "gp_iso"), ("Show All", "gp_showall")], 2)


def _d_key(l, context):
    if not _need(l, context):
        return
    _grid(l, [("Insert Keyframe", "k_insert"),
              ("Delete Keyframes", "k_delete"),
              ("Duplicate", "k_dup"), ("To Current Frame", "k_cur")], 2)
    l.label(text="Keyframe type")
    _grid(l, [(name, "kt:" + t) for name, t in KEY_TYPES], 2)


def _d_extra(l, context):
    if _need(l, context):
        _grid(l, [("Add Layer Group", "gp_group"),
                  ("Duplicate Layer", "gp_dup")], 1)


def _props(layout, owner, names):
    for n in names:
        try:
            layout.prop(owner, n)
        except _API:
            pass


def _d_layer(l, context):
    """What the Layer panel of the sidebar shows."""
    gp = _gp(context)
    layer = gp.layers.active if gp is not None else None
    if layer is None:
        l.label(text="No active layer", icon='INFO')
        return
    l.label(text=layer.name, icon='GREASEPENCIL')
    box = l.box()
    _props(box, layer, ("name", "opacity", "blend_mode", "hide", "lock",
                        "use_lights", "use_onion_skinning", "use_masks"))
    box = l.box()
    box.label(text="Adjustments")
    _props(box, layer, ("tint_color", "tint_factor", "radius_offset"))
    box = l.box()
    box.label(text="Transform")
    _props(box, layer, ("translation", "rotation", "scale"))
    box = l.box()
    box.label(text="Relations")
    _props(box, layer, ("parent", "parent_type", "parent_bone",
                        "pass_index", "viewlayer_render"))


NOMAD_PT_dsgp_select = _panel("NOMAD_PT_dsgp_select", "Select", 12, _d_select)
NOMAD_PT_dsgp_channel = _panel("NOMAD_PT_dsgp_channel", "Channel", 13,
                               _d_channel)
NOMAD_PT_dsgp_key = _panel("NOMAD_PT_dsgp_key", "Key", 13, _d_key)
NOMAD_PT_dsgp_extra = _panel("NOMAD_PT_dsgp_extra", "Extra", 12, _d_extra)
NOMAD_PT_dsgp_layer = _panel("NOMAD_PT_dsgp_layer", "Layer", 14, _d_layer)

CLASSES = (NOMAD_OT_dsgp_action, NOMAD_PT_dsgp_select, NOMAD_PT_dsgp_channel,
           NOMAD_PT_dsgp_key, NOMAD_PT_dsgp_extra, NOMAD_PT_dsgp_layer)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass


# ----------------------------------------------------------------------
# Drawing and interaction (called by timeline_ext)
# ----------------------------------------------------------------------

def _row_at(rr, G, my):
    top = G["chan"][3]
    off = int(round(_s["scroll"] / tl.ROWH)) * tl.ROWH
    for i, row in enumerate(rr):
        y2 = top - i * tl.ROWH + off
        y1 = y2 - tl.ROWH
        if y1 < G["chan"][1] - 0.5 or y2 > top + 0.5:
            continue
        if y1 <= my <= y2:
            return row
    return None


def _apply_request(context, w, rr):
    name = tl._req["name"]
    tl._req["name"] = None
    if name is None:
        return
    sc = context.scene
    if name == 'cur':
        tl._v["f0"] = sc.frame_current - (w - tl.CH_W) / 2 / tl._v["ppf"]
        return
    frames = [f for r in rr for f, s in r["frames"] if s or name == 'fit']
    if not frames:
        if name == 'fit':
            tl._fit_view(sc, w)
        return
    lo, hi = min(frames), max(frames)
    if hi - lo < 1:
        lo, hi = lo - 0.5, hi + 0.5
    tl._v["ppf"] = max(0.05, (w - tl.CH_W - 2 * tl.PAD_X) / (hi - lo))
    tl._v["f0"] = lo - tl.PAD_X / tl._v["ppf"]


def draw(context, w, mx, my):
    sc = context.scene
    G = tl._geom(context, w)
    cx1, cy1, cx2, cy2 = G["chan"]
    kx1, ky1, kx2, ky2 = G["keys"]
    hd, rl = G["head"], G["ruler"]
    rr = rows(context)
    _s["scroll"] = max(0.0, min(_s["scroll"], tl._max_scroll(len(rr), G)))
    off = int(round(_s["scroll"] / tl.ROWH)) * tl.ROWH

    drawing.rect(hd[0], hd[1], hd[2], hd[3], tl.COL_HEAD)
    drawing.text(hd[0] + 10, (hd[1] + hd[3]) / 2 - 5, "Layers", size=12,
                 color=panels.COL_TIP)
    tl._ensure_view(sc, w)
    _apply_request(context, w, rr)
    drawing.rect(rl[0], rl[1], rl[2], rl[3], tl.COL_HEAD)
    overlays = bool(tl._sp("nomad_ds_overlays", True))
    tl.draw_ruler(sc, rl, tl._fx, tl._xf(rl[0]), tl._xf(rl[2]),
                  tl._v["ppf"], span=(ky1, ky2),
                  show_range=overlays and bool(tl._sp("nomad_ds_ov_range",
                                                      True)),
                  seconds=overlays and bool(tl._sp("nomad_ds_ov_seconds",
                                                   False)))
    if not rr:
        msg = ("Select a Grease Pencil object" if _gp(context) is None
               else "This object has no layers: use + Layer")
        drawing.text(tl.CH_W + 16, (ky1 + ky2) / 2 - 5, msg, size=13,
                     color=panels.COL_TIP)

    bg, sep, visible = {}, [], []
    for i, row in enumerate(rr):
        y2 = cy2 - i * tl.ROWH + off
        y1 = y2 - tl.ROWH
        if y1 < cy1 - 0.5 or y2 > cy2 + 0.5:
            continue
        base = tl.COL_ROW_A if i % 2 else tl.COL_ROW_B
        bg.setdefault(base, []).append((0, y1, w, y2 - 1))
        if row["active"]:
            bg.setdefault(tl.COL_SEL, []).append((0, y1, tl.CH_W, y2 - 1))
        sep.append((tl.CH_W, y1, tl.CH_W + 1, y2 - 1))
        visible.append((row, y1, y2))
    for col, rs in bg.items():
        drawing.rects(rs, col)
    drawing.rects(sep, tl.COL_LINE)

    norm, sel = [], []
    ghost = []
    moving = set(map(tuple, _s["move"])) if _s["mode"] == 'move' else set()
    for row, y1, y2 in visible:
        cy = (y1 + y2) / 2
        x = 8 + row["level"] * tl.INDENT
        label = row["name"]
        maxc = max(4, int((tl.CH_W - x - 54) / 6.6))
        if len(label) > maxc:
            label = label[:maxc - 1] + "…"
        drawing.text(x, cy - 4, label, size=12, color=panels.COL_GLYPH)
        drawing.glyph(tl.CH_W - 16, cy, "○" if row["hide"] else "◉", 12,
                      panels.COL_TIP if row["hide"] else panels.COL_GLYPH)
        drawing.glyph(tl.CH_W - 38, cy, "▣" if row["lock"] else "□", 12,
                      panels.COL_GLYPH if row["lock"] else panels.COL_TIP)
        for f, s in row["frames"]:
            kx = tl._fx(f)
            if kx1 - 6 <= kx <= kx2 + 6:
                (sel if s else norm).append((kx, cy))
            if (row["name"], f) in moving and _s["d"]:
                ghost.append((tl._fx(f + _s["d"]), cy))
    drawing.diamonds(norm, tl.KEY_R, tl.COL_KEY)
    drawing.diamonds(sel, tl.KEY_R, tl.COL_KEY_SEL)
    if ghost:
        drawing.diamonds(ghost, tl.KEY_R, tl.COL_GHOST)

    if overlays and tl._sp("nomad_ds_ov_markers", True):
        pts = []
        for mk in sc.timeline_markers:
            mxp = tl._fx(mk.frame)
            if kx1 <= mxp <= kx2:
                pts.append((mxp, ky1 + 9))
                drawing.text(mxp + 7, ky1 + 4, mk.name[:14], size=10,
                             color=tl.COL_MARK)
        drawing.diamonds(pts, 5, tl.COL_MARK)

    px = tl._fx(sc.frame_current)
    if kx1 <= px <= kx2:
        drawing.rect(px - 1, ky1, px + 1, ky2, tl.COL_PLAY)
        drawing.glyph(px, rl[1] + 6, "▼", 10, tl.COL_PLAY)

    tl._draw_buttons(context, tl._dope_items(context, G), mx, my,
                     tl._dope_is_on)


def press(context, w, mx, my):
    sc = context.scene
    G = tl._geom(context, w)
    _s.update(mode=None, last=(mx, my), moved=0.0, x0=mx, row=None,
              d=0, move=[])
    tl._ensure_view(sc, w)
    for key, label, kind, rect, tip in tl._dope_items(context, G):
        if tl._in(rect, mx, my):
            tl._tb_action(context, key, w)
            return True
    if any(tl._in(r, mx, my) for r in G["rows"]):
        return True
    if tl._in(G["ruler"], mx, my):
        sc.frame_set(int(round(tl._xf(mx))))
        _s["mode"] = 'scrub'
        return True
    if tl._in(G["head"], mx, my):
        return True
    rr = rows(context)
    row = _row_at(rr, G, my)
    if tl._in(G["chan"], mx, my):
        _s["mode"], _s["row"] = 'chan', (row["name"] if row else None)
        return True
    if row is not None:
        best, bd = None, 11.0
        for f, _s_ in row["frames"]:
            d = abs(tl._fx(f) - mx)
            if d < bd:
                best, bd = f, d
        if best is not None:
            gp = _gp(context)
            layer = _layer(gp, row["name"]) if gp is not None else None
            if layer is not None:
                already = any(s for f, s in row["frames"] if f == best)
                if not already:
                    _set_select(context, 'NONE')
                    for fr in layer.frames:
                        if fr.frame_number == best:
                            try:
                                fr.select = True
                            except _API:
                                pass
                _flush()
                _s.update(mode='move', ref=best,
                          move=[list(e) for e in _selected(context)])
                return True
    _s["mode"] = 'bg'
    return True


def update(context, w, mx, my):
    sc = context.scene
    tl._ensure_view(sc, w)
    lx, ly = _s["last"]
    dx, dy = mx - lx, my - ly
    _s["last"] = (mx, my)
    _s["moved"] += abs(dx) + abs(dy)
    mode = _s["mode"]
    G = tl._geom(context, w)
    if mode == 'scrub':
        sc.frame_set(int(round(tl._xf(mx))))
    elif mode == 'chan' and _s["moved"] > 8:
        _s["scroll"] = max(0.0, min(_s["scroll"] + dy, tl._max_scroll(
            len(rows(context)), G)))
    elif mode == 'bg' and _s["moved"] > 8:
        tl._v["f0"] -= dx / tl._v["ppf"]
        _s["scroll"] = max(0.0, min(_s["scroll"] + dy, tl._max_scroll(
            len(rows(context)), G)))
    elif mode == 'move' and _s["moved"] > 4:
        raw = _s["ref"] + (mx - _s["x0"]) / tl._v["ppf"]
        _s["d"] = int(round(raw)) - _s["ref"]


def release(context):
    mode, moved = _s["mode"], _s["moved"]
    _s["mode"] = None
    gp = _gp(context)
    if mode == 'chan' and moved <= 8 and _s["row"] and gp is not None:
        layer = _layer(gp, _s["row"])
        if layer is not None:
            if _s["x0"] >= tl.CH_W - 28:
                layer.hide = not layer.hide
            elif _s["x0"] >= tl.CH_W - 50:
                layer.lock = not layer.lock
            else:
                gp.layers.active = layer
    elif mode == 'bg' and moved <= 8:
        _set_select(context, 'NONE')
    elif mode == 'move' and moved > 4 and _s["d"]:
        try:
            _move_selected(context, _s["d"])
            tl._push("Move keyframes")
        except _API as exc:
            print(f"NomadUI Grease Pencil move: {exc!r}")
    _s.update(move=[], d=0)
    _flush()


def wheel(context, w, mx, my, direction):
    G = tl._geom(context, w)
    if tl._in(G["keys"], mx, my):
        tl._ensure_view(context.scene, w)
        tl._zoom_time(mx, 1.15 ** direction)
        return True
    _s["scroll"] = max(0.0, min(_s["scroll"] - direction * tl.ROWH,
                                tl._max_scroll(len(rows(context)), G)))
    return True