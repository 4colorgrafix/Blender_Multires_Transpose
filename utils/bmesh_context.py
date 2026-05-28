import bmesh
import contextlib


@contextlib.contextmanager
def bmesh_from_obj(obj, write_back=True):
    """
    Context manager that creates a BMesh from obj.data, yields it, and optionally
    writes it back and frees it on exit.

    Args:
        obj: Blender object whose mesh data to wrap
        write_back (bool): If True, writes the bmesh back to obj.data on exit. Defaults to True.
    """
    mesh_data = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh_data)
    try:
        yield bm
    finally:
        if write_back:
            bm.to_mesh(mesh_data)
        bm.free()