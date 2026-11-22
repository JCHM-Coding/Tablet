"""Drag operators of the top bar "Operators" dropdown (Extrude, Inset, Bevel,
Move, Shrink/Fatten...) with a touch friendly gesture:

  1. the release on the menu item ARMS the operator (nothing starts yet),
  2. the press in the viewport LAUNCHES it, so the drag starts where the
     finger is (Blender would start it at the menu item and the first touch
     made the result jump),
  3. the next release CONFIRMS it (release_confirm).

Blender's own menus launch an operator on the release and confirm it on the
next press. The menus are drawn through a proxy layout that swaps the buttons
of the operators that can be confirmed on release for "arm" buttons; every
other button of the menu stays untouched."""

import inspect
import itertools
import time
import types

import bpy

from . import drawing, panels, style

# C operators that start a transform inside, without release_confirm (the
# macros are found through their TRANSFORM_OT_* properties)
ALWAYS_DRAG = {"mesh.bevel", "mesh.inset",
               "view3d.edit_mesh_extrude_move_normal",
               "view3d.edit_mesh_extrude_individual_move",
               "view3d.edit_mesh_extrude_manifold_normal",
               "view3d.edit_mesh_extrude_shrink_fatten"}

armed = None                     # {"idname", "kwargs", "label"} while armed
_DB = {}                         # token -> (idname, kwargs, label)
_tokens = itertools.count(1)
_kind = {}                       # idname -> True/False (cache of is_drag_op)


# ----------------------------------------------------------------------
# Which operators are drag operators
# ----------------------------------------------------------------------

def _rna(idname):
    mod, name = idname.split(".", 1)
    return getattr(getattr(bpy.ops, mod), name).get_rna_type()


def _prop_names(idname):
    try:
        return {p.identifier for p in _rna(idname).properties}
    except (AttributeError, KeyError, RuntimeError, ValueError):
        return set()


def is_drag_op(idname):
    """Operators that can confirm on the release: they have release_confirm
    or are macros that contain a transform (TRANSFORM_OT_*)."""
    if idname not in _kind:
        names = _prop_names(idname)
        _kind[idname] = (idname in ALWAYS_DRAG or "release_confirm" in names
                         or any(n.startswith("TRANSFORM_OT_") for n in names))
    return _kind[idname]


def _label(idname):
    try:
        return _rna(idname).name or idname
    except (AttributeError, KeyError, RuntimeError, ValueError):
        return idname


# ----------------------------------------------------------------------
# Proxy layout: Blender's menus draw through it
# ----------------------------------------------------------------------

class _Rec:
    """Receives the properties that the menu sets on an operator button
    (even nested ones: props.TRANSFORM_OT_translate.value = ...)."""

    def __init__(self, store, path=()):
        object.__setattr__(self, "_store", store)
        object.__setattr__(self, "_path", path)

    def __setattr__(self, key, value):
        d = self._store
        for p in self._path:
            d = d.setdefault(p, {})
        d[key] = value

    def __getattr__(self, key):
        return _Rec(self._store, self._path + (key,))


class _Layout:
    def __init__(self, real, context):
        object.__setattr__(self, "_real", real)
        object.__setattr__(self, "_ctx", context)

    def __setattr__(self, key, value):
        setattr(self._real, key, value)       # operator_context, scale_y...

    def __getattr__(self, name):
        attr = getattr(self._real, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            res = attr(*args, **kwargs)
            if isinstance(res, bpy.types.UILayout):
                return _Layout(res, self._ctx)
            return res
        return call

    def operator(self, idname, **kw):
        if "." not in idname or not is_drag_op(idname):
            return self._real.operator(idname, **kw)
        kw.setdefault("text", _label(idname))
        op = self._real.operator("nomad.arm_op", **kw)
        token = next(_tokens)
        store = {}
        _DB[token] = (idname, store, kw["text"])
        op.token = token
        return _Rec(store)

    def menu(self, name, text="", **kw):
        proxy = _proxies.get(name)
        if proxy is None:                 # not a menu that we copied
            return self._real.menu(name, text=text, **kw)
        cls = getattr(bpy.types, name, None)
        label = text or getattr(cls, "bl_label", "") or name
        return self._real.menu(proxy, text=label, **kw)


class _Holder:
    """Stands for the menu instance (self) while the menu's draw() runs:
    .layout is the proxy, everything else (bl_label, helper methods...) comes
    from the menu class."""

    def __init__(self, cls, layout):
        object.__setattr__(self, "_cls", cls)
        object.__setattr__(self, "layout", layout)

    def __getattr__(self, name):
        cls = object.__getattribute__(self, "_cls")
        try:
            static = inspect.getattr_static(cls, name)
        except AttributeError:
            return getattr(cls, name)            # RNA only (bl_idname...)
        if isinstance(static, staticmethod):
            return static.__func__
        if isinstance(static, classmethod):
            return types.MethodType(static.__func__, cls)
        if inspect.isfunction(static):
            return types.MethodType(static, self)
        return getattr(cls, name)


def draw_menu(layout, menu_name, context):
    """Draw one of Blender's menus with the arm buttons."""
    cls = getattr(bpy.types, menu_name, None)
    if cls is None or not hasattr(cls, "draw"):
        layout.menu_contents(menu_name)
        return
    holder = _Holder(cls, _Layout(layout, context))
    try:
        cls.draw(holder, context)
    except Exception as exc:               # a menu that needs its own self
        print(f"NomadUI operators: {menu_name} drawn natively ({exc!r})")
        layout.menu_contents(menu_name)


def reset_tokens():
    """Called on every draw of the dropdown: keep the tokens that buttons
    already hold, only stop the table from growing."""
    if len(_DB) > 600:
        _DB.clear()


# ----------------------------------------------------------------------
# Arm / launch / cancel
# ----------------------------------------------------------------------

class NOMAD_OT_arm_op(bpy.types.Operator):
    bl_idname = "nomad.arm_op"
    bl_label = "Drag Operator"
    bl_description = ("Pick it, then press and drag in the viewport "
                     "(release to confirm)")
    bl_options = {'INTERNAL'}

    token: bpy.props.IntProperty()

    def execute(self, context):
        item = _DB.get(self.token)
        if item is None:
            return {'CANCELLED'}
        global armed
        armed = {"idname": item[0], "kwargs": item[1], "label": item[2]}
        print(f"NomadUI operators: {item[0]} armed (press in the viewport)")
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


def disarm():
    global armed
    armed = None


def _with_release_confirm(idname, kwargs):
    kw = dict(kwargs)
    names = _prop_names(idname)
    if "release_confirm" in names:
        kw["release_confirm"] = True
    for n in names:
        if n.startswith("TRANSFORM_OT_"):
            sub = dict(kw.get(n, {}))
            sub["release_confirm"] = True
            kw[n] = sub
    return kw


_saved = []                      # [(map name, kmi id, old value)]


def _modal_maps():
    kc = bpy.context.window_manager.keyconfigs.user
    if kc is None:
        return []
    return [km for km in kc.keymaps if km.is_modal]


def _confirm_on_release(on):
    """The modal maps (Transform, Bevel...) confirm on the PRESS of the left
    button. While a launched operator runs, confirm on the RELEASE instead
    (press = drag, release = confirm). The values are given back after."""
    maps = _modal_maps()
    if on:
        if _saved:
            return
        for km in maps:
            for kmi in km.keymap_items:
                try:
                    if (kmi.propvalue == 'CONFIRM'
                            and kmi.type == 'LEFTMOUSE'
                            and kmi.value in {'PRESS', 'ANY'}):
                        _saved.append((km.name, kmi.id, kmi.value))
                        kmi.value = 'RELEASE'
                except (AttributeError, TypeError, RuntimeError,
                        ReferenceError):
                    pass
    else:
        by_name = {km.name: km for km in maps}
        for name, kid, value in _saved:
            km = by_name.get(name)
            if km is None:
                continue
            for kmi in km.keymap_items:
                try:
                    if kmi.id == kid:
                        kmi.value = value
                        break
                except (AttributeError, TypeError, RuntimeError,
                        ReferenceError):
                    pass
        _saved.clear()


def _modal_ptrs():
    out = set()
    for win in bpy.context.window_manager.windows:
        for m in win.modal_operators:
            if not m.bl_idname.startswith("NOMAD_OT_"):
                out.add(m.as_pointer())
    return out


def _restore_when_done(before):
    """Give the keymap back when the launched operator has finished."""
    start = time.time()

    def _tick():
        try:
            running = _modal_ptrs() - before
        except (AttributeError, ReferenceError, RuntimeError):
            running = set()
        if not running or time.time() - start > 180.0:
            _confirm_on_release(False)
            return None
        return 0.2
    if not _modal_ptrs() - before:
        _confirm_on_release(False)          # it already finished
        return
    bpy.app.timers.register(_tick, first_interval=0.2)


def launch(context, area=None, region=None):
    """The press in the viewport: start the armed operator now, with the 3D
    View as its context (from the modal handler the context is not the
    view: the transform failed with "convertViewVec: invalid context")."""
    global armed
    if armed is None:
        return False
    win = context.window
    if area is None or region is None:
        from .sculpt_popups import _view3d_override
        win, area, region = _view3d_override()
    idname, kwargs = armed["idname"], armed["kwargs"]
    armed = None
    mod, name = idname.split(".", 1)
    kw = _with_release_confirm(idname, kwargs)
    print(f"NomadUI operators: launching {idname} {kw}")
    before = _modal_ptrs()
    _confirm_on_release(True)
    try:
        with context.temp_override(window=win, area=area, region=region):
            getattr(getattr(bpy.ops, mod), name)('INVOKE_DEFAULT', **kw)
    except (RuntimeError, TypeError, ValueError) as exc:
        print(f"NomadUI operators: {idname} could not start: {exc}")
        _confirm_on_release(False)
        return True
    _restore_when_done(before)
    return True


def draw(context, w, h):
    """Hint while an operator is armed."""
    global armed
    if armed is None:
        return
    if not context.mode.startswith('EDIT'):
        armed = None
        return
    from .top_bar import BAR_H
    text = f"{armed['label']}: press and drag, release to confirm  (Esc cancels)"
    tw = len(text) * 6.4 + 28
    x1 = (w - tw) / 2
    y2 = h - BAR_H - 18
    style.pill(x1, y2 - 30, x1 + tw, y2, style.COL_PILL_DARK)
    drawing.text(w / 2, y2 - 20, text, size=12, color=panels.COL_GLYPH,
                 align='CENTER')


# ----------------------------------------------------------------------
# The dropdown is a real menu (it closes when an item is activated, so the
# next press reaches the viewport) whose submenus are copies of Blender's
# VIEW3D_MT_* menus drawn through the proxy layout.
# ----------------------------------------------------------------------

PROXY_PREFIX = "NOMAD_MT_p_"
_proxies = {}                    # Blender menu name -> proxy menu idname
_proxy_classes = []


def _make_proxy(name):
    cls = getattr(bpy.types, name)
    idname = PROXY_PREFIX + name

    def draw(self, context):
        draw_menu(self.layout, name, context)
    return type(idname, (bpy.types.Menu,), {
        "bl_idname": idname,
        "bl_label": getattr(cls, "bl_label", "") or name,
        "draw": draw})


def _build_proxies():
    _proxies.clear()
    _proxy_classes.clear()
    for name in dir(bpy.types):
        if not name.startswith("VIEW3D_MT_"):
            continue
        cls = getattr(bpy.types, name, None)
        try:
            ok = (isinstance(cls, type) and issubclass(cls, bpy.types.Menu)
                  and hasattr(cls, "draw"))
        except TypeError:
            ok = False
        if not ok or len(PROXY_PREFIX + name) > 63:
            continue
        _proxies[name] = PROXY_PREFIX + name
        _proxy_classes.append(_make_proxy(name))


class NOMAD_MT_edit_operators(bpy.types.Menu):
    bl_idname = "NOMAD_MT_edit_operators"
    bl_label = "Operators"

    def draw(self, context):
        from .mesh_panels import EDIT_MENUS
        layout = self.layout
        reset_tokens()
        menus = EDIT_MENUS.get(context.mode)
        if not menus:
            layout.label(text="No operators for this mode yet", icon='INFO')
            return
        for label, name in menus:
            if name in _proxies:
                layout.menu(_proxies[name], text=label)
            elif hasattr(bpy.types, name):
                layout.menu(name, text=label)
            else:
                layout.label(text=f"{name} not found", icon='INFO')


CLASSES = (NOMAD_OT_arm_op, NOMAD_MT_edit_operators)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _build_proxies()
    for cls in _proxy_classes:
        try:
            bpy.utils.register_class(cls)
        except (RuntimeError, ValueError) as exc:
            print(f"NomadUI operators: proxy {cls.__name__}: {exc}")


def unregister():
    global armed
    armed = None
    try:
        _confirm_on_release(False)
    except Exception:
        pass
    for cls in reversed(_proxy_classes):
        try:
            bpy.utils.unregister_class(cls)
        except (RuntimeError, ValueError):
            pass
    _proxy_classes.clear()
    _proxies.clear()
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass