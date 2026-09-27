# Cold War terrain model export

Load the map, click **Load Game**, select its TerrainGfx asset, then **Export Selected**.
**Settings > Terrain** defaults to **Whole map** and **CAST**. A 5 x 5 area near the
current view is available for tests. Choose **Use formats selected in Model settings**
to use Greyhound's existing model writers instead.

Each mapping is divided into groups of up to 5 x 5 terrain tiles. Empty tiles are
skipped. Each group gets its own model, `_mat_info`, and `_images` directory.
`terrain_export.json` lists the placement origin of each package in game units.
CAST, OBJ, SEModel, glTF, Maya and XNA store positions in centimetres, following
Greyhound's existing 2.54 conversion; XMODEL and SMD use game units.

The bake uses the validated original composition shader captured from the loaded
game, the native material records, height/control textures, and recovered distortion.
No shader or game assets ship with Greyhound. Material source textures use installed
mips up to 1024; height/control maps retain full resolution. Output is PNG colour,
normal, gloss and AO. CAST links all four channels; other format capabilities vary,
and `_mat_info` retains the complete material mapping.

The Terrain page has an **Output folder** field. A blank field uses
`exported_files/black_ops_cw/terrain_models/<asset>/<new run>`; a custom folder
receives `<asset>/<new run>` directly. Generated names are compact and stable so
Windows importers can open the model and image paths.
Existing packages are never overwritten. Large intermediate textures are reused
per tile, and owned scratch files are removed after successful package validation.
Failed exports retain their inputs and logs for diagnosis. Whole maps can take
substantial time and disk space.

## Raw source and diagnostics

**Dev Tools > Terrain source capture and checks > Capture raw terrain source**
runs the previous archival exporter, including its source organization and integrity
seal. Output goes under `dev_tools/terrain_sources` in the selected terrain output root
(or the game export folder when the field is blank). BO4 diagnostic modes remain in
Dev Tools; main baked terrain export currently supports the validated CW build only.
The legacy `superterrain` diagnostic command retains its source-capture behavior.

The UI hides the Cold War area/format controls when BO4 is loaded. Selecting a
BO4 terrain for normal model export reports its source-capture route before
creating an export directory; the CLI does the same for `--dry-run`.
`--terrain-area` cannot be combined with `--terrain-source`, and an explicit
`--bo4-capture-mode` requires BO4 and `--type terrain --terrain-source`.

```powershell
Greyhound.exe assets export --type terrain --all --terrain-output D:\_superterrain\exports\greyhound_terrain --json
Greyhound.exe assets export --type terrain --all --terrain-area nearby --model-format cast --model-format obj --json
Greyhound.exe assets export --type terrain --all --terrain-source --json
```

## Scope and validation

This produces static visual terrain, preserving the approved blend bake. It does
not produce collision, editable Radiant patches, adaptive LODs or spline/decal models.
The terrain's painted material layers remain included. Independent volume decals
are omitted from baked model packages; reports record these two facts separately
as `terrain_material_layers_included` and `volume_decals_included`. Raw source
capture retains separate decal evidence, but does not convert it to BO3 assets.
Hole borders retain the conservative four-corner mask used by the approved examples.
Dispatch constants are reconstructed; bindless samplers use provisional linear wrap,
and weather globals are omitted. These limits are recorded in every package report.
Unsupported builds, shaders, mapping layouts or missing inputs fail visibly rather
than silently substituting neutral distortion or empty textures.

The bundled runtime includes Python, NumPy, SciPy, Pillow and the WARP shader runner;
Blender and the research directories are not required. `build-greyhound.ps1` builds
the runner and packages the runtime. The main model geometry flows through the same
native model writers as regular Greyhound assets.
