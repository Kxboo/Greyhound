# BO4 volume decals in BO3

`export_bo3.py --capture SOURCE/decal_capture.json --output NEW_BO3_OVERLAY [--placements]` packages one selected BO4 material. The default exports its native BO3 material and two image assets. `--placements` also writes editable `misc_volume_decal` entities to `map_source/_prefabs`. The output is a separate BO3-root overlay; it does not modify the installed game or bake decals into terrain. No BO3 installation is required for export. The optional legacy `--bo3-root` argument only prevents writing inside that path.

`bo3_stock_template_v1.json` is a versioned snapshot of the verified material and image default dictionaries from `texture_assets/t7_decal_grunge.gdt`. The exporter checks its SHA-256 before conversion, and the package report records the snapshot and source-GDT identities. It contains no BO3 textures or binaries; the generated image files come from the selected BO4 capture.

Only the measured `6e0a762e671e6047` color/reveal shader family and its verified image bindings, sampler states, blend state, and material constants are accepted. Every source placement is checked independently. Unsupported transforms, UVs, masks, facing, target filters, forward materials, or values outside native editor bounds remain listed by original world index in `package_report.json`. A partial placement package exits with code 3 and is marked `complete: false`; asset-only packages contain no source placements. BO3 in-game visual parity remains unverified.

For native placement ordering, BO4 source priority 1–22 maps to the BO3 layer name and enum 0–21. The BO3 `misc_volume_decal` definition lists this exact order, and 1,902 same-name stock-material instances corroborate twelve category pairs in saved BO4/BO3 data, including priorities 2 and 15 in the measured 32-instance material. Priority 3 follows the contiguous native category order; it lacks a direct same-name stock-material pair. BO3 `cod2map64.exe` reads the entity's `decalLayerSort` and editor sort separately when building its decal sort ID; the material's default Grunge category does not replace the per-entity value. This establishes the native field mapping, not pixel-identical overlapping draw order.

BO4 records store the per-axis runtime feather threshold. In BO3 `Radiant_modtools.exe`, each editor `edgeFeatherX/Y/Z` is clamped to 0–1 and subtracted from 1 before the three runtime values are written to the projector GPU record at the same offsets used by BO4. The exporter therefore writes BO3 editor feather as `1 - BO4 runtime feather`: BO4 `(1,1,1)` becomes BO3 `(0,0,0)`, and `(0.5,1,1)` becomes `(0.5,0,0)`. The package report records both values for every exported decal placement. It does not claim the two games' shader curves or facing behavior are visually identical.

## Evidence locators

Paths below are relative to the inspected BO3 installation. Native addresses
are virtual addresses for image base `0x140000000`.

- `bin/t7.def.json:7885` defines the editor feather fields;
  `:7912` defines the 22 layer names, followed by their numeric and editor sorts.
  `deffiles/material.awi:434–460` uses the matching material category order.
- `bin/Radiant_modtools.exe`, SHA256
  `b44c6d21426b9e33b4463345020671613efdc7678bd39e3b36d54634eb851091`:
  feather subtraction instructions are at `0x140CA4CEE`, `0x140CA4DAF`,
  and `0x140CA4E70`. The float at `0x14227BB04` is `1.0`.
  The complemented triple reaches `0x140B69330`; instructions at
  `0x140B69400–0x140B69416` copy it to GPU offsets `0x80/0x84/0x88`.
- `bin/cod2map64.exe:0x1400A6252–0x1400A628B` reads the entity's layer name
  and editor sort separately. At `0x1400A63FE–0x1400A6411`, it calls
  `GetDecalSortID` (`0x14008E760`) and stores the instance result at `+0x90`.
- `map_source/_prefabs/zm/zm_giant/geo/zone_b/zoneb_pack_a_punch_area.map:68039`
  provides a stock `Damage - New` / enum `1` placement example.
