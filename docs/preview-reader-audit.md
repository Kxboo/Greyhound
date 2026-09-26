# Library preview reader audit

The WebView preview uses the same model metadata readers, geometry translators,
material image handlers and direct-image readers as export. This audit checks
all 20 concrete `SupportedGames` routes in the current source. It is a route
audit, not evidence that every game executable/version was exercised live.
`None` is an unloaded state and `Parasyte` is an attachment route which resolves
to a concrete game before assets are read.

Preview does not write models or images to the export folder. The diagnostic
CLI builds the same in-memory packet and prints metadata and its buffer length:

```powershell
.\Greyhound.exe assets preview --type model --name EXACT_MODEL_NAME --json
.\Greyhound.exe assets preview --type image --name EXACT_IMAGE_NAME --json
.\Greyhound.exe assets preview --type image --name EXACT_IMAGE_NAME --file C:\path\images.iwd --json
```

The last form exercises an existing package reader without a running game.
It is not a live-game smoke test. Names must identify exactly one asset. CLI
logging still writes its normal diagnostic log; no asset export is requested.

## Every concrete game route

Every row enters `CoDAssets::LoadGenericModelAsset` and the named
`Game…::ReadXModel`. “Generic” means the shared translator reads vertex/index
data through `ProcessReader`; “streamed” means the translator calls that
game's existing `LoadXModel`. Material images always use the installed
`CoDAssets::GameXImageHandler` and the source `XImage_t`, including its pointer,
semantic and usage. Resident direct image rows use that game's `ReadXImage`.

| Game / enum | Model geometry | Material color image | Selected image route | Live coverage in this run |
| --- | --- | --- | --- | --- |
| Quantum of Solace / `QuantumSolace` | Generic, QS vertex layout | `GameQuantumSolace::LoadXImage` is an existing **unsupported/null stub** | No image rows/read handler | Not available |
| World at War / `WorldAtWar` | Generic | IWD cache through `GameWorldAtWar::LoadXImage` | IWD file entries through `IWDSupport::ReadImageFile` | Not available |
| Black Ops / `BlackOps` | Generic | IWD cache through `GameBlackOps::LoadXImage` | IWD file entries | Four real IWD image cases passed; no live model process |
| Black Ops II / `BlackOps2` | Generic | IPAK cache through `GameBlackOps2::LoadXImage`; resident non-streamed images can be unavailable | IPAK file entries through `IPAKSupport::ReadImageFile` | Not available |
| Black Ops III / `BlackOps3` | Streamed `GameBlackOps3::LoadXModel` | XPAK/resident through `LoadXImage` | `ReadXImage`, or `XPAKSupport::ReadImageFile` | Not available |
| Black Ops 4 / `BlackOps4` | Streamed `GameBlackOps4::LoadXModel` | XPAK/CASC or resident mip through `LoadXImage` | `ReadXImage`, or XPAK file entries | Running process available; see smoke evidence below |
| Black Ops Cold War / `BlackOpsCW` | Streamed `GameBlackOpsCW::LoadXModel` | XSUB/CASC or resident mip through `LoadXImage` | `ReadXImage`, or existing XPAK file route | Not available |
| Call of Duty 4 / `ModernWarfare` | Generic | IWD cache through `GameModernWarfare::LoadXImage` | IWD file entries | Not available |
| Modern Warfare 2 (2009) / `ModernWarfare2` | Generic | IWD cache through `GameModernWarfare2::LoadXImage` | IWD file entries | Not available |
| Modern Warfare 3 (2011) / `ModernWarfare3` | Generic | IWD cache through `GameModernWarfare3::LoadXImage` | IWD file entries | Not available |
| Ghosts / `Ghosts` | Generic | PAK/resident through `GameGhosts::LoadXImage` | `ReadXImage` | Not available |
| Advanced Warfare / `AdvancedWarfare` | Generic, native or PS metadata | `LoadXImage` or installed `LoadXImagePS` | `ReadXImage` now dispatches native/PS consistently | Not available |
| Modern Warfare Remastered / `ModernWarfareRemastered` | Generic, native or PS metadata | `LoadXImage` or installed `LoadXImagePS` | `ReadXImage` dispatches native/PS | Not available |
| Modern Warfare 2 Remastered / `ModernWarfare2Remastered` | Generic, native or PS metadata | `LoadXImage` or installed `LoadXImagePS` | `ReadXImage` dispatches native/PS | Not available |
| Infinite Warfare / `InfiniteWarfare` | Generic, native or PS metadata | `LoadXImage` or installed `LoadXImagePS` | `ReadXImage` dispatches native/PS | Not available |
| WWII / `WorldWar2` | Streamed `GameWorldWar2::LoadXModel` | XPTOC/PAK/resident through `LoadXImage` | `ReadXImage` | Not available |
| Modern Warfare (2019) / `ModernWarfare4` | PS + streamed `GameModernWarfare4::LoadXModel` | XPAK/on-demand/CDN reader | `ReadXImage`, or existing XPAK file route | Not available |
| Vanguard / `Vanguard` | PS + streamed `GameVanguard::LoadXModel` | XSUB v2/VGXPAK/on-demand/CDN reader | `ReadXImage` | Not available |
| Modern Warfare II (2022) / `ModernWarfare5` | PS + streamed `GameModernWarfare5::LoadXModel` | XSUB v3/CDN reader | `ReadXImage`, or existing XPAK file route | Not available |
| Modern Warfare III (2023) / `ModernWarfare6` | PS + streamed `GameModernWarfare6::LoadXModel` | XSUB v3/CDN reader | `ReadXImage` | Not available |

`LoadGamePS` establishes Parasyte variants for Advanced Warfare, MWR, MW2R and
Infinite Warfare, as well as MW2019, Vanguard, MWII and MWIII. The preview must
not replace the installed image handler with a hardcoded native loader. The
AW direct-image wrapper previously did exactly that; its PS dispatch is fixed
to match the other three wrappers.

The old titles do not expose resident image pools through the current Library
readers; opening their supported image package exposes file-entry image rows.
Quantum of Solace geometry can preview with neutral, counted missing materials;
this feature does not invent a decoder for its unimplemented image path.
No additional game version or attachment compatibility is implied.

## Material and geometry fidelity

- The shared translator merges export materials by **name** and rewrites source
  submesh material indices. Preview retains the selected LOD's original material
  array and binds it by source submesh position. Same-named materials with
  different source images therefore remain distinct.
- A reader's diffuse/color semantic selects the image; preview does not assume
  that the first image or a normal/gloss map is a color texture. Missing image
  references, failed package reads, unsupported formats and texture-budget
  exhaustion retain neutral geometry and contribute to the missing-texture
  count.
- All generic and eight streamed geometry routes consult a thread-local preview
  color override through `CoDAssets::LoadVertexColors`. This preserves source
  vertex colors even when export vertex colors are disabled, without mutating
  export settings. QS's existing RGBA fields are copied for preview only;
  classic QS export retains its prior behavior.
- Static geometry is shown in the reader's bind/static pose. Skin animation,
  game material graphs, layered shaders, wind and other runtime deformations
  are outside this viewer.
- Empty and oversized LODs are excluded before translation. Usable candidates
  are ranked by actual triangle/vertex count, with stable source order for
  ties. A missing streamed candidate can fall through to a lower usable one;
  material references always come from that actual selected LOD.

## Images, alpha and resource bounds

The game handlers produce DDS bytes. Preview decodes those bytes in memory
through DirectXTex into bounded RGBA data. It selects a suitable existing mip,
then reduces dimensions if necessary; compressed data is decompressed for the
selected slice/mip. Array, cubemap and volume images show the first slice and
report that choice. The source dimensions remain available in metadata.

Normal map export patches and the user's “clean colour maps” setting do not
globally rewrite preview settings. DDS alpha is retained and premultiplied
alpha is converted to straight RGBA. Infinite Warfare's color alpha may encode
specular information instead of opacity; the model caller treats this known
packed channel as opaque, while a directly selected image retains its data.
Game shader-specific transparency semantics remain outside this approximation.

Default limits are 500,000 vertices, 1,000,000 triangles, 2,048 submeshes,
64 MiB final packet, 24 MiB total model texture pixels, 64 model textures,
1,024-pixel model textures and 2,048-pixel selected images. Decode also bounds
DDS source bytes, scratch storage, source dimensions and expanded pixel count.
An existing synchronous game/package decoder can temporarily allocate its
native result before preview checks it; cancellation is cooperative between
those existing reader calls.

## Source lifetime and request ordering

`CoDAssets` holds global process, pool, cache and handler state. A generation
check after reading is insufficient: `CleanUpGame` can free all of it first.
The WebView bridge serializes preview reader work with load, unload and export
using its game-data lock. A cancelled worker checks its token again after
acquiring that lock, before dereferencing the selected asset. Package and
on-demand cache loading must finish before image reads.

`LatestPreviewWorker` owns one thread and at most one pending request. New work
invalidates the active token and replaces queued work; unload clears pending
work. Destruction cancels and joins the thread. The UI also verifies request
identity and view generation before accepting asynchronous status/data. Source
pointers are never sent to the renderer. Pop-out/dock shares the same preview
service and already-built data rather than starting a second game reader.

## Verification and limits

Checked source routes: `assets/CoDAssets.cpp`,
`exporters/CoDXModelTranslator.cpp`, all 20 `games/*/reader/Game*.cpp`, the
IWD/IPAK/XPAK support classes, `assets/preview/PreviewData.*` and
`assets/preview/PreviewImage.*`.

The following independent native checks run against the implementation:

```powershell
.\tests\run-native-tests.ps1 -TestPattern 'shared/native/preview*test.cpp'
.\tests\run-preview-image-tests.ps1
```

- `preview_policy_test.cpp`: duplicate material names with different image
  pointers, absent material/image references, empty LODs, oversized high-detail
  fallback, stable detail ties, submesh limits and overflow-safe byte budgets.
- `preview_lifecycle_test.cpp`: replacing active work, coalescing queued work,
  cancellation while blocked on the source lock, unload cancellation, exception
  recovery and destructor joining.
- `preview_image_roundtrip.cpp`: real DDS RGBA/BC3 decoding, transparent and
  partial alpha, forced opacity, premultiplied-to-straight conversion, texture
  resizing and byte budgets, first array slice and malformed input rejection.

These tests passed during implementation. The x64 Release build completed at
`src/WraithXCOD/x64/Release/Greyhound.exe`; the final incremental build is logged
in `test-output/preview/build-final.log`. Existing link/runtime-staging warnings
do not prevent the preview build; the missing optional terrain shader reflection
DLL is unrelated to preview's DirectXTex decoder.

The final binary passed four image previews from the installed Black Ops
`main/iw_01.iwd` package. Every result exited 0, independently verified packet
ranges/indices/texture bindings (`packet_verified: true`), and reported an empty
`generated_files` array. These exercise the real IWD cache, IWI translation and
preview DDS decoder, without exporting assets:

| Real package image | Preview pixels | Result |
| --- | --- | --- |
| `console` | 4 x 4; 64 bytes | Opaque RGBA |
| `$blacktransparent` | 4 x 4; 64 bytes | Alpha retained |
| `aperture_crosshair_c` | 256 x 256; 262,144 bytes | Color and alpha retained |
| `cave_creek_cube` | 128 x 128; 65,536 bytes | First cubemap face, `firstSlice: true` |

Packet generation took 30–44 ms for these cases. Saved machine-readable evidence:
[`legacy-smoke-summary.json`](../test-output/preview/legacy-smoke-summary.json),
with per-case JSON and stderr files in the same folder. A package smoke test does
not substitute for a live legacy model test. At audit time only `BlackOps4.exe`
was running (PID 1516); no legacy game process was available. Frontend mock and
live BO4 checks are recorded with final integration evidence. All other game
rows above remain source route audits until exercised against an available
installation/process.

### Live BO4 and WebView integration

The final Release application was exercised against the user's loaded BO4 map.
Both the CLI and real WebView rendered `attach_t8_ar_accurate_barrel_view`:
1,974 vertices, 1,916 triangles, its referenced 512 x 128 color image, zero
missing textures and a 356,200-byte packet. The CLI independently verified the
packet and generated no export files. Native UI checks also covered the
two-submesh barricade collision model, `$alpha`, and `*cookie_array` (512 x 512,
first slice). The user separately confirmed the BO4 preview worked.

The native runs confirmed focused-row preview with export selection preserved,
shared-buffer uploads, pop-out rendering, closing the native popup
back into the Library, focus cancellation and unload clearing, with zero browser
exceptions and zero export commands. Repeated observers in the second native
run inflated its raw event count; it is evidence of successful shared delivery,
not a count of unique transfers. Chunk fallback, duplicate-name/different-texture
binding, malformed buffers, resizing, layout persistence and graphics-context recovery were exercised by the
transport and browser mock tests. No older WebView runtime was available to
exercise native shared-buffer API absence directly.

Evidence: [`bo4-model-preview.json`](../test-output/preview/bo4-model-preview.json),
[`native shared smoke`](../test-output/preview/native-shared/native-ui-smoke.json),
[`native textured smoke`](../test-output/preview/native-streamed/native-ui-smoke.json).
