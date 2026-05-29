import bpy
import bmesh
import time
import logging
from .data_types import MeshDomain, MeshLayerType
from .utils.bmesh_context import bmesh_from_obj
from .utils.utils import copy_multires_objs_to_new_mesh, create_meshes_by_original_name, restore_vertex_index
from .utils.utils import ORIGINAL_SUBDIVISION_LEVEL_LAYER
from .utils.bmesh_utils import bmesh_copy_vert_location, read_layer_data
import numpy as np

TRANSPOSE_TARGET_NAME = "Multires_Transpose_Target"


class LoggerOperator(bpy.types.Operator):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(__name__ + "." + self.__class__.__name__)


class MULTIRES_TRANSPOSE_OT_create_transpose_target(LoggerOperator):
    bl_idname = "multires_transpose.create_transpose_target"
    bl_label = "Create Transpose Target"
    bl_options = {'REGISTER', 'UNDO'}

    multires_level: bpy.props.IntProperty(
        name="Multires Level",
        default=0,
        min=0,
        description="Multires subdivision level to use when creating the transpose target. "
                    "Only used if 'Use Multires Level As Is' is disabled"
    )
    use_multires_level_as_is: bpy.props.BoolProperty(
        name="Use Multires Level As Is",
        default=False,
        description="Use the current multires level of the selected objects for the transpose target"
    )
    include_non_multires: bpy.props.BoolProperty(
        name="Include Non-Multires Objects",
        default=False,
        description="Include objects that do not have a multires modifier in the transpose target"
    )
    hide_original: bpy.props.BoolProperty(
        name="Hide Original Objects",
        default=True,
        description="Hide the original objects after creating the transpose target"
    )

    def execute(self, context):
        start_time = time.time()
        multires_level = self.multires_level if not self.use_multires_level_as_is else None
        transpose_target, merged_objs = copy_multires_objs_to_new_mesh(
            context, context.selected_objects, multires_level, self.include_non_multires
        )
        transpose_target.name = TRANSPOSE_TARGET_NAME

        for obj in context.selected_objects:
            # Applies location, rotation, and scale
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            obj.select_set(False)

        if self.hide_original:
            for obj in merged_objs:
                obj.hide_set(True)

        context.view_layer.objects.active = transpose_target
        transpose_target.select_set(True)

        print(f"Time taken to create Transpose Target: {time.time() - start_time:.4f}s")
        return {"FINISHED"}

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.label(text="Settings:", icon="SETTINGS")

        col.prop(self, "use_multires_level_as_is", text="Use Multires Level As Is")
        col.prop(self, "include_non_multires", text="Include Non-Multires Objects")
        col.prop(self, "hide_original", text="Hide Original Objects")

        row = col.row()
        row.prop(self, "multires_level", text="Freeze Multires Level at")
        row.enabled = not self.use_multires_level_as_is

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


class MULTIRES_TRANSPOSE_OT_apply_transpose_target(LoggerOperator):
    bl_idname = "multires_transpose.apply_transpose_target"
    bl_label = "Apply Transpose Target"
    bl_options = {'REGISTER', 'UNDO'}

    threshold: bpy.props.FloatProperty(
        name="Threshold",
        default=0.01,
        min=0.0,
        step=0.01,
        description="Convergence threshold for auto-iterations. "
                    "Iteration stops when the max vertex delta falls below this value"
    )
    auto_iterations: bpy.props.BoolProperty(
        name="Auto Iterations",
        default=False,
        description="Automatically apply reshape until the threshold is reached"
    )
    max_auto_iterations: bpy.props.IntProperty(
        name="Max Auto Iterations",
        default=100,
        min=1,
        description="Maximum number of reshape iterations when Auto Iterations is enabled"
    )
    iterations: bpy.props.IntProperty(
        name="Max Iterations",
        default=1,
        min=1,
        description="Number of reshape iterations. Only used if Auto Iterations is disabled"
    )
    hide_transpose: bpy.props.BoolProperty(
        name="Hide Transpose Target",
        default=True,
        description="Hide the transpose target after applying it"
    )

    def execute(self, context):
        start_time = time.time()
        active_obj = context.active_object

        # Applies location, rotation, and scale
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

        # Split the merged transpose target back into per-object meshes
        transpose_targets = create_meshes_by_original_name(active_obj)
        print(f"Created {len(transpose_targets)} transpose targets")

        for target_obj in transpose_targets:
            # Derive the original object name by stripping the "_Target" suffix
            substr =  target_obj.name.split("_Target")
            original_obj_name = substr[0]
            if original_obj_name not in bpy.data.objects:
                print(
                    f"Object '{target_obj.name}' does not have a matching original object, skipping"
                )
                continue

            original_obj = bpy.data.objects[original_obj_name]
            original_obj.hide_set(False)

            with bmesh_from_obj(target_obj, write_back=False) as bm:
                # Restore vertex indices that may have been reordered during the split
                # restore_vertex_index(bm)
                # Undo the world-space transform that was baked in during target creation
                # bmesh.ops.transform(bm, verts=bm.verts, matrix=original_obj.matrix_world.inverted())

                original_multires_level = read_layer_data(
                    bm, MeshDomain.VERTS, MeshLayerType.INT,
                    ORIGINAL_SUBDIVISION_LEVEL_LAYER, uniform=True
                )

                if original_multires_level > 0:
                    print("Multires level > 0")
                    # Flush bmesh edits to the mesh data so the reshape operator can read them
                    bm.to_mesh(target_obj.data)

                    with bpy.context.temp_override(
                        object=original_obj,
                        selected_editable_objects=(original_obj, target_obj)
                    ):
                        multires_modifier = original_obj.modifiers[0]
                        saved_level = multires_modifier.levels
                        multires_modifier.levels = original_multires_level

                        if not self.auto_iterations:
                            for _ in range(self.iterations):
                                bpy.ops.object.multires_reshape(modifier=multires_modifier.name)
                        else:
                            diff = self.threshold + 1
                            last_diff = 0
                            iteration = 0
                            prev_verts = None

                            while (
                                diff > self.threshold
                                and abs(diff - last_diff) > 1e-5
                                and iteration < self.max_auto_iterations
                            ):
                                bpy.ops.object.multires_reshape(modifier=multires_modifier.name)

                                multires_mesh = context.evaluated_depsgraph_get().objects[original_obj.name].data
                                curr_verts = np.array([v.co for v in multires_mesh.vertices])

                                if prev_verts is not None:
                                    if curr_verts.shape != prev_verts.shape:
                                        print(
                                            "Vertex count changed between iterations — stopping early"
                                        )
                                        break
                                    last_diff = diff
                                    diff = np.abs(curr_verts - prev_verts).max()

                                prev_verts = curr_verts
                                iteration += 1

                            print(
                                f"\n{'=' * 60}\n"
                                f"Auto Reshape for '{original_obj.name}' finished:\n"
                                f"  {'Threshold:':<20}{self.threshold}\n"
                                f"  {'Final diff:':<20}{diff}\n"
                                f"  {'Last diff:':<20}{last_diff}\n"
                                f"  {'Iterations:':<20}{iteration}/{self.max_auto_iterations}\n"
                                f"{'=' * 60}"
                            )

                        multires_modifier.levels = saved_level

                else:
                    print("Multires level == 0 or no multires modifier")
                    # Level 0 or no multires modifier (level == -1): copy verts directly
                    with bmesh_from_obj(original_obj) as obm:
                        print(f"{original_obj.name} converted")
                        bmesh_copy_vert_location(bm, obm)

        # Remove temporary split objects
        for obj in transpose_targets:
            bpy.data.objects.remove(obj, do_unlink=True, do_id_user=True, do_ui_user=True)

        if self.hide_transpose:
            active_obj.hide_set(True)

        print(f"Time taken to apply Transpose Target: {time.time() - start_time:.4f}s")
        return {'FINISHED'}

    def draw(self, context):
        layout = self.layout
        col = layout.column()
        col.label(text="Settings:", icon="SETTINGS")

        col.prop(self, "auto_iterations", text="Auto Iterations (may take a while)")
        col.prop(self, "hide_transpose", text="Hide Transpose Target")

        row = col.row()
        if self.auto_iterations:
            row.prop(self, "threshold", text="Threshold")
            row.prop(self, "max_auto_iterations", text="Max Iterations")
        else:
            row.prop(self, "iterations", text="Reshape Iterations")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)


classes = (
    MULTIRES_TRANSPOSE_OT_create_transpose_target,
    MULTIRES_TRANSPOSE_OT_apply_transpose_target,
)

register, unregister = bpy.utils.register_classes_factory(classes)