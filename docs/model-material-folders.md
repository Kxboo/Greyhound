# Model material files

Normal model export and **Models from JSON** share mesh decoding, but now use different layouts. The Cold War CAST JSON batch uses flat `models`, `materials`, and `images` directories; see [the batch layout](cold-war-json-batch-layout.md). The per-material folder settings below apply to normal exports.

In Model Settings, enable **Export material image list + settings** to write `<material>_images.txt` and, when captured parameters are available, `<material>_settings.txt`. This is the existing `exportimgnames` setting with a clearer label.

With **Group images + settings by material** enabled (`mdlmtlfolders`), those text files now accompany the textures in `_images/<material>/`. Turning **Use global images folder** off keeps that folder inside each model directory; turning it on shares `_images/<material>/` between models. Model texture references use the corresponding relative path.

Metadata-only exports also create the material folder. Disabling material folders retains the older flat layout and writes the text files beside the model. Standalone material exports already write settings and images together in the material export directory.

Existing exported files are not moved or removed. The change applies on subsequent exports. Shared material metadata writes are serialized so concurrent model exports cannot truncate each other's text files.

Validation: solution build `Release|x64`, command-line `PlatformToolset=v143`; no project-file changes. See `C:\SuperTerrain\research\cw-clip\material-folder-build.log`. A live model/image export has not yet been run for this path change.

## Selected formats and extra files

Normal exports use the selected model formats. The Cold War JSON batch now explicitly exports CAST, without changing these saved selections. Settings are stored beside each executable in `greyhound.json`, so two installations can have different selections.

Maya `_cosmetics.mel` helpers are now written only when Maya export is enabled and cosmetic bones exist. Material images and reports now follow the selected LOD, instead of collecting dependencies from every loaded LOD when exporting just one.

For one CAST per model, select only CAST, turn off all LODs, and disable images and material text if they are not wanted. Textured CAST files still reference external image files. Existing exports in other formats are not deleted.

The rebuilt exporter was exercised with one live `p9_nt6x_candle_stick` CAST-only export with images/reports disabled. The output directory contained exactly one CAST and it loaded through the installed reference CAST parser. This exercised the common export path via CLI, not the GUI batch dialog. Evidence: `C:\SuperTerrain\research\cw-clip\cast-only-export-check.json`.
