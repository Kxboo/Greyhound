# Greyhound — Kxboo fork

A Call of Duty asset exporter with Cold War and Black Ops 4 map research,
capture, decoding, and conversion tools.

## Build and use

Start with the **[documentation](docs/README.md)**:

- [Build on Windows](docs/README.md#build-on-windows)
- [Run the GUI or CLI](docs/README.md#run-greyhound)
- [Export from the command line](docs/README.md#cli-discover-before-exporting)
- [Find your placement exports](docs/README.md#placement-folders-and-duplication)

## How to help

Read the **[contribution guide](docs/contributing.md)** for a source walkthrough,
testing instructions, other-game support and working with an AI assistant.

The **[script directory guide](tools/README.md)** groups tools by game and task.
Bug reports should include the game/build, map, steps and relevant export report.

## Research guides

| Question | Start here |
| --- | --- |
| Where is TerrainGfx found and how is it decoded? | [CW terrain](docs/cw-terrain.md) · [CW/BO4 TerrainGfx reference](docs/terraingfx-reference.md) |
| Where are map placements and scene objects found? | [CW placements](docs/cw-placements.md) · [CW effects and entities](docs/cw-effects-entities.md) · [BO4 placements](docs/bo4.md) |
| Where are collision and navigation records decoded? | [CW collision](docs/cw-collision.md) · [CW navigation](docs/cw-navigation.md) · [BO4 terrain and collision](docs/bo4-terrain-research.md) |
| What proves a capture or preview? | [Capture contracts](docs/capture-research.md) · [Preview reader audit](docs/preview-reader-audit.md) |

The [documentation index](docs/README.md) maps each topic to its reader,
decoder, and saved evidence. These guides distinguish measured layouts
from preview assumptions and conversion output.

## Credits and license

Based on [Greyhound](https://github.com/Scobalula/Greyhound) by Scobalula and
[Wraith Archon](https://github.com/dtzxporter/WraithXArchon/) by DTZxPorter and
ID Daemon. Thanks to dest1yo and the
[upstream contributors](https://github.com/Scobalula/Greyhound/graphs/contributors).
The [upstream wiki](https://scobalula.github.io/Greyhound/) covers general
Greyhound usage and game support.

Licensed under [GPL-3.0](LICENSE); see [NOTICE](NOTICE.md) for fork attribution.
Distributed without warranty. Extracted assets remain the property of their
respective owners. This project is not affiliated with Activision.
