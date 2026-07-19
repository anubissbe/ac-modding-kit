"""Generate original Ancient Cities Blender/FBX authoring examples.

Run only with the pinned Blender version documented in modeling/BLENDER_VERSION:

    blender --background --factory-startup --disable-autoexec \
      --python-exit-code 1 --python tools/blender/generate_all.py

The outputs are authoring examples, not drop-in game mods. No game or Workshop asset
is read, imported, reconstructed, or redistributed by this generator.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import bpy
from mathutils import Euler, Vector

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = REPO_ROOT / "modeling" / "assets"
EXPECTED_BLENDER = (5, 2, 0)
TEXTURE_SIZE = 256
WHITE = (1.0, 1.0, 1.0, 1.0)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PRIVATE_PNG_CHUNKS = {b"eXIf", b"iTXt", b"tEXt", b"tIME", b"zTXt"}
SANITIZED_FILE_BROWSER_DIRECTORY = (
    b"//.acmk-sanitized-file-browser/placeholder/placeholder/placeholder/"
)


@dataclass
class MeshBuilder:
    """Small deterministic triangle-mesh builder with per-face RGBA."""

    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    faces: list[tuple[int, int, int]] = field(default_factory=list)
    colors: list[tuple[float, float, float, float]] = field(default_factory=list)

    def _append(
        self,
        vertices: Sequence[Vector],
        faces: Sequence[tuple[int, int, int]],
        color: tuple[float, float, float, float],
    ) -> None:
        offset = len(self.vertices)
        self.vertices.extend(tuple(float(value) for value in vertex) for vertex in vertices)
        self.faces.extend(tuple(offset + index for index in face) for face in faces)
        self.colors.extend(color for _ in faces)

    def add_box(
        self,
        center: tuple[float, float, float],
        size: tuple[float, float, float],
        *,
        rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
        color: tuple[float, float, float, float] = WHITE,
    ) -> None:
        hx, hy, hz = (value / 2.0 for value in size)
        local = [
            Vector((-hx, -hy, -hz)),
            Vector((hx, -hy, -hz)),
            Vector((hx, hy, -hz)),
            Vector((-hx, hy, -hz)),
            Vector((-hx, -hy, hz)),
            Vector((hx, -hy, hz)),
            Vector((hx, hy, hz)),
            Vector((-hx, hy, hz)),
        ]
        matrix = Euler(rotation, "XYZ").to_matrix()
        origin = Vector(center)
        vertices = [matrix @ vertex + origin for vertex in local]
        faces = [
            (0, 2, 1),
            (0, 3, 2),
            (4, 5, 6),
            (4, 6, 7),
            (0, 1, 5),
            (0, 5, 4),
            (1, 2, 6),
            (1, 6, 5),
            (2, 3, 7),
            (2, 7, 6),
            (3, 0, 4),
            (3, 4, 7),
        ]
        self._append(vertices, faces, color)

    def add_cylinder_between(
        self,
        start: tuple[float, float, float],
        end: tuple[float, float, float],
        radius: float,
        *,
        sides: int = 8,
        color: tuple[float, float, float, float] = WHITE,
    ) -> None:
        start_v = Vector(start)
        end_v = Vector(end)
        axis = end_v - start_v
        if axis.length <= 1e-8:
            raise ValueError("cylinder endpoints must differ")
        direction = axis.normalized()
        helper = Vector((0.0, 0.0, 1.0))
        if abs(direction.dot(helper)) > 0.95:
            helper = Vector((1.0, 0.0, 0.0))
        tangent = direction.cross(helper).normalized()
        bitangent = direction.cross(tangent).normalized()
        vertices: list[Vector] = []
        for point in (start_v, end_v):
            for index in range(sides):
                angle = 2.0 * math.pi * index / sides
                vertices.append(
                    point + radius * (math.cos(angle) * tangent + math.sin(angle) * bitangent)
                )
        vertices.extend((start_v, end_v))
        start_center = 2 * sides
        end_center = start_center + 1
        faces: list[tuple[int, int, int]] = []
        for index in range(sides):
            following = (index + 1) % sides
            faces.extend(
                (
                    (index, following, sides + following),
                    (index, sides + following, sides + index),
                    (start_center, following, index),
                    (end_center, sides + index, sides + following),
                )
            )
        self._append(vertices, faces, color)

    def add_octahedron(
        self,
        center: tuple[float, float, float],
        scale: tuple[float, float, float],
        *,
        rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
        color: tuple[float, float, float, float] = WHITE,
    ) -> None:
        base = [
            Vector((1.0, 0.0, 0.0)),
            Vector((-1.0, 0.0, 0.0)),
            Vector((0.0, 1.0, 0.0)),
            Vector((0.0, -1.0, 0.0)),
            Vector((0.0, 0.0, 1.0)),
            Vector((0.0, 0.0, -1.0)),
        ]
        matrix = Euler(rotation, "XYZ").to_matrix()
        origin = Vector(center)
        scale_v = Vector(scale)
        vertices = [
            matrix @ Vector(tuple(a * b for a, b in zip(vertex, scale_v, strict=True))) + origin
            for vertex in base
        ]
        faces = [
            (4, 0, 2),
            (4, 2, 1),
            (4, 1, 3),
            (4, 3, 0),
            (5, 2, 0),
            (5, 1, 2),
            (5, 3, 1),
            (5, 0, 3),
        ]
        self._append(vertices, faces, color)

    def add_leaf(
        self,
        base: tuple[float, float, float],
        *,
        azimuth: float,
        length: float,
        width: float,
        lift: float,
        color: tuple[float, float, float, float],
    ) -> None:
        radial = Vector((math.cos(azimuth), math.sin(azimuth), 0.0))
        side = Vector((-math.sin(azimuth), math.cos(azimuth), 0.0))
        base_v = Vector(base)
        tip = base_v + radial * length + Vector((0.0, 0.0, lift))
        middle = (base_v + tip) * 0.5
        vertices = [
            base_v,
            middle + side * (width / 2.0),
            tip,
            middle - side * (width / 2.0),
        ]
        self._append(vertices, ((0, 1, 2), (0, 2, 3)), color)

    def build(self, name: str, material: bpy.types.Material) -> bpy.types.Object:
        mesh = bpy.data.meshes.new(f"{name}_Mesh")
        mesh.from_pydata(self.vertices, [], self.faces)
        mesh.update(calc_edges=True)
        obj = bpy.data.objects.new(name, mesh)
        bpy.context.scene.collection.objects.link(obj)
        mesh.materials.append(material)

        uv_layer = mesh.uv_layers.new(name="UVMap")
        for polygon in mesh.polygons:
            loops = list(polygon.loop_indices)
            first, second, third = (
                mesh.vertices[mesh.loops[loop_index].vertex_index].co for loop_index in loops
            )
            edge = second - first
            if edge.length <= 1e-8:
                raise ValueError(f"{name} contains a degenerate triangle edge")
            horizontal = edge.normalized()
            third_edge = third - first
            projected_u = third_edge.dot(horizontal)
            projected_v = math.sqrt(max(third_edge.length_squared - projected_u**2, 0.0))
            if projected_v <= 1e-8:
                raise ValueError(f"{name} contains a zero-area triangle")
            coordinates = ((0.0, 0.0), (edge.length, 0.0), (projected_u, projected_v))
            minimum_u = min(u for u, _ in coordinates)
            maximum_u = max(u for u, _ in coordinates)
            scale = max(maximum_u - minimum_u, projected_v)
            for loop_index, (u, v) in zip(loops, coordinates, strict=True):
                uv_layer.data[loop_index].uv = ((u - minimum_u) / scale, v / scale)

        color_layer = mesh.color_attributes.new(name="Color", type="BYTE_COLOR", domain="CORNER")
        for polygon, color in zip(mesh.polygons, self.colors, strict=True):
            for loop_index in polygon.loop_indices:
                color_layer.data[loop_index].color = color
            polygon.use_smooth = False
        try:
            mesh.color_attributes.active_color = color_layer
        except (AttributeError, TypeError):
            pass

        obj.location = (0.0, 0.0, 0.0)
        obj.rotation_euler = (0.0, 0.0, 0.0)
        obj.scale = (1.0, 1.0, 1.0)
        obj["ac_authoring_example"] = True
        return obj


def reset_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.length_unit = "METERS"
    scene.unit_settings.scale_length = 1.0
    scene.render.resolution_x = 512
    scene.render.resolution_y = 512
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    if scene.world is None:
        scene.world = bpy.data.worlds.new("World")
    scene.world.color = (0.035, 0.045, 0.055)


def make_material(name: str, color: tuple[float, float, float, float]) -> bpy.types.Material:
    material = bpy.data.materials.new(name)
    material.diffuse_color = color
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader is not None:
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Roughness"].default_value = 0.82
    material["ac_texture_C"] = "../textures/C.tga"
    material["ac_texture_N"] = "../textures/N.tga"
    material["ac_texture_T"] = "../textures/T.tga"
    material["ac_texture_O"] = "../textures/O.tga"
    return material


def ensure_directories(asset_dir: Path) -> None:
    for relative in ("source", "exports", "textures"):
        (asset_dir / relative).mkdir(parents=True, exist_ok=True)


def write_tga(
    path: Path,
    *,
    kind: str,
    base_color: tuple[int, int, int],
) -> None:
    width = height = TEXTURE_SIZE
    header = struct.pack(
        "<BBBHHBHHHHBB",
        0,
        0,
        2,
        0,
        0,
        0,
        0,
        0,
        width,
        height,
        32,
        0x28,
    )
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            checker = 8 if ((x // 32) + (y // 32)) % 2 == 0 else -8
            if kind == "C":
                red, green, blue = (max(0, min(255, value + checker)) for value in base_color)
                alpha = 255
            elif kind == "N":
                red, green, blue, alpha = 128, 128, 255, 64
            elif kind == "T":
                red = green = blue = 160
                alpha = 255
            elif kind == "O":
                red = green = blue = 255
                alpha = 255
            else:
                raise ValueError(f"unknown texture kind: {kind}")
            pixels.extend((blue, green, red, alpha))
    path.write_bytes(header + pixels)


def write_textures(asset_dir: Path, base_color: tuple[int, int, int]) -> list[Path]:
    outputs = []
    for kind in ("C", "N", "T", "O"):
        path = asset_dir / "textures" / f"{kind}.tga"
        write_tga(path, kind=kind, base_color=base_color)
        outputs.append(path)
    return outputs


def select_only(objects: Iterable[bpy.types.Object]) -> list[bpy.types.Object]:
    selected = list(objects)
    bpy.ops.object.select_all(action="DESELECT")
    for obj in selected:
        obj.hide_set(False)
        obj.select_set(True)
    if not selected:
        raise ValueError("at least one object must be selected")
    bpy.context.view_layer.objects.active = selected[0]
    return selected


def export_fbx(path: Path, objects: Iterable[bpy.types.Object]) -> None:
    selected = select_only(objects)
    for obj in selected:
        if obj.type != "MESH":
            raise ValueError(f"refusing to export non-mesh object {obj.name}")
    result = bpy.ops.export_scene.fbx(
        filepath=str(path),
        use_selection=True,
        object_types={"MESH"},
        use_mesh_modifiers=True,
        mesh_smooth_type="FACE",
        use_triangles=True,
        use_custom_props=True,
        add_leaf_bones=False,
        bake_anim=False,
        path_mode="STRIP",
        embed_textures=False,
        axis_forward="-Z",
        axis_up="Y",
        apply_unit_scale=True,
        apply_scale_options="FBX_SCALE_UNITS",
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"FBX export failed for {path}")


def object_bounds(objects: Sequence[bpy.types.Object]) -> tuple[Vector, Vector]:
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    minimum = Vector(tuple(min(point[index] for point in points) for index in range(3)))
    maximum = Vector(tuple(max(point[index] for point in points) for index in range(3)))
    return minimum, maximum


def look_at(obj: bpy.types.Object, target: Vector) -> None:
    obj.rotation_euler = (target - obj.location).to_track_quat("-Z", "Y").to_euler()


def strip_png_metadata(path: Path) -> None:
    """Remove Blender file paths, timestamps, and free-form text from a PNG."""

    source = path.read_bytes()
    if not source.startswith(PNG_SIGNATURE):
        raise ValueError(f"render did not produce a PNG: {path}")
    output = bytearray(PNG_SIGNATURE)
    offset = len(PNG_SIGNATURE)
    found_end = False
    while offset < len(source):
        if offset + 12 > len(source):
            raise ValueError(f"truncated PNG chunk in {path}")
        length = int.from_bytes(source[offset : offset + 4], "big")
        chunk_end = offset + 12 + length
        if chunk_end > len(source):
            raise ValueError(f"invalid PNG chunk length in {path}")
        chunk_type = source[offset + 4 : offset + 8]
        if chunk_type not in PRIVATE_PNG_CHUNKS:
            output.extend(source[offset:chunk_end])
        offset = chunk_end
        if chunk_type == b"IEND":
            found_end = True
            break
    if not found_end or offset != len(source):
        raise ValueError(f"invalid PNG termination in {path}")
    path.write_bytes(output)


def sanitize_file_browser_paths() -> None:
    """Prevent Blender's startup file browser from serializing a user directory."""

    bpy.context.preferences.filepaths.save_version = 0
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "FILE_BROWSER":
                continue
            params = getattr(area.spaces.active, "params", None)
            if params is not None:
                # Blender uses a fixed-size buffer here and may retain bytes beyond a
                # shorter replacement. A deliberately long neutral value overwrites the
                # complete startup directory instead of only its visible prefix.
                params.directory = SANITIZED_FILE_BROWSER_DIRECTORY
                params.filename = b""


def render_preview(path: Path, visible: Sequence[bpy.types.Object]) -> None:
    all_meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    for obj in all_meshes:
        obj.hide_render = obj not in visible

    minimum, maximum = object_bounds(visible)
    center = (minimum + maximum) * 0.5
    size = max((maximum - minimum).length, 1.0)

    camera_data = bpy.data.cameras.new("PreviewCamera")
    camera = bpy.data.objects.new("PreviewCamera", camera_data)
    bpy.context.scene.collection.objects.link(camera)
    camera.location = center + Vector((size * 1.25, -size * 1.6, size * 0.9))
    camera_data.lens = 52
    look_at(camera, center)
    bpy.context.scene.camera = camera

    key_data = bpy.data.lights.new("PreviewKey", type="AREA")
    key_data.energy = 900
    key_data.shape = "DISK"
    key_data.size = size * 1.4
    key = bpy.data.objects.new("PreviewKey", key_data)
    bpy.context.scene.collection.objects.link(key)
    key.location = center + Vector((size, -size, size * 1.8))
    look_at(key, center)

    fill_data = bpy.data.lights.new("PreviewFill", type="AREA")
    fill_data.energy = 450
    fill_data.size = size
    fill = bpy.data.objects.new("PreviewFill", fill_data)
    bpy.context.scene.collection.objects.link(fill)
    fill.location = center + Vector((-size, -size * 0.5, size))
    look_at(fill, center)

    ground_material = make_material("PreviewGroundMaterial", (0.08, 0.095, 0.11, 1.0))
    ground_builder = MeshBuilder()
    ground_builder.add_box(
        (center.x, center.y, minimum.z - 0.03),
        (size * 3.0, size * 3.0, 0.05),
    )
    ground = ground_builder.build("PreviewGround", ground_material)
    ground.hide_render = False

    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    strip_png_metadata(path)

    for obj in (camera, key, fill, ground):
        bpy.data.objects.remove(obj, do_unlink=True)
    for obj in all_meshes:
        obj.hide_render = False


def mesh_report(obj: bpy.types.Object) -> dict[str, object]:
    mesh = obj.data
    minimum, maximum = object_bounds([obj])
    return {
        "name": obj.name,
        "vertices": len(mesh.vertices),
        "triangles": len(mesh.polygons),
        "all_faces_triangles": all(len(polygon.vertices) == 3 for polygon in mesh.polygons),
        "bounds_m": {
            "min": [round(value, 6) for value in minimum],
            "max": [round(value, 6) for value in maximum],
        },
        "uv_layers": [layer.name for layer in mesh.uv_layers],
        "color_attributes": [layer.name for layer in mesh.color_attributes],
        "transform_identity": (
            tuple(round(value, 6) for value in obj.location) == (0.0, 0.0, 0.0)
            and tuple(round(value, 6) for value in obj.rotation_euler) == (0.0, 0.0, 0.0)
            and tuple(round(value, 6) for value in obj.scale) == (1.0, 1.0, 1.0)
        ),
    }


def write_report(
    asset_dir: Path,
    *,
    asset_id: str,
    category: str,
    rgba_mode: str | None,
    objects: Sequence[bpy.types.Object],
    exports: Sequence[Path],
) -> Path:
    report = {
        "schema_version": 1,
        "asset_id": asset_id,
        "category": category,
        "license": "MIT",
        "authoring_example": True,
        "runtime_tested": False,
        "contains_game_or_workshop_assets": False,
        "creation_method": "Procedurally generated from original primitive geometry",
        "ai_assistance": (
            "Generator design and documentation were AI-assisted; geometry is original"
        ),
        "blender": {
            "version": bpy.app.version_string,
            "build_hash": bpy.app.build_hash.decode("ascii"),
        },
        "scene": {"unit_system": "METRIC", "scale_length": 1.0, "source_up_axis": "Z"},
        "fbx": {
            "binary": True,
            "triangulated": True,
            "axis_forward": "-Z",
            "axis_up": "Y",
            "embedded_textures": False,
        },
        "rgba_mode": rgba_mode,
        "objects": [mesh_report(obj) for obj in objects],
        "exports": [path.relative_to(asset_dir).as_posix() for path in exports],
        "textures": [f"textures/{kind}.tga" for kind in ("C", "N", "T", "O")],
        "limitations": [
            "This is an authoring example, not a complete Ancient Cities mod.",
            "The running v1.9.3 game and Log.txt remain the final compatibility test.",
        ],
    }
    path = asset_dir / "report.json"
    path.write_bytes((json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return path


def write_checksums(asset_dir: Path, files: Sequence[Path]) -> None:
    unique = sorted(set(files), key=lambda item: item.relative_to(asset_dir).as_posix())
    lines = []
    for path in unique:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.relative_to(asset_dir).as_posix()}")
    (asset_dir / "checksums.sha256").write_bytes(("\n".join(lines) + "\n").encode("ascii"))


def finish_asset(
    asset_dir: Path,
    *,
    source_name: str,
    asset_id: str,
    category: str,
    rgba_mode: str | None,
    objects: Sequence[bpy.types.Object],
    exports: Sequence[Path],
    preview_objects: Sequence[bpy.types.Object],
    texture_color: tuple[int, int, int],
) -> None:
    source_path = asset_dir / "source" / source_name
    sanitize_file_browser_paths()
    result = bpy.ops.wm.save_as_mainfile(
        filepath=str(source_path),
        check_existing=False,
        compress=False,
        relative_remap=True,
    )
    if "FINISHED" not in result:
        raise RuntimeError(f"Blender source save failed for {source_path}")
    texture_paths = write_textures(asset_dir, texture_color)
    preview_path = asset_dir / "preview.png"
    render_preview(preview_path, preview_objects)
    report_path = write_report(
        asset_dir,
        asset_id=asset_id,
        category=category,
        rgba_mode=rgba_mode,
        objects=objects,
        exports=exports,
    )
    write_checksums(
        asset_dir,
        [source_path, *exports, *texture_paths, preview_path, report_path],
    )


def build_building() -> None:
    reset_scene()
    asset_dir = ASSET_ROOT / "building" / "starter_shelter"
    ensure_directories(asset_dir)
    material = make_material("StarterShelterMaterial", (0.42, 0.25, 0.11, 1.0))

    build = MeshBuilder()
    for x in (-1.6, 0.0, 1.6):
        for y in (-1.05, 1.05):
            build.add_cylinder_between((x, y, 0.0), (x, y, 1.65), 0.075)
    build.add_cylinder_between((-1.75, -1.05, 1.6), (1.75, -1.05, 1.6), 0.08)
    build.add_cylinder_between((-1.75, 1.05, 1.6), (1.75, 1.05, 1.6), 0.08)
    build_obj = build.build("StarterBuilding_Build_00", material)

    complete = MeshBuilder()
    for x in (-1.6, 0.0, 1.6):
        for y in (-1.05, 1.05):
            complete.add_cylinder_between((x, y, 0.0), (x, y, 1.65), 0.075)
    for y in (-1.05, 1.05):
        complete.add_box((0.0, y, 0.9), (3.35, 0.10, 1.55))
    complete.add_box((-1.65, 0.0, 0.9), (0.10, 2.0, 1.55))
    complete.add_box((1.65, 0.0, 0.9), (0.10, 2.0, 1.55))
    complete.add_box((0.0, -0.58, 1.82), (3.6, 1.65, 0.12), rotation=(0.45, 0.0, 0.0))
    complete.add_box((0.0, 0.58, 1.82), (3.6, 1.65, 0.12), rotation=(-0.45, 0.0, 0.0))
    default_obj = complete.build("StarterBuilding_Default", material)

    decay = MeshBuilder()
    for x, y in ((-1.6, -1.05), (-1.6, 1.05), (0.0, -1.05), (1.6, 1.05)):
        decay.add_cylinder_between((x, y, 0.0), (x, y, 1.65), 0.075)
    decay.add_box((0.0, -0.58, 1.82), (3.6, 1.65, 0.12), rotation=(0.45, 0.0, 0.0))
    decay.add_box((-1.65, 0.0, 0.75), (0.10, 2.0, 1.25))
    decay_obj = decay.build("StarterBuilding_Decay_00", material)

    collider_builder = MeshBuilder()
    collider_builder.add_box((0.0, 0.0, 1.1), (3.4, 2.15, 2.2))
    collider_obj = collider_builder.build("StarterBuilding_Collider", material)

    dark_builder = MeshBuilder()
    dark_builder.add_box((0.0, 0.0, 0.04), (3.2, 2.0, 0.08))
    dark_obj = dark_builder.build("StarterBuilding_Dark", material)

    blueprint_builder = MeshBuilder()
    blueprint_builder.add_box((0.0, 0.0, 0.025), (3.6, 2.4, 0.05))
    blueprint_obj = blueprint_builder.build("StarterBuilding_Blueprint", material)

    objects = [build_obj, default_obj, decay_obj, collider_obj, dark_obj, blueprint_obj]
    exports = []
    for obj in objects:
        path = asset_dir / "exports" / f"{obj.name}.fbx"
        export_fbx(path, [obj])
        exports.append(path)
    finish_asset(
        asset_dir,
        source_name="starter_shelter.blend",
        asset_id="starter_shelter",
        category="building",
        rgba_mode=None,
        objects=objects,
        exports=exports,
        preview_objects=[default_obj],
        texture_color=(116, 77, 42),
    )


def build_plant() -> None:
    reset_scene()
    asset_dir = ASSET_ROOT / "plant" / "starter_plant"
    ensure_directories(asset_dir)
    material = make_material("StarterPlantMaterial", (0.17, 0.44, 0.14, 1.0))
    neutral_wind = (0.0, 0.0, 0.0, 1.0)

    lod0 = MeshBuilder()
    lod0.add_cylinder_between((0.0, 0.0, 0.0), (0.0, 0.0, 0.58), 0.025, sides=6, color=neutral_wind)
    for index in range(10):
        lod0.add_leaf(
            (0.0, 0.0, 0.08 + 0.045 * index),
            azimuth=2.0 * math.pi * index / 10.0,
            length=0.34 - 0.012 * index,
            width=0.14,
            lift=0.16 + 0.008 * index,
            color=neutral_wind,
        )
    lod0_obj = lod0.build("LOD0", material)
    lod0_obj["ac_mode_rgba"] = "WindNone"

    lod1 = MeshBuilder()
    for angle in (0.0, math.pi / 2.0):
        side = Vector((-math.sin(angle), math.cos(angle), 0.0))
        vertices = (
            Vector((0.0, 0.0, 0.0)),
            -side * 0.18 + Vector((0.0, 0.0, 0.22)),
            -side * 0.11 + Vector((0.0, 0.0, 0.48)),
            Vector((0.0, 0.0, 0.65)),
            side * 0.11 + Vector((0.0, 0.0, 0.48)),
            side * 0.18 + Vector((0.0, 0.0, 0.22)),
        )
        lod1._append(
            vertices,
            ((0, 5, 1), (1, 5, 4), (1, 4, 2), (2, 4, 3)),
            neutral_wind,
        )
    lod1_obj = lod1.build("LOD1", material)
    lod1_obj["ac_mode_rgba"] = "WindNone"

    path = asset_dir / "exports" / "Mesh.fbx"
    export_fbx(path, [lod0_obj, lod1_obj])
    finish_asset(
        asset_dir,
        source_name="starter_plant.blend",
        asset_id="starter_plant",
        category="plant",
        rgba_mode="WindNone",
        objects=[lod0_obj, lod1_obj],
        exports=[path],
        preview_objects=[lod0_obj],
        texture_color=(61, 134, 49),
    )


def split_alpha(index: int, count: int) -> float:
    if count <= 1:
        return 254.0 / 255.0
    return round(254.0 * (count - 1 - index) / (count - 1)) / 255.0


def resource_object(
    name: str,
    positions: Sequence[tuple[float, float, float]],
    *,
    low_detail: bool,
    material: bpy.types.Material,
) -> bpy.types.Object:
    builder = MeshBuilder()
    count = len(positions)
    for index, position in enumerate(positions):
        alpha = split_alpha(index, count)
        scale = (0.16, 0.12, 0.10) if low_detail else (0.19, 0.14, 0.12)
        rotation = (0.15 * index, 0.21 * index, 0.37 * index)
        rotation_matrix = Euler(rotation, "XYZ").to_matrix()
        scaled_axes = (
            Vector((scale[0], 0.0, 0.0)),
            Vector((-scale[0], 0.0, 0.0)),
            Vector((0.0, scale[1], 0.0)),
            Vector((0.0, -scale[1], 0.0)),
            Vector((0.0, 0.0, scale[2])),
            Vector((0.0, 0.0, -scale[2])),
        )
        local_minimum_z = min((rotation_matrix @ vertex).z for vertex in scaled_axes)
        builder.add_octahedron(
            (position[0], position[1], position[2] - local_minimum_z),
            scale,
            rotation=rotation,
            color=(1.0, 1.0, 1.0, alpha),
        )
    obj = builder.build(name, material)
    obj["ac_mode_rgba"] = "ColorVSplit"
    return obj


def build_resource() -> None:
    reset_scene()
    asset_dir = ASSET_ROOT / "resource" / "starter_resource"
    ensure_directories(asset_dir)
    material = make_material("StarterResourceMaterial", (0.38, 0.31, 0.22, 1.0))

    resource = resource_object("Resource", [(0.0, 0.0, 0.0)], low_detail=False, material=material)
    heap_positions = [
        (-0.48, -0.35, 0.0),
        (-0.15, -0.42, 0.0),
        (0.22, -0.36, 0.0),
        (0.48, -0.18, 0.0),
        (-0.45, 0.04, 0.0),
        (-0.08, -0.02, 0.0),
        (0.28, 0.02, 0.0),
        (-0.25, 0.34, 0.0),
        (0.18, 0.32, 0.0),
    ]
    heap_lod0 = resource_object("Heap_LOD0", heap_positions, low_detail=False, material=material)
    heap_lod1 = resource_object(
        "Heap_LOD1", heap_positions[::2], low_detail=True, material=material
    )
    pile = resource_object(
        "PileContent",
        [
            (-0.22, -0.16, 0.0),
            (0.16, -0.18, 0.0),
            (-0.18, 0.16, 0.0),
            (0.2, 0.14, 0.0),
            (0.0, 0.0, 0.18),
        ],
        low_detail=False,
        material=material,
    )
    load = resource_object(
        "Load_Human",
        [(-0.12, 0.0, 0.0), (0.12, 0.0, 0.0), (0.0, 0.0, 0.16)],
        low_detail=False,
        material=material,
    )
    objects = [resource, heap_lod0, heap_lod1, pile, load]
    exports = []
    for obj in objects:
        path = asset_dir / "exports" / f"{obj.name}.fbx"
        export_fbx(path, [obj])
        exports.append(path)
    finish_asset(
        asset_dir,
        source_name="starter_resource.blend",
        asset_id="starter_resource",
        category="resource",
        rgba_mode="ColorVSplit",
        objects=objects,
        exports=exports,
        preview_objects=[heap_lod0],
        texture_color=(105, 86, 62),
    )


def main() -> None:
    if tuple(bpy.app.version) != EXPECTED_BLENDER:
        raise RuntimeError(f"expected Blender {EXPECTED_BLENDER}, got {tuple(bpy.app.version)}")
    build_building()
    build_plant()
    build_resource()
    print(f"Generated original starter models under {ASSET_ROOT}")


if __name__ == "__main__":
    main()
