# Black Ops 4 Radiant export

Load a BO4 map, choose **Load Game**, then **Radiant Brushes → Export brushes**.
The same action supports Cold War. The setting that mentions automatic Cold War
pool export is a separate shortcut; it does not limit the Export brushes button.

Each BO4 run reserves a fresh map-named directory under the configured export
root. Repeated exports get a unique suffix. Existing exports are not replaced.

| Folder | Contents |
| --- | --- |
| `prefabs/brushes` | Non-clip tool geometry and available source render surfaces |
| `prefabs/clips` | World and inline collision using named BO3 stock tools |
| `prefabs/model clips` | Model-attached collision hulls |
| `prefabs/review` | Remaining tool-category substitutions and provisional volumes |
| `_mat_info` | Recovered source material records |
| `_images` | Recovered material images, grouped by material |
| `metadata` | Assignments, omissions, verification and final export report |
| `diagnostics` | Captured source bytes and conversion evidence |

## How material assignment works

BO4 collision side and axial indices address collision filters, which contain
contents and surface flags. They do **not** identify the rendered material.
The exporter translates their named collision categories into BO3 stock tool
materials. Where one stock material cannot express the category combination,
coincident hulls can provide a verified union of stock tool categories.

Remaining category differences go into review prefabs. The report at
`metadata/material_mapping_report.json` lists each affected source and the
added or omitted categories. Detailed assignments also preserve differences in
surface response. Matching category names is not proof of identical gameplay
after compilation. BO4 always performs this assignment; the optional automatic
type checkbox applies to Cold War.

Visible materials come from the original GfxWorld surface material reference.
Available source triangles are written as separate patches with explicit UVs,
alongside their material records and decoded images. These are static render
surfaces; they do not reconstruct the original editor brush topology or shaders.
Their material identity is not inferred from nearby collision.

There is no generic concrete, grey or clip replacement for a missing original
visual material. Unresolved material names, missing dependencies, unsupported
ownership and visual brush faces without sufficient evidence are reported.
When the original name is unknown but its captured identity and dependencies
are available, a hash-named asset preserves that original material and its
images. Its metadata explicitly records that the name was unresolved.
Excluded source data remains in diagnostics. Material records and images are
porting inputs; they are not a finished BO3 asset database or shader conversion.

## Verification and limits

The converter verifies emitted brush planes, stock tool assignments and certified
partitions before reporting success. Partitioned brushes have at most 64 planes.
Published files and material dependencies are hashed in
`metadata/export_report.json`; **Verify saved export** detects missing or changed
files. The native job requires both converter success and a final verification
report, so a failed conversion cannot appear as a completed export.

The report distinguishes omitted primitives, placements and review geometry.
Triangle collision metadata, when requested, remains a separate representation.
Scripts and game logic are not ported. Open the chosen prefabs at origin zero,
rotation zero and scale one. BO3 Radiant opening, compilation and gameplay checks
remain necessary before treating the result as a playable port.
