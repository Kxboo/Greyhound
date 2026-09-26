#pragma once

// Greyhound v2 window: a WebView2 page served from the ui folder beside the
// exe, driven through UiBridge. The classic MFC window stays available with
// --classic and is used automatically when the WebView2 runtime is missing.
namespace UiHost
{
    // True when the WebView2 runtime is installed and the ui folder exists.
    bool Available();
    // Runs the window on its own STA thread and returns once it has closed.
    // Returns false when the window could not be created at all.
    bool Run();
}
