"""Open and semantically validate the committed Blender and FBX starter models.

Run with the pinned Blender build documented in ``modeling/toolchain.lock.json``::

    blender --background --factory-startup --disable-autoexec \
      --python-exit-code 1 --python tools/blender/validate_models.py

This verifies authoring and interchange contracts. It cannot prove that Ancient Cities
accepts an asset at runtime; an isolated in-game test remains a separate manual step.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import bpy

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET_ROOT = REPO_ROOT / "modeling" / "assets"
EXPECTED_BLENDER = (5, 2, 0)
EPSILON = 1e-5


@dataclass(frozen=True)
class AssetContract:
    category: str
    asset_id: str
    source_name: str
    source_objects: tuple[str, ...]
    exports: dict[str, tuple[str, ...]]

    @property
    def directory(self) -> Path:
        return ASSET_ROOT / self.category / self.asset_id


CONTRACTS = (
    AssetContract(
        category="building",
        asset_id="starter_shelter",
        source_name="starter_shelter.blend",
        source_objects=(
            "StarterBuilding_Blueprint",
            "StarterBuilding_Build_00",
            "StarterBuilding_Collider",
            "StarterBuilding_Dark",
            "StarterBuilding_Decay_00",
            "StarterBuilding_Default",
        ),
        exports={
            "StarterBuilding_Blueprint.fbx": ("StarterBuilding_Blueprint",),
            "StarterBuilding_Build_00.fbx": ("StarterBuilding_Build_00",),
            "StarterBuilding_Collider.fbx": ("StarterBuilding_Collider",),
            "StarterBuilding_Dark.fbx": ("StarterBuilding_Dark",),
            "StarterBuilding_Decay_00.fbx": ("StarterBuilding_Decay_00",),
            "StarterBuilding_Default.fbx": ("StarterBuilding_Default",),
        },
    ),
    AssetContract(
        category="plant",
        asset_id="starter_plant",
        source_name="starter_plant.blend",
        source_objects=("LOD0", "LOD1"),
        exports={"Mesh.fbx": ("LOD0", "LOD1")},
    ),
    AssetContract(
        category="resource",
        asset_id="starter_resource",
        source_name="starter_resource.blend",
        source_objects=("Heap_LOD0", "Heap_LOD1", "Load_Human", "PileContent", "Resource"),
        exports={
            "Heap_LOD0.fbx": ("Heap_LOD0",),
            "Heap_LOD1.fbx": ("Heap_LOD1",),
            "Load_Human.fbx": ("Load_Human",),
            "PileContent.fbx": ("PileContent",),
            "Resource.fbx": ("Resource",),
        },
    ),
)


def fail(message: str) -> None:
    raise AssertionError(message)


def scene_meshes() -> list[bpy.types.Object]:
    return sorted(
        (obj for obj in bpy.context.scene.objects if obj.type == "MESH"), key=lambda obj: obj.name
    )


def assert_finite_mesh(obj: bpy.types.Object, label: str) -> None:
    for vertex in obj.data.vertices:
        if not all(math.isfinite(value) for value in vertex.co):
            fail(f"{label}: {obj.name} contains a non-finite vertex")


def assert_identity_transform(obj: bpy.types.Object, label: str) -> None:
    location = tuple(float(value) for value in obj.location)
    rotation = tuple(float(value) for value in obj.rotation_euler)
    scale = tuple(float(value) for value in obj.scale)
    if any(abs(value) > EPSILON for value in location + rotation):
        fail(f"{label}: {obj.name} has an unapplied location or rotation")
    if any(abs(value - 1.0) > EPSILON for value in scale):
        fail(f"{label}: {obj.name} has an unapplied scale")


def assert_mesh_contract(obj: bpy.types.Object, label: str, *, require_identity: bool) -> None:
    mesh = obj.data
    if not mesh.vertices or not mesh.polygons:
        fail(f"{label}: {obj.name} is empty")
    if any(len(polygon.vertices) != 3 for polygon in mesh.polygons):
        fail(f"{label}: {obj.name} is not fully triangulated")
    if "UVMap" not in mesh.uv_layers:
        fail(f"{label}: {obj.name} has no UVMap layer")
    if "Color" not in mesh.color_attributes:
        fail(f"{label}: {obj.name} has no Color vertex-RGBA attribute")
    color = mesh.color_attributes["Color"]
    if color.domain != "CORNER" or color.data_type != "BYTE_COLOR":
        fail(f"{label}: {obj.name} Color must be CORNER/BYTE_COLOR")
    if len(color.data) != len(mesh.loops):
        fail(f"{label}: {obj.name} Color does not cover every polygon corner")
    uv_layer = mesh.uv_layers["UVMap"]
    for polygon in mesh.polygons:
        first, second, third = (uv_layer.data[index].uv for index in polygon.loop_indices)
        signed_double_area = (second.x - first.x) * (third.y - first.y) - (second.y - first.y) * (
            third.x - first.x
        )
        if abs(signed_double_area) <= EPSILON:
            fail(f"{label}: {obj.name} contains a degenerate UV triangle")
    assert_finite_mesh(obj, label)
    if require_identity:
        assert_identity_transform(obj, label)


def assert_clean_source_scene(contract: AssetContract) -> list[bpy.types.Object]:
    source_path = contract.directory / "source" / contract.source_name
    if not source_path.is_file():
        fail(f"missing Blender source: {source_path.relative_to(REPO_ROOT)}")
    bpy.ops.wm.open_mainfile(filepath=str(source_path), load_ui=True, use_scripts=False)
    label = source_path.relative_to(REPO_ROOT).as_posix()

    if bpy.context.scene.unit_settings.system != "METRIC":
        fail(f"{label}: scene units must be metric")
    if abs(bpy.context.scene.unit_settings.scale_length - 1.0) > EPSILON:
        fail(f"{label}: scene scale_length must be 1.0")
    if bpy.data.libraries:
        fail(f"{label}: linked libraries are forbidden")
    if bpy.data.texts:
        fail(f"{label}: embedded scripts/text blocks are forbidden")
    if bpy.data.actions:
        fail(f"{label}: unexpected animation actions are forbidden in static starters")
    if bpy.data.images:
        fail(f"{label}: embedded or externally linked image datablocks are forbidden")
    animation_blocks = [
        *bpy.data.objects,
        *bpy.data.meshes,
        *bpy.data.materials,
        *bpy.data.scenes,
        *bpy.data.worlds,
        *bpy.data.node_groups,
    ]
    for datablock in animation_blocks:
        animation_data = getattr(datablock, "animation_data", None)
        if animation_data is not None and animation_data.drivers:
            fail(f"{label}: driver found on {datablock.name}")
    expected_texture_properties = {
        "ac_texture_C": "../textures/C.tga",
        "ac_texture_N": "../textures/N.tga",
        "ac_texture_O": "../textures/O.tga",
        "ac_texture_T": "../textures/T.tga",
    }
    for material in bpy.data.materials:
        actual = {key: material.get(key) for key in expected_texture_properties}
        if actual != expected_texture_properties:
            fail(f"{label}: {material.name} has unexpected external texture references")
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type != "FILE_BROWSER":
                continue
            params = getattr(area.spaces.active, "params", None)
            directory = bytes(params.directory).lower() if params is not None else b""
            if b":\\" in directory or b":/" in directory or directory.startswith(b"/home/"):
                fail(f"{label}: file browser contains a private absolute directory")
    non_mesh = sorted(obj.name for obj in bpy.context.scene.objects if obj.type != "MESH")
    if non_mesh:
        fail(f"{label}: source scene contains non-mesh objects: {non_mesh}")

    objects = scene_meshes()
    names = tuple(obj.name for obj in objects)
    if names != contract.source_objects:
        fail(f"{label}: expected objects {contract.source_objects}, got {names}")
    for obj in objects:
        assert_mesh_contract(obj, label, require_identity=True)
        if not bool(obj.get("ac_authoring_example")):
            fail(f"{label}: {obj.name} lacks the original-authoring marker")

    minimum_z = min(float(vertex.co.z) for obj in objects for vertex in obj.data.vertices)
    if minimum_z < -EPSILON:
        fail(f"{label}: geometry extends below ground by {-minimum_z:.6f} m")
    if minimum_z > EPSILON:
        fail(f"{label}: no source geometry touches the ground/origin plane")
    return objects


def alpha_u8_values(obj: bpy.types.Object) -> set[int]:
    layer = obj.data.color_attributes["Color"]
    return {round(float(item.color[3]) * 255.0) for item in layer.data}


def connected_components(obj: bpy.types.Object) -> list[set[int]]:
    adjacency = {vertex.index: set() for vertex in obj.data.vertices}
    for edge in obj.data.edges:
        first, second = edge.vertices
        adjacency[first].add(second)
        adjacency[second].add(first)
    remaining = set(adjacency)
    components: list[set[int]] = []
    while remaining:
        seed = remaining.pop()
        component = {seed}
        stack = [seed]
        while stack:
            current = stack.pop()
            neighbours = adjacency[current] & remaining
            remaining.difference_update(neighbours)
            component.update(neighbours)
            stack.extend(neighbours)
        components.append(component)
    return components


def component_alpha_values(obj: bpy.types.Object, component: set[int]) -> set[int]:
    layer = obj.data.color_attributes["Color"]
    return {
        round(float(layer.data[loop.index].color[3]) * 255.0)
        for loop in obj.data.loops
        if loop.vertex_index in component
    }


def assert_category_semantics(contract: AssetContract, objects: list[bpy.types.Object]) -> None:
    by_name = {obj.name: obj for obj in objects}
    label = f"{contract.category}/{contract.asset_id}"
    if contract.category == "plant":
        if len(by_name["LOD1"].data.polygons) >= len(by_name["LOD0"].data.polygons):
            fail(f"{label}: LOD1 must contain fewer triangles than LOD0")
        for obj in objects:
            if obj.get("ac_mode_rgba") != "WindNone":
                fail(f"{label}: {obj.name} must declare WindNone")
            for item in obj.data.color_attributes["Color"].data:
                red, green, blue, alpha = (float(value) for value in item.color)
                if max(abs(red), abs(green), abs(blue)) > 1.0 / 255.0:
                    fail(f"{label}: {obj.name} neutral WIND RGB must be zero")
                if abs(alpha - 1.0) > 1.0 / 255.0:
                    fail(f"{label}: {obj.name} unused alpha must be opaque")
    elif contract.category == "resource":
        if len(by_name["Heap_LOD1"].data.polygons) >= len(by_name["Heap_LOD0"].data.polygons):
            fail(f"{label}: Heap_LOD1 must contain fewer triangles than Heap_LOD0")
        for obj in objects:
            if obj.get("ac_mode_rgba") != "ColorVSplit":
                fail(f"{label}: {obj.name} must declare ColorVSplit")
            components = connected_components(obj)
            values = set()
            for component in components:
                alpha_values = component_alpha_values(obj, component)
                if len(alpha_values) != 1:
                    fail(f"{label}: {obj.name} has non-uniform split alpha in one element")
                values.update(alpha_values)
            if values != alpha_u8_values(obj):
                fail(f"{label}: {obj.name} split-alpha inspection is inconsistent")
        expected_values = {
            "Resource": {254},
            "Heap_LOD0": {0, 32, 64, 95, 127, 159, 190, 222, 254},
            "Heap_LOD1": {0, 64, 127, 190, 254},
            "PileContent": {0, 64, 127, 190, 254},
            "Load_Human": {0, 127, 254},
        }
        for name, expected in expected_values.items():
            actual = alpha_u8_values(by_name[name])
            if actual != expected:
                fail(f"{label}: {name} expected split alpha {expected}, got {actual}")


def import_fbx(path: Path) -> list[bpy.types.Object]:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    result = bpy.ops.import_scene.fbx(filepath=str(path), use_custom_normals=True)
    if "FINISHED" not in result:
        fail(f"FBX import failed: {path.relative_to(REPO_ROOT)}")
    return scene_meshes()


def assert_fbx_round_trip(contract: AssetContract) -> None:
    for filename, expected_names in contract.exports.items():
        path = contract.directory / "exports" / filename
        if not path.is_file():
            fail(f"missing FBX export: {path.relative_to(REPO_ROOT)}")
        label = path.relative_to(REPO_ROOT).as_posix()
        objects = import_fbx(path)
        names = tuple(obj.name for obj in objects)
        if names != expected_names:
            fail(f"{label}: expected mesh names {expected_names}, got {names}")
        for obj in objects:
            assert_mesh_contract(obj, label, require_identity=False)
            if any(abs(value) > 20.0 for vertex in obj.data.vertices for value in vertex.co):
                fail(f"{label}: imported coordinates exceed the 20 metre safety envelope")


def main() -> None:
    if tuple(bpy.app.version) != EXPECTED_BLENDER:
        fail(f"expected Blender {EXPECTED_BLENDER}, got {tuple(bpy.app.version)}")
    for contract in CONTRACTS:
        source_objects = assert_clean_source_scene(contract)
        assert_category_semantics(contract, source_objects)
        assert_fbx_round_trip(contract)
        print(f"PASS {contract.category}/{contract.asset_id}")
    print("All Blender and FBX semantic model checks passed")


if __name__ == "__main__":
    main()
