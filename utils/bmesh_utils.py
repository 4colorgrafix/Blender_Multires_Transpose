import bmesh
from ..data_types import MeshDomain, MeshLayerType
from typing import Iterable, Any
import operator

ALL_DOMAINS = {'faces', 'edges', 'verts', 'loops'}
ALL_POSSIBLE_LAYERS = {'bevel_weight', 'int', 'paint_mask', 'float_color', 'string', 'freestyle', 'skin', 'float_vector', 'uv', 'shape', 'deform', 'crease', 'face_map', 'color', 'float'}
GET_LAYER_FNS = [operator.attrgetter(f'{domain}.layers') for domain in ALL_DOMAINS]

# Dispatch tables replace the repeated match/get/new blocks
_DOMAIN_MAP = {
    MeshDomain.FACES: lambda bm: bm.faces,
    MeshDomain.LOOPS: lambda bm: bm.loops,
    MeshDomain.EDGES: lambda bm: bm.edges,
    MeshDomain.VERTS: lambda bm: bm.verts,
}

_LAYER_TYPE_MAP = {
    MeshLayerType.STRING:       lambda dom: dom.layers.string,
    MeshLayerType.INT:          lambda dom: dom.layers.int,
    MeshLayerType.FLOAT:        lambda dom: dom.layers.float,
    MeshLayerType.FLOAT_VECTOR: lambda dom: dom.layers.float_vector,
}


def resolve_domain_and_layer_type(bm: bmesh.types.BMesh, domain: MeshDomain, layer_type: MeshLayerType, layer_name: str) -> tuple[bmesh.types.BMElemSeq, Any]:
    """
    Resolve the domain and layer type to the corresponding bmesh domain and layer type.

    Args:
        bm (bmesh.types.BMesh): bmesh object to resolve domain and layer type on
        domain (MeshDomain): domain where the data is stored
        layer_type (MeshLayerType): type of the data
        layer_name (str): name of the data layer

    Returns:
        dom, layer: resolved domain and layer object
    """
    dom = _DOMAIN_MAP[domain](bm)
    layer_accessor = _LAYER_TYPE_MAP[layer_type](dom)
    layer = layer_accessor.get(layer_name) or layer_accessor.new(layer_name)
    return dom, layer


def write_layer_data(bm: bmesh.types.BMesh, domain: MeshDomain, layer_type: MeshLayerType, layer_name: str, data: Iterable[Any], start_index: int = 0) -> None:
    """
    Write custom data to a mesh's layer at one of its types, create the layer if it doesn't exist.

    Args:
        bm (bmesh.types.BMesh): bmesh object to write to
        domain (MeshDomain): Domain to write to
        layer_type (MeshLayerType): Layer type to write to
        layer_name (str): Name of the layer to write to
        data (Iterable[Any]): Data to write
        start_index (int, optional): Index to start writing data from. Defaults to 0.
    """
    dom, layer = resolve_domain_and_layer_type(bm, domain, layer_type, layer_name)
    # Encode strings to bytes; leave everything else as-is
    encoded = [d.encode() if isinstance(d, str) else d for d in data]
    # zip naturally stops at the shorter sequence — no explicit end index needed
    for element, value in zip(dom[start_index:], encoded):
        element[layer] = value


def read_layer_data(bm: bmesh.types.BMesh, domain: MeshDomain, layer_type: MeshLayerType, layer_name: str, uniform: bool = False, start_index: int = 0, size: int = None) -> Iterable[Any]:
    """
    Read custom data from a mesh's layer at one of its types, create the layer if it doesn't exist.

    Args:
        bm (bmesh.types.BMesh): bmesh object to read from
        domain (MeshDomain): Domain to read from
        layer_type (MeshLayerType): Layer type to read from
        layer_name (str): Name of the layer to read from
        uniform (bool, optional): Whether the data is expected to be the same across the mesh. Defaults to False.
        start_index (int, optional): Index to start reading data from. Defaults to 0.
        size (int, optional): Number of elements to read. Defaults to None (read all).

    Returns:
        Iterable[Any]: Data read
    """
    dom, layer = resolve_domain_and_layer_type(bm, domain, layer_type, layer_name)

    def _decode(v: Any) -> Any:
        return v.decode() if isinstance(v, bytes) else v

    if uniform:
        # Return the value of the first element, or None if the mesh is empty
        for element in dom:
            return _decode(element[layer])
        return None

    end = (start_index + size) if size is not None else None
    return [_decode(element[layer]) for element in dom[start_index:end]]


def copy_all_layers(src_bmesh: bmesh.types.BMesh, dst_bmesh: bmesh.types.BMesh) -> None:
    """
    Copy all layers from src_bmesh to dst_bmesh.

    Args:
        src_bmesh (bmesh.types.BMesh): bmesh to copy from
        dst_bmesh (bmesh.types.BMesh): bmesh to copy to
    """
    for get_layers in GET_LAYER_FNS:
        layers = get_layers(src_bmesh)
        layer_names = [name for name in dir(layers) if name in ALL_POSSIBLE_LAYERS]

        for layer_name in layer_names:
            attrs = getattr(layers, layer_name)
            dst_attrs = getattr(get_layers(dst_bmesh), layer_name)
            for name, _ in attrs.items():
                if name not in dst_attrs.keys():
                    dst_attrs.new(name)


def bmesh_from_faces(src_bmesh: bmesh.types.BMesh, faces: Iterable[bmesh.types.BMFace]) -> bmesh.types.BMesh:
    """
    Create a new bmesh from a given sequence of faces from the given src_bmesh.

    Args:
        src_bmesh (bmesh.types.BMesh): source bmesh to copy from
        faces (Iterable[bmesh.types.BMFace]): faces to copy

    Returns:
        bmesh.types.BMesh: new bmesh containing the given faces
    """
    dst_bmesh = bmesh.new()
    copy_all_layers(src_bmesh, dst_bmesh)

    faces = list(faces)  # allow multiple iteration
    all_verts = {v for f in faces for v in f.verts}
    min_index = min(v.index for v in all_verts)

    # Build an explicit vert_map so face creation is correct regardless of index contiguity
    vert_map: dict[int, bmesh.types.BMVert] = {}
    for v in sorted(all_verts, key=lambda v: v.index):
        nv = dst_bmesh.verts.new(v.co, v)
        nv.index = v.index - min_index
        vert_map[v.index] = nv

    dst_bmesh.verts.sort()
    dst_bmesh.verts.ensure_lookup_table()

    for face in faces:
        dst_bmesh.faces.new([vert_map[v.index] for v in face.verts], face)

    dst_bmesh.faces.index_update()
    dst_bmesh.faces.sort()
    return dst_bmesh


def bmesh_join(list_of_bmeshes: Iterable[bmesh.types.BMesh], normal_update: bool = False) -> bmesh.types.BMesh:
    """
    Takes as input a list of bmesh references and outputs a single merged bmesh.
    Layers from all source meshes are copied (not just the first).
    Allows an additional 'normal_update=True' to force normal calculations.

    Modified from https://blender.stackexchange.com/questions/50160/scripting-low-level-join-meshes-elements-hopefully-with-bmesh
    """
    bm = bmesh.new()

    for src in list_of_bmeshes:
        copy_all_layers(src, bm)

    for src_bm in list_of_bmeshes:
        vert_map = {}
        for v in src_bm.verts:
            nv = bm.verts.new(v.co)
            nv.normal = v.normal
            vert_map[v] = nv

        bm.verts.index_update()
        bm.verts.ensure_lookup_table()

        for face in src_bm.faces:
            nf = bm.faces.new([vert_map[v] for v in face.verts], face)
            nf.copy_from(face)

    bm.faces.index_update()

    if normal_update:
        bm.normal_update()

    return bm


def bmesh_copy_vert_location(src_bmesh: bmesh.types.BMesh, dst_bmesh: bmesh.types.BMesh) -> None:
    """
    Copy the vertex locations from src_bmesh to dst_bmesh by vertex indices.
    Both must have the same number of vertices.

    Args:
        src_bmesh (bmesh.types.BMesh): source bmesh to copy from
        dst_bmesh (bmesh.types.BMesh): destination bmesh to copy to
    """
    print(f"transpose verts: {len(src_bmesh.verts)}, original verts: {len(dst_bmesh.verts)}")

    if len(src_bmesh.verts) != len(dst_bmesh.verts):
        raise ValueError("src_bmesh and dst_bmesh must have the same number of vertices")

    for src_v, dst_v in zip(src_bmesh.verts, dst_bmesh.verts):
        dst_v.co = src_v.co
