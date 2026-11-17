import sys

import bpy

_exit_flag = [False]


def _in_exit_stack():
    """True when called from bpy.utils._on_exit (Blender is quitting)."""
    if _exit_flag[0]:
        return True
    try:
        f = sys._getframe(2)
        while f is not None:
            if f.f_code.co_name == "_on_exit":
                _exit_flag[0] = True
                return True
            f = f.f_back
    except Exception:
        pass
    return False


def exiting():
    """Blender has no window manager (timers can still call this)."""
    try:
        return (len(bpy.data.window_managers) == 0
                or bpy.context.window_manager is None)
    except Exception:
        return True


def no_window():
    """No current window, or Blender is quitting: never write to spaces
    or areas (RNA updates that re-init areas would crash)."""
    try:
        if bpy.context.window is None:
            return True
    except Exception:
        return True
    return _in_exit_stack()


def quitting():
    return exiting() or no_window()