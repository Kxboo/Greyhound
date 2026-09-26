#pragma once
#include <string>
#include <cstring>
#include <cctype>
#include <map>
#include <set>
#include <stdexcept>
#include <vector>
#include <algorithm>
#include <cstdint>

namespace ModelExportNaming
{
    // Runtime names remain identifiers. This is only the exported display stem.
    inline std::string Stem(const std::string& Name)
    {
        size_t Start = 0;
        if (!Name.empty() && Name[0] == '*') Start = 1;
        else if (Name.compare(0, 3, "%2A") == 0 || Name.compare(0, 3, "%2a") == 0) Start = 3;
        if (!Start) return Name;
        auto Lower = Name;
        for (auto& C : Lower) C = static_cast<char>(std::tolower(static_cast<unsigned char>(C)));
        const auto End = Lower.find(".map", Start);
        if (End == std::string::npos || End == Start ||
            (End + 4 < Name.size() && Name[End + 4] != '_')) return Name;
        return Name.substr(Start, End - Start);
    }

    inline std::string Escape(const std::string& Name)
    {
        std::string Out;
        const char* Hex = "0123456789ABCDEF";
        for (unsigned char C : Name)
        {
            if (C < 32 || C == '%' || std::strchr("<>:\"/\\|?*", C))
            { Out += '%'; Out += Hex[C >> 4]; Out += Hex[C & 15]; }
            else Out += char(C);
        }
        return Out;
    }

    inline std::string FileStem(const std::string& Name) { return Escape(Stem(Name)); }

    // Baked spline mesh: splm_<model>_<spline instance>. Each instance is its own
    // deformed mesh, so the instance index keeps names unique within a map.
    inline std::string SplineName(const std::string& Source, uint32_t Index)
    {
        const auto Slash = Source.find_last_of('/');
        std::string Out = "splm_";
        for (unsigned char C : Stem(Slash == std::string::npos ? Source : Source.substr(Slash + 1)))
            Out += std::isalnum(C) ? char(std::tolower(C)) : '_';
        return Out + "_" + std::to_string(Index);
    }

    // Map every source slot to a highest-detail-first output index. Empty slots
    // sort last; ties retain source order. Never mutate source LOD selection data.
    template<class Lods> std::vector<int> DetailRanks(const Lods& Items)
    {
        struct Entry { int Source; uint64_t Faces, Vertices; };
        std::vector<Entry> Order;
        for (size_t i = 0; i < Items.size(); ++i)
        {
            uint64_t Faces = 0, Vertices = 0;
            for (const auto& Surface : Items[i].Submeshes)
            { Faces += Surface.FaceCount; Vertices += Surface.VertexCount; }
            if (!Faces || !Vertices) Faces = Vertices = 0;
            Order.push_back({static_cast<int>(i), Faces, Vertices});
        }
        std::stable_sort(Order.begin(), Order.end(), [](const Entry& A, const Entry& B) {
            return A.Faces != B.Faces ? A.Faces > B.Faces : A.Vertices > B.Vertices;
        });
        std::vector<int> Ranks(Items.size());
        for (size_t i = 0; i < Order.size(); ++i) Ranks[Order[i].Source] = static_cast<int>(i);
        return Ranks;
    }

    inline std::string LodSuffix(bool AllLods, bool MatchGameIndex, int Index)
    {
        return AllLods || MatchGameIndex ? "_LOD" + std::to_string(Index) : std::string();
    }

    template<class Json> inline void PublishPlacementName(Json& Row)
    {
        const auto Source = Row.value("SourceName", Row.value("Name", std::string()));
        Row["SourceName"] = Source;
        Row["Name"] = FileStem(Source);
        Row.erase("ExportName");
    }

    // Accept new placement JSON, legacy raw names, and unambiguous clean names.
    // The runtime identifier is never inferred from a colliding clean name.
    struct SourceLookup
    {
        std::set<std::string> Original;
        std::map<std::string, std::set<std::string>> Clean;
        void Add(const std::string& Name, const std::string& HashAlias = "")
        {
            Original.insert(Name); Clean[FileStem(Name)].insert(Name);
            if (!HashAlias.empty()) Clean[HashAlias].insert(Name);
        }
        std::string Resolve(const std::string& Name, const std::string& Source) const
        {
            const auto& Requested = Source.empty() ? Name : Source;
            if (Original.count(Requested)) return Requested;
            const auto Found = Clean.find(Requested);
            if (Found == Clean.end()) return Requested;
            if (Found->second.size() != 1)
                throw std::runtime_error("Several runtime models share the name '" + Name + "'. Use placement JSON containing SourceName.");
            return *Found->second.begin();
        }
    };
}
