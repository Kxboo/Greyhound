#pragma once
#include <string>
#include <vector>
#include "TerrainResearchCapture.h"
#include "GameBlackOpsCW.h"

// Renders the decoded Cold War entity/trigger candidates as a flat key/value
// document in the same shape a C2M export uses, so the two can be diffed
// directly. Every value here comes from the decoded candidate JSON; nothing is
// re-read from the process and no unknown hash is replaced with a guess.
namespace CWMapEntityExport
{
    using TerrainResearch::json;

    // C2M prints the shortest round-trippable form: "8", "0.5", "0 0 0".
    inline std::string Number(double V)
    {
        if (!std::isfinite(V)) return "0";
        auto Text = Strings::Format("%.7g", V);
        if (Text == "-0") Text = "0";
        return Text;
    }

    inline std::string ResolveHash(uint64_t Hash)
    {
        const auto& Models = GameBlackOpsCW::AssetNameCache.NameDatabase;
        const auto& Text = GameBlackOpsCW::StringCache.NameDatabase;
        for (uint64_t Key : {Hash, Hash & 0xFFFFFFFFFFFFFFFull})
        {
            const auto M = Models.find(Key);
            if (M != Models.end()) return M->second;
            const auto S = Text.find(Key);
            if (S != Text.end()) return S->second;
        }
        // Unresolved hashes stay hexadecimal, matching what C2M writes.
        return Strings::Format("%llX", Hash);
    }

    inline bool Value(const json& Property, std::string& Out)
    {
        const auto Type = Property.value("type_tag", 0);
        if (Type == 2)
        {
            if (!Property.contains("string_candidate")) return false;
            const auto& S = Property["string_candidate"];
            if (!S.value("terminated", false) || !S.contains("text")) return false;
            Out = S["text"].get<std::string>();
            return true;
        }
        if (Type == 3)
        {
            if (!Property.contains("vector_candidate")) return false;
            const auto& V = Property["vector_candidate"];
            if (!V.is_array() || V.size() != 3) return false;
            Out = Number(V[0].get<double>()) + " " + Number(V[1].get<double>()) +
                " " + Number(V[2].get<double>());
            return true;
        }
        if (Type == 4)
        {
            if (!Property.contains("asset_hash_candidate")) return false;
            const auto Hex = Property["asset_hash_candidate"].get<std::string>();
            Out = ResolveHash(std::strtoull(Hex.c_str() + (Hex.rfind("0x", 0) == 0 ? 2 : 0), nullptr, 16));
            return true;
        }
        if (Type == 5)
        {
            if (!Property.contains("float_candidate")) return false;
            Out = Number(Property["float_candidate"].get<double>());
            return true;
        }
        if (Type == 6)
        {
            // C2M prints these unsigned; that reproduced every sampled value,
            // including the guid fields that are negative when read signed.
            if (!Property.contains("uint32_candidate")) return false;
            Out = std::to_string(Property["uint32_candidate"].get<uint64_t>());
            return true;
        }
        return false;
    }

    inline void Emit(TerrainResearch::Capture& C, uint32_t Pool, const json& Decoded)
    {
        if (!Decoded.contains("entities") || !Decoded["entities"].is_array()) return;

        json Entities = json::array();
        std::string Text;
        uint64_t Rendered = 0, Skipped = 0;
        for (const auto& E : Decoded["entities"])
        {
            // origin and angles lead each block, as they do in a C2M dump.
            std::vector<std::pair<std::string, std::string>> Pairs;
            const char* Leading[] = {"origin", "angles"};
            for (const char* Want : Leading)
                for (const auto& P : E["properties"])
                    if (P.contains("key") && P["key"].value("text", "") == Want)
                    {
                        std::string V;
                        if (Value(P, V)) Pairs.emplace_back(Want, V);
                    }
            for (const auto& P : E["properties"])
            {
                if (!P.contains("key")) { ++Skipped; continue; }
                const auto Key = P["key"].value("text", std::string());
                if (Key.empty()) { ++Skipped; continue; }
                if (Key == "origin" || Key == "angles") continue;
                std::string V;
                if (!Value(P, V)) { ++Skipped; continue; }
                Pairs.emplace_back(Key, V);
            }

            json Object = json::object();
            Text += "{\n";
            for (const auto& KV : Pairs)
            {
                Object[KV.first] = KV.second;
                Text += "\"" + KV.first + "\" \"" + KV.second + "\"\n";
            }
            Text += "}\n";
            Entities.push_back(Object);
            ++Rendered;
        }

        const std::string Stem = Pool == 0x80 ? "triggers" : "entities";
        json Document = {{"schema", "cw-entity-keyvalues-v1"}, {"source_pool", Pool},
            {"source_name_hash", Decoded.value("source_name_hash", std::string())},
            {"entity_count", Rendered}, {"properties_skipped", Skipped},
            {"value_status", "typed candidate values; unresolved asset hashes remain hexadecimal"},
            {"Entities", Entities}};
        const auto JsonText = Document.dump(2);
        const bool SavedJson = C.Write(Stem + ".json",
            reinterpret_cast<const uint8_t*>(JsonText.data()), JsonText.size());
        const bool SavedText = C.Write(Stem + ".txt",
            reinterpret_cast<const uint8_t*>(Text.data()), Text.size());

        C.Report["keyvalue_export"] = {{"json", Stem + ".json"}, {"text", Stem + ".txt"},
            {"saved", SavedJson && SavedText}, {"entities", Rendered},
            {"properties_skipped", Skipped}};
    }
}
