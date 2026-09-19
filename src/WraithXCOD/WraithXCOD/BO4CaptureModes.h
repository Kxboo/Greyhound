#pragma once

// Shared by Terrain settings, Dev Tools and the native capture dispatcher.
namespace BO4Diagnostics
{
    // Black Ops 4 has no reversed TerrainGfx structure, so its Export button
    // runs a measurement capture rather than a reconstruction one. The same
    // button also reaches six other world captures that previously existed
    // only as GREYHOUND_BO4_WORLD_PROBE values, undiscoverable from here.
    struct CaptureMode
    {
        const char* Value;
        const wchar_t* Label;
        const wchar_t* Hint;
    };

    const CaptureMode BO4CaptureModes[] =
    {
        { "0", L"Terrain source probe (default)",
          L"Measures the TerrainGfx header: header.terraingfx.bin, referenced regions, resident height / cutout / layer weight mips and a shader scan, summarised in terraingfx_probe.json. No terrain mesh is reconstructed." },
        { "1", L"Map world pools",
          L"Bounded map-pool evidence: world_pools_probe.json with the per-pool and per-slot payload dumps. Avoids re-running the terrain, texture and shader capture while working on collision layouts." },
        { "2", L"Model collision references",
          L"model_collision_probe.json with model headers, the counted collision surface and triangle arrays and instance transforms. Decode and placement validation happen offline." },
        { "3", L"Model collision (physics only)",
          L"model_physics_probe.json and model_physics.bin: references, transforms and brush / primitive lists only. This is the capture the Radiant brush export consumes." },
        { "4", L"Model placements",
          L"model_placement_capture.json plus static_models.json and placement_report.json. Placement records, not render meshes." },
        { "5", L"Radiant brush prefabs",
          L"Runs the full BO4 brush, clip and model-physics prefab export, the same as Settings / Radiant Brushes / Export brushes now. Output goes to its own export folder, not this terrain run." },
        { "6", L"Collision handler tables",
          L"collision_handlers.json and the located handler byte ranges from the executable. Research evidence for how collision types are dispatched." },
        { "7", L"Named surface-flag declarations only",
          L"surface_flags_probe.json: the stable named flag declarations with no map-pool capture, so it does not depend on a loaded map's layout." },
    };

    constexpr int BO4CaptureModeCount =
        int(sizeof(BO4CaptureModes) / sizeof(BO4CaptureModes[0]));
}
