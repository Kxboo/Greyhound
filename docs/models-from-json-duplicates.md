# Duplicate model names in Models from JSON

The previous queue set its model pointer to null whenever a second exact-name model appeared. It reported both absent names and duplicates as `missing_or_ambiguous` without calling the exporter. Manual selection did not have that restriction.

For the user's Silver export, the saved report contained12 such names. A fresh live list found24 loaded records: exactly two for each of the12 names. None was absent. The separate `p9_zm_ndu_grill_barbecue` failure was excluded from this work.

The new queue retains all candidates. It selects a previously exported candidate first, then a loaded one, then another usable candidate; lower asset address provides a deterministic tie break. Placeholders, not-loaded and currently processing entries are not selected. It exports once per requested name. The later Cold War-only update exports CAST into flat models/materials/images folders; image and LOD preferences still apply. See [the current batch layout](cold-war-json-batch-layout.md).

This is a representative selection policy, not a proof that same-named models have identical geometry. Every candidate address, pool index and selection is recorded in the report. Runtime pointers are capture-specific evidence, not persistent identities. A selected candidate's export failure is still reported as failure; the exporter does not silently retry another variant over a potentially partial output.

Report schema `greyhound-models-from-json-v3` retains the v2 distinction between `missing`, `unavailable`, `failed`, and `exported`, and records the flat output root and CAST format. `duplicate_names` counts names with several candidates; it no longer makes them missing. Progress remains per unique requested name.

Validation:

- Standalone C++ selection tests cover absent names, unavailable candidates, duplicate names, manual-success preference, placeholders, order-independent address selection, prior error states and aliased pointers.
- Solution builds as Release|x64 with command-line PlatformToolset=v143; no project-file edits.
- A live twelve-name CAST-only CLI export used the common export path:12 exported,12 duplicate entries skipped,0 failures. All12 files loaded through the installed reference CAST reader.
- An isolated GUI test hung after loading the asset list, before a JSON file could be selected. The temporary test process was stopped; the user's original GUI process was not stopped. End-to-end GUI retry validation remains pending.

Evidence: `C:\SuperTerrain\research\cw-clip\duplicate-model-selection-audit.json`, `duplicate-models-export-check.json`, and `duplicate-models-cast-validation.json`.

The initial duplicate fix was staged as `Greyhound-duplicate-fix.exe`; the current build with subsequent naming and flat-batch changes is `src/WraithXCOD/x64/Release/Greyhound.exe`. The original duplicate-test CAST files remain under `bin/duplicate-model-fix/exported_files/black_ops_cw/xmodels/`; that test deliberately omitted textures and material reports.
