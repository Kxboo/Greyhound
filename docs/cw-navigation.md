# Cold War navigation and progression

[Documentation index](README.md) | [Contribution walkthrough](contributing.md)

This reference consolidates measured findings and their limitations.
Capture counts and local output paths below identify development samples,
not bundled fixtures or guarantees for every game build. Historical
validation is distinct from tests run on your current checkout.


## Silver navigation graph and corrected tool bounds

The September 15 live read of GAME_MAP was anchored to the unchanged saved
ENTITYLIST capture. It opened process 6640 with read/query access only. The map
hash remained `0x6BF83815978FDE24`. Every requested node/child span passed a
second-read equality check; this is not an atomic whole-game snapshot.

Evidence directory:
`C:\SuperTerrain\research\cw-clip\stock-first-review-20260915\game-map-current`

### Compiled relationships now recovered

* There are 286 candidate 176-byte navigation records. The filtered ENTITYLIST
  class ordering agrees with their type values, including type 20 for 122
  negotiation volumes and type 19 for 32 mantle nodes.
* The word at +84 identifies a reciprocal volume partner: all 122 volumes form
  61 pairs. The same field matches the explicit begin/end partner indices.
* The word at +88 is either `0xFFFFFFFF` or a mantle index shared by both
  volumes. Exactly 32 pairs reference the 32 mantle nodes, without sharing one
  mantle between multiple pairs.
* Sixty-one volume text targets agree with those compiled relationships.
  Entity 2048's target `pfA8FB293E_auto37` is absent by name, but its compiled
  partner identifies entity 2049, which has no targetname. This recovers the
  pair association without inventing a replacement name.
* The float at +92 agrees with available named `cost_modifier` values.

The word at +68 matches the movement-ignore properties. Sparse patterns
independently identify `bot` as bit 0, `dog` as bit 8, `vehicle` as bit 10, and
`zombie_dog` as bit 14. Other names are preserved from ENTITYLIST; individual
bit positions are not claimed merely from their order in a comma-separated
list. Full observed groups include `0xFFFF` and `0x3FFFFF`.

Using the source ignore names at each endpoint, 38 pairs have only one direction
that does not exclude `zombie`, and 23 have two. These counts describe source
restrictions, not proof of every runtime eligibility condition. A brush-only
conversion cannot encode those directional restrictions.

`navigation-graph.json` contains all records, raw bytes, source properties,
pair relationships, restrictions and child points. Capture-file hashes are
verified before decoding. Five synthetic tests cover pair validation,
movement-mask disagreement, corrupted input, point preservation and recovery
of a missing text target through the compiled index.

### Sampled edge geometry

All 154 volume/mantle records have a counted child array, totaling 1,706 float3
points. Their half-dimensions exactly match half of the ENTITYLIST width,
length and height. Their compiled positions exactly match the record-level
ENTITYLIST positions. The yaw and direction fields independently agree.

In the compiled yaw-only frame, samples run along local Y between the one-unit
inset endpoints, in eight-unit intervals with a shortened last interval. All
154 arrays satisfy this geometry within 0.001 units. Volume samples lie on one
local-X side; mantle samples lie on local X=0. Z values vary with the captured
geometry and are preserved rather than replaced by a constant height offset.

Paired volume arrays have equal point counts and parallel edges on all 61
pairs. That does not establish a direct point-index pairing: opposite sampling
directions and shortened final intervals must be respected. Most mantle arrays
also differ in point count from their associated volume arrays.

### Corrected prefab

`C:\SuperTerrain\research\cw-clip\stock-first-review-20260915\navigation-stock\zm_silver_navigation_tools.map`

This replaces the old navigation **tool brushes**, using centered bounds from
the compiled half-dimensions. The previous exporter added half-height to the
origin. That misplaced the lower bound above much of the sampled navigation
geometry. All 1,706 points fit the corrected centered bounds. Reconstructing
the old stored bounds, including its rounded transforms and full orientation,
contains only 314 of those points (`old-bound-comparison.json`).

The compiled edge geometry uses yaw even on twelve source entities with
nonzero authored pitch/roll. The new export uses the checked compiled yaw
frame and retains all original angles in metadata.

The result contains 154 brushes: 122 `traverse`, five `mantle_on`, and 27
`mantle_over`. All are installed BO3 nonSolid/noDraw tools. The mantle-on/over
choice is still inferred from paired volume heights; it is not a decoded
source climb enum. All serialized planes were checked against the intended
bounds, all 1,706 points remain within tolerance, and the map was parsed back
to verify brush/material counts.

The prefab contains no point entities and no collision solids. It can accompany
`zm_silver_traversal_nodes_stock.map` for the seven explicit endpoint pairs.
Replace the older navigation tool brushes rather than placing duplicate copies.
No files in the BO3 installation were replaced by this correction.

### Remaining work

The 61 volume pairs still need BO3 navigation-edge conversion with their
directed restrictions. Mantle clearance, edge width, animation suitability,
and compiler/runtime behavior remain unverified. The corrected tools preserve
compiled bounds but do not implement those links. Other maps/builds and the
remaining NAVMESH/NAVVOLUME data still need validation.

Reusable tools:

* `tools/cold_war/capture/capture_cw_navigation_nodes.py` — bounded live read anchored to
  a matching ENTITYLIST capture.
* `tools/cold_war/capture/decode_cw_navigation_graph.py` — saved-byte graph/geometry checks.
* `tools/cold_war/brushes/export_cw_navigation_tools.py` — centered BO3
  tool-bound export from the checked graph, included in the packaged runtime.

These are developer entry points; the regular Greyhound export button does not
yet capture and convert this navigation graph automatically.


## Cold War traversal nodes: stock BO3 animation conversion

The saved Silver ENTITYLIST has seven explicit negotiation begin/end pairs.
The new developer exporter at
`tools/cold_war/brushes/export_cw_bo3_navigation.py` converts those fourteen
nodes to stock BO3 animation traversal. It retains exact captured transforms,
target names, the begin-to-end links, and supported movement restrictions.

Output:
`C:\SuperTerrain\research\cw-clip\stock-first-review-20260915\navigation-stock\zm_silver_traversal_nodes_stock.map`

The neighboring `navigation-report.json` preserves all source properties,
omissions, selected animation evidence, and the 154 mantle/volume entities that
still need edge conversion. This is not wired to the regular Greyhound brush
button. The converter and reference are included in its packaged Python tools.

### Evidence chain in the installed BO3 files

All paths below are relative to
`C:\Program Files (x86)\Steam\steamapps\common\Call of Duty Black Ops III`.

1. `bin/t7.def.json` defines negotiation begin/end classes, movement restrictions,
   named flag values and the begin node's target and animation script.
2. `share/raw/behavior/zm_zombie.ai_bt` links to
   `share/raw/behavior/zombie/ZombieTraverseBehavior.json`. That branch invokes
   `zombieTraverseAction` with `traverse@zombie`.
3. `share/raw/animtables/zombie.ai_ast`, starting at line 104, selects animation
   aliases by traversal type and other actor conditions. The builder resolves
   matching aliases through `share/raw/animtables/zombie.ai_am`. Fourteen stock
   jump types have resolved entries: up/down at 36, 48, 72, 96, 128 and 160,
   plus across at 128 and 256.
4. `map_source/_prefabs/library/traverse/t7_zm_jump_128.map` puts `jump_up_128`
   on its begin node and `jump_down_128` on its end node. This supplies direct
   authoring evidence for preserving a reverse animation on the end, even
   though the end's class declaration does not list `animscript`.

The bundled reference records source hashes and animation-table row numbers.
Availability in these base animation tables does not prove that every custom
AI archetype or map-specific animation profile includes those rows or assets.

### Current Silver selections

| Source pairs | Captured displacement used for selection | BO3 forward / reverse |
| --- | --- | --- |
| 3 | Rise of 36 units | `jump_up_36` / `jump_down_36` |
| 3 | Rise of 59 units | `jump_up_48` / `jump_down_48` |
| 1 | Horizontal distance about 208, height change -5 | `jump_across_256` in each direction |

The policy chooses the closest nominal stock distance within the geometric
family. A height change within eight units selects the across family. These
are explicit conversion approximations, not decoded CW animation semantics.
The report records actual vectors, chosen nominal distances and differences.
No endpoint is moved to fit a stock animation. Runtime path clearance,
animation alignment and reverse traversal still need an in-game test.

All fourteen serialized entity dictionaries match their intended properties.
All seven begin nodes still ignore `vehicle`. Unknown movement restriction
tokens reject a pair rather than silently widening actor access. Raw CW
spawnflag bits are never copied as BO3 flags; supported named flags are used.

This point-only prefab can replace the fourteen point nodes in the older
`cw_silver_navigation.map`. Do not place both copies of those nodes together:
their targetnames are intentionally preserved. Keep the separate brush geometry
if needed. The generated file adds no collision and no compiled navmesh.

### Why procedural flags alone were rejected

`share/raw/scripts/shared/ai/zombie.gsc:1346` requires
`SPAWNFLAG_PATH_PROCEDURAL` on both traversal endpoints.
`share/raw/scripts/shared/shared.gsh:84` defines that flag as 1024.
However, the inspected default zombie traversal branch does not call that
predicate. `share/raw/behavior/zm_genesis_zombie.ai_bt` has the procedural branch,
which uses `robotCalcProceduralTraversal` and additional jump/air/land states.

Therefore a flags-only prefab would not establish ordinary usermap zombie
traversal. The published export uses stock animation traversal and disables the
procedural bit. No behavior tree, archetype, GDT or game script was modified.

### Remaining negotiation volumes and mantle nodes

The source graph contains 32 volume-to-mantle links, 32 mantle-to-volume links,
29 direct volume-to-volume links, and one volume target absent from this list.
There are 122 negotiation volumes and 32 mantle nodes. Of the volumes, 114
carry movement restrictions. Turning all of them into `traverse` brushes loses
those restrictions and their directed links; brush materials cannot encode
that information by themselves.

The existing mantle-on/over geometry remains an approximation. A complete AI
conversion must establish endpoint placement, directed edge and width rules,
actor restrictions and obstacle clearance. Stock BO3 negotiation nodes provide
the relevant authoring mechanism; creating an APE material alone will not solve
the missing edge semantics. All affected source records remain in the report.

The subsequent live GAME_MAP decode recovers all 61 reciprocal volume pairs
and resolves the missing text target through its compiled partner index. It
also corrects the older floor-anchored tool bounds. See
`docs/cw-navigation.md` and the separate
`zm_silver_navigation_tools.map` in this output directory. Directed behavior
conversion and gameplay validation remain outstanding.

### Reproduce

```powershell
C:\SuperTerrain\.venv\Scripts\python.exe tools\cold_war\brushes\export_cw_bo3_navigation.py `
  --entities C:\SuperTerrain\research\cw-clip\stock-first-review-20260915\entitylist\entities.decoded.json `
  --reference tools\black_ops_3\reference\bo3_reference.json `
  --output C:\SuperTerrain\research\cw-clip\stock-first-review-20260915\navigation-stock `
  --name zm_silver
```


## Silver zone progression v1 — BO3 test package

This is a new, separate prefab and GSC module. It uses The Giant's `info_volume`,
`zombie_door`, `script_flag`, `zombie_cost`, `target` and DYNAMICPATH conventions,
with BO3's existing `_zm_zonemgr` and `_zm_blockers`. It does not replace the
host map's main script automatically and does not call `init_blockers` twice.

### Files

* `cw_silver_zone_progression_v1.map`: 97 captured zone volumes, 8 reference
  zone boxes, 25 captured door trigger hulls and 25 editable test blocker brushes.
* `cw_silver_zone_progression_v1.gsc`: all 41 source connections across 28 zones,
  all 24 flag-link calls, and optional console diagnostics.
* `cw_silver_zone_progression_v1_spawn_locations.map`: optional 54 ordinary
  spawn/riser locations at captured transforms. Includes neither AI actor
  spawners nor custom animated entrances. Use the host map's BO3 zombie spawner.
* `zone-progression-mapping.json`: source TRIGGER indices and IDs, ENTITYLIST
  region-node indices, spawn targets, original door models/properties, source
  script lines and exact prefab entity indices. The two source index namespaces
  are separate.

### Install in the existing zm_silver project

1. Import `map_source/_prefabs/codex/cw_silver_zone_progression_v1.map` once at
   **origin 0 0 0, angles 0 0 0, scale 1**. Stamp it into individual entities so
   prefab name prefixes cannot change the zone names referenced by the script.
   Use it instead of the old zone/door entities, not stacked over duplicates.
   Keep terrain and general collision separately.
2. The new GSC module is installed under `share/raw/scripts/zm/`. Add this to
   the top of `usermaps/zm_silver/scripts/zm/zm_silver.gsc`:

   ```c
   #using scripts\zm\cw_silver_zone_progression_v1;
   ```

3. In `main()`, after `zm_usermap::main()`, replace the existing zone-manager
   setup block (`init_zones`, `level.zone_manager_init_func`, and `manage_zones`)
   with this call:

   ```c
   cw_silver_zone_progression_v1::main();
   ```

   The old `zm_silver_zone_init()` can remain unused. Run only one zone manager.
   Keep the rest of your main script, weapons and other setup.
4. Add this line to `usermaps/zm_silver/zone_source/zm_silver.zone`:

   ```csv
   scriptparsetree,scripts/zm/cw_silver_zone_progression_v1.gsc
   ```

5. Put the host map's starting player spawn/respawn group inside a captured
   `zone_proto_start` volume and set its zone `script_noteworthy` accordingly.
   BO3 locks respawn groups whose zone has not been enabled. Do not leave it
   referencing the old `start_zone`. Retain the normal BO3 player-spawn setup.
   The captured source start group's reference origin is
   `1256.73999 -263.744995 33` (ENTITYLIST 1); its target is `initial_spawn_points`.
6. Import the optional spawn-location prefab if wanted, or link your own BO3
   spawn/riser locations using each volume's `target`. Compile your map with
   navigation and link, then test in game.

### What is faithful and what is a test substitute

**Preserved:** all 41 connections, direction arguments, source flag names,
24 alias calls, 17 blocker target groups, 25 prices/trigger associations and
97 actual volume hulls. Each volume targets the spawn group named by its CW
region node, including the three prefab-generated spawn-group names.
One captured volume used `script_string=player_volume`; this version uses BO3's
`script_noteworthy=player_volume` consistently.

**Eight missing volume boundaries:** Cold War permits a named navigation-region
node where BO3 requires an `info_volume`. These eight zones therefore receive
128-unit boxes centered at their captured node positions in the
`REVIEW_Zone_Extents` layer. Resize/split them against your map's walls and
floor before treating zone coverage as finished. The placeholders may overlap
other zones and are not an inferred final partition of the map:

* zone_center_upper_west
* zone_power_room_outside
* zone_power_trans_south
* zone_proto_roof_center
* zone_trans_north_pap_room
* zone_trans_south_pap_room
* zone_trans_south_tunnel
* zone_wonder_weapon_room

**Door geometry:** the original trigger hulls, costs and flags are preserved.
All door interactions use BO3 `trigger_use`, following The Giant; CW's
`trigger_use_touch` is adapted to this BO3 convention. Each trigger targets a
thin editable `script_brushmodel` test gate derived from its interaction hull.
It has `DYNAMICPATH=1`, `spawnflags=1` and `script_noteworthy=clip`, so the stock
door handler removes its collision and connects paths on opening. These gates
are not decoded original door geometry. Replace/reshape them in the
`REVIEW_Door_Geometry` layer and keep their targetnames. Imported static collision
across the same doorway will continue blocking it until you remove that overlap.
Original model names, transforms, sliding vectors and dynamite tags remain in JSON.

Electric-door tags are retained. BO3's stock power system opens those doors;
they are not ordinary paid doors despite having a source `zombie_cost` field.
Animations and CW quest/power systems are not included.

Only `zone_proto_start` is placed in `init_zones`. The real source `always_on`
connection enables `zone_proto_start2`. All other zones follow their door/quest
flags and the source alias rules; they are not all made active at startup.

### Test diagnostics

After loading your map, opt in using `set cw_silver_zone_debug 1`. The module
prints zone enable-state changes to the developer console. With debug enabled:

```text
set cw_silver_zone_test_power 1
set cw_silver_zone_test_flag open_wonder_weapon_room
```

These are one-shot controls. Power uses the host BO3 `power_on` flag. A test
flag sets zone state only; it does not emulate buying a door or remove unrelated
collision. Use actual purchases to test doors. The mapping JSON lists quest
flags without captured door or alias producers; their real quest handlers are
outside this version. No testing flags are set automatically.

Start by buying the 750-point start-to-interior or start-to-cave door. Confirm
the correct source flag becomes active, the related test gate stops blocking,
and the zone enables. Then test multiple triggers on the same blocker group,
electric doors after power, and the eight reshaped zones. Rebuild navmesh when
you change blocker or walkable geometry.

### Evidence

Primary local authoring references: `map_source/zm/zm_giant.map`, its nested
`_prefabs/zm/zm_giant/geo/factory_doors.map`, `zm_giant.gsc`, `_zm_zonemgr.gsc`,
`_zm_blockers.gsc`, `_zm_power.gsc` and `docs_modtools/bo3_scriptapifunctions.htm`.
The source zone statements come from the supplied Cold War
`scripts/zm/zm_silver_zones.gsc`; captured entity/hull data comes from the saved
Silver capture. Relevant source hashes are recorded in the JSON.

The provided guides corroborate volume KVPs and the role of door flags:
[Modme zones](https://wiki.modme.co/wiki/black_ops_3/basics/Setting-up-zones.html),
[UGX zones](https://www.ugx-mods.com/forum/mapping/92/tutorial-making-zones-the-right-way/12916/),
[Modme basics](https://wiki.modme.co/wiki/black_ops_3/Basics.html).
The BO3 source controls implementation choices. In particular, adding every
zone to `init_zones` would defeat the requested progression.

This is a testable authoring version, not a full quest or zombie-spawn port.
The script passed the installed BO3 linker in an isolated script-only project.
The main prefab passed `cod2map64` in a sealed test wrapper with no reported
errors or leak. These checks do not establish in-game behavior or final
navmesh/volume coverage; those depend on the assembled map.
