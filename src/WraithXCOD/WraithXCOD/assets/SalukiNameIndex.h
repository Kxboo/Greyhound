#pragma once
#include <cstdint>
#include <cstring>
#include <istream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

// Saluki / porter-utils PNDB: LZ4 block containing N nul-terminated names,
// followed by N little-endian uint64 keys. CSV is the cod-name-db source format.
namespace SalukiNames
{
    using Dictionary = std::unordered_map<uint64_t, std::string>;
    constexpr uint64_t AssetMask = 0x0FFFFFFFFFFFFFFFULL;
    constexpr size_t MaxFileSize = 512 * 1024 * 1024;

    inline bool Hex(const std::string& Text, uint64_t& Value)
    {
        size_t Start = Text.compare(0, 2, "0x") == 0 || Text.compare(0, 2, "0X") == 0 ? 2 : 0;
        if (Text.size() <= Start || Text.size() - Start > 16) return false;
        Value = 0;
        for (size_t I = Start; I < Text.size(); ++I)
        {
            const char C = Text[I];
            const int Digit = C >= '0' && C <= '9' ? C - '0' : C >= 'a' && C <= 'f' ? C - 'a' + 10 : C >= 'A' && C <= 'F' ? C - 'A' + 10 : -1;
            if (Digit < 0) return false;
            Value = (Value << 4) | Digit;
        }
        return true;
    }

    inline bool Placeholder(const std::string& Name, uint64_t Hash)
    {
        if (Name.empty()) return true;
        const auto Split = Name.find_last_of('_');
        if (Split == std::string::npos) return false;
        const auto Prefix = Name.substr(0, Split);
        if (!Prefix.empty() && Prefix != "xmodel" && Prefix != "ximage" && Prefix != "xmaterial" &&
            Prefix != "xanim" && Prefix != "xsound" && Prefix != "xstring" && Prefix != "bone" && Prefix != "hash") return false;
        uint64_t Suffix;
        return Hex(Name.substr(Split + 1), Suffix) && Suffix == Hash;
    }

    inline bool InsertFallback(Dictionary& Into, uint64_t Hash, const std::string& Name)
    {
        if (Name.empty() || Name.size() > 4096 || Name.find_first_of(std::string("\0\r\n", 3)) != std::string::npos || Placeholder(Name, Hash)) return false;
        const auto Existing = Into.find(Hash);
        if (Existing == Into.end()) { Into.emplace(Hash, Name); return true; }
        if (Placeholder(Existing->second, Hash)) { Existing->second = Name; return true; }
        return false;
    }

    template<class Emit> size_t ReadCsv(std::istream& In, Emit Add)
    {
        std::string Line;
        size_t Count = 0, Row = 0;
        while (std::getline(In, Line))
        {
            ++Row;
            if (Row == 1 && Line.compare(0, 3, "\xEF\xBB\xBF") == 0) Line.erase(0, 3);
            if (!Line.empty() && Line.back() == '\r') Line.pop_back();
            if (Line.empty()) continue;
            if (Line.size() > 8192) throw std::runtime_error("Name database CSV row is too long.");
            std::vector<std::string> Fields;
            size_t Pos = 0;
            do
            {
                std::string Field;
                if (Pos < Line.size() && Line[Pos] == '"')
                {
                    ++Pos;
                    bool Closed = false;
                    while (Pos < Line.size())
                    {
                        const auto C = Line[Pos++];
                        if (C != '"') Field += C;
                        else if (Pos < Line.size() && Line[Pos] == '"') { Field += '"'; ++Pos; }
                        else { Closed = true; break; }
                    }
                    if (!Closed || (Pos < Line.size() && Line[Pos] != ',')) throw std::runtime_error("Invalid quoted CSV name.");
                }
                else
                    while (Pos < Line.size() && Line[Pos] != ',') Field += Line[Pos++];
                Fields.push_back(std::move(Field));
                if (Pos == Line.size()) break;
                ++Pos;
            } while (Pos <= Line.size());
            uint64_t Hash;
            // The upstream converter ignores malformed keys/records. Some
            // published source CSVs contain merge markers; never treat those as names.
            if (Fields.size() != 2 || !Hex(Fields[0], Hash)) continue;
            Add(Hash, Fields[1]);
            ++Count;
        }
        if (In.bad()) throw std::runtime_error("Could not read name database CSV.");
        return Count;
    }

    template<class Emit, class Decompress> size_t ReadCdb(std::istream& In, Emit Add, Decompress Unpack)
    {
        uint32_t Header[4]{};
        if (!In.read(reinterpret_cast<char*>(Header), sizeof(Header)) || Header[0] != 0x42444E50)
            throw std::runtime_error("Invalid Saluki CDB header.");
        const uint32_t Count = Header[1], Packed = Header[2], Size = Header[3];
        if (Packed > MaxFileSize || Size > MaxFileSize || uint64_t(Count) * 9 > Size)
            throw std::runtime_error("Invalid Saluki CDB sizes.");
        std::vector<char> Compressed(Packed), Data(Size);
        if (!In.read(Compressed.data(), Packed) || In.peek() != std::char_traits<char>::eof())
            throw std::runtime_error("Truncated or oversized Saluki CDB.");
        if (!Size && !Count) return 0;
        if (Unpack(Compressed.data(), Data.data(), Packed, Size) != Size)
            throw std::runtime_error("Saluki CDB decompression failed.");
        const size_t Keys = Size - size_t(Count) * 8;
        size_t Pos = 0;
        // Validate the complete file before exposing any entries to a live cache.
        for (uint32_t I = 0; I < Count; ++I)
        {
            const auto Begin = Pos;
            while (Pos < Keys && Data[Pos]) ++Pos;
            if (Pos >= Keys || Pos - Begin > 4096) throw std::runtime_error("Invalid Saluki CDB name table.");
            ++Pos;
        }
        if (Pos != Keys) throw std::runtime_error("Invalid Saluki CDB key table.");
        Pos = 0;
        for (uint32_t I = 0; I < Count; ++I)
        {
            uint64_t Hash;
            std::memcpy(&Hash, Data.data() + Keys + size_t(I) * 8, 8);
            const std::string Name(Data.data() + Pos);
            Pos += Name.size() + 1;
            Add(Hash, Name);
        }
        return Count;
    }
}
