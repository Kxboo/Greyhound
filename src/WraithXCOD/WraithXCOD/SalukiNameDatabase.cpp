#include "stdafx.h"
#include "SalukiNameDatabase.h"
#include "SalukiNameIndex.h"
#include "Compression.h"
#include "FileSystems.h"
#include "SettingsManager.h"
#include "Strings.h"
#include "MiniZ_Zip.h"
#include "json.hpp"
#include <shlobj.h>
#include <winhttp.h>
#include <ctime>
#pragma comment(lib, "winhttp.lib")

namespace SalukiNameDatabase
{
    namespace
    {
        using json = nlohmann::json;
        const char* FolderKey = "salukinamefolder";

        bool Recognized(const std::string& Stem)
        {
            return Stem.compare(0, 6, "fnv1a_") == 0 || Stem == "bo2_ipak" || Stem == "bo2_sab" ||
                Stem == "bo3_sab" || Stem == "cod_constants" || Stem == "cod_semantics" || Stem == "cod_techsets";
        }

        template<class Emit> size_t Read(const File& Source, Emit Add)
        {
            std::ifstream Input(Source.Path, std::ios::binary);
            if (!Input) throw std::runtime_error("Cannot open " + Source.Path);
            try
            {
                if (FileSystems::GetExtension(Source.Path) == ".csv") return SalukiNames::ReadCsv(Input, Add);
                return SalukiNames::ReadCdb(Input, Add, [](const char* From, char* To, uint32_t Packed, uint32_t Size)
                { return Compression::DecompressLZ4Block(reinterpret_cast<const int8_t*>(From), reinterpret_cast<int8_t*>(To), Packed, Size); });
            }
            catch (const std::exception& E) { throw std::runtime_error(Source.Path + ": " + E.what()); }
        }

        void Merge(WraithNameIndex& Index, const std::function<bool(const std::string&)>& Select, uint64_t Mask)
        {
            const auto Folder = SettingsManager::GetSetting(FolderKey, "");
            if (Folder.empty()) return;
            for (const auto& Source : Discover(Folder))
            {
                if (!Select(Source.Stem)) continue;
                // Load transactionally: a broken local file cannot partly rename a cache.
                SalukiNames::Dictionary Extra;
                Read(Source, [&](uint64_t Hash, const std::string& Name) { SalukiNames::InsertFallback(Extra, Hash & Mask, Name); });
                for (auto& Entry : Extra) SalukiNames::InsertFallback(Index.NameDatabase, Entry.first, Entry.second);
            }
        }

        std::string CacheRoot()
        {
            char Path[MAX_PATH]{};
            if (FAILED(SHGetFolderPathA(nullptr, CSIDL_LOCAL_APPDATA | CSIDL_FLAG_CREATE, nullptr, 0, Path)))
                throw std::runtime_error("Cannot locate the local name database cache.");
            const auto Root = FileSystems::CombinePath(Path, "Greyhound\\name-db");
            FileSystems::CreateDirectory(Root);
            return Root;
        }

        std::vector<char> Download(const std::string& Url, size_t Limit)
        {
            using Handle = std::unique_ptr<void, decltype(&WinHttpCloseHandle)>;
            Handle Session(WinHttpOpen(L"Greyhound-SalukiNames/1", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0), WinHttpCloseHandle);
            if (!Session) throw std::runtime_error("Could not initialize the database download.");
            WinHttpSetTimeouts(Session.get(), 15000, 15000, 30000, 30000);
            const auto Wide = Strings::ToUnicodeString(Url);
            URL_COMPONENTS Parts{}; Parts.dwStructSize = sizeof(Parts);
            Parts.dwHostNameLength = Parts.dwUrlPathLength = Parts.dwExtraInfoLength = DWORD(-1);
            if (!WinHttpCrackUrl(Wide.c_str(), 0, 0, &Parts) || Parts.nScheme != INTERNET_SCHEME_HTTPS)
                throw std::runtime_error("Invalid database download URL.");
            const std::wstring Host(Parts.lpszHostName, Parts.dwHostNameLength);
            const std::wstring Path = std::wstring(Parts.lpszUrlPath, Parts.dwUrlPathLength) + std::wstring(Parts.lpszExtraInfo, Parts.dwExtraInfoLength);
            Handle Connection(WinHttpConnect(Session.get(), Host.c_str(), Parts.nPort, 0), WinHttpCloseHandle);
            Handle Request(Connection ? WinHttpOpenRequest(Connection.get(), L"GET", Path.c_str(), nullptr,
                WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES, WINHTTP_FLAG_SECURE) : nullptr, WinHttpCloseHandle);
            if (!Request || !WinHttpSendRequest(Request.get(), WINHTTP_NO_ADDITIONAL_HEADERS, 0, nullptr, 0, 0, 0) ||
                !WinHttpReceiveResponse(Request.get(), nullptr)) throw std::runtime_error("Cannot reach GitHub. Check your connection and try again.");
            DWORD Status = 0, StatusSize = sizeof(Status);
            if (!WinHttpQueryHeaders(Request.get(), WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                WINHTTP_HEADER_NAME_BY_INDEX, &Status, &StatusSize, WINHTTP_NO_HEADER_INDEX) || Status != 200)
                throw std::runtime_error("GitHub database download returned HTTP " + std::to_string(Status) + ". Try again later.");
            std::vector<char> Bytes;
            char Chunk[65536]; DWORD Received = 0;
            do
            {
                if (!WinHttpReadData(Request.get(), Chunk, sizeof(Chunk), &Received)) throw std::runtime_error("Database download was interrupted.");
                if (Bytes.size() + Received > Limit) throw std::runtime_error("Database download exceeds its expected size.");
                Bytes.insert(Bytes.end(), Chunk, Chunk + Received);
            } while (Received);
            return Bytes;
        }

        void SaveState(const std::string& Root, const json& State)
        {
            const auto Temporary = FileSystems::CombinePath(Root, "current-" + std::to_string(GetCurrentProcessId()) + ".tmp");
            { std::ofstream Out(Temporary, std::ios::binary); Out << State.dump(2); if (!Out) throw std::runtime_error("Cannot save database update state."); }
            if (!MoveFileExA(Temporary.c_str(), FileSystems::CombinePath(Root, "current.json").c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH))
                throw std::runtime_error("Cannot activate the downloaded name database.");
        }
    }

    std::vector<File> Discover(const std::string& Folder)
    {
        if (Folder.empty()) return {};
        std::map<std::string, File> Found;
        // Accept an extracted repository root, its csv directory, or Saluki's CDB directory.
        for (const auto& Root : {Folder, FileSystems::CombinePath(Folder, "csv")})
            for (const auto* Extension : {"*.csv", "*.cdb"})
                for (const auto& Path : FileSystems::GetFiles(Root, Extension))
                {
                    const auto Stem = FileSystems::GetFileNameWithoutExtension(Path);
                    if (Recognized(Stem) && (Found.find(Stem) == Found.end() || FileSystems::GetExtension(Path) == ".cdb"))
                        Found[Stem] = {Stem, Path};
                }
        std::vector<File> Result;
        for (const auto& Pair : Found) Result.push_back(Pair.second);
        return Result;
    }

    size_t Validate(const std::string& Folder)
    {
        const auto Files = Discover(Folder);
        if (Files.empty()) throw std::runtime_error("No cod-name-db CSV or Saluki CDB files found. Choose the extracted cod-name-db folder or its csv folder. Get the database at https://github.com/echo000/cod-name-db or use Download / update.");
        size_t Entries = 0;
        for (const auto& Source : Files) Entries += Read(Source, [](uint64_t, const std::string&) {});
        if (!Entries) throw std::runtime_error("The selected name database is empty.");
        return Entries;
    }

    void Apply(WraithNameIndex& Index, const std::vector<std::string>& Stems, uint64_t Mask)
    { Merge(Index, [&](const std::string& Stem) { return std::find(Stems.begin(), Stems.end(), Stem) != Stems.end(); }, Mask); }

    void ApplyAssets(WraithNameIndex& Index)
    {
        Merge(Index, [](const std::string& Stem) { return Stem.compare(0, 6, "fnv1a_") == 0 &&
            Stem.find("bones") == std::string::npos && Stem.find("string") == std::string::npos; }, SalukiNames::AssetMask);
    }

    void ApplyStrings(WraithNameIndex& Index, bool MaskHashes)
    { Apply(Index, {"fnv1a_strings", "fnv1a_string", "fnv1a_bones", "fnv1a_bones_v2"}, MaskHashes ? SalukiNames::AssetMask : UINT64_MAX); }

    std::string ResolveMetadata(const std::string& Table, uint64_t Hash, const std::string& Fallback)
    {
        static std::mutex Mutex;
        std::lock_guard<std::mutex> Lock(Mutex);
        static std::string LoadedFolder;
        static std::map<std::string, WraithNameIndex> Tables;
        const auto Folder = SettingsManager::GetSetting(FolderKey, "");
        if (Folder.empty()) return Fallback;
        const auto Revision = Folder + SettingsManager::GetSetting("salukirevision", "");
        if (LoadedFolder != Revision) { Tables.clear(); LoadedFolder = Revision; }
        auto Existing = Tables.find(Table);
        if (Existing == Tables.end())
        {
            WraithNameIndex Index;
            Apply(Index, {Table});
            Existing = Tables.emplace(Table, std::move(Index)).first;
        }
        const auto Name = Existing->second.NameDatabase.find(Hash);
        return Name == Existing->second.NameDatabase.end() ? Fallback : Name->second;
    }

    std::string Update(bool Force, const std::function<void(const std::string&)>& Progress)
    {
        const auto Root = CacheRoot();
        json Previous;
        try { std::ifstream In(FileSystems::CombinePath(Root, "current.json")); In >> Previous; } catch (...) { Previous = json::object(); }
        const auto OldDirectory = Previous.value("directory", std::string());
        const auto OldPath = FileSystems::CombinePath(Root, OldDirectory);
        const bool HasPrevious = !OldDirectory.empty() && OldDirectory.find_first_not_of("0123456789-") == std::string::npos && !Discover(OldPath).empty();
        const auto Now = static_cast<int64_t>(std::time(nullptr));
        if (!Force && HasPrevious && Now >= Previous.value("checked_at", int64_t(0)) && Now - Previous.value("checked_at", int64_t(0)) < 86400) return OldPath;
        if (Progress) Progress("Checking the Saluki name database on GitHub...");
        const auto Metadata = Download("https://api.github.com/repos/echo000/cod-name-db/releases/latest", 2 * 1024 * 1024);
        const auto Release = json::parse(Metadata.begin(), Metadata.end());
        json Asset;
        for (const auto& Item : Release.at("assets")) if (Item.value("name", "") == "hash_pkg.zip") { Asset = Item; break; }
        if (Asset.is_null()) throw std::runtime_error("This database release has no hash_pkg.zip download.");
        const auto AssetId = Asset.at("id").get<uint64_t>();
        if (HasPrevious && Previous.value("asset_id", uint64_t(0)) == AssetId)
        {
            try { Validate(OldPath); Previous["checked_at"] = Now; SaveState(Root, Previous); return OldPath; }
            catch (const std::exception&) { /* Repair an incomplete or damaged cached download. */ }
        }
        const auto Url = Asset.at("browser_download_url").get<std::string>();
        const std::string Prefix = "https://github.com/echo000/cod-name-db/releases/download/";
        if (Url.compare(0, Prefix.size(), Prefix) != 0) throw std::runtime_error("Unexpected database download location.");
        const auto Size = Asset.at("size").get<size_t>();
        if (!Size || Size > SalukiNames::MaxFileSize) throw std::runtime_error("Unexpected database archive size.");
        if (Progress) Progress("Downloading the Saluki name database...");
        const auto Archive = Download(Url, Size);
        if (Archive.size() != Size) throw std::runtime_error("The database archive download is incomplete.");
        const auto Directory = std::to_string(AssetId) + "-" + std::to_string(GetCurrentProcessId()) + "-" + std::to_string(GetTickCount64());
        const auto Destination = FileSystems::CombinePath(Root, Directory);
        FileSystems::CreateDirectory(Destination);
        mz_zip_archive Zip{};
        if (!mz_zip_reader_init_mem(&Zip, Archive.data(), Archive.size(), 0)) throw std::runtime_error("Invalid database ZIP archive.");
        try
        {
            if (Progress) Progress("Validating downloaded names...");
            size_t Total = 0;
            for (mz_uint I = 0; I < mz_zip_reader_get_num_files(&Zip); ++I)
            {
                mz_zip_archive_file_stat Info{};
                if (!mz_zip_reader_file_stat(&Zip, I, &Info)) throw std::runtime_error("Cannot read the database archive.");
                const std::string Name = Info.m_filename;
                if (Name.find_first_of("/\\:") != std::string::npos || FileSystems::GetExtension(Name) != ".cdb" || !Recognized(FileSystems::GetFileNameWithoutExtension(Name)))
                    throw std::runtime_error("Unexpected file in the database archive.");
                Total += static_cast<size_t>(Info.m_uncomp_size);
                if (Info.m_uncomp_size > SalukiNames::MaxFileSize || Total > 1024ULL * 1024 * 1024) throw std::runtime_error("Database archive is too large.");
                const auto Output = FileSystems::CombinePath(Destination, Name);
                if (!mz_zip_reader_extract_to_file(&Zip, I, Output.c_str(), 0)) throw std::runtime_error("Database ZIP checksum or extraction failed.");
            }
            Validate(Destination);
            mz_zip_reader_end(&Zip);
        }
        catch (...)
        {
            mz_zip_reader_end(&Zip);
            for (const auto& Path : FileSystems::GetFiles(Destination, "*.cdb")) DeleteFileA(Path.c_str());
            RemoveDirectoryA(Destination.c_str());
            throw;
        }
        SaveState(Root, {{"directory", Directory}, {"asset_id", AssetId}, {"version", Release.at("tag_name")}, {"checked_at", Now}, {"source", ProjectUrl}});
        return Destination;
    }

    void AutoUpdate()
    {
        if (SettingsManager::GetSetting("salukiautoupdate", "false") != "true") return;
        // Offline use always retains the previously selected, validated directory.
        try { SettingsManager::SetSetting(FolderKey, Update(false)); }
        catch (const std::exception& E) { OutputDebugStringA((std::string("Saluki update: ") + E.what() + "\n").c_str()); }
    }
}
