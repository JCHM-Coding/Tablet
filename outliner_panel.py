# Outliner popup: collections (add / remove / assign / collapse), rename,
# assets.
import bpy

ROOT = "*ROOT*"     # value of nomad_ol_coll when the Scene Collection is chosen
FOLD = "nomad_collapsed"    # ID property stored on each collection


def _target(sc):
    name = sc.nomad_ol_coll
    if name == ROOT:
        return sc.collection
    return bpy.data.collections.get(name) if name else None


def _parents(coll, sc):
    pool = [sc.collection] + list(bpy.data.collections)
    return [c for c in pool if coll.name in c.children]


def _collapsed(coll, sc, root=False):
    if root:
        return bool(sc.nomad_ol_root_collapsed)
    return bool(coll.get(FOLD, False))


def _set_collapsed(coll, sc, root, value):
    if root:
        sc.nomad_ol_root_collapsed = value
        return
    try:
        coll[FOLD] = bool(value)
    except (RuntimeError, TypeError):
        pass        # library-linked collections can't store it


class NOMAD_OT_outliner_select(bpy.types.Operator):
    bl_idname = "nomad.outliner_select"
    bl_label = "Select Object"
    bl_options = {'INTERNAL'}

    obj_name: bpy.props.StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.obj_name)
        if obj is None:
            return {'CANCELLED'}
        if context.mode == 'OBJECT':
            for o in context.selected_objects:
                o.select_set(False)
            obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


class NOMAD_OT_outliner_toggle(bpy.types.Operator):
    bl_idname = "nomad.outliner_toggle"
    bl_label = "Toggle Visibility"
    bl_options = {'INTERNAL'}

    coll_name: bpy.props.StringProperty()
    obj_name: bpy.props.StringProperty()

    def execute(self, context):
        if self.obj_name:
            obj = bpy.data.objects.get(self.obj_name)
            if obj:
                obj.hide_viewport = not obj.hide_viewport
        else:
            coll = bpy.data.collections.get(self.coll_name)
            if coll:
                coll.hide_viewport = not coll.hide_viewport
        return {'FINISHED'}


class NOMAD_OT_outliner_fold(bpy.types.Operator):
    """Collapse / expand a collection (or all of them)."""
    bl_idname = "nomad.outliner_fold"
    bl_label = "Collapse Collection"
    bl_options = {'INTERNAL'}

    name: bpy.props.StringProperty()
    action: bpy.props.EnumProperty(
        items=[('TOGGLE', "Toggle", ""),
               ('COLLAPSE_ALL', "Collapse All", ""),
               ('EXPAND_ALL', "Expand All", "")],
        default='TOGGLE')

    def execute(self, context):
        sc = context.scene
        if self.action == 'TOGGLE':
            root = self.name == ROOT
            coll = sc.collection if root \
                else bpy.data.collections.get(self.name)
            if coll is None:
                return {'CANCELLED'}
            _set_collapsed(coll, sc, root, not _collapsed(coll, sc, root))
        else:
            value = self.action == 'COLLAPSE_ALL'
            for c in bpy.data.collections:      # Scene Collection stays open
                _set_collapsed(c, sc, False, value)
        return {'FINISHED'}


class NOMAD_OT_outliner_coll(bpy.types.Operator):
    """Select, add or remove a collection."""
    bl_idname = "nomad.outliner_coll"
    bl_label = "Collection"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.EnumProperty(items=[
        ('SELECT', "Select", ""), ('ADD', "Add", ""),
        ('REMOVE', "Remove", "")])
    name: bpy.props.StringProperty()

    def execute(self, context):
        sc = context.scene
        target = _target(sc)

        if self.action == 'SELECT':
            sc.nomad_ol_coll = "" if sc.nomad_ol_coll == self.name \
                else self.name
        elif self.action == 'ADD':
            parent = target or sc.collection
            new = bpy.data.collections.new("Collection")
            parent.children.link(new)
            # make sure the new one is visible
            if parent != sc.collection:
                _set_collapsed(parent, sc, False, False)
            sc.nomad_ol_coll = new.name
        elif self.action == 'REMOVE':
            if target is None or target == sc.collection:
                self.report({'WARNING'}, "Select a collection first")
                return {'CANCELLED'}
            parents = _parents(target, sc) or [sc.collection]
            parent = parents[0]
            for ob in list(target.objects):          # keep the contents
                if ob.name not in parent.objects:
                    parent.objects.link(ob)
            for ch in list(target.children):
                if ch.name not in parent.children:
                    parent.children.link(ch)
            bpy.data.collections.remove(target)
            sc.nomad_ol_coll = ""
        return {'FINISHED'}


class NOMAD_OT_outliner_assign(bpy.types.Operator):
    """Move or link the selected objects to the chosen collection."""
    bl_idname = "nomad.outliner_assign"
    bl_label = "Assign to Collection"
    bl_options = {'REGISTER', 'UNDO'}

    mode: bpy.props.EnumProperty(items=[
        ('MOVE', "Move", ""), ('LINK', "Link", "")])

    def execute(self, context):
        target = _target(context.scene)
        if target is None:
            self.report({'WARNING'}, "Select a collection first")
            return {'CANCELLED'}
        objs = list(context.selected_objects)
        if not objs and context.active_object:
            objs = [context.active_object]
        for ob in objs:
            if self.mode == 'MOVE':
                for c in list(ob.users_collection):
                    if c != target:
                        c.objects.unlink(ob)
            if ob.name not in target.objects:
                target.objects.link(ob)
        return {'FINISHED'}


class NOMAD_OT_outliner_asset(bpy.types.Operator):
    """Mark / clear the active object or the chosen collection as asset."""
    bl_idname = "nomad.outliner_asset"
    bl_label = "Asset"
    bl_options = {'REGISTER', 'UNDO'}

    action: bpy.props.EnumProperty(items=[
        ('MARK', "Mark", ""), ('CLEAR', "Clear", "")])
    what: bpy.props.EnumProperty(items=[
        ('OBJECT', "Object", ""), ('COLLECTION', "Collection", "")])

    def execute(self, context):
        if self.what == 'OBJECT':
            idb = context.active_object
        else:
            idb = _target(context.scene)
            if idb == context.scene.collection:
                idb = None
        if idb is None:
            self.report({'WARNING'}, "Nothing selected")
            return {'CANCELLED'}
        try:
            if self.action == 'MARK':
                idb.asset_mark()
            else:
                idb.asset_clear()
        except Exception as exc:
            self.report({'WARNING'}, f"Asset: {exc}")
            return {'CANCELLED'}
        return {'FINISHED'}


def _obj_icon(obj):
    icons = {'MESH': 'MESH_DATA', 'LIGHT': 'LIGHT',
             'CAMERA': 'CAMERA_DATA', 'CURVE': 'CURVE_DATA',
             'ARMATURE': 'ARMATURE_DATA', 'EMPTY': 'EMPTY_AXIS',
             'LATTICE': 'LATTICE_DATA', 'GPENCIL': 'GREASEPENCIL'}
    return icons.get(obj.type, 'OBJECT_DATA')


class NOMAD_PT_outliner(bpy.types.Panel):
    bl_label = "Outliner"
    bl_idname = "NOMAD_PT_outliner"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'WINDOW'

    def draw(self, context):
        l = self.layout
        l.ui_units_x = 8
        sc = context.scene

        col = l.column()
        col.scale_y = 1.4
        op = col.operator("nomad.outliner_coll", text="Add Collection",
                          icon='COLLECTION_NEW')
        op.action = 'ADD'
        op = col.operator("nomad.outliner_coll", text="Remove Collection",
                          icon='X')
        op.action = 'REMOVE'

        l.separator()
        coll = _target(sc)
        use_coll = coll is not None and coll != sc.collection
        obj = context.active_object
        name = coll.name if use_coll else (obj.name if obj else "")
        l.label(text=name or "Nothing selected",
                icon='OUTLINER_COLLECTION' if use_coll else 'OBJECT_DATA')
        what = 'COLLECTION' if use_coll else 'OBJECT'
        col = l.column()
        col.scale_y = 1.4
        op = col.operator("nomad.outliner_asset", text="Mark Asset",
                          icon='ASSET_MANAGER')
        op.action, op.what = 'MARK', what
        op = col.operator("nomad.outliner_asset", text="Clear Asset",
                          icon='X')
        op.action, op.what = 'CLEAR', what


CLASSES = (NOMAD_OT_outliner_select, NOMAD_OT_outliner_toggle,
           NOMAD_OT_outliner_fold, NOMAD_OT_outliner_coll,
           NOMAD_OT_outliner_assign, NOMAD_OT_outliner_asset,
           NOMAD_PT_outliner)


def register():
    bpy.types.Scene.nomad_ol_coll = bpy.props.StringProperty(default="")
    bpy.types.Scene.nomad_ol_root_collapsed = bpy.props.BoolProperty(
        default=False)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    for name in ("nomad_ol_coll", "nomad_ol_root_collapsed"):
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)