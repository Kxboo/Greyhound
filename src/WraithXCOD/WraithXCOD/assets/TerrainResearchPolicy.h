#pragma once
#include <Windows.h>
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <vector>

namespace TerrainResearch
{
    struct Budgets
    {
        static constexpr uint64_t MiB = 1024ull * 1024;
        std::map<std::string, uint64_t> Limits{
            {"structure", 1024 * MiB}, {"speculative", 512 * MiB},
            {"resident_terrain", 512 * MiB}, {"resident_scene", 128 * MiB},
            {"packages_terrain", 4096 * MiB}, {"packages_scene", 1024 * MiB},
            {"completion", MiB}};
        std::map<std::string, uint64_t> Used;
        bool Fits(const std::string& Lane, uint64_t Bytes) const
        {
            const auto L = Limits.find(Lane), U = Used.find(Lane);
            return L != Limits.end() && Bytes <= L->second - (U == Used.end() ? 0 : U->second);
        }
        bool Charge(const std::string& Lane, uint64_t Bytes)
        {
            if (!Fits(Lane, Bytes)) return false;
            Used[Lane] += Bytes; return true;
        }
        uint64_t Total() const { uint64_t T = 0; for (const auto& P : Used) T += P.second; return T; }
    };

    inline bool ReadableRange(HANDLE Process, uint64_t Address, uint64_t Bytes,
        std::string& Reason)
    {
        if (!Bytes || Address < 0x10000 || Address >= 0x800000000000ull ||
            Bytes > 0x800000000000ull - Address) { Reason = "invalid_range"; return false; }
        const uint64_t End = Address + Bytes;
        for (uint64_t Cursor = Address; Cursor < End;)
        {
            MEMORY_BASIC_INFORMATION M{};
            if (!VirtualQueryEx(Process, reinterpret_cast<const void*>(Cursor), &M, sizeof(M)))
            { Reason = "query_failed"; return false; }
            const DWORD Access = M.Protect & 0xFF;
            const bool CanRead = Access == PAGE_READONLY || Access == PAGE_READWRITE ||
                Access == PAGE_WRITECOPY || Access == PAGE_EXECUTE_READ ||
                Access == PAGE_EXECUTE_READWRITE || Access == PAGE_EXECUTE_WRITECOPY;
            if (M.State != MEM_COMMIT || (M.Protect & PAGE_GUARD) || !CanRead)
            { Reason = "not_committed_readable"; return false; }
            const auto Base = reinterpret_cast<uint64_t>(M.BaseAddress);
            if (Base > Cursor || M.RegionSize > UINT64_MAX - Base || Base + M.RegionSize <= Cursor)
            { Reason = "invalid_region"; return false; }
            Cursor = std::min<uint64_t>(End, Base + M.RegionSize);
        }
        Reason = "readable_at_query_time"; return true;
    }

    struct PackageBlock { size_t Offset, InputBytes, OutputBytes; uint32_t Codec; };
    struct PackagePlan
    {
        bool Valid = false;
        uint64_t OutputBytes = 0;
        std::string Reason;
        std::vector<PackageBlock> Blocks;
    };
    inline uint32_t Read32(const uint8_t* Data) { uint32_t N; memcpy(&N, Data, 4); return N; }
    // Size an LZ4 block without decompressing or allocating its output.
    inline bool Lz4Size(const uint8_t* D, size_t Size, uint64_t Limit, size_t& Output)
    {
        size_t P = 0; uint64_t N = 0;
        auto Length = [&](uint64_t& L) {
            if (L != 15) return true;
            for (;;) {
                if (P == Size) return false;
                const auto V = D[P++]; L += V;
                if (L > Limit) return false;
                if (V != 255) return true;
            }
        };
        while (P < Size)
        {
            const auto Token = D[P++];
            uint64_t Literals = Token >> 4;
            if (!Length(Literals) || Literals > Size - P || Literals > Limit - N) return false;
            P += static_cast<size_t>(Literals); N += Literals;
            if (P == Size) { Output = static_cast<size_t>(N); return true; }
            if (Size - P < 2) return false;
            const uint32_t Distance = D[P] | (uint32_t(D[P + 1]) << 8); P += 2;
            if (!Distance || Distance > N) return false;
            uint64_t Match = Token & 15;
            if (!Length(Match) || Match + 4 > Limit - N) return false;
            N += Match + 4;
        }
        return false;
    }
    // Uses the existing CW XSUB command layout, with explicit bounds. Unknown
    // codecs retain their raw package but are not guessed at or decompressed.
    inline PackagePlan PlanPackage(const uint8_t* Data, size_t Size,
        uint64_t FileOffset, uint64_t OutputLimit)
    {
        PackagePlan R; size_t P = 0;
        while (P < Size)
        {
            if (Size - P < 8) { R.Reason = "truncated_header"; return R; }
            const auto Count = Read32(Data + P);
            if (!Count || Count > 256) { R.Reason = "unsupported_command_count"; return R; }
            const size_t Header = 8 + std::max<size_t>(30, Count) * 4;
            if (Header > Size - P) { R.Reason = "truncated_commands"; return R; }
            const size_t Commands = P + 8; P += Header;
            for (size_t I = 0; I < Count; ++I)
            {
                const auto Cmd = Read32(Data + Commands + I * 4);
                const uint32_t Codec = Cmd >> 24;
                const size_t In = Cmd & 0xFFFFFF;
                if (In > Size - P) { R.Reason = "truncated_block"; return R; }
                size_t Out = 0;
                if (Codec == 0) Out = In;
                else if (Codec == 8 || Codec == 9)
                {
                    if (In < 4) { R.Reason = "truncated_oodle_size"; return R; }
                    Out = Read32(Data + P);
                }
                else if (Codec == 3)
                {
                    if (!Lz4Size(Data + P, In, OutputLimit - R.OutputBytes, Out))
                    { R.Reason = "invalid_or_oversize_lz4"; return R; }
                }
                else if (Codec != 0xCF) { R.Reason = "unsupported_codec"; return R; }
                if (Out > OutputLimit - R.OutputBytes) { R.Reason = "decoded_span_limit"; return R; }
                if (Codec != 0xCF) R.Blocks.push_back({P, In, Out, Codec});
                R.OutputBytes += Out; P += In;
            }
            if (FileOffset > UINT64_MAX - P - 127) { R.Reason = "offset_overflow"; return R; }
            const auto Next = ((FileOffset + P + 127) & ~uint64_t(127)) - FileOffset;
            if (Next >= Size) break; // final alignment padding may be omitted from the cache entry
            P = static_cast<size_t>(Next);
        }
        R.Valid = R.OutputBytes != 0;
        R.Reason = R.Valid ? "validated_block_sizes" : "empty";
        return R;
    }
}
