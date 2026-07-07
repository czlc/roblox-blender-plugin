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

"""
Returns upload targets selected in any outliner by the user.
If an uploadable object is selected, its first user collection is returned as the upload target.
For a collection to be selectable, it must contain an uploadable descendant.
"""

import bpy

UPLOADABLE_TYPES = [
    bpy.types.Mesh,
    bpy.types.Armature,
    bpy.types.Curve,
    bpy.types.MetaBall,
    bpy.types.Text,
]


def __is_uploadable_object(instance):
    is_object = isinstance(instance, bpy.types.Object)
    if not is_object:
        return False
    is_uploadable_type = any(isinstance(instance.data, uploadable_type) for uploadable_type in UPLOADABLE_TYPES)
    return is_uploadable_type


def __contains_uploadable_object(collection):
    if isinstance(collection, bpy.types.Collection):
        return any(__is_uploadable_object(child) for child in collection.all_objects)
    else:
        return False


def __is_user_collection(collection):
    return any(collection == user_collection for user_collection in bpy.data.collections)


def __get_first_user_collection(instance):
    if not __is_uploadable_object(instance):
        return None

    user_collection = next(
        (collection for collection in instance.users_collection if __is_user_collection(collection)),
        None,
    )
    if user_collection:
        return user_collection

    if instance.users_collection:
        return instance.users_collection[0]

    return None


def __get_upload_target(instance):
    if isinstance(instance, bpy.types.Collection):
        return instance if __contains_uploadable_object(instance) else None

    return __get_first_user_collection(instance)


def get_selected_objects(context):
    """Returns a list of collection upload targets across all OUTLINER and VIEW_3D contexts"""
    current_area = context.area
    upload_targets = []

    # To get the complete selection we need to iterate over all outliner objects as it is possible the user
    # may have multiple open
    for area in context.screen.areas:
        # We cannot override the context to the current area
        if area == current_area:
            continue
        if area.type == "OUTLINER" or area.type == "VIEW_3D":
            for region in area.regions:
                if region.type == "WINDOW":
                    # Temporary context override requires Blender version >= 3.2.0
                    with context.temp_override(area=area, region=region):
                        for selected_object in context.selected_ids:
                            # Avoid double-counting objects that are selected in multiple outliners
                            upload_target = __get_upload_target(selected_object)
                            if not upload_target or upload_target in upload_targets:
                                continue

                            upload_targets.append(upload_target)

    return upload_targets
