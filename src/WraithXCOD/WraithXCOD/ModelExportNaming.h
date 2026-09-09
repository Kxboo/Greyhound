#pragma once
#include <string>
#include <cstring>
#include <cctype>
#include <map>
#include <set>
#include <stdexcept>

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
        void Add(const std::string& Name) { Original.insert(Name); Clean[FileStem(Name)].insert(Name); }
        std::string Resolve(const std::string& Name, const std::string& Source) const
        {
            if (!Source.empty()) return Source;
            if (Original.count(Name)) return Name;
            const auto Found = Clean.find(Name);
            if (Found == Clean.end()) return Name;
            if (Found->second.size() != 1)
                throw std::runtime_error("Several runtime models share the name '" + Name + "'. Use placement JSON containing SourceName.");
            return *Found->second.begin();
        }
    };
}
