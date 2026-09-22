# Built-in Cold War Radiant export

Load the current map in Greyhound, open **Settings > Radiant Brushes**, and
choose **Export brushes now**. **Automatically assign BO3 brush and tool types** and **Include triggers,
volumes and entity JSON**
export are enabled by default. The BO3 reference catalogue and isolated conversion
runtime ship in `tools/` beside Greyhound; users need no GDT paths, scripts,
Python installation or BO3 installation to produce the prefabs.

Cold War direct export also reconstructs the supported whole-map brush set:
after the existing bounded cleanup and conservative subdivision, it recombines
certified convex pieces within each source brush, up to 32 faces. Merges must
reuse supplied support equations and pass independent face-volume/hull-volume
checks. This adds no simplification tolerance and never merges different source
brushes or placements. Uncertified and tetrahedral fallback partitions stay as
they were. Model-local collmaps and BO4 keep their separate conversion policies.

The 32-face cap was chosen after a full-map BO3 compile; a 64-face variant failed
the compiler's intermediate winding limit even with smaller final polygons.
That regression test does not imply every newly exported map has been compiled.

The export folder contains:

* `<map>_brush_collision.map`: collision clip families after source-based role
  exclusions. Unknown contents (including the unresolved base-solid bit) still
  retain their collision fallback and explicit uncertainty.
* `<map>_nonblocking_reference.map`: source non-solid/no-query shapes, zero-contents
  shapes with unjoined surfaces, and stock clip candidates that would add player
  collision to a fully decoded non-player query mask. Every face uses stock
  `nodraw_notsolid`; proposed materials, source flags and exclusion reasons remain
  in metadata. These shapes retain their placement on the visible `CW_Reference`
  editor layer, with `flags ignore` to exclude them from compilation. This uses
  the same BO3 layer mechanism as Corvid's No Comp layer, without hiding it.
  Keep this layer excluded: compiling thousands of reference brushes can exceed
  BSP compiler limits even when their material has no collision queries.
  A reference classification does not assert the source lacked projectile/AI queries.
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
* `brush_faces.jsonl`: ordered world-space face corners, support planes, areas,
  source identities, final prefab brush ordinals, assigned materials and internal
  partition-face classification. Render material/UV fields remain unset until a
  verified render association exists; collision surface flags cannot supply it.
* `brush_face_audit.json`: independent final MAP plane/material readback against
  the checked hull cache, corner coverage, cache hashes and measured float32
  plane-parsing error. Unresolved polygons remain explicit and never remove a
  solid. Both face files and collision metadata are hashed in the v11 report.
* `render_transfer.json`: explicit texture-transfer availability, source hashes,
  material dependencies and surface counts. Collision face UVs remain unset;
  actual render associations live in `verified_render_surfaces.jsonl`.
* `<map>_render_surfaces.map`, when verified associations are supplied: separate
  nonColliding render patches preserving material names, corner UVs and colors.
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
* `bo3_stock_reference.json`: the complete bundled stock material definitions,
  inheritance, GDT source hashes, tool-image aliases and editor property data.
* `stock_material_audit.json`: every emitted brush and lightmap material name,
  its stock definition and per-map face counts. Unavailable names use the closest
  captured stock recommendation, then a compatible stock authoring profile when
  available, with generic `clip` as the last fallback. Geometry is retained and
  every substitution is recorded. Lightmaps fall back to stock `lightmap_gray`.
  These files and `material_assignments.json` are always embedded and hashed,
  even when automatic assignment is disabled. The source comparison then remains
  a recommendation; the audit inventories the materials actually emitted.
  Individual model collmap runs carry the same reference and source decisions.

### Verified texture transfer

The direct CW export consumes `verified_render_surfaces.jsonl` automatically
when present beside the native capture, or accepts `--surfaces <file>` in the
packaged converter CLI. Records follow TerrainReconstructor's
`brush-render-surface-v1` contract: matching normalized capture SHA-256,
`source_id` (world, instance, collision asset, brush), `association: verified`,
producer evidence, world vertices, normalized-repeat UVs, texture dimensions,
material name and optional vertex RGBA. Planar convex polygons are accepted;
source triangles preserve triangulation-dependent UVs. Quads produce one patch;
triangles produce three nondegenerate quads with interpolated attributes.

The material names and UVs are retained without collision-stock substitution.
Required target materials/images must be installed separately. The producer's
join is not established by this writer: the saved collision-only Silver and
Mauer captures currently contain no verified render/UV association file. Such
exports explicitly report unavailable and emit no fabricated textured prefab.
All supplied association bytes and rendered prefab hashes are sealed in v11.

### Optional collision surfaces

Two checkboxes on the same settings page add the collision representations that
are not convex brushes. Both are off by default and neither changes the prefabs.

* **Also write float collision triangles as OBJ** (Cold War, `--float-triangles`)
  writes `collision_surfaces/float-collision-triangles.obj` and
  `float-collision-index.json` from the captured float-triangle branch. Groups
  keep their source triangle ranges and filter indices. These are reference
  meshes in source capture coordinates with no placement applied; they are not
  Radiant brushes and must not be compiled as such. `export_report.json` gains a
  `float_collision_triangles` block with the decoded counts.
* **Include BO4 triangle collision surfaces** (`--model-triangles`) decodes the
  world triangle-collision arrays into `metadata/triangle_collision.json`, and
  additionally captures the full model collision reference probe so
  `metadata/model_collision_data.json` can record per-model surfaces, instances
  and recovered triangles. That second capture is a separate memory walk, which
  is why the option is opt-in. Model collision vertices are reconstructed from
  captured float32 equations rather than authored coordinates, surface ownership
  is still untraced, and neither file is exported as geometry.

Four pipeline modules stay deliberately outside this entry point:
`analyze_bo4_physics_primitives`, `audit_bo4_world_probe` and
`decode_bo4_physgeom_samples` are research validators by their own description,
not export stages; `combine_cw_radiant_prefabs` targets a different volume-export
shape than `export_cw_bo3_trigger_entities` returns and would need that mismatch
resolved before it could be offered as a layout option.

Verified uniform surface enums can refine an unresolved generic clip to a stock
surface variant, such as `concrete_clip`. Exact enums precede documented related
stock families. Additional approximations are asphalt to concrete, ceramic to
brick, rubber to plastic and paper to cloth; these are authoring choices, not
recovered enum equivalences or authored textures. This keeps the source contents bits
unresolved and records added collision flags; it does not equate implicit solid
behavior across engines. Mixed, default, unknown and unjoined surfaces retain
the generic fallback. Stock availability and named-property matches are separate
from compiler or gameplay equivalence.

Unresolved map names use `cw_map_<hash>` filenames. Data association uses the
verified map hash, not filenames or a previous map's export.

Progress JSON is best-effort telemetry. Windows file-sharing conflicts are
retried and never abort geometry conversion; the native reader permits
delete-sharing. `export_report.json` remains the completion authority.

Individual model-local collision maps use a fresh map folder for each export:
`collmaps/black_ops_cw/<map>`, then `<map>_2`, `<map>_3`, and so on. Existing
files and manifests are retained even if collision materials or geometry have
changed. The brush export report's `model_collmaps.folder` identifies the folder
for that run.

Model-local runs use the same source behavior gate. Root model-named `.map`
files contain collision; `references/<model>.map` holds excluded pieces using
`nodraw_notsolid` on the same no-compile reference layer, still at the model-local origin. Physics-only shapes no
longer become player clips: the proposed stock clip is recorded but not applied.
Mixed models are split per brush, preserving all supported geometry across both
roles. Neither `noDraw` nor `nonSolid` alone proves absence of collision queries.

## Automatic selection and current limits

Greyhound captures the active map's filter table and named flag definitions with
the brush payloads, then verifies the readbacks. A filter table can supply surface
names only when pointers and per-brush contents unions agree. Null-pointer shapes
retain their raw indices without borrowing another map's surface labels.
Each pointer-backed brush is validated independently. A mismatched contents union
or out-of-range index on one brush does not discard the other brushes' matching
surface evidence. Per-brush validation results are retained in assignments v5.

Selection preserves omitted queries, added non-item queries, and slick/nonSolid
behavior first. Within those constraints, exact and related surfaces precede
generic tools. An extra itemClip property is explicitly recorded but no longer
erases an otherwise compatible surface match. Unknown and mixed side data stay
unresolved; a category vote is not a brush-to-render UV association.

The bundled catalogue contains stock material definitions from BO3's clip and
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

**Settings > Dev Tools > Export workflows and checks** provides direct access
to terrain settings, model placements and brush exports. **Check runtime** checks
the installed converter hashes, imports, BO3 catalogue and terrain helper entry
points. **Check saved export** verifies a published brush
`metadata/export_report.json` against its prefab hashes, or a sealed terrain
`research_capture.report.json` against its source inventory. Both actions write
JSON under a fresh diagnostics export directory and work without a loaded game.
These checks establish file integrity, not full decoding or BO3 gameplay parity.

The repository build script packages the conversion runtime after a successful
native build. A usable Python installation is required for packaging; missing
dependencies fail the build instead of leaving a partially staged runtime.

`build_reference.py` reproducibly regenerates the shipped catalogue from the two
stock GDTs, tool definitions, Giant player-volume examples and inherited BO3
entity definitions. This is a developer maintenance
step, never a user export requirement. `package_runtime.py` bundles the converter,
catalogue and isolated Python/NumPy/SciPy runtime and writes integrity hashes.

The primary material catalogue includes 233 installed definitions, resolving
inherited clip/tool materials across both GDTs with source provenance. The full
installed GDT scan additionally retains tool/invisible definitions and an inventory
of every remaining render material. Each captured semantic profile compares every
primary and supplemental tool, including slick and special-role materials which
need more source evidence before automatic application. No candidates are hidden
by the five-result preview. All six caulk variants participate in property ranking;
ordinary caulk ties retain caulk_shadow, while captured shadow/occlusion flags can
select a specialized variant. Caulk is emitted in the other-brushes prefab.
Every export embeds STOCK_MATERIALS.md, CAPTURED_BRUSH_MATERIALS.md and
BO3_RENDER_MATERIALS.md with the JSON evidence and integrity hashes. Related
stock surface families can be selected when an exact type is unavailable;
assignment metadata records the approximation. See
[collision documentation](../../../docs/cw-collision.md) for the workflow and remaining gaps.
The separate saved-capture ENTITYLIST decoder and precise conversion JSON are
documented in [effects and entities](../../../docs/cw-effects-entities.md).

Build `WraithXCOD.sln` as `Release|x64` with `PlatformToolset=v143`; no project-file
changes are required. Ship the complete `tools` directory with the binary.
