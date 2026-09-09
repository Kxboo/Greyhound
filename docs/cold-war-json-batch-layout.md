# Cold War CAST batch export

With Cold War loaded, **Models from JSON** reads a placement JSON and exports each unique referenced runtime model. This batch feature currently supports Cold War and CAST only.

Each run creates `exported_files/models_from_json_<run>/` beside Greyhound:

```text
models_from_json_<run>/
  static_models.json
  model_export_report.json
  model_identities.json
  models/
    doorframe_single_4.cast
    p8_wmd_generator.cast
  materials/
    material_name.json
    material_name_images.txt       (when material text reports are enabled)
    material_name_settings.txt     (when enabled and parameters exist)
    material_name_images_failed.txt (only for unavailable/failed textures)
  images/
    image_name.png
```

There are no per-model or per-material subdirectories. Material JSON records the source name, techset, surface type, settings, and image bindings with relative paths. CAST files refer to `../images/<name>.<extension>`, so the whole run can be moved together. Available shared images use one path. Materials with identical descriptions reuse one JSON; conflicting material descriptions with the same filename fail rather than overwrite. A root identity map protects cleaned model names from collisions.

Placement `Name`, model filename stem, and model names inside CAST are consistent. `SourceName` remains available for exact live lookup. Default single-LOD exports have no `_LOD0`; explicit all-LOD/match-game-index settings retain actual LOD suffixes. The progress bar counts completed unique runtime models, and the final report distinguishes missing, unavailable, failed and exported requests. Texture failures are reported separately in the materials folder; a model success does not imply every texture was available.

The batch forces CAST without changing saved model-format preferences. Image enable/disable, image format, optional material text reports, and LOD preferences still apply. Material JSON is always produced for the exported LOD's materials. Ordinary selected/all-asset exports keep their existing paths and format settings. Existing exports are not rearranged.

The UI and CLI share `CoDAssets::ExportJsonBatchModel`. For reproducible bounded testing:

```text
Greyhound.exe assets export --type model --name p9_nt6x_candle_stick --model-batch-root C:\SuperTerrain\research\cw-clip\flat-batch-example --model-format cast --model-images --image-names --json
```

The CLI flag uses the same exporter but does not read a placement JSON or create the GUI placement/report documents. Other games and non-CAST formats are rejected for this batch path.

## Verification

Solution build passed as Release|x64 with command-line PlatformToolset=v143 and no project-file edits. Existing linker/PDB warnings remain. OBJ exporter files have no changes from this work, and saved `greyhound.json` remained byte-identical.

The attempted native three-model test could not attach: no Cold War process was running. Therefore native live output and end-to-end GUI execution for this new batch path remain unverified. `research/cw-clip/flat-cw-cast-batch-export.json` records the attachment failure. A non-CAST CLI request was rejected before attachment, as intended.

An explicitly offline fixture built from existing captures contains three CASTs, three material descriptions and nine shared images in the three flat folders. All 15 CAST image references resolve, no nested folders exist, mesh vertex/index arrays remain unchanged, and all three files import through Blender's installed CAST addon with zero evaluated-bounds difference. This checks the proposed path layout and Blender compatibility, not native live extraction. The fixture's material JSON is marked OfflineFixture and records CAST bindings; native output adds runtime parameters/techset/surface type.

Artifacts: `C:/SuperTerrain/research/cw-clip/flat-cw-cast-batch-offline-example/`, `flat-batch-blender-validation/blender-import-validation.json`, `flat-batch-scope-rejection.json`, and `flat-cw-cast-batch-build.log`. Reproduce the fixture with `tools/analysis/build_flat_cast_offline_fixture.py` and check its paths with `tools/analysis/validate_flat_model_batch.py`.
