# Modified Greyhound sources (GPL-3.0)

This directory contains **modified source files from
[Greyhound](https://github.com/Scobalula/Greyhound)** by Scobalula, which is
itself based on [Wraith Archon](https://github.com/dtzxporter/WraithXArchon/)
by DTZxPorter.

Greyhound is licensed under the **GNU General Public License v3.0**. The
upstream licence is preserved beside this file as `LICENSE`, and **everything
in this `greyhound/` directory is GPL-3.0**, not MIT.

If you redistribute a build of this modified Greyhound, GPL-3.0 obligations
apply: you must offer the complete corresponding source.

## Modifications

Modified by Kxboo in 2026 to add Black Ops Cold War `TerrainGfx` (asset type
`0xB1`) discovery and complete source-data export.

Base: Greyhound `master` (changelog head 1.3.30.0).

This repository is a complete fork and builds from its own source tree.

### New files

| file | purpose |
| --- | --- |
| `TerrainSettings.cpp` / `.h` | Source-only terrain settings page. Reconstruction controls and presets are intentionally absent. |

### Changed files

| file | change |
| --- | --- |
| `CoDAssets.cpp` / `.h` | TerrainGfx capture: header decode, image bindings, quadtree, holes, index and control maps, and the research metadata block. |
| `CoDAssetType.cpp` / `.h` | The terrain asset type. |
| `GameBlackOpsCW.cpp` / `.h` | BOCW pool discovery for asset type `0xB1`. |
| `Main.cpp` | Headless `superterrain` source-capture CLI. |
| `MainWindow.cpp`, `SettingsWindow.cpp` / `.h` | Terrain asset list and settings page registration. |
| `WraithXCOD.rc`, `resource.h` | Terrain settings dialog layout and control IDs. |
| `WraithXCOD.vcxproj`, `.filters` | New source files added to the project. |
| `WraithX/WraithAsset.h`, `WraithX/stdafx.h` | Terrain asset kind. |

## Third-party dependencies

Not included here. Greyhound vendors `src/External/*` as git submodules
(DirectXShaderCompiler, CascLib, DirectXTex, Opus), each under its own licence,
and none of them are modified by this work. `oo2core_8_win64.dll` (Oodle) is
proprietary and is deliberately not redistributed.
