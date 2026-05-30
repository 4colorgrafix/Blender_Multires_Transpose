import bpy
import bmesh
from typing import Iterable, List, Tuple
from .bmesh_context import bmesh_from_obj
from .bmesh_utils import write_layer_data, read_layer_data, bmesh_join, bmesh_from_faces
from ..data_types import MeshDomain, MeshLayerType

ORIGINAL_OBJECT_NAME_LAYER = "original_object_name"
ORIGINAL_VERTEX_INDEX_LAYER = "original_vertex_index"
ORIGINAL_SUBDIVISION_LEVEL_LAYER = "original_subdivision_level"


def set_multires_to_nth_level(objects: Iterable[bpy.types.Object], n: int | None) -> Tuple[List[bpy.types.Object], List[int]]:
    """
    Set all selected objects' multiresolution modifier view subdivision level to n.

    Args:
        objects (Iterable[bpy.types.Object]): Objects to change multires level on
        n (int | None): Level to set multires to. If None, uses levels as they are.

    Returns:
        Tuple[List[bpy.types.Object], List[int]]: Objects that had their multires level
            changed, and their corresponding subdivision levels.
    """
    changed_objs: List[bpy.types.Object] = []
    levels: List[int] = []
    for obj in set(objects):
        if obj.type == "MESH":
            for mod in obj.modifiers:
                if mod.type == "MULTIRES":
                    if n is not None:
                        mod.levels = n
                    changed_objs.append(obj)
                    levels.append(mod.levels)
                    bpy.ops.object.modifier_apply(modifier="{mod.name}")
                    break
    return changed_objs, levels


def restore_vertex_index(bm: bmesh.types.BMesh) -> None:
    """
    Restore the vertex indices of the given bmesh to the originally recorded vertex indices.

    Args:
        bm (bmesh.types.BMesh): BMesh to restore vertex indices on
    """
    original_vertex_indices = read_layer_data(bm, MeshDomain.VERTS, MeshLayerType.INT, ORIGINAL_VERTEX_INDEX_LAYER)
    for v, original_index in zip(bm.verts, original_vertex_indices):
        v.index = original_index
    bm.verts.sort()
    bm.verts.ensure_lookup_table()


def create_meshes_by_original_name(object: bpy.types.Object) -> List[bpy.types.Object]:
    """
    Split the given object into multiple objects based on the original object name recorded
    in the mesh's face layer. The given object's mesh is not modified.

    Args:
        object (bpy.types.Object): Object to split

    Returns:
        List[bpy.types.Object]: List of split objects
    """
    split_objects = []
    depsgraph = bpy.context.evaluated_depsgraph_get()

    with bmesh_from_obj(depsgraph.objects[object.name]) as bm:
        original_obj_names = read_layer_data(bm, MeshDomain.FACES, MeshLayerType.STRING, ORIGINAL_OBJECT_NAME_LAYER, uniform=False)
        if not all(original_obj_names):
            raise ValueError(
                "Object does not have original object names recorded on all faces, "
                "cannot split to transpose targets"
            )

        # Build a map of original object name -> list of face objects
        transpose_map: dict[str, list] = {name: [] for name in set(original_obj_names)}
        for face, name in zip(bm.faces, original_obj_names):
            transpose_map[name].append(face)

        for obj_name, faces in transpose_map.items():
            # Pass the actual face objects directly — no fragile contiguous-slice assumption
            d_bm = bmesh_from_faces(bm, faces)
            temp_mesh = bpy.data.meshes.new(name=f"{obj_name}_tgt")
            d_bm.to_mesh(temp_mesh)
            d_bm.free()

            tmp_obj = bpy.data.objects.new(name=f"{obj_name}_Target", object_data=temp_mesh)
            bpy.context.collection.objects.link(tmp_obj)
            split_objects.append(tmp_obj)

    return split_objects


def copy_multires_objs_to_new_mesh(
    context: bpy.types.Context,
    objects: Iterable[bpy.types.Object],
    level: int | None = 1,
    use_non_multires: bool = False,
) -> Tuple[bpy.types.Object, List[bpy.types.Object]]:
    """
    Copy all objects to a new merged mesh at the given multires level.

    Args:
        context (bpy.types.Context): Blender context
        objects (Iterable[bpy.types.Object]): Objects to copy from
        level (int | None, optional): Multires subdivision level. Defaults to 1.
            If None, uses the current multires level of each object.
        use_non_multires (bool, optional): Include objects without a multires modifier.
            Defaults to False.

    Returns:
        Tuple[bpy.types.Object, List[bpy.types.Object]]:
            The merged transpose-target object and the list of source objects that were merged.
    """
    def record_data_helper(bm: bmesh.types.BMesh, obj: bpy.types.Object, multires_level: int | None) -> None:
        # Bake world-space transform into the mesh
        bmesh.ops.transform(bm, verts=bm.verts, matrix=obj.matrix_world)

        write_layer_data(bm, MeshDomain.FACES, MeshLayerType.STRING, ORIGINAL_OBJECT_NAME_LAYER,
                         [obj.name for _ in bm.faces])
        write_layer_data(bm, MeshDomain.VERTS, MeshLayerType.INT, ORIGINAL_VERTEX_INDEX_LAYER,
                         [v.index for v in bm.verts])
        # Store -1 when there is no multires level to record
        write_layer_data(bm, MeshDomain.VERTS, MeshLayerType.INT, ORIGINAL_SUBDIVISION_LEVEL_LAYER,
                         [multires_level if multires_level is not None else -1 for _ in bm.verts])

    transpose_target_mesh = bpy.data.meshes.new(name="Multires_Transpose_Target")

    multires_objs, multires_levels = set_multires_to_nth_level(objects, level)

    # Disable all modifiers except MULTIRES so the depsgraph reflects only the base mesh
    disabled_modifiers = []
    broken_modifiers = []
    for obj in multires_objs:
        for mod in obj.modifiers:
            if mod.type != "MULTIRES":
                mod.show_viewport = False
                disabled_modifiers.append(mod)
            else:
                bpy.context.view_layer.objects.active = obj
                try:
                    bpy.ops.object.modifier_apply(modifier=mod.name)
                except:
                    broken_modifiers.append(mod)          
                finally:
                    bpy.ops.object.modifier_add(type='MULTIRES')

    depsgraph = context.evaluated_depsgraph_get()

    bms: List[bmesh.types.BMesh] = []
    merged_objs: List[bpy.types.Object] = []

    for i, obj in enumerate(multires_objs):
        bm = bmesh.new()
        bm.from_mesh(depsgraph.objects[obj.name].data)
        record_data_helper(bm, obj, multires_levels[i])
        bms.append(bm)
        merged_objs.append(obj)

    if use_non_multires:
        for obj in objects:
            if obj not in multires_objs:
                bm = bmesh.new()
                bm.from_mesh(obj.data)
                record_data_helper(bm, obj, None)
                bms.append(bm)
                merged_objs.append(obj)

    final_bm = bmesh_join(bms)

    # Free source bmeshes immediately after joining — don't hold them until after to_mesh
    for bm in bms:
        bm.free()
    bms.clear()

    final_bm.to_mesh(transpose_target_mesh)
    final_bm.free()

    # Re-enable any modifiers that were hidden
    for mod in disabled_modifiers:
        mod.show_viewport = True

    transpose_target_obj = bpy.data.objects.new(
        name="Multires_Transpose_Target", object_data=transpose_target_mesh
    )
    context.collection.objects.link(transpose_target_obj)
    return transpose_target_obj, merged_objs

def restore_lower_levels(context):
    """
    Restores lower subdivision levels for all selected meshes

    Args:
        context (bpy.types.Context): Blender context
    """
    for obj in context.selected_objects:
        bpy.context.view_layer.objects.active = obj
        for mod in obj.modifiers:
            if mod.type == "MULTIRES":
                bpy.ops.object.multires_rebuild_subdiv(modifier=mod.name)