#include "ui/native/PreviewService.h"

#include <chrono>
#include <cstdlib>
#include <future>
#include <iostream>
#include <stdexcept>

namespace
{
    void Check(bool Value, const char* Message)
    {
        if (!Value) { std::cerr << Message << '\n'; std::abort(); }
    }
    template<typename T> T Await(std::future<T>& Future)
    {
        Check(Future.wait_for(std::chrono::seconds(5)) == std::future_status::ready,
            "Preview worker did not finish in five seconds");
        return Future.get();
    }
}

int main()
{
    // A replacement invalidates running work and coalesces the pending queue.
    {
        LatestPreviewWorker Worker;
        std::promise<void> Started, Release, Finished;
        auto StartedFuture = Started.get_future();
        auto ReleaseFuture = Release.get_future().share();
        auto FinishedFuture = Finished.get_future();
        std::atomic<bool> SawCancellation{ false }, ObsoleteRan{ false };
        std::atomic<int> ActiveReaders{ 0 };
        Worker.Submit([&](const auto& Cancelled)
        {
            Check(++ActiveReaders == 1, "Source readers overlapped");
            Started.set_value();
            ReleaseFuture.wait();
            SawCancellation = Cancelled();
            --ActiveReaders;
        });
        Await(StartedFuture);
        Check(Worker.Busy(), "Busy must include active work");
        Worker.Submit([&](const auto&) { ObsoleteRan = true; });
        Worker.Submit([&](const auto& Cancelled)
        {
            Check(++ActiveReaders == 1, "Source readers overlapped");
            Check(!Cancelled(), "Latest request was unexpectedly cancelled");
            --ActiveReaders;
            Finished.set_value();
        });
        Release.set_value();
        Await(FinishedFuture);
        Check(SawCancellation, "Running request did not observe its replacement");
        Check(!ObsoleteRan, "Superseded pending request performed source reads");
    }

    // A reader blocked on game data must recheck cancellation under that lock:
    // unload may have freed the pointed-to pool before it becomes available.
    {
        LatestPreviewWorker Worker;
        std::mutex DataAccess;
        std::unique_lock<std::mutex> HoldData(DataAccess);
        std::promise<void> Waiting, Finished;
        auto WaitingFuture = Waiting.get_future();
        auto FinishedFuture = Finished.get_future();
        std::atomic<bool> SourceRead{ false };
        Worker.Submit([&](const auto& Cancelled)
        {
            Waiting.set_value();
            std::lock_guard<std::mutex> Lock(DataAccess);
            if (!Cancelled()) SourceRead = true;
            Finished.set_value();
        });
        Await(WaitingFuture);
        Worker.Cancel();
        HoldData.unlock();
        Await(FinishedFuture);
        Check(!SourceRead, "Cancelled lock waiter read an obsolete source pointer");
    }

    // Unload/reload cancellation invalidates active work and removes queued work.
    {
        std::atomic<bool> OldRan{ false }, SawCancellation{ false };
        std::promise<void> Started, Release;
        auto StartedFuture = Started.get_future();
        auto ReleaseFuture = Release.get_future().share();
        {
            LatestPreviewWorker Worker;
            Worker.Submit([&](const auto& Cancelled)
            {
                Started.set_value();
                ReleaseFuture.wait();
                SawCancellation = Cancelled();
            });
            Await(StartedFuture);
            Worker.Submit([&](const auto&) { OldRan = true; });
            Worker.Cancel();
            Release.set_value();
        }
        Check(SawCancellation, "Unload did not invalidate the active request");
        Check(!OldRan, "Unload retained queued work pointing to the old pool");
    }

    // A failed callback cannot strand the worker; a later preview can succeed.
    {
        LatestPreviewWorker Worker;
        std::promise<void> Failed, Recovered;
        auto FailedFuture = Failed.get_future();
        auto RecoveredFuture = Recovered.get_future();
        Worker.Submit([&](const auto&) { Failed.set_value(); throw std::runtime_error("fixture"); });
        Await(FailedFuture);
        Worker.Submit([&](const auto&) { Recovered.set_value(); });
        Await(RecoveredFuture);
    }

    // Destruction cancels and joins active work before any captured owner dies.
    {
        std::promise<void> Started;
        auto StartedFuture = Started.get_future();
        std::atomic<bool> Exited{ false };
        {
            LatestPreviewWorker Worker;
            Worker.Submit([&](const auto& Cancelled)
            {
                Started.set_value();
                while (!Cancelled()) std::this_thread::yield();
                Exited = true;
            });
            Await(StartedFuture);
        }
        Check(Exited, "Worker outlived its service owner");
    }
    std::cout << "Preview replacement, cancellation, exception recovery and shutdown passed\n";
}
