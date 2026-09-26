#pragma once

#include <cstdint>
#include <string>

// Where a long-running export reports to. The classic window forwards to its
// progress dialog, the v2 UI to its job panel. Called from the worker thread.
struct JobSink
{
    virtual ~JobSink() = default;
    virtual void Status(const std::string& Text) = 0;
    virtual void Progress(uint32_t Percent) = 0;
    // A yes / no / cancel question. Returns IDYES, IDNO or IDCANCEL.
    virtual int Ask(const std::string& Title, const std::string& Text) = 0;
};

struct JobResult
{
    bool Ok = false;
    // Nothing ran: the user backed out before any output was created.
    bool Cancelled = false;
    // The final line shown to the user.
    std::string Status;
    // The output folder, when one was created.
    std::string Path;
};

// Map-level and diagnostic exports shared by both UIs. Check* functions run
// before any file dialog and return a message when the job cannot start.
namespace ExportJobs
{
    std::string CheckModelsFromJson();
    std::string CheckSplineModels();
    std::string CheckRadiantBrushes();
    std::string CheckTerrainSource();
    // Resolves the capture mode from the setting or GREYHOUND_BO4_WORLD_PROBE.
    // Mode 5 is the brush capture, which callers run as RadiantBrushes.
    std::string CheckBo4Diagnostic(int& Mode);

    JobResult ModelPlacements(JobSink& Sink);
    JobResult RadiantBrushes(JobSink& Sink);
    JobResult ModelsFromJson(const std::string& File, JobSink& Sink);
    JobResult SplineModels(const std::string& Placements, const std::string& Controls, JobSink& Sink);
    JobResult TerrainSource(JobSink& Sink);
    JobResult Bo4Diagnostic(int Mode, JobSink& Sink);
    // Checks the installed runtime, or a saved export when Report is a report path.
    JobResult VerifyRuntime(const std::string& Report, JobSink& Sink);
}
