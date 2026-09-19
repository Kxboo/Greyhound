# Cold War collision and brush research

[Documentation index](README.md) | [Contribution walkthrough](contributing.md)

This reference consolidates measured findings and their limitations.
Capture counts and local output paths below identify development samples,
not bundled fixtures or guarantees for every game build. Historical
validation is distinct from tests run on your current checkout.


## Cold War surface clips and local model collmaps

The Radiant brush export now reads the current Cold War build's surface enum
declarations alongside its contents, traversal, and side-filter tables. The
`zm_tungsten` capture verified all 39 surface declarations by stable readback.
Surface-specific BO3 clips are candidates only when the source side filters
are joined and their contents union matches the source brush. Selection first
minimizes omitted collision properties, then added properties, then surface
differences. Mixed source surfaces use their most frequent named type, with a
deterministic alphabetical tie. Each source brush gets one selected tool;
partitioning for the BO3 plane limit does not add overlapping material copies.

### Local model collision

Output: `exported_files/collmaps/black_ops_cw/<map>/<model>.map`.

Ownership comes from an exact pointer join between each occupied
`BOCWXModel.XCollisionPtr` and the map's captured 96-byte collision assets.
The entire XModel pool descriptor and occupied/free slot headers are verified
by readback. Names use Greyhound's loaded model-name database, with an explicit
hash fallback. Repeated instances reuse one model file. Filenames that collide
after sanitization receive an identity hash; an existing different file is
retained and reported as a conflict rather than overwritten.

The current implementation exports **convex brush components only**. It does
not yet export compact triangle components, even when they coexist with an
exported brush component. `manifest.json` marks `complete_model_collision=false`
and lists the missing components/models. It must not be described as complete
model collision. No bounding boxes or enclosing hulls replace missing triangles.

These brushes are read from the compound model's own local payload. The
variable binding table is followed by 80-byte counted surface headers. Live
surface pointers independently check the calculated coordinate/group/tree
offsets. Byte coordinates start immediately after preceding data; word
coordinates align to 2, group words to 4, and the subsequent brush header to 8.
Tree byte counts are **not rounded between surfaces**. The brush component
uses the established 208-byte world-brush header layout at its own offset.
The decoder adapts offsets, retaining the original geometry bytes and recording
the source payload hash and component offset.

No instance translation, rotation, scale, or recentering is applied to a
collmap. Hulls use exact predicates over captured vertices. Hulls exceeding
64 support planes are subdivided with checked positive volumes and cancelling
internal faces. Serialized planes and source vertices are checked to 1e-6.
The map contains no render model or world placement.

### Live validation

On zm_tungsten, 2,740 loaded render-model records joined 2,735 collision assets.
530 distinct model files contain 1,499 source convex brushes, serialized as
2,270 brush pieces. Compact triangle-only models and other unresolved layouts
remain listed in the manifest. This is file/geometry validation, not a claim
of BO3 compilation or identical gameplay behavior.

Use the existing **Export brushes now** action or the CLI's
`assets export --type rawfile --name cw_pool_018_clip_map_headers --cw-radiant-brushes`.
Rebuild Greyhound and package `tools/` together after source changes.
TerrainReconstructor is not involved or modified.


### Model collision and physics research are separate (2026-09-13)

Model-local collmaps remain ordinary BO3 collision geometry. The user's selected
policy replaces `clip_physics` / physicsGeom assignments with a standard `clip`,
or a surface-specific `<surface>_clip` only when captured surface information and
the bundled BO3 material catalogue support it. This deliberately adds player
blocking; it is a fallback, not a verified conversion of CW physics behavior.
World brush assignments are not affected by this model-only policy.

Original source assignments remain under `diagnostics/radiant_work/physics_research`.
No mass, inertia, constraints, dynamics, or compact-triangle reconstruction is
published as part of these model collmaps. Export manifests identify the policy,
source material, and substitutions and set `physics_conversion_verified=false`.

Applied to the 141 selected Silver model collmaps, still excluding t7/p7:
72 physics-only brushes in 40 models became plain `clip` because their source
surface type is unresolved. Every plane coordinate and UV transform was retained.
Other clip, surface, and traversal materials were preserved. The packaged Python
exporter was synchronized and its manifest hashes updated; no C++ rebuild needed.
Offline checks covered source immutability, generic/surface fallback selection,
installed-file readback, and preservation of unselected collmaps. BO3 compile and
gameplay behavior remain unverified.


## Cold War collision reader code span

**Settings > Dev Tools > Cold War: capture options > Dump the collision reader code span instead of the pool
export (build-pinned)**, or `--cw-collision-code-probe`.

The option replaces a Cold War pool evidence export with a single 16 MB read of
the game module at RVA `0xC800000`, saved as `collision_reader_code.bin` beside a
report recording the module base, the RVA and the readback check. It is read-only
process access; nothing is written to the game.

It is checked before any capture-depth branching, so it applies to every shared
capture mode, headers-only included, and it returns as soon as the span is saved.
The run therefore contains the code span **instead of** `headers.bin`, the pool
descriptor and the rest of the pool evidence — which is why the label says so.

`GREYHOUND_CW_COLLISION_CODE_PROBE` still forces it on regardless of the
checkbox, so existing research scripts keep working unedited.

Explicit Radiant brush exports bypass this diagnostic override. A checked box
or inherited environment variable therefore cannot replace the geometry capture
requested by the brush export workflow. While the override is active, the Dev
Tools page disables the pool capture depth and section controls and explains
that they do not apply to the code span.

### What "build-pinned" means

The RVA was measured against one Cold War build. Another build moves the code,
and the capture will still succeed: the read lands wherever that address now
points and `readback_unchanged` will still be true, because re-reading the same
wrong address gives the same wrong bytes. Nothing in the output proves the span
contains the collision reader.

Treat the result as evidence only when it came from the build the RVA was
measured against. This is a reverse-engineering aid for locating collision
dispatch code offline; it decodes nothing and is not part of any export.


## Silver clip and BO3 stock review, September 15, 2026

Evidence and outputs: `C:\SuperTerrain\research\cw-clip\stock-first-review-20260915`.
The live capture identified `zm_silver`, hash `0x6BF83815978FDE24`, from Cold War
process 6640. No desktop interaction or BO3 gameplay test was performed.

### Stock material selection

The regenerated bundled catalogue contains 233 installed tool/clip material
definitions. The parser now resolves inherited definitions across the two
source GDTs. Twelve inherited definitions were previously missed, including
surface-specific metal player/nosight clips. The installed main tools GDT also
contains four direct definitions absent from the older bundled snapshot.
Every definition retains file/line provenance and inherited properties.

Source installation:
`C:\Program Files (x86)\Steam\steamapps\common\Call of Duty Black Ops III`.

* `texture_assets/tools.gdt` and
  `art_assets/t6_legacy/texture_assets/clip.gdt` define the material catalogue.
* `deffiles/material.awi` defines the APE collision/query checkboxes,
  `surfaceType`, and `surfaceClimbType`. BO3 authoring climb types include ladder,
  mantleOn, mantleOver, climbWall and climbPipe.
* `docs_modtools/Radiant_Launcher_QuickStart.pdf`, pages 7–8, documents APE asset
  editing and saving GDT changes. `Materials.pdf` does not prove that an
  arbitrary Cold War collision-bit combination can be implemented by BO3.

The selector now considers related stock surface families when exact types
are unavailable, while prioritizing collision-query coverage. This follows the
request to use a similar BO3 material where suitable. Metal/wood ladder tools
retain their surface type. Three Silver brushes improve from generic
`clip_nosight` to inherited `metal_clip_nosight_thin`. A 39-brush metal-catwalk
profile uses `metal_clip_full` as an explicitly recorded approximation; it adds
bulletClip and uses the related metal surface. Exact query/surface parity is
not claimed.

`silver-stock-first-audit.json` groups 7,865 unique source brushes into 106
profiles. It identifies 1,775 brushes with an available exact named stock
profile and 55 with preferred similar stock profiles. Another 4,917 need
source decoding and 1,118 need source or engine review under this stricter
audit. These categories describe evidence sufficiency, not how many brushes
were exported. The updated audit proposes no new APE material recipes.

Existing custom test GDTs under BO3 `source_data/cw_silver_collision_test_20260914*`
were preserved. Missing APE controls and unresolved source joins do not justify
creating a guessed custom equivalent.

### Published replay and limits

The fresh captured brush data was replayed successfully with the updated
packaged runtime. The four prefabs are under `review-prefabs`:

* `zm_silver_brush_collision.map`
* `zm_silver_other_brushes.map`
* `zm_silver_volumes.map`
* `zm_silver_triggers.map`

All published prefab hashes verified. The runtime verification checked 58
packaged files and the 233-material catalogue. The existing suite passed 50
tests and 11 subtests before adding the separate entity decoder's four tests.

The original export stopped at a differing existing monkey model collmap. It
preserved that file. The successful replay uses the separate `model-collision`
directory in this review folder. Neither Radiant compilation nor gameplay
equivalence has been tested by this review.

The source report still records 1,241 collision assets outside the supported
brush layout and 26 layouts without brushes. Of the 7,865 unique brushes,
6,084 have verified pointer-backed side-filter unions; 1,781 do not have a
resolved global-filter association. These are not full collision-decoding
coverage claims.

### Mantle and traversal are spread across assets

There are four joined clip_map brushes with a uniform named mantleOn type.
Separately, ENTITYLIST contains 32 mantle nodes, 122 negotiation volumes and
14 negotiation endpoints. The new accurate JSON is documented in
`docs/cw-effects-entities.md`.

An earlier standalone navigation exporter exists at
`C:\SuperTerrain\tools\analysis\export_cw_navigation_prefab.py`, producing
`C:\SuperTerrain\research\cw-clip\bo3-export-silver-20260914\special-purpose\cw_silver_navigation.map`.
It is also installed at BO3 `map_source/_prefabs/cw_silver_navigation.map`.
The 168 relevant current entity-property dictionaries match that earlier
capture; the installed prefab matches its recorded research copy byte-for-byte.

That prefab contains 122 traverse, five mantle_on and 27 mantle_over brushes,
plus 14 point entities. Its mantle-on/over choice is inferred from geometry,
not decoded from an explicit source traversal enum. Volume anchoring, some
movement semantics and script references still need review. It is not wired
into Greyhound's regular brush export, which captures TRIGGERLIST separately.

Installed BO3 `bin/t7.def.json` describes negotiation begin/end nodes and
their flags and animation-script controls. It does not define CW's
`node_negotiation_mantle` or `node_negotiation_volume` classes. Shipped example
`map_source/_prefabs/library/traverse/t7_zm_jump_128.map` demonstrates BO3
traverse brushes with paired endpoints. A similar authoring structure is
available, but the CW animation scripts are not automatically ported.

Further evidence is in
`C:\SuperTerrain\tools\analysis\audit_cw_game_nodes.py` and
`C:\SuperTerrain\tools\analysis\decode_cw_navigation_index.py`:
GAME_MAP pool 0x1A contains candidate 176-byte navigation records and a spatial
index. Position, angle and dimension comparisons support those associations;
child semantics and runtime traversal behavior remain incomplete. Fresh
NAVMESH 0x75 and NAVVOLUME 0x76 headers/prefixes were saved, but they do not
constitute a decoded navigation mesh. The candidate NAVINPUT 0xC2 lookup found
no matching export row. See `navigation-leads.json` and
`live-navigation-probe.json` for exact capture paths.

The later endpoint conversion in `docs/cw-navigation.md` now supplies
the seven explicit pairs with stock BO3 animation types and precise transforms.
It also identifies the default-versus-Genesis procedural behavior distinction
and the movement restrictions lost by a brush-only negotiation-volume export.

### Current placement/reference delivery

The subsequent GAME_MAP capture resolved the volume geometry and pairing
described as incomplete above. See `cw-navigation.md` for the
checked 286-node graph, 61 volume pairs, 32 mantle associations and all 1,706
sampled edge points. The old installed navigation prefab uses incorrect floor
anchoring; use the corrected centered/yaw-only tool prefab in the new package.

`cw-effects-entities.md` documents the consolidated delivery at
`C:\SuperTerrain\research\cw-clip\stock-first-review-20260915\placement-reference`.
The user requested placements and mapping references and will set up animations.
Its two endpoint prefabs therefore leave all 182 animation fields empty. Every
captured ENTITYLIST entity and all 12,059 supported exported collision pieces
are indexed; unknowns, approximations and unsupported layouts remain explicit.
The standalone builder is `tools/cold_war/capture/build_cw_placement_reference.py`.
This complete inventory of captured/exportable data does not claim full decode
coverage of all CW collision layouts or automatic Greyhound button integration.

Validation: all package hashes and entity/reference links checked, 14 original
endpoint coordinates preserved, 168 derived endpoint placements accounted for,
and all 12,059 placed pieces have material lookup entries. Current brush-export
tests passed (36), entity decoder tests passed (4), navigation graph tests passed
(5), and the packaged runtime passed all 15 checks. The compiler fixture passed;
the combined Silver geometry check reported a leak and 39 node projection
errors, so it must not be described as a clean game-ready compile.
