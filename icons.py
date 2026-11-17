# Real Blender tool icons from datafiles/icons/*.dat (vector triangles).
# Format: "VCO\0" + 4 header bytes, then N triangles: N*3 (x, y) uint8
# vertices followed by N*3 RGBA uint8 colours. y grows downwards.
from pathlib import Path

import bpy
import gpu
from gpu_extras.batch import batch_for_shader

# glyph -> {mode: icon name}; "*" = any mode; None = keep the glyph
ICON_MAP = {
    "▭": {"*": "ops.generic.select_box"},
    "⌖": {"PAINT_GREASE_PENCIL": None, "*": "ops.generic.cursor"},
    "✥": {"*": "ops.transform.transform"},
    "✐": {"*": "ops.gpencil.draw"},
    "↔": {"*": "ops.view3d.ruler"},
    "✚": {"*": "ops.mesh.primitive_cube_add_gizmo"},
    "◐": {"OBJECT": "ops.pose.breakdowner", "POSE": "ops.pose.breakdowner"},
    "▱": {"EDIT_GREASE_PENCIL": "ops.gpencil.edit_shear",
          "*": "ops.transform.shear"},
    "⇧": {"EDIT_MESH": "ops.mesh.extrude_region_move",
          "EDIT_ARMATURE": "ops.armature.extrude_move",
          "EDIT_CURVE": "ops.curve.extrude_move",
          "EDIT_SURFACE": "ops.curve.extrude_move",
          "EDIT_GREASE_PENCIL": "ops.gpencil.extrude_move"},
    "↺": {"EDIT_ARMATURE": "ops.armature.bone.roll",
          "EDIT_CURVE": "ops.transform.tilt",
          "EDIT_SURFACE": "ops.transform.tilt"},
    "◎": {"EDIT_CURVE": "ops.curve.radius", "EDIT_SURFACE": "ops.curve.radius",
          "EDIT_GREASE_PENCIL": "ops.gpencil.radius"},
    "✎": {"EDIT_CURVE": "ops.curve.draw", "EDIT_SURFACE": "ops.curve.draw",
          "EDIT_GREASE_PENCIL": "ops.gpencil.draw"},
    "✒": {"EDIT_CURVE": "ops.curve.pen"},
    "∿": {"*": "ops.curve.vertex_random"},
    "⌒": {"EDIT_GREASE_PENCIL": "ops.gpencil.edit_bend"},
    "▤": {"PAINT_WEIGHT": "ops.paint.weight_gradient",
          "EDIT_GREASE_PENCIL": "ops.gpencil.transform_fill"},
    "◖": {"EDIT_ARMATURE": "ops.transform.bone_size"},
    "✦": {"EDIT_MESH": "ops.mesh.loopcut_slide"},
    "◔": {"PAINT_WEIGHT": "brush.paint_weight.blur",
          "WEIGHT_GREASE_PENCIL": "brush.paint_weight.blur",
          "PAINT_VERTEX": "brush.paint_vertex.blur",
          "VERTEX_GREASE_PENCIL": "brush.paint_vertex.blur",
          "PAINT_TEXTURE": "brush.paint_texture.soften",
          "SCULPT_GREASE_PENCIL": "ops.gpencil.sculpt_blur"},
    "◍": {"PAINT_WEIGHT": "brush.paint_weight.average",
          "WEIGHT_GREASE_PENCIL": "brush.paint_weight.average",
          "PAINT_VERTEX": "brush.paint_vertex.average",
          "VERTEX_GREASE_PENCIL": "brush.paint_vertex.average",
          "SCULPT_GREASE_PENCIL": "ops.gpencil.sculpt_average"},
    "≈": {"PAINT_WEIGHT": "brush.paint_weight.smear",
          "WEIGHT_GREASE_PENCIL": "brush.paint_weight.smear",
          "PAINT_VERTEX": "brush.paint_vertex.smear",
          "VERTEX_GREASE_PENCIL": "brush.paint_vertex.smear",
          "PAINT_TEXTURE": "brush.paint_texture.smear",
          "SCULPT_GREASE_PENCIL": "ops.gpencil.sculpt_smear"},
    "⎘": {"PAINT_TEXTURE": "brush.paint_texture.clone",
          "SCULPT_GREASE_PENCIL": "ops.gpencil.sculpt_clone"},
    "◼": {"PAINT_TEXTURE": "brush.paint_texture.fill",
          "PAINT_GREASE_PENCIL": "brush.gpencil_draw.fill"},
    "⊘": {"PAINT_TEXTURE": "brush.paint_texture.mask"},
    "⌫": {"PAINT_GREASE_PENCIL": "brush.gpencil_draw.erase"},
    "◌": {"SCULPT": "ops.sculpt.border_hide"},
    "✂": {"SCULPT": "ops.sculpt.box_trim"},
    "≋": {"SCULPT": "ops.sculpt.mesh_filter"},
}

_batches = {}
_state = {"dir": None, "shader": None}


def lookup(glyph, mode):
    entry = ICON_MAP.get(glyph)
    if not entry:
        return None
    return entry.get(mode, entry.get("*"))


def _shader():
    if _state["shader"] is None:
        _state["shader"] = gpu.shader.from_builtin('SMOOTH_COLOR')
    return _state["shader"]


def _folder():
    if _state["dir"] is None:
        try:
            _state["dir"] = Path(bpy.utils.system_resource('DATAFILES')) / "icons"
        except Exception:
            _state["dir"] = Path()
    return _state["dir"]


def _load(name):
    try:
        data = (_folder() / f"{name}.dat").read_bytes()
    except OSError:
        return None
    if data[:4] != b'VCO\x00' or (len(data) - 8) % 18:
        return None
    n = (len(data) - 8) // 18
    co = data[8:8 + n * 6]
    cl = data[8 + n * 6:]
    pos = [(co[2 * i], co[2 * i + 1]) for i in range(n * 3)]
    col = [(cl[4 * i] / 255, cl[4 * i + 1] / 255, cl[4 * i + 2] / 255,
            cl[4 * i + 3] / 255) for i in range(n * 3)]
    return batch_for_shader(_shader(), 'TRIS', {"pos": pos, "color": col})


def draw(name, cx, cy, size):
    """Draw the icon centred at (cx, cy), `size` px. False if missing."""
    batch = _batches.get(name, False)
    if batch is False:
        batch = _batches[name] = _load(name)
    if batch is None:
        return False
    s = size / 255.0
    gpu.matrix.push()
    try:
        gpu.matrix.translate((round(cx - size / 2), round(cy + size / 2)))
        gpu.matrix.scale((s, -s))
        batch.draw(_shader())
    finally:
        gpu.matrix.pop()
    return True


def exists(name):
    return (_folder() / f"{name}.dat").is_file()