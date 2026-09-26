#pragma once

#include <atomic>
#include <condition_variable>
#include <cstdint>
#include <functional>
#include <mutex>
#include <thread>

// One reader at a time, at most one queued request. Work must check Cancelled
// before touching a source asset, including after waiting for the reader lock.
// The destructor joins: no detached preview work may outlive its owning bridge.
class LatestPreviewWorker
{
public:
    using Cancelled = std::function<bool()>;
    using Work = std::function<void(const Cancelled&)>;
    LatestPreviewWorker() : Thread([this] { Run(); }) {}
    ~LatestPreviewWorker()
    {
        {
            std::lock_guard<std::mutex> Lock(Mutex);
            Stopping = true;
            ++Epoch;
            Pending = {};
        }
        Wake.notify_one();
        Thread.join();
    }
    LatestPreviewWorker(const LatestPreviewWorker&) = delete;
    LatestPreviewWorker& operator=(const LatestPreviewWorker&) = delete;

    void Submit(Work Next)
    {
        {
            std::lock_guard<std::mutex> Lock(Mutex);
            ++Epoch;
            Pending = std::move(Next);
        }
        Wake.notify_one();
    }
    void Cancel()
    {
        std::lock_guard<std::mutex> Lock(Mutex);
        ++Epoch;
        Pending = {};
    }
    bool Busy()
    {
        std::lock_guard<std::mutex> Lock(Mutex);
        return Running || bool(Pending);
    }

private:
    std::mutex Mutex;
    std::condition_variable Wake;
    std::atomic<uint64_t> Epoch{0};
    bool Running = false, Stopping = false;
    Work Pending;
    std::thread Thread;

    void Run()
    {
        for (;;)
        {
            Work Task;
            uint64_t Ticket;
            {
                std::unique_lock<std::mutex> Lock(Mutex);
                Wake.wait(Lock, [this] { return Stopping || bool(Pending); });
                if (Stopping) return;
                Task = std::move(Pending);
                Pending = {};
                Running = true;
                Ticket = Epoch;
            }
            // Callers report errors; this last boundary still keeps the worker
            // alive if a completion callback fails unexpectedly.
            try { Task([this, Ticket] { return Epoch.load() != Ticket; }); }
            catch (...) {}
            {
                std::lock_guard<std::mutex> Lock(Mutex);
                Running = false;
            }
        }
    }
};
