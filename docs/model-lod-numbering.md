# Model LOD numbering

In Model settings, enable **Reverse LODs: 0 = highest (BO4 / CW)** before exporting Black Ops 4 or Cold War models. The option defaults to off and leaves other games unchanged.

Enabled exports assign LOD0 to the highest-detail source mesh, ordered by triangle count and then vertex count. Equal counts retain source order; empty slots sort last. This handles irregular source ordering as well as reversed ordering. Largest-only export selects this highest-detail mesh and names it `_LOD0`; all-LOD export uses the same ranking across every selected format. Cold War spline models use the shared model export path and inherit the labels.

CLI: `--reverse-lod-numbering` enables it; `--no-reverse-lod-numbering` disables it. The setting key is `reverse_lod_numbering`. It takes precedence over `match_game_lod_index` when enabled.

Use a fresh output folder or turn off skipping previously exported models when changing numbering for an existing export. Old files are not inspected to determine their LOD convention.

This renumbers existing model LODs. It does not generate terrain LODs or collision.
