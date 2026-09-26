#include "stdafx.h"

// The class we are implementing
#include "assets/AssetSearch.h"

#include <algorithm>
#include <sstream>
#include "assets/CoDAssets.h"
#include "Strings.h"

// Search language shared by the classic window and the v2 UI: comma-separated
// name terms (! negates) plus key:value filters such as bonecount:>40.

template <typename T, T min, T defaultVal, T max>
class RangedIntSearchValue
{
public:
    T Min;
    T Value;
    T Max;

    RangedIntSearchValue()
    {
        Min = min;
        Value = defaultVal;
        Max = max;
    }

    void SetFromSearchString(std::string view)
    {
        if (view.size() == 0)
            return;

        if (view[0] == '<')
        {
            Max = strtoll(view.data() + 1, NULL, 10);
        }
        else if (view[0] == '>')
        {
            Min = strtoll(view.data() + 1, NULL, 10);
        }
        else
        {
            Value = strtoll(view.data(), NULL, 10);
        }
    }
};

class StringMatch
{
public:
    // The value
    std::string Value;
    // Whether or not to negate the result
    bool Negate;

    // Initializes String Match
    StringMatch(std::string& value) :
        Value(value),
        Negate(false) { }

    // Initializes String Match
    StringMatch(std::string& value, bool negate) :
        Value(value),
        Negate(negate) { }
};

class SearchContext
{
public:
    // List of assets to search for
    std::vector<StringMatch> AssetNames;
    // List of bones to search for
    std::vector<StringMatch> BoneNames;
    // Lod Count Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> LodCount;
    // Bone Count Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> BoneCount;
    // Frame Count Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> FrameCount;
    // Shape Count Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> ShapeCount;
    // Frame Rate Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> Framerate;
    // Width Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> Width;
    // Height Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> Height;
    // Sound Length Search Value
    RangedIntSearchValue<int64_t, LONGLONG_MIN, -1, LONGLONG_MAX> SoundLength;
    // Streamed Value
    RangedIntSearchValue<int64_t, 0,            -1, 1>            Streamed;
    // Placeholder Value
    RangedIntSearchValue<int64_t, 0,            -1, 1>            Placeholder;


    // Initializes the search context
    SearchContext(std::string& search);
};

SearchContext::SearchContext(std::string& search)
{
    if (search.size() == 0)
        return;

    bool negate = false;

    size_t currentIndex = 0;

    if (search[currentIndex] == '!')
    {
        negate = true;
        currentIndex++;
    }

    std::string currentString = search;
    size_t currentStart = currentIndex;
    size_t valueStart = 0;

    while (currentIndex < search.length())
    {
        auto nextChar = search[currentIndex++];
        auto atEnd = currentIndex == search.length();

        if (nextChar == ',' || atEnd)
        {
            // We have a value
            if (valueStart != 0)
            {
                auto name = currentString.substr(currentStart, valueStart - 1 - currentStart);
                auto value = currentString.substr(valueStart, currentIndex - (atEnd ? 0 : 1) - valueStart);

                // C# TODO: Use reflection
                if (name == "lodcount")
                {
                    LodCount.SetFromSearchString(value);
                }
                else if (name == "bonecount")
                {
                    BoneCount.SetFromSearchString(value);
                }
                else if (name == "framecount")
                {
                    FrameCount.SetFromSearchString(value);
                }
                else if (name == "shapecount")
                {
                    ShapeCount.SetFromSearchString(value);
                }
                else if (name == "framerate")
                {
                    Framerate.SetFromSearchString(value);
                }
                else if (name == "width")
                {
                    Width.SetFromSearchString(value);
                }
                else if (name == "height")
                {
                    Height.SetFromSearchString(value);
                }
                else if (name == "length")
                {
                    SoundLength.SetFromSearchString(value);
                }
                else if (name == "streamed")
                {
                    Streamed.SetFromSearchString(value);
                }
                else if (name == "placeholder")
                {
                    Placeholder.SetFromSearchString(value);
                }
                else if (name == "bonename")
                {
                    auto boneName = std::string(value.data(), value.size());
                    BoneNames.emplace_back(Strings::ToLower(Strings::Trim(boneName)));
                }
            }
            // Standard asset name
            else
            {
                auto view = currentString.substr(currentStart, currentIndex - currentStart - (atEnd ? 0 : 1));

                if (view.size() != 0)
                {
                    auto assetName = std::string(view.data(), view.size());
                    AssetNames.emplace_back(Strings::ToLower(Strings::Trim(assetName)), negate);
                }
            }

            currentStart = currentIndex;
            valueStart = 0;
        }
        else if (nextChar == ':')
        {
            valueStart = currentIndex;
        }
    }
}

// -- Hashing Functions for BO4 --

const uint64_t FNVPrime = 0x100000001B3;
const uint64_t FNVOffset = 0xCBF29CE484222325;

// Generates a 64bit FNV Hash for the given string
uint64_t FNVHash(std::string data, const uint64_t fnvPrime, const uint64_t fnvOffset)
{
    uint64_t Result = fnvOffset;

    for (uint32_t i = 0; i < data.length(); i++)
    {
        Result ^= data[i];
        Result *= fnvPrime;
    }

    return Result & 0xFFFFFFFFFFFFFFF;
}

std::vector<CoDAsset_t*> AssetSearch::Filter(const std::string& Text, const std::vector<CoDAsset_t*>& Assets)
{
    std::vector<CoDAsset_t*> Results;
    std::string SearchText = Text;
    SearchContext Context(SearchText);

    // Iterate and append what we find
    for (auto& Asset : Assets)
    {
        // Grab the string
        std::string AssetName = Asset->AssetName;
        // Make it lowercase
        std::transform(AssetName.begin(), AssetName.end(), AssetName.begin(), ::tolower);

        // Whether or not we can add
        bool CanAdd = true;

        // Check type and format it
        switch (Asset->AssetType)
        {
        case WraithAssetType::Model:
        {
            auto XModelBoneCount = (int64_t)((CoDModel_t*)Asset)->BoneCount;
            auto XModelLodCount = (int64_t)((CoDModel_t*)Asset)->LodCount;
            auto XModelBoneNames = ((CoDModel_t*)Asset)->BoneNames;

            if (Context.BoneCount.Value != -1 && XModelBoneCount != Context.BoneCount.Value)
                CanAdd = false;
            if (XModelBoneCount < Context.BoneCount.Min)
                CanAdd = false;
            if (XModelBoneCount > Context.BoneCount.Max)
                CanAdd = false;

            if (Context.LodCount.Value != -1 && XModelLodCount != Context.LodCount.Value)
                CanAdd = false;
            if (XModelLodCount < Context.LodCount.Min)
                CanAdd = false;
            if (XModelLodCount > Context.LodCount.Max)
                CanAdd = false;

            if (!Context.BoneNames.empty())
            {
                bool XModelBoneMatch = false;

                for (auto& BoneName : Context.BoneNames)
                {
                    for (auto& XModelBoneName : XModelBoneNames)
                    {
                        // If we match, add, then stop
                        auto Result = XModelBoneName.find(BoneName.Value);
                        // Check match type
                        if (Result != std::string::npos)
                        {
                            XModelBoneMatch = true;
                            break;
                        }
                    }
                }

                if (!XModelBoneMatch)
                    CanAdd = false;
            }

            break;
        }
        case WraithAssetType::Animation:
        {
            auto XAnimBoneCount = (int64_t)((CoDAnim_t*)Asset)->BoneCount;
            auto XAnimFrameCount = (int64_t)((CoDAnim_t*)Asset)->FrameCount;
            auto XAnimShapeCount = (int64_t)((CoDAnim_t*)Asset)->ShapeCount;
            auto XAnimFrameRate = ((CoDAnim_t*)Asset)->Framerate;
            auto XAnimBoneNames = ((CoDAnim_t*)Asset)->BoneNames;

            if (Context.BoneCount.Value != -1 && XAnimBoneCount != Context.BoneCount.Value)
                CanAdd = false;
            if (XAnimBoneCount < Context.BoneCount.Min)
                CanAdd = false;
            if (XAnimBoneCount > Context.BoneCount.Max)
                CanAdd = false;

            if (Context.ShapeCount.Value != -1 && XAnimShapeCount != Context.ShapeCount.Value)
                CanAdd = false;
            if (XAnimShapeCount < Context.ShapeCount.Min)
                CanAdd = false;
            if (XAnimShapeCount > Context.ShapeCount.Max)
                CanAdd = false;

            if (Context.FrameCount.Value != -1 && XAnimFrameCount != Context.FrameCount.Value)
                CanAdd = false;
            if (XAnimFrameCount < Context.FrameCount.Min)
                CanAdd = false;
            if (XAnimFrameCount > Context.FrameCount.Max)
                CanAdd = false;

            if (Context.Framerate.Value != -1 && XAnimFrameRate != Context.Framerate.Value)
                CanAdd = false;
            if (XAnimFrameRate < Context.Framerate.Min)
                CanAdd = false;
            if (XAnimFrameRate > Context.Framerate.Max)
                CanAdd = false;

            if (!Context.BoneNames.empty())
            {
                bool XModelBoneMatch = false;

                for (auto& XAnimBoneName : XAnimBoneNames)
                {
                    for (auto& BoneName : Context.BoneNames)
                    {
                        // If we match, add, then stop
                        auto Result = XAnimBoneName.find(BoneName.Value);
                        // Check match type
                        if (Result != std::string::npos)
                        {
                            XModelBoneMatch = true;
                            break;
                        }
                    }
                }

                if (!XModelBoneMatch)
                    CanAdd = false;
            }

            break;
        }
        case WraithAssetType::Image:
        {
            auto ImageWidth = (int64_t)((CoDImage_t*)Asset)->Width;
            auto ImageHeight = (int64_t)((CoDImage_t*)Asset)->Height;

            if (Context.Width.Value != -1 && ImageWidth != Context.Width.Value)
                CanAdd = false;
            if (ImageWidth < Context.Width.Min)
                CanAdd = false;
            if (ImageWidth > Context.Width.Max)
                CanAdd = false;

            if (Context.Height.Value != -1 && ImageHeight != Context.Height.Value)
                CanAdd = false;
            if (ImageHeight < Context.Height.Min)
                CanAdd = false;
            if (ImageHeight > Context.Height.Max)
                CanAdd = false;

            break;
        }
        case WraithAssetType::Sound:
        {
            auto SoundLength = (int64_t)((CoDSound_t*)Asset)->Length;

            if (Context.SoundLength.Value != -1 && SoundLength != Context.SoundLength.Value)
                CanAdd = false;
            if (SoundLength < Context.SoundLength.Min)
                CanAdd = false;
            if (SoundLength > Context.SoundLength.Max)
                CanAdd = false;

            break;
        }
        }

        if (Context.Streamed.Value != -1)
            CanAdd = (Context.Streamed.Value == 1 && Asset->Streamed) || (Context.Streamed.Value == 0 && !Asset->Streamed);
        if (Context.Placeholder.Value != -1)
            CanAdd = (Context.Placeholder.Value == 1 && Asset->AssetStatus == WraithAssetStatus::Placeholder) || (Context.Placeholder.Value == 0 && Asset->AssetStatus != WraithAssetStatus::Placeholder);


        // At this point we've checked out with value checks, skip names
        // if other values haven't checked
        if (!CanAdd)
            continue;

        bool AssetNameMatch = true;

        for (auto& MapFind : Context.AssetNames)
        {
            // If we match, add, then stop
            auto Result = AssetName.find(MapFind.Value);

            // Check match type
            if (Result == std::string::npos && MapFind.Negate)
            {
                AssetNameMatch = true;
                break;
            }
            if (Result == std::string::npos && !MapFind.Negate)
            {
                AssetNameMatch = false;
            }
            else
            {
                AssetNameMatch = true;
                break;
            }

            // Second pass for Bo4, hash
            if (CoDAssets::GameID == SupportedGames::BlackOps4 || CoDAssets::GameID == SupportedGames::BlackOpsCW)
            {
                // Convert to hex string
                std::stringstream HashValue;
                HashValue << std::hex << FNVHash(MapFind.Value, FNVPrime, FNVOffset) << std::dec;

                // If we match, add, then stop
                Result = AssetName.find(HashValue.str());

                // Check match type
                if (Result == std::string::npos && MapFind.Negate)
                {
                    AssetNameMatch = true;
                    break;
                }
                if (Result == std::string::npos && !MapFind.Negate)
                {
                    AssetNameMatch = false;
                }
                else
                {
                    AssetNameMatch = true;
                    break;
                }
            }
            // Second pass for Bo4, hash
            else if (CoDAssets::GameID == SupportedGames::ModernWarfare5 || CoDAssets::GameID == SupportedGames::ModernWarfare6)
            {
                // Convert to hex string
                std::stringstream HashValue;
                HashValue << std::hex << FNVHash(MapFind.Value, 0x100000001B3, 0x47F5817A5EF961BA) << std::dec;

                // If we match, add, then stop
                Result = AssetName.find(HashValue.str());

                // Check match type
                if (Result == std::string::npos && MapFind.Negate)
                {
                    AssetNameMatch = true;
                    break;
                }
                if (Result == std::string::npos && !MapFind.Negate)
                {
                    AssetNameMatch = false;
                }
                else
                {
                    AssetNameMatch = true;
                    break;
                }
            }
        }

        if (!AssetNameMatch)
            CanAdd = false;

        // Check to add
        if (CanAdd)
        {
            Results.push_back(Asset);
        }
    }

    return Results;
}
