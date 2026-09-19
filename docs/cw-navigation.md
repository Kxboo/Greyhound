# Cold War navigation and progression

[Documentation index](README.md) | [Contributing](contributing.md)

Navigation tools are developer workflows under
[CW capture](../tools/cold_war/capture/) and
[CW brushes](../tools/cold_war/brushes/). The normal export button does not
automatically capture and convert the navigation graph.

## Start with matching source evidence

Capture ENTITYLIST for the loaded map, then use
[capture_cw_navigation_nodes.py](../tools/cold_war/capture/capture_cw_navigation_nodes.py)
to collect bounded GAME_MAP records. This live tool requires the matching raw
entity capture, process ID and current module base; obtain them from the active
session instead of copying another run's addresses.

```powershell
python tools/cold_war/capture/capture_cw_navigation_nodes.py --help
```

Keep the map stable during capture. Readback equality is checked, but it is not
an atomic snapshot. Decode the raw entity capture using the
[entity decoder](cw-effects-entities.md#decode-a-saved-entity-list) before graph conversion.

## Decode and export offline

Use your own paths for each input and a new output location:

```powershell
$capture = '<path to your GAME_MAP node capture>'
$entities = '<path to your entities.decoded.json>'
$graph = '<path for navigation-graph.json>'
$reference = 'tools/black_ops_3/reference/bo3_reference.json'
$output = '<path to a new navigation export folder>'
$mapName = '<captured map name>'

python tools/cold_war/capture/decode_cw_navigation_graph.py --capture $capture --entities $entities --output $graph
python tools/cold_war/brushes/export_cw_navigation_tools.py --graph $graph --reference $reference --output $output --name $mapName
python tools/cold_war/brushes/export_cw_bo3_navigation.py --entities $entities --reference $reference --output $output --name $mapName --placement-only
python tools/cold_war/brushes/export_cw_volume_connections.py --graph $graph --reference $reference --output $output --name $mapName --placement-only
```

These steps check saved hashes and source relationships, then create separate
tool brushes, explicit endpoints and derived volume connections.
`--placement-only` leaves animation fields empty for manual authoring.

Inspect the reports before importing prefabs at **origin 0 0 0, angles 0 0 0,
scale 1**. Keep one copy of each endpoint/targetname in the map.

## Measured graph relationships

The current decoder was established from the Silver capture. Its candidate
GAME_MAP node records are 176 bytes. Validate the active build and map instead
of treating these offsets as a universal navigation format.

| Field | Interpretation and checks |
| --- | --- |
| Type | Compared with the filtered ENTITYLIST class ordering |
| +68 | Movement-ignore mask; names and independently supported bits are retained |
| +84 | Reciprocal volume or explicit endpoint partner index |
| +88 | Mantle index, or `0xFFFFFFFF` |
| +92 | Compared with authored `cost_modifier` |
| Counted child arrays | Captured float3 edge samples, preserved with source identities |

The historical Silver sample contains 286 records, 61 reciprocal volume pairs,
32 mantle associations and 1,706 child points. These are sample measurements,
not expected counts for every map. Compiled indices can recover a pair even
when a text target name is missing; retain that evidence instead of inventing
a name.

Restrictions are directional. A pair can allow an actor in one direction and
exclude it in the other. A brush-only export cannot encode those restrictions.
Do not infer all mask bits from the order of a comma-separated name list.

## Bounds and derived endpoints

Tool brushes use centered bounds from compiled half-dimensions and the checked
yaw-only frame. Adding half-height to the origin incorrectly floor-anchors
these records. Original pitch/roll and sampled edge points remain in metadata.

The decoder checks sample containment and preserves varying Z coordinates.
Parallel edges and equal point counts do not prove point-index pairing:
opposite sampling directions and shortened final intervals matter.

Mantle-on versus mantle-over selection is an approximation based on paired
heights, not a decoded CW climb enum. Derived volume-connection endpoints use
sampled edge centers with an explicit authoring lift. They are not original
CW point entities. Reports retain source directions, unsupported actor types,
omissions and the derivation used.

## Optional stock animation selection

Without `--placement-only`, the explicit-node exporter can choose stock BO3
jump animation types from the bundled reference. It preserves the source
endpoints and records the chosen nominal distance and discrepancy.

Closest-distance selection is an authoring approximation. It does not establish
CW animation semantics, runtime clearance, reverse traversal or alignment.
Unknown restriction tokens reject a pair instead of silently widening access.
Raw CW spawnflag bits are not copied into BO3 flags.

BO3 reference sources, relative to your installation, include:

- `bin/t7.def.json` for endpoint classes and named restrictions.
- `share/raw/behavior/zm_zombie.ai_bt` and its traversal behavior.
- `share/raw/animtables/zombie.ai_ast` and `zombie.ai_am` for animation aliases.
- `map_source/_prefabs/library/traverse/t7_zm_jump_128.map` for authoring examples.

The default zombie and Genesis procedural traversal branches differ. Setting
a procedural flag alone does not establish functioning traversal for a usermap.
Map-specific AI profiles may also lack otherwise stock animation rows.

## Silver zone-progression experiment

[build_cw_zone_progression.py](../tools/cold_war/capture/build_cw_zone_progression.py)
builds a separate Silver zone/door prefab and GSC module from supplied captures,
CW scripts and BO3 references. It has fixed research inputs and map-specific
authoring policies; it is not a generic zone converter.

```powershell
python tools/cold_war/capture/build_cw_zone_progression.py --help
```

Inspect the builder's `--research`, `--cw-root`, `--bo3` and `--output`
inputs before running it. The repository does not contain a preinstalled
usermap or the original research capture.

Generated artifacts use the `cw_silver_zone_progression_v1` stem. The mapping
report records source zone statements, flags, entity indices, prices, hulls,
output entities and authoring overrides.

### Integrate generated artifacts deliberately

1. Inspect the mapping report and review layers. Import the generated prefab
   once at identity transform, then stamp it so name prefixes do not alter the
   zone/target names expected by the script.
2. Place the generated GSC in your BO3 project's script search path. Add its
   `#using` declaration and a `scriptparsetree` entry to your map's zone file.
3. Call its `main()` after the host usermap setup, replacing the existing
   zone-manager setup for this experiment. Run only one zone manager.
4. Link starting spawn/respawn groups to the intended initial zone. Keep the
   host map's normal BO3 player and zombie spawning setup.
5. Compile/link the assembled map, rebuild navigation and test door progression.

This tool creates editable reference boxes for zones without captured volumes
and proxy gate brushes for doors. Those are review geometry, not recovered
original boundaries or door meshes. Resolve overlaps with imported static
collision. Preserve captured trigger costs/flags while checking the chosen
BO3 door behavior.

CW quest, power, animation and custom spawn systems are not automatically
ported. The source includes explicit room-zone authoring overrides; inspect
them instead of assuming every generated connection is an untouched CW rule.

Optional `cw_silver_zone_debug` diagnostics and one-shot test controls belong
to this generated module. They can help inspect zone state but do not replace
testing actual purchases, collision removal and actor traversal.

## What still needs validation

Navigation-edge width, mantle clearance, animation suitability, unsupported
actor restrictions, other maps/builds and remaining NAVMESH/NAVVOLUME layouts
need separate evidence. Captured bounds do not by themselves prove behavior.

Synthetic tests, saved-byte checks, isolated compiler fixtures and full-map
gameplay are different validation levels. Report which ones you ran. Earlier
combined-map checks found leaks and node-projection errors; no general
game-ready navigation conversion is claimed.
