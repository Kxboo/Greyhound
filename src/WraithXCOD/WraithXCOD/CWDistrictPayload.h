#pragma once
#include <cstdint>
#include <cstring>
#include <cmath>
#include <string>
#include <vector>
#include <algorithm>

// Pure validation shared by live and locally packaged CW placement districts.
// No map names, district ordinals, process addresses or asset hashes are fixed.
namespace CWDistrictPayload
{
    constexpr uint64_t MaxBytes = 64ull * 1024 * 1024;
    constexpr uint32_t Stride = 64, HeaderBytes = 304;
    inline uint32_t U32(const uint8_t* P) { uint32_t V; memcpy(&V, P, 4); return V; }
    inline uint64_t U64(const uint8_t* P) { uint64_t V; memcpy(&V, P, 8); return V; }
    inline float F32(const uint8_t* P) { float V; memcpy(&V, P, 4); return V; }
    struct Layout { uint32_t Start = 0, Count = 0; uint64_t References = 0, Transforms = 0; };

    inline bool PackageLayout(const std::vector<uint8_t>& B, uint64_t ExpectedBytes,
        Layout& L, std::string& Error)
    {
        if (B.size() != ExpectedBytes || B.size() < HeaderBytes || B.size() > MaxBytes)
        { Error = "package_allocation_size_mismatch"; return false; }
        L.Start = U32(B.data() + 264); L.Count = U32(B.data() + 268);
        const uint64_t Required = HeaderBytes + 240ull * L.Count + (L.Count % 2 ? 8 : 0);
        if (Required != B.size() || U32(B.data()) != B.size() - 256 ||
            uint64_t(L.Start) + L.Count > UINT32_MAX)
        { Error = "unsupported_package_placement_layout"; return false; }
        for (size_t O = 272; O < HeaderBytes; O += 8)
            if (U64(B.data() + O))
            { Error = "package_contains_relocated_pointers"; return false; }
        L.References = HeaderBytes;
        L.Transforms = HeaderBytes + uint64_t(L.Count) * Stride;
        return true;
    }

    inline bool ValidateArrays(const std::vector<uint8_t>& R, const std::vector<uint8_t>& T,
        uint32_t Count, bool Packaged, std::string& Error)
    {
        const uint64_t Bytes = uint64_t(Count) * Stride;
        if (Bytes > MaxBytes || R.size() != Bytes || T.size() != Bytes)
        { Error = "placement_array_size_mismatch"; return false; }
        std::vector<bool> Seen(Count);
        for (uint32_t I = 0; I < Count; ++I)
        {
            const auto* P = T.data() + size_t(I) * Stride;
            const uint32_t Index = U32(P + 56) & 0x7FFFFFFF;
            if (Index >= Count || Seen[Index])
            { Error = "reference_indices_not_a_permutation"; return false; }
            Seen[Index] = true;
            const auto Identity = U64(R.data() + size_t(Index) * Stride + 16);
            if (!Identity || (Packaged && !(Identity & 0xFFFFFFFFFFFFFFFull)))
            { Error = "empty_model_identity"; return false; }
            for (size_t K = 0; K < 14; ++K)
                if (!std::isfinite(F32(P + K * 4)))
                { Error = "nonfinite_transform_or_bounds"; return false; }
            double Norm = 0;
            for (size_t K = 0; K < 4; ++K) Norm += double(F32(P + K * 4)) * F32(P + K * 4);
            if (std::abs(Norm - 1.0) > 0.002 || !(F32(P + 28) > 0 && F32(P + 28) < 1000))
            { Error = "invalid_rotation_or_scale"; return false; }
            for (size_t K = 0; K < 3; ++K)
                if (std::abs(F32(P + 16 + K * 4)) > 1.0e7f ||
                    F32(P + 32 + K * 4) > F32(P + 44 + K * 4))
                { Error = "invalid_position_or_bounds"; return false; }
        }
        return true;
    }

    // Sort ranges rather than relying on district order in any particular map.
    inline bool Contiguous(std::vector<std::pair<uint32_t, uint32_t>> Ranges)
    {
        std::sort(Ranges.begin(), Ranges.end());
        uint64_t End = 0;
        for (const auto& R : Ranges)
        {
            if (!R.second) continue;
            if (R.first != End) return false;
            End += R.second;
            if (End > UINT32_MAX) return false;
        }
        return true;
    }
}
