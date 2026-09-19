# Model export and batch resume

[Documentation index](README.md) | [Contribution walkthrough](contributing.md)

This reference consolidates measured findings and their limitations.
Capture counts and local output paths below identify development samples,
not bundled fixtures or guarantees for every game build. Historical
validation is distinct from tests run on your current checkout.


## CAST models from placement JSON

With Cold War or BO4 loaded, **Models from JSON** exports each unique referenced
model into its own model-name folder:

```text
<batch>/
  model_name/
    model_name.cast
    _images/
      material_name/
        texture_name.png
    _mat_info/
      material_name.txt
```

When **Export all available LODs** is enabled, the selected LOD files sit directly
inside the same model folder as `model_name_LOD0.cast`, `model_name_LOD1.cast`, etc.
A single largest-LOD export has no suffix unless matching the game LOD index is
selected. Model names are cleaned consistently with placement JSON; SourceName
retains the original lookup identity.

Each model has its own images and material text reports. Images are grouped under
their material names. CAST texture references use
`_images/<material>/<name>.<extension>`, so a model folder can be moved independently.
There are no shared models/materials/images directories and no material JSON
files. Batch exports include images and material text automatically, preserving
the selected image format and LOD options. Failed image diagnostics, if needed,
also live in that model's `_mat_info` folder.

Batch-level placement JSON, identity protection, checkpoints and the final report
remain at the batch root. Selecting the original placement JSON searches existing
batch folders for the same model names and export settings. The resume prompt
offers the matching folder with the most complete exports, so an accidentally
started newer batch does not hide an older batch with more progress. Completed
CAST files are checked against the saved file sizes; interrupted files are retried.
You can also select the batch's own `static_models.json` directly. Old flat
batches are not resumed into this layout or rearranged; choosing their placement
JSON starts a new run. Ordinary selected/all-asset exports are unchanged.

The GUI and headless path share `CoDAssets::ExportJsonBatchModel`:

```powershell
.\Greyhound.exe assets export --type model --name p8_usa_food_canned_corn `
  --model-batch-root C:\SuperTerrain\repos\Greyhound\test-output\model-folder-layout `
  --model-format cast --all-lods --model-images --image-names --json
```

### Verification

Release|x64 build passed. A live BO4 model exported five CAST LODs, nine images and
two material text files in the requested structure (about 554 KiB total).
The independent Blender CAST reader loaded all five LODs with nonempty meshes;
all 20 nonempty texture references resolve within the model's `_images` folder.
Ten empty optional texture slots were present and were not counted as file paths.
Evidence is in `test-output/model-folder-layout-validation.json`. No full model
batch or terrain capture was generated. Cold War uses the same path code but was
not live-tested in this run because BO4 was loaded.

The subsequent material-subfolder correction enables `_images/<material>/` for
every JSON batch and writes the same path into CAST texture references. Release
build passed; BO4 was closed during this correction, so the earlier live capture
above validates the exporter before this path change, not a new nested export.


## Compiled-map XModel exports

Names such as `*doorframe_single_4.map_psh7ma2cqrgytjnmi6llllbdbn_16` are runtime XModel names. The exporter reads a BOCWXModel, its LOD mesh information, vertex buffer and surface indices. It does not open a source Radiant `.map` file or expand a prefab based on this string. The precise meaning of the generated token is not established here.

Previously the filesystem escaped the leading `*` as `%2A` and retained the complete name in both the directory and filename. In Silver's 70 existing CAST exports, 13 complete paths were 260–276 characters long. Blender 5.2's installed CAST importer could not open these paths. All 57 shorter paths imported successfully. Moving byte-identical CAST copies to short paths made all 70 import successfully, establishing a path-dependent failure without changing any mesh data.

Some geometry is also offset from the model origin. For example, the staircase step has coordinates around X=-4000 in CAST units. The exporter preserves these coordinates. Frame the imported meshes and increase the viewport Clip End when inspecting large or distant geometry. Do not recenter source meshes to fix visibility: doing so changes how placement transforms apply.

### Naming and identity

- `*doorframe_single_4.map_<generated data>` exports by default to `xmodels/doorframe_single_4/doorframe_single_4.cast`. Its placement `Name` is `doorframe_single_4` too.
- An encoded leading `%2A` is handled the same way when paired with a `.map` name. The leading marker and `.map` plus generated data are removed; text between them is preserved, including any leading underscore.
- A single default export has no `_LOD0` suffix. Export-all-LODs and the explicit match-game-LOD-index setting keep the actual `_LOD<n>` suffix. HITBOX remains distinct.
- Ordinary model and unresolved hash names keep their existing spelling. Filesystem-invalid characters remain escaped.
- User-facing placement `Name`, folder and default model filename use the same cleaned stem. `SourceName` preserves the runtime identity separately for game lookup. Models-from-JSON accepts this format, legacy raw `Name` values, and unique cleaned names without `SourceName`; ambiguous cleaned names require `SourceName`. The export report likewise uses cleaned `Name`, separate `SourceName`, and the actual output directory. The earlier redundant `ExportName` field is removed.
- Each cleaned model directory contains `model_identity.json`, recording its original name and export name. A conflicting identity is refused, including with overwrite enabled. Existing unlabelled directories with files are not silently claimed. A shortened name is never evidence that two source assets are equivalent.
- Existing long-name exports are left intact. New exports use short names. No persisted format settings are changed.

### Validation on Silver, 2026-09-07

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

`tools/shared/models/shared/models/shared\models\normalize_placement_names.cpp` uses the same C++ naming implementation to migrate an existing JSON to a new plain-array file. The Silver example `exported_files/model_placements_700610296/static_models_clean.json` contains 29,961 placements, with 215 instance names cleaned; original identifiers are kept as SourceName. This is an offline naming migration, not a new placement capture.

The follow-up live export produced all 70 models as `folder/folder.cast`, with unchanged mesh positions/indices. All 215 corresponding instances in the migrated JSON match those filenames. Previous `_LOD0.cast` samples from those 70 cleaned folders were moved to `research/cw-clip/previous-default-lod-names/`; older user exports elsewhere were not migrated. Every non-name placement field was verified unchanged. An isolated `p8_wmd_generator` all-LOD export still produced eight distinct `_LOD0` through `_LOD7` CASTs. All parsed, but LOD0 contains no meshes; the other seven contain mesh vertices. The cause of that empty LOD was not established by these naming tests. Evidence: `consistent-model-names-validation.json`, `consistent-model-names-export.json`, `consistent-model-names-all-lods.json`, and `consistent-model-names-all-lods-validation.json` under the research directory.


## Model material files

Normal model export and **Models from JSON** share mesh decoding. Current CW/BO4
CAST batches use the per-model layout described above, with `_images/<material>/`
and `_mat_info/` inside each model folder. Older flat batches are historical.

In Model Settings, enable **Export material image list + settings** to write one `<material>.txt` per material. This is the existing `exportimgnames` setting with a clearer label.

Those files collect in a `_mat_info` folder beside `_images`, matching the layout other Cold War extractors produce:

```text
_zm_silver_weapons_lab_v2/
  _zm_silver_weapons_lab_v2_LOD0.cast
  _images/
    bbn_metal_corroded_grey_07/
      i_bbn_metal_corroded_grey_07_col.png
  _mat_info/
    bbn_metal_corroded_grey_07.txt
```

Each file reads:

```text
Name: mc/bbn_metal_corroded_grey_07

Techset: techset_779f5e9babe46117

semantic,image_name
colorMap,i_bbn_metal_corroded_grey_07_col

name,type,x,y,z,w
colorTint,float33,0.000000,0.000000,0.000000,0.000000
```

`Name` is the resolved game path when the name database has one, otherwise the generated `xmaterial_<hash>` that also names the file. The `name,type,x,y,z,w` block is Greyhound's captured shader constants and is omitted when a material has none; the header above it has no counterpart in the reference layout.

**Group images + settings by material** (`mdlmtlfolders`) now only controls the `_images/<material>/` texture grouping. **Use global images folder** moves `_images` — and `_mat_info` with it — out of the model directory to be shared between models. Model texture references use the corresponding relative path. Standalone material exports write the same file beside their images in the material export directory.

Existing exported files are not moved or removed. The change applies on subsequent exports. Shared material metadata writes are serialized so concurrent model exports cannot truncate each other's text files.

Validation: solution build `Release|x64`, command-line `PlatformToolset=v143`; no project-file changes. See `C:\SuperTerrain\research\cw-clip\material-folder-build.log`. A live model/image export has not yet been run for this path change.

### Selected formats and extra files

Normal exports use the selected model formats. The Cold War JSON batch now explicitly exports CAST, without changing these saved selections. Settings are stored beside each executable in `greyhound.json`, so two installations can have different selections.

Maya `_cosmetics.mel` helpers are now written only when Maya export is enabled and cosmetic bones exist. Material images and reports now follow the selected LOD, instead of collecting dependencies from every loaded LOD when exporting just one.

For one CAST per model, select only CAST, turn off all LODs, and disable images and material text if they are not wanted. Textured CAST files still reference external image files. Existing exports in other formats are not deleted.

The rebuilt exporter was exercised with one live `p9_nt6x_candle_stick` CAST-only export with images/reports disabled. The output directory contained exactly one CAST and it loaded through the installed reference CAST parser. This exercised the common export path via CLI, not the GUI batch dialog. Evidence: `C:\SuperTerrain\research\cw-clip\cast-only-export-check.json`.


## Duplicate model names in Models from JSON

The previous queue set its model pointer to null whenever a second exact-name model appeared. It reported both absent names and duplicates as `missing_or_ambiguous` without calling the exporter. Manual selection did not have that restriction.

For the user's Silver export, the saved report contained12 such names. A fresh live list found24 loaded records: exactly two for each of the12 names. None was absent. The separate `p9_zm_ndu_grill_barbecue` failure was excluded from this work.

The queue retains all candidates. It selects a previously exported candidate first,
then a loaded one, then another usable candidate; lower asset address provides a
deterministic tie break. Placeholders, not-loaded and currently processing entries
are not selected. It exports once per requested name. Current CW/BO4 batches use
the per-model layout above; image and LOD preferences still apply.

This is a representative selection policy, not a proof that same-named models have identical geometry. Every candidate address, pool index and selection is recorded in the report. Runtime pointers are capture-specific evidence, not persistent identities. A selected candidate's export failure is still reported as failure; the exporter does not silently retry another variant over a potentially partial output.

Report schema `greyhound-models-from-json-v3` retains the v2 distinction between `missing`, `unavailable`, `failed`, and `exported`, and records the flat output root and CAST format. `duplicate_names` counts names with several candidates; it no longer makes them missing. Progress remains per unique requested name.

Validation:

- Standalone C++ selection tests cover absent names, unavailable candidates, duplicate names, manual-success preference, placeholders, order-independent address selection, prior error states and aliased pointers.
- Solution builds as Release|x64 with command-line PlatformToolset=v143; no project-file edits.
- A live twelve-name CAST-only CLI export used the common export path:12 exported,12 duplicate entries skipped,0 failures. All12 files loaded through the installed reference CAST reader.
- An isolated GUI test hung after loading the asset list, before a JSON file could be selected. The temporary test process was stopped; the user's original GUI process was not stopped. End-to-end GUI retry validation remains pending.

Evidence: `C:\SuperTerrain\research\cw-clip\duplicate-model-selection-audit.json`, `duplicate-models-export-check.json`, and `duplicate-models-cast-validation.json`.

The initial duplicate fix was staged as `Greyhound-duplicate-fix.exe`; the current build with subsequent naming and flat-batch changes is `src/WraithXCOD/x64/Release/Greyhound.exe`. The original duplicate-test CAST files remain under `bin/duplicate-model-fix/exported_files/black_ops_cw/xmodels/`; that test deliberately omitted textures and material reports.
