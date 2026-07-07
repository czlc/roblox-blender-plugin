# Copyright © 2023 Roblox Corporation

# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
# associated documentation files (the “Software”), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do
# so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all copies or substantial
# portions of the Software.

# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
# FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS
# OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

# SPDX-License-Identifier: MIT

import bpy

VERTEX_COLOR_ATTRIBUTE_NAME = "Col"
DEFAULT_VERTEX_COLOR = (1.0, 1.0, 1.0, 1.0)


def __find_wrapping_layer_collection_recursively(layer_collection, target_collection):
    """Recursively finds the LayerCollection that wraps a target collection"""
    if layer_collection.collection == target_collection:
        return layer_collection

    for nested_layer_collection in layer_collection.children:
        result = __find_wrapping_layer_collection_recursively(nested_layer_collection, target_collection)
        if result:
            return result


def __get_export_objects(target_object):
    if isinstance(target_object, bpy.types.Collection):
        return target_object.all_objects
    return [target_object]


def __duplicate_mesh_data_for_baking(target_object):
    temporary_mesh_data = []
    temporary_materials = []

    for obj in __get_export_objects(target_object):
        if not isinstance(obj, bpy.types.Object) or obj.type != "MESH":
            continue

        original_mesh = obj.data
        baked_mesh = original_mesh.copy()
        obj.data = baked_mesh
        temporary_mesh_data.append((obj, original_mesh, baked_mesh))

        for material_index, material in enumerate(baked_mesh.materials):
            if material:
                copied_material = material.copy()
                baked_mesh.materials[material_index] = copied_material
                temporary_materials.append(copied_material)

    return temporary_mesh_data, temporary_materials


def __restore_mesh_data(temporary_mesh_data, temporary_materials):
    for obj, original_mesh, baked_mesh in reversed(temporary_mesh_data):
        obj.data = original_mesh
        if baked_mesh.users == 0:
            bpy.data.meshes.remove(baked_mesh)

    for material in temporary_materials:
        if material.users == 0:
            bpy.data.materials.remove(material)


def __ensure_vertex_color_attribute(mesh):
    color_attributes = getattr(mesh, "color_attributes", None)
    # NOTE: an empty color_attributes collection is falsy, so test for API presence
    # with "is not None" — otherwise meshes that don't already have a color layer
    # would never get one created, and nothing would be baked.
    if color_attributes is not None:
        existing_attribute = color_attributes.get(VERTEX_COLOR_ATTRIBUTE_NAME)
        if existing_attribute:
            color_attributes.remove(existing_attribute)

        color_attribute = color_attributes.new(
            name=VERTEX_COLOR_ATTRIBUTE_NAME,
            type="FLOAT_COLOR",
            domain="CORNER",
        )
        attribute_index = list(color_attributes).index(color_attribute)
        try:
            color_attributes.active_color = color_attribute
        except Exception:
            pass
        try:
            color_attributes.active_color_index = attribute_index
        except Exception:
            pass
        try:
            color_attributes.render_color_index = attribute_index
        except Exception:
            pass
        return color_attribute

    vertex_colors = getattr(mesh, "vertex_colors", None)
    if vertex_colors is not None:
        existing_attribute = vertex_colors.get(VERTEX_COLOR_ATTRIBUTE_NAME)
        if existing_attribute:
            vertex_colors.remove(existing_attribute)

        color_attribute = vertex_colors.new(name=VERTEX_COLOR_ATTRIBUTE_NAME)
        try:
            vertex_colors.active_index = list(vertex_colors).index(color_attribute)
        except Exception:
            pass
        return color_attribute

    return None


def __srgb_to_linear(channel):
    if channel <= 0.04045:
        return channel / 12.92
    return ((channel + 0.055) / 1.055) ** 2.4


def __get_material_base_color(material):
    """Returns a material's flat RGBA color in linear space.

    Prefers the Base Color of a Principled BSDF node when it is a flat value
    (not driven by a texture or other node), and otherwise falls back to the
    material's viewport display color. Blender already stores both of these in
    linear space, matching the linear values produced by image sampling below.
    """
    if not material:
        return DEFAULT_VERTEX_COLOR

    if material.use_nodes and material.node_tree:
        for node in material.node_tree.nodes:
            if node.type != "BSDF_PRINCIPLED":
                continue

            base_color_input = node.inputs.get("Base Color")
            if base_color_input and not base_color_input.is_linked:
                color = base_color_input.default_value
                return (color[0], color[1], color[2], color[3])
            break

    diffuse_color = material.diffuse_color
    return (diffuse_color[0], diffuse_color[1], diffuse_color[2], diffuse_color[3])


def __get_material_image(material):
    """Returns the image a material is colored by (e.g. a palette texture).

    Prefers the image feeding the Principled BSDF Base Color, and otherwise
    falls back to any image texture node in the material."""
    if not material or not material.use_nodes or not material.node_tree:
        return None

    for node in material.node_tree.nodes:
        if node.type != "BSDF_PRINCIPLED":
            continue
        base_color_input = node.inputs.get("Base Color")
        if base_color_input and base_color_input.is_linked:
            from_node = base_color_input.links[0].from_node
            if from_node.type == "TEX_IMAGE" and from_node.image:
                return from_node.image
        break

    for node in material.node_tree.nodes:
        if node.type == "TEX_IMAGE" and node.image:
            return node.image

    return None


def __get_image_pixels(image_pixel_cache, image):
    if image.name not in image_pixel_cache:
        width, height = image.size
        if width == 0 or height == 0:
            image_pixel_cache[image.name] = None
        else:
            image_pixel_cache[image.name] = (image.pixels[:], width, height)

    return image_pixel_cache[image.name]


def __sample_image(image_pixel_cache, image, uv):
    """Samples an image at a UV coordinate, returning linear RGBA (alpha kept raw)."""
    image_data = __get_image_pixels(image_pixel_cache, image)
    if not image_data:
        return None

    pixels, width, height = image_data
    u = uv[0] % 1.0
    v = uv[1] % 1.0
    pixel_x = min(int(u * width), width - 1)
    pixel_y = min(int(v * height), height - 1)
    pixel_index = (pixel_y * width + pixel_x) * 4

    return (
        __srgb_to_linear(pixels[pixel_index]),
        __srgb_to_linear(pixels[pixel_index + 1]),
        __srgb_to_linear(pixels[pixel_index + 2]),
        pixels[pixel_index + 3],
    )


def __bake_object_material_colors_to_vertex_colors(obj):
    mesh = obj.data
    if not mesh.materials:
        return False

    # Resolve each material slot to a palette image (sampled per UV) and/or a flat color.
    material_images = {}
    material_flat_colors = {}
    for material_index, material in enumerate(mesh.materials):
        material_flat_colors[material_index] = __get_material_base_color(material)
        image = __get_material_image(material)
        if image:
            material_images[material_index] = image

    color_attribute = __ensure_vertex_color_attribute(mesh)
    if not color_attribute:
        return False

    uv_data = None
    if mesh.uv_layers and mesh.uv_layers.active:
        uv_data = mesh.uv_layers.active.uv

    image_pixel_cache = {}
    baked_any_color = False
    for polygon in mesh.polygons:
        image = material_images.get(polygon.material_index)
        flat_color = material_flat_colors.get(polygon.material_index, DEFAULT_VERTEX_COLOR)
        for loop_index in polygon.loop_indices:
            color = None
            if image is not None and uv_data is not None:
                color = __sample_image(image_pixel_cache, image, uv_data[loop_index].vector)
            if color is None:
                color = flat_color
            color_attribute.data[loop_index].color = color
            baked_any_color = True

    mesh.update()
    return baked_any_color


def __bake_material_colors_to_vertex_colors(target_object):
    for obj in __get_export_objects(target_object):
        if not isinstance(obj, bpy.types.Object) or obj.type != "MESH":
            continue

        __bake_object_material_colors_to_vertex_colors(obj)


def __strip_textures_from_materials(materials):
    """Removes image texture nodes from (temporary) materials so the exported FBX
    carries no texture references. Without this, embed_textures would upload the
    material's images and Roblox would assign a TextureID to the mesh even though
    the color is already baked into vertex colors."""
    for material in materials:
        if not material or not material.use_nodes or not material.node_tree:
            continue

        nodes = material.node_tree.nodes
        for node in list(nodes):
            if node.type == "TEX_IMAGE":
                nodes.remove(node)


def __export_scene_fbx(export_options, export_vertex_colors):
    if not export_vertex_colors:
        bpy.ops.export_scene.fbx(**export_options)
        return

    # Roblox interprets FBX vertex colors as sRGB (this matches Blender's default
    # FBX export and the vertex-color import workflow documented on the DevForum).
    # The baked values are scene-linear, so exporting as SRGB reproduces the color
    # the user picked in Blender.
    try:
        bpy.ops.export_scene.fbx(**export_options, colors_type="SRGB")
    except TypeError:
        bpy.ops.export_scene.fbx(**export_options)


def export_fbx(scene, view_layer, target_object, exported_file_path, preferences):
    """Exports the given object to a FBX file in the given directory_path, subject to the given preferences"""
    collection = None
    temporary_mesh_data = []
    temporary_materials = []

    # If the object is not a collection, we'll need to create a temporary collection to house it for export
    is_collection = isinstance(target_object, bpy.types.Collection)
    if not is_collection:
        collection = bpy.data.collections.new("RobloxExportCollection")
        scene.collection.children.link(collection)
        collection.objects.link(target_object)
    else:
        collection = target_object

    # Identify the LayerCollection corresponding with our Collection
    layer_collection = __find_wrapping_layer_collection_recursively(view_layer.layer_collection, collection)
    # Store the previous active collection so we can reset it later
    previous_active_layer_collection = view_layer.active_layer_collection
    # Set the current active LayerCollection to the LayerCollection corresponding with our Layer
    # This method is called synchronously on the main thread, so we do not need to worry about user
    # input interfering with this selection during export
    view_layer.active_layer_collection = layer_collection

    # Ensure cleanup happens while still passing export exceptions through
    try:
        if preferences.bake_texture_to_vertex_colors:
            temporary_mesh_data, temporary_materials = __duplicate_mesh_data_for_baking(target_object)
            __bake_material_colors_to_vertex_colors(target_object)
            # The color now lives in vertex colors, so drop textures to avoid uploading
            # them and having Roblox assign a TextureID to the mesh.
            __strip_textures_from_materials(temporary_materials)

        # Because we are using the use_active_collection parameter when we export, only objects from the collection
        # specified will be exported
        __export_scene_fbx(
            {
                "filepath": str(exported_file_path),
                "global_scale": preferences.export_scale,
                "bake_anim": preferences.bake_anim,
                "bake_anim_use_all_bones": preferences.bake_anim_use_all_bones,
                "bake_anim_use_nla_strips": preferences.bake_anim_use_nla_strips,
                "bake_anim_use_all_actions": preferences.bake_anim_use_all_actions,
                "bake_anim_force_startend_keying": preferences.bake_anim_force_startend_keying,
                "bake_anim_step": preferences.bake_anim_step,
                "bake_anim_simplify_factor": preferences.bake_anim_simplify_factor,
                "axis_forward": "-Z",
                "axis_up": "Y",
                # When baking to vertex colors we strip textures, so don't embed any.
                "path_mode": "STRIP" if preferences.bake_texture_to_vertex_colors else "COPY",
                "embed_textures": not preferences.bake_texture_to_vertex_colors,
                "use_active_collection": True,
                "add_leaf_bones": preferences.add_leaf_bones,
                "use_custom_props": preferences.use_custom_props,
            },
            preferences.bake_texture_to_vertex_colors,
        )
    finally:
        # Return to the previous active LayerCollection
        view_layer.active_layer_collection = previous_active_layer_collection
        __restore_mesh_data(temporary_mesh_data, temporary_materials)

        # If we had to make a temporary collection, remove it
        if not is_collection:
            bpy.data.collections.remove(collection)

    return exported_file_path
