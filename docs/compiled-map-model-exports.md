# Compiled-map XModel exports

Names such as `*doorframe_single_4.map_psh7ma2cqrgytjnmi6llllbdbn_16` are runtime XModel names. The exporter reads a BOCWXModel, its LOD mesh information, vertex buffer and surface indices. It does not open a source Radiant `.map` file or expand a prefab based on this string. The precise meaning of the generated token is not established here.

Previously the filesystem escaped the leading `*` as `%2A` and retained the complete name in both the directory and filename. In Silver's 70 existing CAST exports, 13 complete paths were 260–276 characters long. Blender 5.2's installed CAST importer could not open these paths. All 57 shorter paths imported successfully. Moving byte-identical CAST copies to short paths made all 70 import successfully, establishing a path-dependent failure without changing any mesh data.

Some geometry is also offset from the model origin. For example, the staircase step has coordinates around X=-4000 in CAST units. The exporter preserves these coordinates. Frame the imported meshes and increase the viewport Clip End when inspecting large or distant geometry. Do not recenter source meshes to fix visibility: doing so changes how placement transforms apply.

## Naming and identity

- `*doorframe_single_4.map_<generated data>` exports by default to `xmodels/doorframe_single_4/doorframe_single_4.cast`. Its placement `Name` is `doorframe_single_4` too.
- An encoded leading `%2A` is handled the same way when paired with a `.map` name. The leading marker and `.map` plus generated data are removed; text between them is preserved, including any leading underscore.
- A single default export has no `_LOD0` suffix. Export-all-LODs and the explicit match-game-LOD-index setting keep the actual `_LOD<n>` suffix. HITBOX remains distinct.
- Ordinary model and unresolved hash names keep their existing spelling. Filesystem-invalid characters remain escaped.
- User-facing placement `Name`, folder and default model filename use the same cleaned stem. `SourceName` preserves the runtime identity separately for game lookup. Models-from-JSON accepts this format, legacy raw `Name` values, and unique cleaned names without `SourceName`; ambiguous cleaned names require `SourceName`. The export report likewise uses cleaned `Name`, separate `SourceName`, and the actual output directory. The earlier redundant `ExportName` field is removed.
- Each cleaned model directory contains `model_identity.json`, recording its original name and export name. A conflicting identity is refused, including with overwrite enabled. Existing unlabelled directories with files are not silently claimed. A shortened name is never evidence that two source assets are equivalent.
- Existing long-name exports are left intact. New exports use short names. No persisted format settings are changed.

## Validation on Silver, 2026-09-07

- All 70 old CAST files parsed with the installed reference reader and contained nonempty, nondegenerate triangle geometry.
- All 70 freshly exported short-name CAST files succeeded through Greyhound's live CLI/common model export path. Their vertex positions and triangle index arrays were exactly equal to the previous files, per mesh.
- All 70 new files imported through the installed Blender addon with zero evaluated-bounds difference from their CAST data. The longest new path was 202 characters.
- The path control used byte-identical copies: 13 import failures at original paths became zero failures at short paths.
- A live negative control seeded a conflicting identity in an isolated test directory. Export failed as intended, even with `--overwrite`, and the existing CAST SHA-256 remained unchanged.
- Naming unit tests cover raw/encoded markers, ordinary names, malformed names, preserved LODs and colliding simplified stems.
- Additional tests cover unsuffixed single exports, numbered multi-LOD exports, legacy/new JSON lookup, ambiguity rejection, and unchanged position/rotation/scale when publishing cleaned names.
- Solution built Release|x64 with command-line PlatformToolset=v143. No project files edited, no commits. Existing linker/PDB warnings remain.

These checks establish preservation and Blender importability of the tested render meshes. They do not independently prove every material shader, every runtime deformation, or every map's placement. The separate barbecue model failure was not investigated.

Evidence under `C:/SuperTerrain/research/cw-clip/`:

- `map-named-cast-audit.json`
- `map-named-blender-check/blender-import-validation.json`
- `map-named-short-path-control/blender-import-validation.json`
- `map-named-fresh-export.json` and `map-named-fresh-audit.json`
- `map-named-fresh-blender/blender-import-validation.json`
- `map-naming-guard-before.json` and `map-naming-guard-result.json`

Fresh exports are in `src/WraithXCOD/x64/Release/exported_files/black_ops_cw/xmodels/`, beside the old directories. Available referenced textures (1,409 copies) and material text reports were copied from the originals into these new directories without editing the originals. There were 76 texture references already missing from the originals; this is separate from the CAST path failure.

Framed inspection scenes, with unmodified coordinates:

- `C:/SuperTerrain/research/cw-clip/map-named-fresh-blender/support_component.blend` — a model whose old path failed to open.
- `C:/SuperTerrain/research/cw-clip/map-named-fresh-blender/staircase_step_original_coordinates.blend` — an offset model.

Reproducible scripts are in `C:/SuperTerrain/tools/analysis/`: `audit_cw_map_named_cast.py`, `verify_cw_cast_blender.py`, `copy_cw_renamed_model_dependencies.py`, and `preview_cw_map_named_cast.py`.

`tools/normalize_placement_names.cpp` uses the same C++ naming implementation to migrate an existing JSON to a new plain-array file. The Silver example `exported_files/model_placements_700610296/static_models_clean.json` contains 29,961 placements, with 215 instance names cleaned; original identifiers are kept as SourceName. This is an offline naming migration, not a new placement capture.

The follow-up live export produced all 70 models as `folder/folder.cast`, with unchanged mesh positions/indices. All 215 corresponding instances in the migrated JSON match those filenames. Previous `_LOD0.cast` samples from those 70 cleaned folders were moved to `research/cw-clip/previous-default-lod-names/`; older user exports elsewhere were not migrated. Every non-name placement field was verified unchanged. An isolated `p8_wmd_generator` all-LOD export still produced eight distinct `_LOD0` through `_LOD7` CASTs. All parsed, but LOD0 contains no meshes; the other seven contain mesh vertices. The cause of that empty LOD was not established by these naming tests. Evidence: `consistent-model-names-validation.json`, `consistent-model-names-export.json`, `consistent-model-names-all-lods.json`, and `consistent-model-names-all-lods-validation.json` under the research directory.
