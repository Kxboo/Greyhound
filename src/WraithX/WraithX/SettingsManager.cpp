#include "stdafx.h"

#include "SettingsManager.h"

#include "Strings.h"
#include "FileSystems.h"
#include "BinaryReader.h"
#include "BinaryWriter.h"
#include "TextWriter.h"
#include "TextReader.h"
#include "Hashing.h"
#include "json.hpp"

std::unordered_map<std::string, std::string> SettingsManager::SettingsCache;
std::string SettingsManager::SettingsFileName = "";
bool SettingsManager::PersistenceEnabled = true;

void SettingsManager::LoadTransientSettings(const std::map<std::string, std::string>& Defaults)
{
    SettingsCache.clear();
    SettingsFileName.clear();
    PersistenceEnabled = false;
    for (const auto& Entry : Defaults)
        SettingsCache.insert(Entry);
}

void SettingsManager::LoadSettings(const std::string& SettingsName, const std::map<std::string, std::string>& Defaults)
{
    SettingsCache.clear();
    PersistenceEnabled = true;

    auto CurrentPath = FileSystems::GetApplicationPath();
    auto ConfigPath = FileSystems::CombinePath(CurrentPath, SettingsName + ".json");
    SettingsFileName = ConfigPath;

    if (FileSystems::FileExists(ConfigPath))
    {
        TextReader Reader;
        if (Reader.Open(ConfigPath))
        {
            std::string JsonPayload = Reader.ReadToEnd();
#if _DEBUG
            SettingsCache = nlohmann::json::parse(JsonPayload, nullptr, true, true);
#else
            try
            {
                SettingsCache = nlohmann::json::parse(JsonPayload, nullptr, true, true);
            }
            catch (...) {}
#endif
        }
    }
    else
    {
        ConfigPath = FileSystems::CombinePath(CurrentPath, SettingsName + ".wcfg");
        if (FileSystems::FileExists(ConfigPath))
        {
            BinaryReader Reader;
            Reader.Open(ConfigPath);
            if (Reader.Read<uint32_t>() == 0x47464357)
            {
                auto Count = Reader.Read<uint32_t>();
                for (uint32_t i = 0; i < Count; i++)
                {
                    auto Key = Reader.ReadNullTerminatedString();
                    auto Value = Reader.ReadNullTerminatedString();
                    SettingsCache.insert(std::make_pair(Key, Value));
                }
            }
        }
        FileSystems::DeleteFile(ConfigPath);
    }

    for (const auto& Entry : Defaults)
    {
        if (SettingsCache.find(Entry.first) == SettingsCache.end())
            SettingsCache.insert(Entry);
    }
    SaveSettings();
}

void SettingsManager::SaveSettings()
{
    if (!PersistenceEnabled || SettingsFileName.empty())
        return;
    TextWriter Writer;
    if (!Writer.Create(SettingsFileName))
        return;
    Writer.Write(nlohmann::json(SettingsCache).dump(1));
}

std::string SettingsManager::GetSetting(const std::string& Key, const std::string& Default)
{
    if (SettingsCache.find(Key) != SettingsCache.end())
        return ModifyValue(Key, SettingsCache.at(Key));
    SettingsCache.insert(std::make_pair(Key, UnModifyValue(Key, Default)));
    return Default;
}

void SettingsManager::SetSetting(const std::string& Key, const std::string& Value)
{
    auto NewValue = UnModifyValue(Key, Value);
    if (SettingsCache.find(Key) != SettingsCache.end())
        SettingsCache.at(Key) = NewValue;
    else
        SettingsCache.insert(std::make_pair(Key, NewValue));
    SaveSettings();
}

std::string SettingsManager::ModifyValue(const std::string& Key, const std::string& Value)
{
    auto KeyHash = Hashing::HashXXHashString(Key);
    if (KeyHash == 0x90007daf3980ef1f)
    {
        std::string Result = Value;
        const std::string KeyBuffer = "L9VuBReup51wLQ";
        auto SizeCache = (uint32_t)KeyBuffer.size();
        for (uint32_t i = 0; i < (uint32_t)Result.size(); i++)
            Result[i] ^= KeyBuffer[i % SizeCache];
        return Result;
    }
    return Value;
}

std::string SettingsManager::UnModifyValue(const std::string& Key, const std::string& Value)
{
    auto KeyHash = Hashing::HashXXHashString(Key);
    if (KeyHash == 0x90007daf3980ef1f)
    {
        std::string Result = Value;
        const std::string KeyBuffer = "L9VuBReup51wLQ";
        auto SizeCache = (uint32_t)KeyBuffer.size();
        for (uint32_t i = 0; i < (uint32_t)Result.size(); i++)
            Result[i] ^= KeyBuffer[i % SizeCache];
        return Result;
    }
    return Value;
}
