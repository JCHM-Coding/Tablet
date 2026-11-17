# NLA editor on the expanded timeline (objects only): object > action line
# > tracks. Strips can be selected, moved, resized, split, duplicated and
# moved between tracks; tracks and strips can be added, muted and deleted;
# the active strip's values (blending, influence...) are edited in a popup.
# Header: Push / Edit (only while an object is in action), Track+, Strip+,
# then the View / Select / Marker / Edit / Modifiers dropdowns.
# Gestures keep only plain data and every write re-resolves the strip and
# checks it is still the same one. The Python API cannot split a strip or
# change its track, so those operations build a copy in free space of the
# target track and remove the original only when the copy is in place.
import time

import bpy

from . import drawing, panels
from . import timeline_ext as tl
from .anim_options import _fcurves

ROWH = tl.ROWH
CH_W = tl.CH_W
EDGE = 9
BTN = (0.20, 0.20, 0.23, 1.0)

COL_STRIP = {'CLIP': (0.30, 0.55, 0.38, 1.0),
             'TRANSITION': (0.60, 0.32, 0.32, 1.0),
             'META': (0.50, 0.38, 0.65, 1.0),
             'SOUND': (0.30, 0.45, 0.70, 1.0)}
COL_MUTED = (0.30, 0.30, 0.33, 1.0)
COL_ACTION = (0.80, 0.52, 0.20, 1.0)
COL_TWEAK = (0.95, 0.80, 0.25, 1.0)
COL_NOTE = (1.0, 0.85, 0.4, 1.0)

_BOOLS = ("use_auto_blend", "use_sync_length", "use_reverse",
          "use_animated_time", "use_animated_time_cyclic", "mute")
_fold = set()
_scroll = 0.0
_tool = {"snap": True}
_note = {"text": "", "until": 0.0}
_st = {"mode": None, "last": (0, 0), "moved": 0.0, "x0": 0.0, "y0": 0.0,
       "snap": [], "row": None, "w": 0, "hover": None, "src": None,
       "src_row": None, "was_sel": False, "tap": None}


def _in(r, mx, my):
    return r[0] <= mx <= r[2] and r[1] <= my <= r[3]


def _push(msg):
    try:
        bpy.ops.ed.undo_push(message=msg)
    except RuntimeError:
        pass


def _say(text):
    _note["text"], _note["until"] = text, time.time() + 3.0
    print(f"NomadUI NLA: {text}")


# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------

def _words(context):
    sc = context.scene
    if getattr(sc, "nomad_tl_search_on", False):
        return sc.nomad_tl_search.strip().lower().split()
    return []


def _objects(context):
    return [o for o in tl._objects(context) if o.animation_data is not None]


def _rows(context):
    words = _words(context)
    rows = []
    for obj in _objects(context):
        ad = obj.animation_data
        trk = []
        for ti in reversed(range(len(ad.nla_tracks))):
            tr = ad.nla_tracks[ti]
            text = " ".join([obj.name, tr.name]
                            + [s.name for s in tr.strips]).lower()
            if words and not all(t in text for t in words):
                continue
            trk.append({"kind": "trk", "key": f"n:t:{obj.name}:{ti}",
                        "label": tr.name, "level": 1, "obj": obj.name,
                        "ti": ti})
        act = ad.action
        act_ok = act is not None and (
            not words or all(t in (obj.name + " " + act.name).lower()
                             for t in words))
        if words and not trk and not act_ok:
            continue
        okey = "n:o:" + obj.name
        fold = okey in _fold
        rows.append({"kind": "obj", "key": okey, "label": obj.name,
                     "level": 0, "obj": obj.name, "fold": fold})
        if fold:
            continue
        if act_ok:
            rows.append({"kind": "act", "key": f"n:a:{obj.name}",
                         "label": act.name, "level": 1, "obj": obj.name})
        rows += trk
    return rows


def _track(row):
    obj = bpy.data.objects.get(row["obj"])
    ad = obj.animation_data if obj else None
    if ad is None or row["ti"] >= len(ad.nla_tracks):
        return None, None
    return ad, ad.nla_tracks[row["ti"]]


def _strip(key, name):
    """Fresh (anim data, track, strip) for a plain key; None if the strip
    is not the one we expect any more."""
    oname, ti, si = key
    obj = bpy.data.objects.get(oname)
    ad = obj.animation_data if obj else None
    if ad is None or ti >= len(ad.nla_tracks):
        return None, None, None
    tr = ad.nla_tracks[ti]
    if si >= len(tr.strips):
        return None, None, None
    st = tr.strips[si]
    if st.name != name:
        return None, None, None
    return ad, tr, st


def _akey(key, name):
    return f"{key[0]}|{key[1]}|{key[2]}|{name}"


def _active_strip(context):
    """The active strip: by its stored key, or by name if it moved."""
    s = context.scene.nomad_nla_active
    try:
        o, t, i, n = s.split("|", 3)
        key = (o, int(t), int(i))
    except ValueError:
        return None, None, None
    ad, tr, st = _strip(key, n)
    if st is not None:
        return ad, tr, st
    obj = bpy.data.objects.get(o)
    ad = obj.animation_data if obj else None
    if ad is None:
        return None, None, None
    for t2 in ad.nla_tracks:
        for s2 in t2.strips:
            if s2.name == n:
                return ad, t2, s2
    return None, None, None


def _deselect(context):
    for obj in _objects(context):
        for tr in obj.animation_data.nla_tracks:
            tr.select = False
            for st in tr.strips:
                st.select = False


def _selected_strips(context):
    out = []
    for obj in _objects(context):
        ad = obj.animation_data
        for ti, tr in enumerate(ad.nla_tracks):
            for si, st in enumerate(tr.strips):
                if st.select:
                    out.append(((obj.name, ti, si), st.name,
                                st.frame_start, st.frame_end))
    return out


# ----------------------------------------------------------------------
# Building strips (copy into free space, then place)
# ----------------------------------------------------------------------

def _clone_into(src, tr, start, act_start=None, act_end=None,
                blend_in=None, blend_out=None, name=None):
    """Copy the action strip `src` into track `tr` at `start`. Returns the
    new strip, or None (and leaves nothing behind) if it does not fit."""
    act = src.action
    if act is None or src.type != 'CLIP':
        return None
    a0 = src.action_frame_start if act_start is None else act_start
    a1 = src.action_frame_end if act_end is None else act_end
    bi = src.blend_in if blend_in is None else blend_in
    bo = src.blend_out if blend_out is None else blend_out
    far = int(max([s.frame_end for s in tr.strips] + [start]) + 5)
    try:
        new = tr.strips.new(name or src.name, far, act)
    except (RuntimeError, TypeError, ValueError):
        return None
    if new is None:
        return None
    try:
        slot = getattr(src, "action_slot", None)
        if slot is not None:
            new.action_slot = slot
    except (AttributeError, RuntimeError, TypeError):
        pass
    for attr, val in (("action_frame_end", a1), ("action_frame_start", a0),
                      ("scale", src.scale), ("repeat", src.repeat)):
        try:
            setattr(new, attr, val)
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass
    for attr in ("blend_type", "extrapolation"):
        try:
            setattr(new, attr, getattr(src, attr))
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass
    for attr in _BOOLS:
        try:
            setattr(new, attr, getattr(src, attr))
        except (RuntimeError, TypeError, ValueError, AttributeError):
            pass
    try:
        if not src.use_animated_influence:
            new.influence = src.influence
    except (RuntimeError, TypeError, ValueError, AttributeError):
        pass
    try:
        new.blend_in = bi
        new.blend_out = bo
    except (RuntimeError, TypeError, ValueError, AttributeError):
        pass
    try:
        new.frame_start_ui = start
    except (RuntimeError, TypeError, ValueError, AttributeError):
        pass
    if abs(new.frame_start - start) > 0.01:        # there is no room
        try:
            tr.strips.remove(new)
        except (RuntimeError, TypeError):
            pass
        return None
    return new


def _split(context):
    f = context.scene.frame_current
    done = 0
    order = sorted(_selected_strips(context),
                   key=lambda e: (e[0][0], e[0][1], -e[0][2]))
    for key, name, a, b in order:
        ad, tr, st = _strip(key, name)
        if st is None or tr.lock:
            continue
        if st.type != 'CLIP' or st.action is None:
            _say("Only action strips can be split")
            continue
        if not (st.frame_start + 0.01 < f < st.frame_end - 0.01):
            continue
        if st.repeat != 1.0 or st.use_reverse or st.use_animated_time:
            _say("Cannot split a repeated, reversed or time-animated strip")
            continue
        a_start, a_end = st.action_frame_start, st.action_frame_end
        a_split = a_start + (f - st.frame_start) / st.scale
        bo = st.blend_out
        try:
            st.blend_out = 0.0
            st.action_frame_end = a_split
        except (RuntimeError, TypeError, ValueError):
            continue
        new = _clone_into(st, tr, f, act_start=a_split, act_end=a_end,
                          blend_in=0.0, blend_out=bo,
                          name=st.name + ".001")
        if new is None:                              # undo the shortening
            try:
                st.action_frame_end = a_end
                st.blend_out = bo
            except (RuntimeError, TypeError, ValueError):
                pass
            _say("No room to split this strip")
            continue
        new.select = True
        done += 1
    if done:
        _push("Split NLA strips")


def _duplicate(context):
    done = 0
    order = sorted(_selected_strips(context),
                   key=lambda e: (e[0][0], -e[0][1], -e[0][2]))
    for key, name, a, b in order:
        ad, tr, st = _strip(key, name)
        if st is None or st.type != 'CLIP' or st.action is None:
            continue
        try:
            new_tr = ad.nla_tracks.new(prev=tr)          # a track above
        except (RuntimeError, TypeError):
            continue
        copy = _clone_into(st, new_tr, st.frame_start,
                           name=st.name + ".001")
        if copy is None:
            try:
                ad.nla_tracks.remove(new_tr)
            except (RuntimeError, TypeError):
                pass
            _say("Could not duplicate the strip")
            continue
        st.select = False
        copy.select = True
        done += 1
    if done:
        _push("Duplicate NLA strips")


def _to_track(context, key, name, target_key):
    ad, tr, st = _strip(key, name)
    trow = next((r for r in _rows(context) if r["key"] == target_key), None)
    if st is None or trow is None or trow["kind"] != "trk":
        return
    t_ad, t_tr = _track(trow)
    if t_tr is None or t_tr.as_pointer() == tr.as_pointer():
        return
    if trow["obj"] != key[0]:
        _say("A strip can only move to a track of the same object")
        return
    if t_tr.lock:
        _say("That track is locked")
        return
    if st.type != 'CLIP' or st.action is None:
        _say("Only action strips can change track")
        return
    new = _clone_into(st, t_tr, st.frame_start, name=st.name)
    if new is None:
        _say("No room for the strip in that track")
        return
    new.select = True
    try:
        tr.strips.remove(st)
    except (RuntimeError, TypeError):
        pass
    _push("Move strip to another track")


# ----------------------------------------------------------------------
# Geometry
# ----------------------------------------------------------------------

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


def _hit_strip(row, mx):
    """(strip index, name, start, end, edge?) under mx on a track row."""
    ad, tr = _track(row)
    if tr is None:
        return None
    for si, st in enumerate(tr.strips):
        xa, xb = tl._fx(st.frame_start), tl._fx(st.frame_end)
        if xa - 2 <= mx <= xb + 2:
            return si, st.name, st.frame_start, st.frame_end, \
                abs(mx - xb) <= EDGE
    return None


# ----------------------------------------------------------------------
# Toolbar
# ----------------------------------------------------------------------

_MENUS = ("view", "select", "marker", "edit", "mods")
_PANELS = {"view": "NOMAD_PT_nla_view", "select": "NOMAD_PT_nla_select",
           "marker": "NOMAD_PT_gr_marker", "edit": "NOMAD_PT_nla_edit",
           "mods": "NOMAD_PT_nla_mods"}


def _in_action(context):
    """Objects that have an active action (also while editing a strip)."""
    return [o for o in _objects(context)
            if o.animation_data.action is not None]


def _tweaking(context):
    return any(o.animation_data.use_tweak_mode for o in _objects(context))


def _tb_items(context):
    """Push / Edit and Modifiers only exist while an object is in action."""
    in_action = bool(_in_action(context))
    items = []
    if in_action:
        items.append(("pe", "Exit Edit" if _tweaking(context) else "Push",
                      "Push the active action down into a strip (while "
                      "editing a strip's action: back to the NLA)"))
    items += [("trk", "Track+", "Add a track"),
              ("add", "Strip+",
               "Add an action as a strip at the current frame"),
              None,
              ("view", "View", "View options"),
              ("select", "Select", "Select strips"),
              ("marker", "Marker", "Markers"),
              ("edit", "Edit", "Strips and tracks")]
    if in_action:
        items.append(("mods", "Modifiers",
                      "F-curve modifiers of the active action"))
    return items


def _buttons(context, tb):
    out, x = [], tb[0] + 8
    for it in _tb_items(context):
        if it is None:
            x += 12
            continue
        key, label, tip = it
        if key in _MENUS:
            wb = int(len(label) * 6.8) + 24
        else:
            wb = max(40, int(len(label) * 6.8) + 16)
        out.append((key, label, (x, tb[1] + 3, x + wb, tb[3] - 3), tip))
        x += wb + 3
    out += tl.shared_buttons(context, x, tb)
    return out


def _draw_toolbar(context, tb, mx, my):
    for key, label, rect, tip in _buttons(context, tb):
        hot = _in(rect, mx, my)
        on = ((key == "pe" and _tweaking(context))
              or (key in tl.SHARED_KEYS and tl.shared_on(context, key)))
        drawing.rrect(rect[0], rect[1], rect[2], rect[3], 6,
                      panels.COL_HOVER if hot else tl.COL_PLAY if on
                      else BTN)
        cx, cy = (rect[0] + rect[2]) / 2, (rect[1] + rect[3]) / 2
        if key in _MENUS:
            drawing.text(rect[0] + 8, cy - 4, label, size=11,
                         color=panels.COL_GLYPH)
            drawing.glyph(rect[2] - 10, cy, "\u25be", 10, panels.COL_GLYPH)
        else:
            drawing.text(cx, cy - 4, label, size=11,
                         color=panels.COL_GLYPH, align='CENTER')
        if hot:
            panels.hover_tip = tip


def _select_strips(context, mode):
    for obj in _objects(context):
        for tr in obj.animation_data.nla_tracks:
            if mode == 'NONE':
                tr.select = False
            for st in tr.strips:
                st.select = (True if mode == 'ALL' else
                             False if mode == 'NONE' else not st.select)


# --- modifiers of the active action's F-curves ------------------------

_MOD_TYPES = (("Generator", 'GENERATOR'), ("Built-in Function", 'FNGENERATOR'),
              ("Envelope", 'ENVELOPE'), ("Cycles", 'CYCLES'),
              ("Noise", 'NOISE'), ("Limits", 'LIMITS'),
              ("Stepped", 'STEPPED'))


def _action_curves(context):
    out = []
    for obj in _in_action(context):
        out.extend(_fcurves(obj))
    return out


def _mod_add(context, mtype):
    n = 0
    for fc in _action_curves(context):
        if any(m.type == mtype for m in fc.modifiers):
            continue                       # already has one of this type
        try:
            fc.modifiers.new(mtype)
        except (RuntimeError, TypeError, ValueError):
            continue
        fc.update()
        n += 1
    _push("Add F-curve modifiers")
    return n


def _mod_clear(context, mtype):
    """Remove the modifiers of one type (all of them when mtype is '')."""
    for fc in _action_curves(context):
        for m in [m for m in fc.modifiers if not mtype or m.type == mtype]:
            fc.modifiers.remove(m)
        fc.update()
    _push("Remove F-curve modifiers")


def _push_down(obj):
    ad = obj.animation_data
    act = ad.action if ad else None
    if act is None or ad.use_tweak_mode:
        return False
    slot = getattr(ad, "action_slot", None)
    tr = ad.nla_tracks.new()
    try:
        st = tr.strips.new(act.name, int(act.frame_range[0]), act)
    except (RuntimeError, TypeError, ValueError):
        ad.nla_tracks.remove(tr)
        return False
    try:
        if slot is not None:
            st.action_slot = slot
    except (AttributeError, RuntimeError, TypeError):
        pass
    tr.name = act.name
    ad.action = None
    return True


def _tb_action(context, key, w):
    sc = context.scene
    if key in tl.SHARED_KEYS:
        tl.shared_action(context, key)
        return
    if key in _PANELS:
        from .sculpt_popups import open_panel_deferred
        open_panel_deferred(_PANELS[key])
        return
    if key == "pe":
        objs = _objects(context)
        if any(o.animation_data.use_tweak_mode for o in objs):
            for o in objs:
                try:
                    o.animation_data.use_tweak_mode = False
                except (RuntimeError, AttributeError):
                    pass
            _push("Stop editing the strip action")
        else:
            done = [_push_down(o) for o in objs]
            if any(done):
                _push("Push down action")
    elif key == "cur":
        tl._v["f0"] = sc.frame_current - (w - CH_W) / 2 / tl._v["ppf"]
    elif key in ("sel_all", "sel_none", "sel_inv"):
        _select_strips(context, {"sel_all": 'ALL', "sel_none": 'NONE',
                                 "sel_inv": 'INVERT'}[key])
    elif key == "fit":
        tl._fit_view(sc, w)
    elif key in ("hz+", "hz-"):
        tl._zoom_time((CH_W + w) / 2, 1.25 if key == "hz+" else 0.8)
    elif key == "snap":
        _tool["snap"] = not _tool["snap"]
    elif key == "trk":
        for obj in tl._objects(context):
            ad = obj.animation_data or obj.animation_data_create()
            ad.nla_tracks.new()
        _push("Add NLA track")
    elif key == "push":
        done = [_push_down(o) for o in _objects(context)]
        if any(done):
            _push("Push down action")
    elif key == "add":
        from .sculpt_popups import open_panel_deferred
        open_panel_deferred("NOMAD_PT_nla_add")
    elif key == "split":
        _split(context)
    elif key == "dup":
        _duplicate(context)
    elif key == "props":
        if _active_strip(context)[2] is not None:
            from .sculpt_popups import open_panel_deferred
            open_panel_deferred("NOMAD_PT_nla_strip")
        else:
            _say("Select a strip first")
    elif key == "tweak":
        for obj in _objects(context):
            ad = obj.animation_data
            try:
                if ad.use_tweak_mode:
                    ad.use_tweak_mode = False
                elif any(s.select for t in ad.nla_tracks for s in t.strips):
                    ad.use_tweak_mode = True
            except (RuntimeError, AttributeError):
                pass
        _push("Toggle tweak mode")
    elif key == "mute":
        sel = _selected_strips(context)
        if sel:
            for k, name, a, b in sel:
                ad, tr, st = _strip(k, name)
                if st is not None:
                    st.mute = not st.mute
        else:
            for obj in _objects(context):
                for tr in obj.animation_data.nla_tracks:
                    if tr.select:
                        tr.mute = not tr.mute
        _push("Mute NLA")
    elif key == "del":
        sel = _selected_strips(context)
        for k, name, a, b in sorted(sel, key=lambda e: (e[0][0], e[0][1],
                                                         -e[0][2])):
            ad, tr, st = _strip(k, name)
            if st is not None and not tr.lock:
                tr.strips.remove(st)
        if not sel:
            for obj in _objects(context):
                ad = obj.animation_data
                for tr in [t for t in ad.nla_tracks if t.select]:
                    if not tr.lock:
                        ad.nla_tracks.remove(tr)
        _push("Delete NLA")


# ----------------------------------------------------------------------
# Draw
# ----------------------------------------------------------------------

def draw(context, w, mx, my):
    global _scroll
    sc = context.scene
    G = tl._geom(context, w)
    tl._ensure_view(sc, w)
    rows = _rows(context)
    cx1, cy1, cx2, cy2 = G["chan"]
    kx1, ky1, kx2, ky2 = G["keys"]
    _scroll = max(0.0, min(_scroll, tl._max_scroll(len(rows), G)))
    off = int(round(_scroll / ROWH)) * ROWH

    hd, rl, tb = G["head"], G["ruler"], G["tb"]
    drawing.rect(hd[0], hd[1], hd[2], hd[3], tl.COL_HEAD)
    drawing.text(hd[0] + 10, (hd[1] + hd[3]) / 2 - 5, "NLA", size=12,
                 color=panels.COL_TIP)
    drawing.rect(tb[0], tb[1], tb[2], tb[3], tl.COL_HEAD)
    _draw_toolbar(context, tb, mx, my)
    drawing.rect(rl[0], rl[1], rl[2], rl[3], tl.COL_HEAD)
    tl.draw_ruler(sc, rl, tl._fx, tl._xf(rl[0]), tl._xf(rl[2]),
                  tl._v["ppf"], span=(ky1, ky2))
    if not rows:
        drawing.text(CH_W + 16, (ky1 + ky2) / 2 - 5,
                     "No animated objects: select one (or check the "
                     "filters)", size=13, color=panels.COL_TIP)

    bg, visible = {}, []
    for i, row in enumerate(rows):
        y2 = cy2 - i * ROWH + off
        y1 = y2 - ROWH
        if y1 < cy1 - 0.5 or y2 > cy2 + 0.5:
            continue
        base = (tl.COL_OBJ if row["kind"] == "obj"
                else tl.COL_ROW_A if i % 2 else tl.COL_ROW_B)
        bg.setdefault(base, []).append((0, y1, w, y2 - 1))
        visible.append((row, y1, y2))
    for col, rs in bg.items():
        drawing.rects(rs, col)
    drawing.rects([(CH_W, y1, CH_W + 1, y2 - 1) for _r, y1, y2 in visible],
                  tl.COL_LINE)

    for row, y1, y2 in visible:
        kind = row["kind"]
        cy = (y1 + y2) / 2
        x = 8 + row["level"] * 14
        if kind == "obj":
            drawing.glyph(x + 5, cy, "▸" if row["fold"] else "▾", 12,
                          panels.COL_GLYPH)
            x += 16
        label = row["label"]
        maxc = max(4, int((CH_W - x - 56) / 6.6))
        if len(label) > maxc:
            label = label[:maxc - 1] + "…"
        drawing.text(x, cy - 4, label, size=12, color=panels.COL_GLYPH)

        if kind == "trk":
            ad, tr = _track(row)
            if tr is None:
                continue
            if tr.select:
                drawing.rect(0, y1, CH_W, y2 - 1, tl.COL_SEL)
            drawing.glyph(CH_W - 16, cy, "○" if tr.mute else "◉", 12,
                          panels.COL_TIP if tr.mute else panels.COL_GLYPH)
            drawing.glyph(CH_W - 40, cy, "▣" if tr.lock else "▢", 12,
                          panels.COL_GLYPH if tr.lock else panels.COL_TIP)
            for si, st in enumerate(tr.strips):
                xa, xb = tl._fx(st.frame_start), tl._fx(st.frame_end)
                if xb < kx1 or xa > kx2:
                    continue
                xa2, xb2 = max(xa, kx1), min(xb, kx2)
                col = (COL_MUTED if (st.mute or tr.mute)
                       else COL_STRIP.get(st.type, COL_STRIP['CLIP']))
                if st.select:
                    drawing.rrect(xa2 - 1, y1 + 1, xb2 + 1, y2 - 2, 5,
                                  tl.COL_KEY_SEL)
                drawing.rrect(xa2 + 1, y1 + 3, xb2 - 1, y2 - 4, 4, col)
                if xb2 - xa2 > 48:
                    nm = st.name[:max(1, int((xb2 - xa2 - 12) / 6.4))]
                    drawing.text(xa2 + 7, cy - 4, nm, size=11,
                                 color=(1, 1, 1, 1))
        elif kind == "act":
            obj = bpy.data.objects.get(row["obj"])
            ad = obj.animation_data if obj else None
            act = ad.action if ad else None
            if act is not None:
                fa, fb = act.frame_range
                xa, xb = tl._fx(fa), tl._fx(fb)
                if not (xb < kx1 or xa > kx2):
                    drawing.rrect(max(xa, kx1) + 1, y1 + 3,
                                  min(xb, kx2) - 1, y2 - 4, 4,
                                  COL_TWEAK if ad.use_tweak_mode
                                  else COL_ACTION)

    if _st["mode"] == 'move' and _st["hover"]:      # target track
        for row, y1, y2 in visible:
            if row["key"] == _st["hover"] and row["key"] != _st["src_row"]:
                drawing.rects([(kx1, y1, kx2, y1 + 2),
                               (kx1, y2 - 3, kx2, y2 - 1)], tl.COL_KEY_SEL)

    if time.time() < _note["until"]:
        drawing.text(kx1 + 14, ky2 - 18, _note["text"], size=12,
                     color=COL_NOTE)

    px = tl._fx(sc.frame_current)
    if kx1 <= px <= kx2:
        drawing.rect(px - 1, ky1, px + 1, ky2, tl.COL_PLAY)
        drawing.glyph(px, rl[1] + 6, "▼", 10, tl.COL_PLAY)


# ----------------------------------------------------------------------
# Interaction
# ----------------------------------------------------------------------

def press(context, w, mx, my):
    G = tl._geom(context, w)
    sc = context.scene
    tl._ensure_view(sc, w)
    _st.update(last=(mx, my), moved=0.0, x0=mx, y0=my, mode=None, snap=[],
               row=None, w=w, hover=None, src=None, src_row=None,
               was_sel=False)
    if _in(G["ruler"], mx, my):
        sc.frame_set(int(round(tl._xf(mx))))
        _st["mode"] = 'scrub'
        return True
    if _in(G["tb"], mx, my):
        for key, label, rect, tip in _buttons(context, G["tb"]):
            if _in(rect, mx, my):
                _tb_action(context, key, w)
                break
        return True
    if _in(G["head"], mx, my):
        return True

    rows = _rows(context)
    row = _row_at(rows, G, my)
    if _in(G["chan"], mx, my):
        _st["mode"] = 'chan'
        _st["row"] = row["key"] if row else None
        return True

    if row is not None and row["kind"] == "trk":
        hit = _hit_strip(row, mx)
        if hit is not None:
            si, name, a, b, edge = hit
            key = (row["obj"], row["ti"], si)
            ad, tr, st = _strip(key, name)
            if st is not None and not tr.lock:
                was = bool(st.select)
                if not was:
                    _deselect(context)
                    ad, tr, st = _strip(key, name)
                    st.select = True
                    tr.select = True
                sc.nomad_nla_active = _akey(key, name)
                snap = [{"key": k, "name": n, "start": s, "end": e,
                         "cur": s}
                        for k, n, s, e in _selected_strips(context)]
                _st.update(mode='resize' if edge else 'move', snap=snap,
                           src=(key, name), src_row=row["key"],
                           was_sel=was)
                return True
    _st["mode"] = 'bg'
    return True


def update(context, w, mx, my):
    global _scroll
    sc = context.scene
    tl._ensure_view(sc, w)
    lx, ly = _st["last"]
    dx, dy = mx - lx, my - ly
    _st["last"] = (mx, my)
    _st["moved"] += abs(dx) + abs(dy)
    mode = _st["mode"]
    G = tl._geom(context, w)
    if mode == 'scrub':
        sc.frame_set(int(round(tl._xf(mx))))
    elif mode == 'chan' and _st["moved"] > 8:
        _scroll = max(0.0, min(_scroll + dy, tl._max_scroll(
            len(_rows(context)), G)))
    elif mode == 'bg' and _st["moved"] > 8:
        tl._v["f0"] -= dx / tl._v["ppf"]
        _scroll = max(0.0, min(_scroll + dy, tl._max_scroll(
            len(_rows(context)), G)))
    elif mode in ('move', 'resize') and _st["moved"] > 4:
        d = (mx - _st["x0"]) / tl._v["ppf"]
        if _tool["snap"]:
            d = round(d)
        for e in _st["snap"]:
            ad, tr, st = _strip(e["key"], e["name"])
            if st is None or abs(st.frame_start - e["cur"]) > 1e-3:
                _st["mode"] = None                 # stale: cancel
                return
            try:
                if mode == 'move':
                    st.frame_start_ui = e["start"] + d
                    e["cur"] = st.frame_start
                else:
                    st.frame_end_ui = max(e["start"] + 1, e["end"] + d)
            except (RuntimeError, ValueError, TypeError, AttributeError):
                pass
        if mode == 'move' and len(_st["snap"]) == 1:
            row = _row_at(_rows(context), G, my)
            src_obj = _st["src"][0][0] if _st["src"] else None
            _st["hover"] = (row["key"] if row and row["kind"] == "trk"
                            and row["obj"] == src_obj else None)


def release(context):
    mode, moved = _st["mode"], _st["moved"]
    _st["mode"] = None
    if mode == 'chan' and moved <= 8 and _st["row"]:
        _tap_row(context, _st["row"])
    elif mode == 'bg' and moved <= 8:
        _deselect(context)
    elif mode in ('move', 'resize'):
        if moved > 4:
            if (mode == 'move' and _st["hover"] and _st["src"]
                    and _st["hover"] != _st["src_row"]
                    and len(_st["snap"]) == 1):
                key, name = _st["src"]
                _to_track(context, key, name, _st["hover"])
            else:
                _push("Edit NLA strips")
        elif _st["was_sel"] and _st["src"]:        # a tap on a selected one
            from .sculpt_popups import open_panel_deferred
            open_panel_deferred("NOMAD_PT_nla_strip")
    _st.update(snap=[], hover=None)


def _tap_row(context, key):
    row = next((r for r in _rows(context) if r["key"] == key), None)
    if row is None:
        return
    if row["kind"] == "obj":
        _fold.symmetric_difference_update({key})
        return
    if row["kind"] != "trk":
        return
    ad, tr = _track(row)
    if tr is None:
        return
    x0 = _st["x0"]
    if x0 >= CH_W - 28:
        tr.mute = not tr.mute
    elif x0 >= CH_W - 52:
        tr.lock = not tr.lock
    else:
        _deselect(context)
        ad, tr = _track(row)
        if tr is not None:
            tr.select = True


def wheel(context, w, mx, my, direction):
    global _scroll
    G = tl._geom(context, w)
    if _in(G["keys"], mx, my):
        tl._ensure_view(context.scene, w)
        tl._zoom_time(mx, 1.15 ** direction)
        return True
    _scroll = max(0.0, min(_scroll - direction * ROWH, tl._max_scroll(
        len(_rows(context)), G)))
    return True


# ----------------------------------------------------------------------
# Operators and popups
# ----------------------------------------------------------------------

class NOMAD_OT_nla_add_strip(bpy.types.Operator):
    bl_idname = "nomad.nla_add_strip"
    bl_label = "Add Action Strip"
    bl_description = "Add this action as a strip at the current frame"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.StringProperty()

    def execute(self, context):
        act = bpy.data.actions.get(self.action)
        obj = context.active_object
        if act is None or obj is None:
            return {'CANCELLED'}
        ad = obj.animation_data or obj.animation_data_create()
        tr = next((t for t in ad.nla_tracks if t.select), None)
        if tr is None:
            tr = ad.nla_tracks.new()
        try:
            st = tr.strips.new(act.name, int(context.scene.frame_current),
                               act)
        except (RuntimeError, TypeError, ValueError) as exc:
            self.report({'WARNING'}, f"Could not add the strip: {exc}")
            return {'CANCELLED'}
        try:
            slots = list(getattr(act, "slots", []))
            if slots:
                st.action_slot = slots[0]
        except (AttributeError, RuntimeError, TypeError):
            pass
        return {'FINISHED'}


class NOMAD_PT_nla_add(bpy.types.Panel):
    bl_label = "Add Action Strip"
    bl_idname = "NOMAD_PT_nla_add"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 11
        if context.active_object is None:
            l.label(text="No active object", icon='INFO')
            return
        acts = list(bpy.data.actions)
        if not acts:
            l.label(text="No actions in this file", icon='INFO')
            return
        col = l.column(align=True)
        col.scale_y = 1.3
        for a in acts[:30]:
            col.operator("nomad.nla_add_strip", text=a.name,
                         icon='ACTION').action = a.name


class NOMAD_PT_nla_strip(bpy.types.Panel):
    bl_label = "NLA Strip"
    bl_idname = "NOMAD_PT_nla_strip"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 14
        ad, tr, st = _active_strip(context)
        if st is None:
            l.label(text="No strip selected", icon='INFO')
            return
        l.prop(st, "name", text="")
        if st.type == 'CLIP' and st.action is not None:
            l.label(text=f"Action: {st.action.name}", icon='ACTION')

        col = l.column(align=True)
        col.prop(st, "frame_start_ui", text="Start")
        col.prop(st, "frame_end_ui", text="End")

        box = l.box()
        box.label(text="Blending")
        box.prop(st, "blend_type", text="")
        box.prop(st, "extrapolation", text="")
        row = box.row(align=True)
        row.prop(st, "use_animated_influence", text="", icon='ANIM')
        sub = row.row()
        sub.active = not st.use_animated_influence
        sub.prop(st, "influence", slider=True)
        row = box.row(align=True)
        row.prop(st, "blend_in", text="In")
        row.prop(st, "blend_out", text="Out")
        box.prop(st, "use_auto_blend", text="Auto Blend In / Out")

        if st.type == 'CLIP':
            box = l.box()
            box.label(text="Action Clip")
            col = box.column(align=True)
            col.prop(st, "action_frame_start", text="Frame Start")
            col.prop(st, "action_frame_end", text="Frame End")
            row = box.row(align=True)
            row.prop(st, "scale")
            row.prop(st, "repeat")
            row = box.row(align=True)
            row.prop(st, "use_reverse", toggle=True)
            row.prop(st, "use_sync_length", toggle=True, text="Sync Length")
            if st.use_animated_time:
                box.prop(st, "strip_time")
            box.prop(st, "use_animated_time", toggle=True,
                     text="Animated Strip Time")

        row = l.row(align=True)
        row.prop(st, "mute", toggle=True, icon='HIDE_ON')
        if tr is not None:
            row.prop(tr, "lock", toggle=True, icon='LOCKED')
            row.prop(tr, "is_solo", toggle=True, text="Solo",
                     icon='SOLO_OFF')
            l.prop(tr, "name", text="Track")


_DESC = {
    "fit": "Fit the frame range in the view", "cur": "Center on the current frame",
    "hz+": "Zoom in (time)", "hz-": "Zoom out (time)",
    "sel_all": "Select every strip", "sel_none": "Deselect every strip",
    "sel_inv": "Invert the strip selection",
    "split": "Split the selected strips at the current frame",
    "dup": "Duplicate the selected strips on a new track above",
    "props": "Edit the active strip (blending, influence, values)",
    "tweak": "Edit the selected strip's action (tweak mode)",
    "mute": "Mute the selected strips (or tracks)",
    "del": "Delete the selected strips (or tracks)",
    "snap": "Snap strips to whole frames",
    "mod_add": "Add this modifier to every F-curve of the action "
               "that does not have one of the same type",
    "mod_clear": "Remove modifiers from every F-curve of the action",
}


class NOMAD_OT_nla_action(bpy.types.Operator):
    bl_idname = "nomad.nla_action"
    bl_label = "NLA"
    bl_options = {'REGISTER'}

    action: bpy.props.StringProperty()
    value: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, properties):
        return _DESC.get(properties.action, "NLA action")

    def execute(self, context):
        try:
            if self.action == "mod_add":
                _mod_add(context, self.value)
            elif self.action == "mod_clear":
                _mod_clear(context, self.value)
            else:
                _tb_action(context, self.action, _st["w"] or 900)
        except Exception as exc:
            self.report({'WARNING'}, f"{self.action}: {exc}")
            return {'CANCELLED'}
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


def _grid(layout, items, cols=2):
    g = layout.grid_flow(row_major=True, columns=cols, even_columns=True,
                         align=True)
    g.scale_y = 1.3
    for text, action, value in items:
        op = g.operator("nomad.nla_action", text=text)
        op.action, op.value = action, value
    return g


def _nla_panel(idname, title, units, draw_fn):
    def draw(self, context):
        self.layout.ui_units_x = units
        draw_fn(self.layout, context)
    return type(idname, (bpy.types.Panel,), {
        "bl_label": title, "bl_idname": idname,
        "bl_space_type": 'VIEW_3D', "bl_region_type": 'WINDOW',
        "draw": draw})


def _d_view(l, context):
    _grid(l, [("Frame All", "fit", ""), ("Frame Current", "cur", ""),
              ("Zoom In", "hz+", ""), ("Zoom Out", "hz-", "")], 2)


def _d_select(l, context):
    _grid(l, [("All", "sel_all", ""), ("None", "sel_none", ""),
              ("Invert", "sel_inv", "")], 3)


def _d_edit(l, context):
    _grid(l, [("Split", "split", ""), ("Duplicate", "dup", ""),
              ("Strip Properties", "props", ""),
              ("Tweak Mode", "tweak", ""), ("Mute", "mute", ""),
              ("Delete", "del", "")], 2)
    l.separator()
    op = l.operator("nomad.nla_action", text="Snap to Whole Frames",
                    icon='CHECKBOX_HLT' if _tool["snap"]
                    else 'CHECKBOX_DEHLT')
    op.action = "snap"


def _d_mods(l, context):
    curves = _action_curves(context)
    if not curves:
        l.label(text="No active action", icon='INFO')
        return
    names = sorted({o.animation_data.action.name
                    for o in _in_action(context)})
    l.label(text=f"{len(curves)} F-curves: " + ", ".join(names)[:40],
            icon='ACTION')
    l.label(text="Add to the F-curves of the action")
    _grid(l, [(name, "mod_add", t) for name, t in _MOD_TYPES], 2)
    counts = {}
    for fc in curves:
        for m in fc.modifiers:
            counts[m.type] = counts.get(m.type, 0) + 1
    if counts:
        l.separator()
        l.label(text="In this action")
        titles = {t: n for n, t in _MOD_TYPES}
        for t, n in sorted(counts.items()):
            row = l.row(align=True)
            row.label(text=f"{titles.get(t, t.title())}  x{n}")
            op = row.operator("nomad.nla_action", text="", icon='X')
            op.action, op.value = "mod_clear", t
        op = l.operator("nomad.nla_action", text="Remove All")
        op.action, op.value = "mod_clear", ""


NOMAD_PT_nla_view = _nla_panel("NOMAD_PT_nla_view", "View", 11, _d_view)
NOMAD_PT_nla_select = _nla_panel("NOMAD_PT_nla_select", "Select", 11,
                                 _d_select)
NOMAD_PT_nla_edit = _nla_panel("NOMAD_PT_nla_edit", "Edit", 12, _d_edit)
NOMAD_PT_nla_mods = _nla_panel("NOMAD_PT_nla_mods", "Modifiers", 14,
                               _d_mods)

CLASSES = (NOMAD_OT_nla_add_strip, NOMAD_PT_nla_add, NOMAD_PT_nla_strip,
           NOMAD_OT_nla_action, NOMAD_PT_nla_view, NOMAD_PT_nla_select,
           NOMAD_PT_nla_edit, NOMAD_PT_nla_mods)


def register():
    bpy.types.Scene.nomad_nla_active = bpy.props.StringProperty(
        default="", options={'SKIP_SAVE'})
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    if hasattr(bpy.types.Scene, "nomad_nla_active"):
        del bpy.types.Scene.nomad_nla_active