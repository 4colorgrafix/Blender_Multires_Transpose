# Multires Transpose
An addon inspired by ZBrush's Transpose Master Plugin. It aims to mimic that functionality by allowing the user to edit an arbitrary number of multiresolution modifier-enabled meshes at once through a single proxy mesh, with support for objects with different subdivison levels, as well as meshes without the multires modifier.


## How to use:
UI Panel located in the sidebar of the 3D viewport under `Edit > Multires Transpose`.
1. Select meshes to create a Transpose Target proxy mesh.
2. Click `Create Transpose Target` to create a proxy mesh.
3. Make changes to the proxy mesh.
4. Click `Apply Transpose Target` to apply the changes to the original meshes.

## Features:

* Allows editing an arbitrary number of multiresolution modifier-enabled meshes at once through creating a single proxy mesh.
    * This proxy mesh can be created through the Create Transpose Target operator.
    * Once the Multires level is frozen, higher levels are erased. Lower levels can be reconstructed with the Multires modifier.
* Changes to the proxy mesh can be propagated back to the original meshes with the Apply Transpose Target operator.
    * Modifiers can be used on the proxy mesh, this allows you to rig the proxy mesh or use other modifiers.
    * This makes use of the multires modifier's reshape operator, which may not propagate the changes with 100% accuracy.
    * You can specify the number of iterations to apply the reshape operator to improve the accuracy of the changes.
        * Use auto iteration to automatically reshape the mesh until the changes are within a specified threshold, or until the specified number of iterations have been reached.
* Multiple Transpose Targets can be created to store different poses.

## Original Code by Bowen Wu

Requires Blender 3.0 or later.
Multires Tranpose Version 1.0.2:

https://github.com/19829984/Blender_Multires_Transpose/assets/57331630/7cfed5dc-f0de-46e2-a534-f9e1a5b3fcf5
https://github.com/19829984/Blender_Multires_Transpose/assets/57331630/0889b592-a5b5-4d20-a5f2-81b7202f1303
https://github.com/19829984/Blender_Multires_Transpose

## UPDATE by 4ColorGrafix

Requires Blender 4.5.5 or later.
Multires Transpose Version 2.0.0

* Technical changes to files:
  * bmesh_utils.py — dispatch dicts replace the repeated match blocks; write_layer_data slice bug fixed; bmesh_from_faces uses a vert_map dict for correctness; 
    bmesh_join copies layers from all source meshes and also uses per-mesh vert_map.
  * utils.py — return type annotation corrected (List not set); create_meshes_by_original_name passes face objects directly instead of a fragile contiguous 
    slice;  source bmeshes freed immediately after joining.
  * multires_transpose.py — double assignment replaced with str.removesuffix; logger.warn → print; auto-iterations now compares consecutive evaluated 
    states (not mismatched vert counts) with a shape guard; timing logs displays 4 decimal places; Applies transpose matrix to original meshes.
  * ui.py — bl_label added to base class; poll added so panel only appears with an active mesh.
  * bmesh_context.py — added try/finally so the bmesh is always freed even if an exception is raised.

### Known Limitations
Facesets may not be preserved when creating the transpose target

Does not work with multiuser data (instancing)
