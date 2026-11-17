# Add-ons our features depend on (matched by a token in the module name).
import addon_utils
import bpy

REQUIRED = (("Pose Library", "pose_library"), ("Ucupaint", "ucupaint"))


def enabled(token):
    try:
        keys = bpy.context.preferences.addons.keys()
    except (AttributeError, RuntimeError):
        return False
    return any(token in k.lower() for k in keys)


def module_name(token):
    """Installed module that matches the token (to offer an Enable button)."""
    try:
        for m in addon_utils.modules():
            if token in m.__name__.lower():
                return m.__name__
    except Exception:
        pass
    return None