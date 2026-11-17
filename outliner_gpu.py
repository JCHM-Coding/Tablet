# Floating GPU outliner with drag & drop. The whole row is the handle:
# a tap selects, a drag moves it (onto a collection: move; onto an object:
# parent; a collection onto another: re-parent). Scroll with the wheel,
# the thin bar on the right, or by dragging the empty background.
import math

import bpy

from . import drawing, panels, style
from .top_bar import BAR_H
from .outliner_panel import _collapsed, _set_collapsed, _parents, ROOT
from .sculpt_popups import defer_op, open_panel_deferred

W = 280
ROW = 30
HEAD = 34
PAD = 6
SCROLLW = 14
EYE = 28
ARROW = 22
INDENT = 16
DRAG_MIN = 10

visible = False
_obj_fold = set()
_scroll = 0.0
_st = {"src": None, "hover": None, "last": (0, 0), "moved": 0.0,
       "mode": None, "mouse": (0, 0)}

COL_BG = (0.06, 0.06, 0.07, 0.96)
COL_ROW = (0.13, 0.13, 0.15, 1.0)
COL_SEL = (0.22, 0.48, 0.85, 0.55)
COL_DROP = (0.22, 0.48, 0.85, 0.95)
COL_TXT = (0.9, 0.9, 0.92, 1.0)
COL_DIM = (0.6, 0.6, 0.65, 1.0)
COL_BAR = (0.3, 0.3, 0.34, 0.9)


def toggle():
    global visible
    visible = not visible


def register():
    pass


def unregister():
    global visible
    visible = False


def _in(r, mx, my):
    return r[0] <= mx <= r[2] and r[1] <= my <= r[3]


# ----------------------------------------------------------------------
# Model
# ----------------------------------------------------------------------

def _geom(context, w, h, nrows):
    x1 = (panels.MARGIN + 4 + panels.BTN + panels.PAD + 8
          + style.left_inset(context))
    if getattr(context.scene, "nomad_sidebar_left", False):
        x1 += panels.BTN + panels.PAD
    y2 = h - BAR_H - 10 - style.top_inset(context)
    y_lo = style._stack_top(context)
    height = max(HEAD + 2 * PAD + ROW, min(y2 - y_lo,
                                           HEAD + 2 * PAD + nrows * ROW))
    y1 = y2 - height
    return (x1, y1, x1 + W, y2), y2 - HEAD - PAD, y1 + PAD


def _max_scroll(n, top, bot):
    extra = max(0.0, n * ROW - (top - bot))
    return math.ceil(extra / ROW) * ROW


def _snap():
    return int(round(_scroll / ROW)) * ROW


def _head_buttons(rect):
    x1, y1, x2, y2 = rect
    out = []
    x = x2 - PAD
    for key, glyph in (("close", "✕"), ("more", "≡"), ("remove", "-"),
                       ("add", "+")):
        out.append((key, glyph, (x - 26, y2 - HEAD + 4, x, y2 - 4)))
        x -= 30
    return out


def _rows(context):
    sc = context.scene
    rows = []

    def add_obj(ob, level, coll):
        kids = [c for c in ob.children if c.name in coll.objects]
        fold = ob.name in _obj_fold
        rows.append({"kind": "obj", "name": ob.name, "label": ob.name,
                     "level": level, "obj": ob, "has_kids": bool(kids),
                     "fold": fold})
        if fold:
            return
        for ch in kids:
            add_obj(ch, level + 1, coll)

    def add_coll(coll, level, root=False):
        fold = _collapsed(coll, sc, root)
        rows.append({"kind": "coll", "name": ROOT if root else coll.name,
                     "label": coll.name, "level": level, "coll": coll,
                     "root": root, "fold": fold})
        if fold:
            return
        for ob in coll.objects:
            if ob.parent is None or ob.parent.name not in coll.objects:
                add_obj(ob, level + 1, coll)
        for sub in coll.children:
            add_coll(sub, level + 1)

    add_coll(sc.collection, 0, True)
    return rows


def _hit(rows, rect, top, bot, mx, my):
    x1, y1, x2, y2 = rect
    off = _snap()
    if not (bot <= my <= top):
        return None
    for i, row in enumerate(rows):
        ry2 = top - i * ROW + off
        ry1 = ry2 - ROW
        if ry1 < bot - 0.5 or ry2 > top + 0.5:
            continue
        if ry1 <= my <= ry2 and x1 <= mx <= x2:
            tx = x1 + PAD + 4 + row["level"] * INDENT
            if mx >= x2 - PAD - SCROLLW:
                zone = 'scroll'
            elif mx >= x2 - PAD - SCROLLW - EYE:
                zone = 'eye'
            elif ((row["kind"] == 'coll' or row.get("has_kids"))
                  and mx <= tx + ARROW):
                zone = 'arrow'
            else:
                zone = 'name'
            return i, row, zone
    return None


def _descendants(coll):
    out, stack = set(), list(coll.children)
    while stack:
        c = stack.pop()
        out.add(c.name)
        stack.extend(c.children)
    return out


def _is_ancestor(ob, other):
    p = other.parent
    while p is not None:
        if p == ob:
            return True
        p = p.parent
    return False


def _valid_target(src, row):
    sk, sname = src
    if sk == 'obj':
        return not (row["kind"] == 'obj' and row["name"] == sname)
    if row["kind"] != 'coll' or row["name"] == sname:
        return False
    coll = bpy.data.collections.get(sname)
    return coll is not None and row["name"] not in _descendants(coll)


# ----------------------------------------------------------------------
# Draw
# ----------------------------------------------------------------------

def draw(context, w, h, mx, my):
    global _scroll
    if not visible:
        return
    rows = _rows(context)
    rect, top, bot = _geom(context, w, h, len(rows))
    maxs = _max_scroll(len(rows), top, bot)
    _scroll = max(0.0, min(_scroll, maxs))
    x1, y1, x2, y2 = rect
    sc = context.scene
    active = context.active_object

    drawing.rect(x1, y1, x2, y2, COL_BG)
    drawing.text(x1 + PAD + 2, y2 - HEAD / 2 - 6, "Outliner", size=14,
                 color=COL_TXT)
    for key, glyph, r in _head_buttons(rect):
        inside = _in(r, mx, my)
        drawing.rect(r[0], r[1], r[2], r[3],
                     panels.COL_HOVER if inside else panels.COL_BTN)
        drawing.text((r[0] + r[2]) / 2, (r[1] + r[3]) / 2 - 7, glyph,
                     size=15, color=COL_TXT, align='CENTER')

    off = _snap()
    hover = _st["hover"]
    for i, row in enumerate(rows):
        ry2 = top - i * ROW + off
        ry1 = ry2 - ROW
        if ry1 < bot - 0.5 or ry2 > top + 0.5:
            continue
        bg = COL_ROW
        if row["kind"] == 'obj' and active is not None \
                and active.name == row["name"]:
            bg = COL_SEL
        elif row["kind"] == 'coll' and sc.nomad_ol_coll == row["name"]:
            bg = COL_SEL
        if hover == (row["kind"], row["name"]):
            bg = COL_DROP
        drawing.rect(x1 + PAD, ry1 + 1, x2 - PAD, ry2 - 1, bg)

        tx = x1 + PAD + 4 + row["level"] * INDENT
        cy = (ry1 + ry2) / 2 - 7
        if row["kind"] == 'coll' or row.get("has_kids"):
            drawing.text(tx + 2, cy, "▸" if row["fold"] else "▾", size=14,
                         color=COL_TXT)
        else:
            drawing.text(tx + 6, cy, "•", size=14, color=COL_DIM)
        avail = (x2 - PAD - SCROLLW - EYE) - (tx + ARROW)
        maxc = max(4, int(avail / 7.5))
        label = row["label"]
        if len(label) > maxc:
            label = label[:maxc - 1] + "…"
        drawing.text(tx + ARROW, cy, label, size=13, color=COL_TXT)

        hidden = False
        if row["kind"] == 'obj':
            hidden = bool(row["obj"].hide_viewport)
        elif not row["root"]:
            hidden = bool(row["coll"].hide_viewport)
        if row["kind"] == 'obj' or not row["root"]:
            drawing.text(x2 - PAD - SCROLLW - EYE / 2, cy,
                         "○" if hidden else "◉", size=13,
                         color=COL_DIM if hidden else COL_TXT,
                         align='CENTER')

    if maxs > 0:                                   # scroll bar
        track = top - bot
        total = len(rows) * ROW
        thumb = max(24.0, track * track / total)
        pos = _scroll / maxs
        ty2 = top - (track - thumb) * pos
        bx = x2 - PAD - 8
        drawing.rrect(bx, ty2 - thumb, bx + 5, ty2, 2.5, COL_BAR)

    if _st["mode"] == 'item' and _st["moved"] > DRAG_MIN and _st["src"]:
        gx, gy = _st["mouse"]
        drawing.rect(gx + 12, gy - 14, gx + 12 + 150, gy + 14, COL_DROP)
        drawing.text(gx + 18, gy - 7, _st["src"][1][:20], size=13,
                     color=COL_TXT)


# ----------------------------------------------------------------------
# Interaction
# ----------------------------------------------------------------------

def _head_action(context, key):
    global visible
    if key == "close":
        visible = False
    elif key == "more":
        open_panel_deferred("NOMAD_PT_outliner")
    elif key == "add":
        defer_op("nomad", "outliner_coll", 'EXEC_DEFAULT', action='ADD')
    elif key == "remove":
        defer_op("nomad", "outliner_coll", 'EXEC_DEFAULT', action='REMOVE')


def press(context, w, h, mx, my):
    """False | True | 'ol_scroll' | 'ol_item'."""
    if not visible:
        return False
    rows = _rows(context)
    rect, top, bot = _geom(context, w, h, len(rows))
    if not _in(rect, mx, my):
        return False
    for key, glyph, r in _head_buttons(rect):
        if _in(r, mx, my):
            _head_action(context, key)
            return True
    if my > top:
        return True
    _st.update(last=(mx, my), moved=0.0, hover=None, src=None,
               mode=None, mouse=(mx, my))
    hit = _hit(rows, rect, top, bot, mx, my)
    if hit is None:                                 # empty background
        _st["mode"] = 'scroll_area'
        return 'ol_scroll'
    _i, row, zone = hit
    sc = context.scene
    if zone == 'scroll':                            # the thin bar
        _st["mode"] = 'scroll_bar'
        return 'ol_scroll'
    if zone == 'arrow' and row["kind"] == 'coll':
        _set_collapsed(row["coll"], sc, row["root"], not row["fold"])
        return True
    if zone == 'eye':
        if row["kind"] == 'obj':
            row["obj"].hide_viewport = not row["obj"].hide_viewport
        elif not row["root"]:
            row["coll"].hide_viewport = not row["coll"].hide_viewport
        return True
    _st["src"] = (row["kind"], row["name"])
    _st["mode"] = 'tap' if row.get("root") else 'item'
    return 'ol_item'


def update(context, w, h, mx, my, kind):
    global _scroll
    lx, ly = _st["last"]
    dy = my - ly
    _st["last"] = (mx, my)
    _st["moved"] += abs(mx - lx) + abs(dy)
    _st["mouse"] = (mx, my)
    rows = _rows(context)
    rect, top, bot = _geom(context, w, h, len(rows))
    maxs = _max_scroll(len(rows), top, bot)
    mode = _st["mode"]

    if mode == 'scroll_area':                       # finger-follow
        _scroll = max(0.0, min(_scroll + dy, maxs))
    elif mode == 'scroll_bar' and maxs > 0:         # thumb-follow
        track = max(1.0, top - bot)
        _scroll = max(0.0, min(_scroll - dy * (len(rows) * ROW) / track,
                               maxs))
    elif mode == 'item' and _st["moved"] > DRAG_MIN and _st["src"]:
        if my > top - 14:                           # auto-scroll
            _scroll = max(0.0, _scroll - 6)
        elif my < bot + 14:
            _scroll = min(maxs, _scroll + 6)
        hit = _hit(rows, rect, top, bot, mx, my)
        _st["hover"] = None
        if hit is not None and _valid_target(_st["src"], hit[1]):
            _st["hover"] = (hit[1]["kind"], hit[1]["name"])


def wheel(area, region, mx, my, direction):
    global _scroll
    if not visible:
        return False
    context = bpy.context
    w, h = style.region_size(region)
    rows = _rows(context)
    rect, top, bot = _geom(context, w, h, len(rows))
    if not _in(rect, mx, my):
        return False
    _scroll = max(0.0, min(_scroll - direction * ROW,
                           _max_scroll(len(rows), top, bot)))
    return True


def _tap(context, src):
    kind, name = src
    sc = context.scene
    if kind == 'obj':
        ob = bpy.data.objects.get(name)
        if ob is None:
            return
        sc.nomad_ol_coll = ""
        if context.mode == 'OBJECT':
            for o in context.selected_objects:
                o.select_set(False)
            ob.select_set(True)
        context.view_layer.objects.active = ob
    else:
        sc.nomad_ol_coll = "" if sc.nomad_ol_coll == name else name


def _drop(context, src, dst):
    sc = context.scene
    sk, sname = src
    dk, dname = dst
    if sk == 'obj':
        ob = bpy.data.objects.get(sname)
        if ob is None:
            return
        objs = [ob]
        try:
            if ob.select_get():
                objs = list(context.selected_objects) or [ob]
        except (RuntimeError, ReferenceError):
            pass
        if dk == 'coll':
            target = (sc.collection if dname == ROOT
                      else bpy.data.collections.get(dname))
            if target is None:
                return
            for o in objs:
                if o.parent is not None:
                    mw = o.matrix_world.copy()
                    o.parent = None
                    o.matrix_world = mw
                for c in list(o.users_collection):
                    if c != target:
                        c.objects.unlink(o)
                if o.name not in target.objects:
                    target.objects.link(o)
        else:
            parent = bpy.data.objects.get(dname)
            if parent is None:
                return
            for o in objs:
                if o == parent or _is_ancestor(o, parent):
                    continue
                mw = o.matrix_world.copy()
                o.parent = parent
                o.matrix_world = mw                # keep the transform
    else:
        coll = bpy.data.collections.get(sname)
        target = (sc.collection if dname == ROOT
                  else bpy.data.collections.get(dname))
        if (coll is None or target is None or coll == target
                or target.name in _descendants(coll)):
            return
        for p in _parents(coll, sc):
            p.children.unlink(coll)
        target.children.link(coll)
    try:
        bpy.ops.ed.undo_push(message="Outliner drop")
    except RuntimeError:
        pass


def release(context):
    src, hover = _st["src"], _st["hover"]
    mode, moved = _st["mode"], _st["moved"]
    _st.update(src=None, hover=None, mode=None)
    if mode not in ('item', 'tap') or not src:
        return
    if moved <= DRAG_MIN:
        _tap(context, src)                         # a tap selects
    elif mode == 'item' and hover:
        try:
            _drop(context, src, hover)
        except Exception as exc:
            print(f"NomadUI outliner drop: {exc!r}")