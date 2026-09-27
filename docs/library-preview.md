# Library preview

The WebView Library can preview the focused model, image or TerrainGfx asset
without exporting it.
Choose **Preview** in the toolbar or row menu. A multi-row export selection is
preserved. Selecting a row does not read its preview data; Enter and
double-click still export. Image rows follow the existing Library setting.

**List** keeps the asset table, **Split** shares space with the viewer, and
**Viewer** keeps a narrow searchable list. Drag or use the arrow keys on the
split divider. Layout and divider position persist in Greyhound settings.

Drag a model to orbit; Shift-drag or right-drag to pan; scroll to zoom.
Images support pan and zoom over a checkerboard. **Fit**, **+**, and **−** are
available in the viewer. **Pop out** moves the preview to a resizable window;
**Dock** or closing that window brings it back. Models use their static pose.

## Reader and rendering contract

The model path uses Greyhound's shared cross-game metadata loader and model
translator. Before translation merges material names, preview copies the chosen
LOD's material references. Each emitted mesh refers back to its source submesh
position, so equal material names cannot merge distinct texture assignments.
Color images use the installed game image handler; selected image rows use the
same direct-image loader as export. Usable color alpha and vertex RGB are retained.
Unknown or unavailable color images use a neutral material and increase the
missing-texture count. Game shader effects, animation and texture synthesis are
outside this viewer. [Every supported reader route is audited here](preview-reader-audit.md).

TerrainGfx uses a coarse, live map preview. Cold War reads a combined color
image and R16 height image; BO4 reads sectors and approximates layer colors.
See the [TerrainGfx reference](terraingfx-reference.md) for layouts, live
checks and limits.

Default limits are 500,000 vertices, 1,000,000 triangles, 2,048 submeshes,
64 textures, a 64 MiB total packet and 24 MiB of RGBA texture data. Model textures
are at most 1,024 pixels per side; selected images are at most 2,048. Empty,
oversized or unavailable LODs are skipped in favor of a usable lower detail level.
Cubes, arrays and volume images display their first slice. DDS decoding also
limits its scratch storage and decoded pixels before allocating them.

## Bridge and lifetime

`assets.query` returns the native view generation. `preview.request` takes
`index`, `generation` and `requestId`, validates the focused row, returns a
status immediately, and queues one background load. Only the latest queued
request survives. Selection changes cancel pending work without starting a read.
Game loading, unloading and export serialize against the preview reader; a
cancelled task checks its token again after acquiring the data lock. Synchronous
game readers cannot be interrupted mid-call, so teardown waits for that call.
The worker joins before the preview service is destroyed.

`preview.status` carries progress or errors. One packed buffer contains
36-byte vertices (float32 XYZ, normal XYZ, UV and RGBA8), uint32 indices and RGBA8
images. JSON describes byte ranges and per-submesh texture slots. WebView2 shared
buffers are read-only and released by the page after validation and GPU upload;
the host closes its handle after posting. Older runtimes use ordered 48 KiB
chunks, at most eight per timer turn. Request, view and transfer IDs reject old
responses. The frontend checks every range and index before uploading.

Pop-out and docking use the same native bridge, worker and retained packet.
The popup cannot change the main asset list. Closing it replays the last completed
preview into the Library. No second game attachment or model read is needed.

The shared-buffer lifecycle follows Microsoft's
[WebView2 API contract](https://learn.microsoft.com/en-us/microsoft-edge/webview2/reference/win32/icorewebview2_17).

## Verification

The native policy, lifecycle and actual DirectXTex tests are in `tests/shared/native`.
The browser mock and binary transport tests are in `tests/shared/ui`.
`assets preview --type model|image|terrain --name EXACT --json` exercises the same native
builder without writing an export. Add `--file PACKAGE` for an image package.
See the reader audit for the games actually smoke-tested and any unavailable routes.

Build with `build-greyhound.ps1 -Configuration Release -Platform x64 -BuildOnly`.
The application and its UI assets are staged into `src/WraithXCOD/x64/Release`.
The classic interface remains available with `--classic` and has no new viewer.
