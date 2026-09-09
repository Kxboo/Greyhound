#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <vector>

// A duplicate display name is not a missing asset. Select one usable candidate
// per requested name, while retaining the candidate list in the export report.
namespace ModelBatchSelection
{
    struct Candidate
    {
        uint64_t Address;
        size_t SourceIndex;
        bool Usable;
        bool PreviouslyExported;
        bool Loaded;
    };

    inline size_t Select(const std::vector<Candidate>& Candidates)
    {
        const Candidate* Best = nullptr;
        const auto Rank = [](const Candidate& C) { return C.PreviouslyExported ? 0 : C.Loaded ? 1 : 2; };
        for (const auto& C : Candidates)
        {
            if (!C.Usable) continue;
            if (!Best || Rank(C) < Rank(*Best) ||
                (Rank(C) == Rank(*Best) && (C.Address < Best->Address ||
                 (C.Address == Best->Address && C.SourceIndex < Best->SourceIndex))))
                Best = &C;
        }
        return Best ? Best->SourceIndex : (std::numeric_limits<size_t>::max)();
    }
}
