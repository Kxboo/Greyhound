# Built-in Cold War Radiant export

Load the current map in Greyhound, open **Settings → CW Radiant Brushes**, and
choose **Export brushes now**. **Automatically assign BO3 brush and tool types** and **Include triggers,
volumes and entity JSON**
export are enabled by default. The BO3 reference catalogue and isolated conversion
runtime ship in `brush_export` beside Greyhound; users need no GDT paths, scripts,
Python installation or BO3 installation to produce the prefabs.

The export folder contains:

* `<map>_brush_collision.map`: assigned BO3 collision clip families, including
  player, missile, physics, AI, AI-wallrun, `nosight_noclip` and unresolved `clip` fallbacks
  (including source solid geometry assigned `clip`). Source flags and uncertainty
  remain in the metadata; organization does not claim a more certain decode.
* `<map>_other_brushes.map`: ladder/mantle/mount,
  caulk, skip and other non-clip tools. These are preserved for optional use.
  Material properties and geometry are unchanged.
* `<map>_volumes.map`: info_volume entities, grouped by their source purpose.
* `<map>_triggers.map`: trigger entities, including hull and parameter shapes.
  The last two files are produced when trigger/volume export is enabled. Insert
  whichever prefabs you need at origin `0 0 0`, zero rotation and scale 1. All
  prefabs already use the same world coordinates. No combined prefab is generated.
* `collision_metadata.json`: original brush identity, placements, partition
  certificates, bounds and bounded geometry cleanup measurements.
* `material_assignments.json`: original contents and side-filter values, named
  flags, chosen BO3 material, source reference, confidence, unknown fields and
  added/omitted properties. Closest alternatives are recorded for review.
* `triggers.json`, when enabled: supported trigger and info_volume entities,
  names, links, ownership, original properties, emitted properties and geometry.
  Each entry identifies its prefab filename and entity index within that file.
  Player volumes have their own layers within the volumes prefab.
  Unsupported classes and rotated precompiled hulls remain in JSON with reasons.
* `export_report.json`: map hash, completeness, output hashes and summary counts.
  `prefabs` lists the category, filename, SHA-256 and counts for each output.
  `primary_map_file` identifies the brushes/clips prefab for older consumers.

Unresolved map names use `cw_map_<hash>` filenames. Data association uses the
verified map hash, not filenames or a previous map's export.

Progress JSON is best-effort telemetry. Windows file-sharing conflicts are
retried and never abort geometry conversion; the native reader permits
delete-sharing. `export_report.json` remains the completion authority.

## Automatic selection and current limits

Greyhound captures the active map's filter table and named flag definitions with
the brush payloads, then verifies the readbacks. A filter table can supply surface
names only when pointers and per-brush contents unions agree. Null-pointer shapes
retain their raw indices without borrowing another map's surface labels.

The bundled catalogue contains 217 stock material definitions from BO3's clip and
tool GDTs, including their full properties and source hashes. Candidate comparisons
cover the complete catalogue. Named CW mount behavior selects BO3 `mount`, including
when only its contents flag is available. Portal, sky, caulk and non-solid skip
behavior select basic stock tools when their named source properties are present.
Caulk selects `caulk_shadow`, or `caulk_sun_shadow` / `caulk_outdoor_occluder` when
the additional named property is present. These whole-brush approximations keep
their added/omitted properties in JSON. The bundle also records the stock tools-folder image
references and material editor definitions for noDraw, nonSolid, nonColliding and
surfaceClimbType. An image named nodraw is not itself a material definition, and
noDraw does not select a collision type. Supported named
property matches are applied automatically; for example, slick requires positive
evidence on every source side. Contents-only matches are explicitly marked when
surface flags are unavailable. Recognized collision combinations use the closest
supported BO3 match (`CLOSEST_BO3_APPLIED`); named tools with differences use
`APPROXIMATE_BO3_TOOL`. They no longer revert to generic clip simply because a
match is imperfect. Only unidentified behavior retains the unresolved fallback.
Greyhound also captures and verifies the five-entry CW traversal table with each
new type capture. Uniform, joined side enums select `ladder`, `mantle_on`,
`mantle_over`, `wall_climb` or `pipe_climb`. Mantle contributes mount contents in
CW; only a separate surface mount flag selects `mount_mantle_on/over`. Mixed side
enums, unjoined surfaces and older captures missing the enum table keep explicit
unresolved traversal metadata and their basic approximation. Enum values are
compared for equality, never unpacked as overlapping flags.
This is not a guarantee that every CW combination has an exact BO3
equivalent or that named-property agreement proves identical compiled gameplay.

Material assignment verifies that plane-defining points and texture projections
are unchanged. The existing brush partition and projection-separation pipeline
still handles Radiant winding limits for invisible tools; visible sky projections
are preserved. The exporter does not compile or launch BO3.
Trigger/volume geometry and names do not port gameplay scripts automatically.
Every info_volume has `volume_identity` in JSON, retaining its purpose,
variantName, targetname and script_location. Radiant layers group it by purpose.
Explicit stock volume-tool names select that material; `unlock_volume` uses
basic `unlock`, and `vol_death_zone` uses basic `kill`. These labels do not install
door/death scripts or change the source entity class. Other source-specific
purposes, including district toggles, remain named `volume` entities. Instance
targetnames are never fuzzy-matched to invent a gameplay purpose.
Class definitions and inherited properties come from the bundled stock BO3
`bin/t7.def.json`. Raw CW spawnflag bits stay in JSON; only explicit named flags
are translated to the corresponding BO3 bits. Unknown fields and enum values
remain in JSON rather than receiving guessed meanings.

Precompiled hulls have their source origin baked once into world coordinates.
Parameter-based trigger_box and trigger_radius entities retain their source
origin, angles and positive finite dimensions; equivalence of their CW/BO3 bounds
has not been demonstrated. trigger_damage responds to damage; it is not a
replacement for trigger_hurt. Unsupported cases are reported, never relabelled
as solid player clips.

Counts, pointers and ownership come from the current capture, with no map-specific
brush/type lists. The native type locator currently supports the verified CW
executable profile (asset-pool RVA `0x1273C9F0`); unsupported builds fail the requested
type capture rather than assigning data from a guessed address.

The expanded trigger exporter has been exercised on saved Tungsten, Platinum and
Silver captures: respectively 274, 290 and 327 entities, with zero skipped entities
in those captures. The full combined Tungsten export contains 38,853 world brush
pieces and 274 trigger/volume entities, including 593 hull brushes and two
parameter boxes. These are validation results, not baked-in expected counts.
Earlier combined brush/player-volume exports covered Platinum and Tungsten.
Saved Gold/Tungsten brush ownership has separate cross-map checks.
Zero-count trigger arrays need no payload files. Other executable builds and
unrecognized collision layouts are not implied to be supported by these tests.

## Developer packaging

`build_reference.py` reproducibly regenerates the shipped catalogue from the two
stock GDTs, tool definitions, Giant player-volume examples and inherited BO3
entity definitions. This is a developer maintenance
step, never a user export requirement. `package_runtime.py` bundles the converter,
catalogue and isolated Python/NumPy/SciPy runtime and writes integrity hashes.

Build `WraithXCOD.sln` as `Release|x64` with `PlatformToolset=v143`; no project-file
changes are required. Ship the complete `brush_export` directory with the binary.
