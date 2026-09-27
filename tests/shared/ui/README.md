# Preview UI checks

Run from the repository root:

```powershell
node tests/shared/ui/preview_transport_test.cjs
node tests/shared/ui/preview_mock_test.cjs
node tests/shared/ui/terrain_mock_test.cjs
```

The transport check uses Node's built-in assertions and has no package dependencies. The browser check requires the `playwright` package and installed Microsoft Edge; set `NODE_PATH` to the existing package directory if it is not on Node's module path. It starts a temporary loopback server and a headless browser, then closes both. It does not attach to a game, export files, or change native Greyhound settings.

The browser fixture deliberately contains three model parts with the same material name: two reference different color textures and one has no available texture. The image fixture contains transparent pixels. The checks cover:

- Automatic preview on click and keyboard navigation (including uncached rows), focused-row identity and preserving multiple export selections.
- Duplicate-name texture slots, neutral fallback, missing-texture count and decoded image display.
- Orbit, zoom, fit, canvas resize and recovery after graphics context loss.
- List, Split and Viewer layouts, draggable divider and persistent layout settings.
- Pop-out replay, resizable secondary view, closing to dock, and an asset completed in the pop-out before focus changes in the main list.
- A newer focus or game unload overtaking a pending decode.
- Bounded buffer assembly, stale generations and replay transfers, incomplete or invalid geometry and image bounds, and the shared-buffer path.

Set `PREVIEW_SCREENSHOT_DIR` to an output directory to save model and image screenshots during the browser check. The fixture validates frontend behavior; game-specific decoding and LOD fallback require the native preview data checks and real game smoke tests.

`preview_native_smoke.cjs` is an explicit integration check for a caller-owned Greyhound instance launched with WebView remote debugging. It accepts a CDP endpoint, the verified native process ID and an output directory. It reads the running game, temporarily enables model and image rows, previews assets, closes its own pop-out through the native window close path, and unloads Greyhound's asset library; it never exports or closes the game. The caller must snapshot and restore Greyhound settings and owns application shutdown. Optional `NATIVE_PREVIEW_MODEL` and `NATIVE_PREVIEW_IMAGE` pick exact names among the first 100 sorted rows. It saves screenshots and `native-ui-smoke.json`.
