# BO4 terrain export versions

[BO4 workflows](bo4.md) | [Measured layouts](bo4-terrain-research.md) | [Documentation index](README.md)

Greyhound captures terrain and exports source/model packages. **TerrainReconstructor is a separate application**: use it to create Radiant patches and choose collision and non-colliding control budgets. Greyhound does not apply those budgets or create terrain collision patches.

## Choose an output

Load a BO4 map, enable TerrainGfx in Library settings, then use **Settings > Terrain > BO4 export** and export the Terrain asset. The BO4 version selector does not change Cold War's terrain route.

| Version | Contents | Intended use |
| --- | --- | --- |
| Source package (default) | `package/capture/terraingfx.json`, sector arrays, material/image files, captured shader evidence and package audit | Select `package/` in TerrainReconstructor; retain the complete folder |
| Original materials | The source package plus `models/*.cast`, `models/_mat_info/`, `models/_images/`, `terrain.map` and `terrain_export.json` | Convert terrain models using original BO4 material names, images, UVs and independent vertex alpha |
| Baked CAST | Source package, CAST sections with composited colour/normal/gloss/specular maps, `_mat_info`, `_images`, placement map and report | A static material approximation with captured volume decals included |

Original-material mode copies the source PNG files unchanged. Its `_blend` material names are overlay aliases for the same source images, not new baked textures. Native compressed DDS mip chains stay in the source package. CAST positions are centimetres; convert to game inches once during model conversion. Placement prefabs use origin zero because vertices already contain world coordinates.

Original-material CASTs retain the source height lattice and conservative cutout cells. They do not reproduce runtime tessellation displacement, and model importers may not reproduce BO4 reveal blending. The material identities and source inputs remain available regardless of that limitation.

Baked textures are capped at 1024 pixels per side. This is an expensive CPU shader replay; large maps can take a long time. The integrated route permits up to 4096 planned sections and rejects larger plans before baking. It requires runtime layer records for every sector and a captured/empty decal inventory. Missing records are an error, not a reason to copy another sector's material parameters. Inspect failures and `package_audit.json`; a successful source capture is not proof of a complete bake.

## CLI

From your checkout, use the CLI binary you built:

```powershell
$gh = '.\bin\cli\Greyhound-cli.exe'
$output = '<new export root>'
& $gh assets export --type terrain --all --terrain-version source --terrain-output $output --json
# Choose one version for each run:
& $gh assets export --type terrain --all --terrain-version native --terrain-output $output --json
& $gh assets export --type terrain --all --terrain-version baked --terrain-output $output --json
```

`--terrain-source` remains the legacy raw diagnostic capture; it is different from `--terrain-version source`, which also packages the capture for downstream tools. `--terrain-bake-decals` remains an alias for the BO4 baked route. Do not combine these flags with `--terrain-version`. BO4 exports CAST models; Cold War's area/format controls are separate.

For saved data, no running game is needed:

```powershell
$probe = '<full mode-0 capture>\terraingfx_probe.json'
$output = '<new output folder>'
python tools/black_ops_4/capture/export_terrain.py $probe $output --mode source
# A packaged source folder can also be used for source/native exports:
python tools/black_ops_4/capture/export_terrain.py '<source package folder>' '<new native output>' --mode native
# Baking needs the original full probe, including its referenced capture files:
python tools/black_ops_4/capture/export_terrain.py $probe '<new baked output>' --mode baked
```

These offline commands require the Python dependencies described in the build guide. Installed Greyhound uses its bundled runtime. Export into a new folder; existing packages/models are not overwritten. A failed export can retain diagnostic/source files without a completed export manifest.

## Follow the implementation

1. [AssetCli.cpp](../src/WraithXCOD/WraithXCOD/cli/AssetCli.cpp) parses `--terrain-version`; the GUI stores `bo4terrainversion`.
2. [CoDAssets.cpp](../src/WraithXCOD/WraithXCOD/assets/CoDAssets.cpp), `ExportBakedTerrain` (the existing dispatcher name), forces a full BO4 terrain probe and invokes [export_terrain.py](../tools/black_ops_4/capture/export_terrain.py).
3. [GameBlackOps4.cpp](../src/WraithXCOD/WraithXCOD/games/black_ops_4/reader/GameBlackOps4.cpp) captures original image mip chains. [BO4TerrainRuntime.h](../src/WraithXCOD/WraithXCOD/games/black_ops_4/capture/BO4TerrainRuntime.h) matches each runtime layer using its UV record and **shared-array weight slice**, rather than assuming sector-local slice indices.
4. [package_bo4_terrain.py](../tools/black_ops_4/capture/package_bo4_terrain.py) writes the portable source contract and audits exclusions. [bo4_native_source.py](../tools/black_ops_4/capture/bo4_native_source.py), adapted from TerrainReconstructor under its included MIT notice, validates source dimensions and independent BC4 masks.
5. [export_native_terrain.py](../tools/black_ops_4/capture/export_native_terrain.py) writes source-material CAST surfaces. [export_baked_terrain.py](../tools/black_ops_4/capture/export_baked_terrain.py) instead runs the terrain/decal replay and writes composited materials. Neither creates Radiant collision patches.

The initial fixes also preserve linear texture alpha during sRGB decoding, correctly emulate both halves of integer multiply, retain native mip chains, and validate optional captured texture views. [Expanded layer decoding](bo4-terrain-research.md#expanded-layer-parameters-2026-10-12-verification) describes exact byte packing and its evidence. These fixes do **not** establish one-to-one in-game appearance: selected draw LOD, grid sampler state and some CPU derivative/LOD behaviour remain unresolved.

Run focused regressions from the checkout:

```powershell
python -m pytest tests/black_ops_4/capture -q
node tests/shared/ui/terrain_mock_test.cjs
```

See [UI test dependencies](../tests/shared/ui/README.md). Synthetic tests cover version routing, unchanged source images, CAST material/UV/alpha assignments, output protection and texture size planning. They do not constitute a live BO4 capture or a BO3 map compile. No RenderDoc or game-process injection is required by these offline exporters.
