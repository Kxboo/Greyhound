#pragma once

namespace AssetCli
{
    // Runs the headless, agent-facing asset command. argv[1] must be "assets".
    int Run(int argc, char** argv);
}
