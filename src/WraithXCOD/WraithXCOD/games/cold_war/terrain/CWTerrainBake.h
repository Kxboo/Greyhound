#pragma once

// Minimal, read-only inputs for the approved Cold War material bake. The much
// larger archival terrain capture remains a separate Dev Tools operation.
#include <filesystem>
#include <fstream>
#include <set>
#include "assets/CoDAssets.h"
#include "ProcessReader.h"
#include "packages/CoDPackageCache.h"
#include "json.hpp"

namespace CWTerrainBake
{
    using Bytes = std::vector<uint8_t>;
    using json = nlohmann::json;
    namespace fs = std::filesystem;
    template<class T> T At(const Bytes& B, size_t O)
    {
        if (O > B.size() || sizeof(T) > B.size()-O) throw std::runtime_error("Short terrain record");
        T V; std::memcpy(&V,B.data()+O,sizeof V); return V;
    }
    inline Bytes Read(uint64_t Address, size_t Size)
    {
        if (Address < 0x10000 || !Size || Size > 128u*1024*1024)
            throw std::runtime_error("Invalid terrain read bounds");
        uintptr_t Got=0;
        std::unique_ptr<int8_t[]> B(CoDAssets::GameInstance->Read(Address,Size,Got));
        if (!B || Got!=Size) throw std::runtime_error("Terrain resource unavailable; keep the map loaded and retry");
        return Bytes(B.get(),B.get()+Size);
    }
    inline void Save(const fs::path& P,const Bytes& B)
    {
        std::ofstream F(P,std::ios::binary);F.write(reinterpret_cast<const char*>(B.data()),B.size());
        if (!F) throw std::runtime_error("Could not save terrain bake input");
    }
    inline void SaveJson(const fs::path& P,const json& J)
    {
        std::ofstream F(P);F<<J.dump(2)<<"\n";
        if (!F) throw std::runtime_error("Could not save terrain report");
    }
    inline size_t ImageBytes(uint32_t W,uint32_t H,uint32_t Format)
    {
        switch(Format) {
        case 42: return size_t(W)*H*4;
        case 56: return size_t(W)*H*2;
        case 62: return size_t(W)*H;
        case 71: case 72: case 80: return size_t((W+3)/4)*((H+3)/4)*8;
        case 74: case 75: case 77: case 78: case 83: case 98: case 99:
            return size_t((W+3)/4)*((H+3)/4)*16;
        default: throw std::runtime_error("Unsupported terrain texture format "+std::to_string(Format));
        }
    }
    inline json CaptureImage(uint64_t Pointer,const fs::path& Path,bool FullResolution)
    {
        const auto Header=Read(Pointer,208);
        const auto W=At<uint16_t>(Header,160),H=At<uint16_t>(Header,162);
        const auto Format=At<uint32_t>(Header,156);
        const auto Count=Header[184];
        if (!W || !H || W>16384 || H>16384 || Count>15) throw std::runtime_error("Unsupported terrain image dimensions");
        Bytes Data;uint32_t Width=W,Height=H;uint64_t Key=0;
        if (Count) {
            const auto Mips=Read(At<uint64_t>(Header,48),Count*32);
            for (int I=Count-1;I>=0;--I) {
                const uint32_t CW=std::max(1u,uint32_t(W)>>(Count-I-1)),CH=std::max(1u,uint32_t(H)>>(Count-I-1));
                if (!FullResolution && std::max(CW,CH)>1024) continue;
                const auto K=At<uint64_t>(Mips,I*32);
                if (!K || !CoDAssets::GamePackageCache->Exists(K)) continue;
                uint32_t Size=0;auto B=CoDAssets::GamePackageCache->ExtractPackageObject(K,Size);
                const auto Expected=ImageBytes(CW,CH,Format);
                if (!B || !Size) {
                    B=CoDAssets::GamePackageCache->ExtractPackageObjectRaw(K,Size);
                    // A raw BC mip has exactly its calculated block extent.
                    if (Size!=Expected) {B.reset();Size=0;}
                }
                // Package objects may contain a mip tail. Only LOD zero is
                // consumed by this bake; never infer dimensions from byte size.
                if (B && Size>=Expected) {Data.assign(B.get(),B.get()+Expected);Width=CW;Height=CH;Key=K;break;}
            }
            if (Mips!=Read(At<uint64_t>(Header,48),Count*32)) throw std::runtime_error("Terrain mip table changed during capture");
        }
        if (Data.empty()) {
            const auto Size=At<uint32_t>(Header,152);const auto Expected=ImageBytes(W,H,Format);
            if (Size<Expected || (!FullResolution && std::max(W,H)>1024)) throw std::runtime_error("No installed terrain texture at the requested quality");
            Data=Read(At<uint64_t>(Header,40),Expected);
            if (Data!=Read(At<uint64_t>(Header,40),Expected)) throw std::runtime_error("Terrain pixels changed during capture");
        }
        if (Header!=Read(Pointer,208)) throw std::runtime_error("Terrain image changed during capture");
        if (FullResolution && (Width!=W || Height!=H)) throw std::runtime_error("Full-resolution height/control data is required");
        Save(Path,Data);
        return {{"file",Path.generic_string()},{"width",Width},{"height",Height},{"format",Format},{"mips",1},
            {"type",Format==42 || Format==62 ? "uint":"float"},{"package_key",Key}};
    }
    inline void Capture(const CoDTerrain_t* Terrain,const fs::path& Directory)
    {
        if (CoDAssets::GameID!=SupportedGames::BlackOpsCW) throw std::runtime_error("Baked terrain models currently support Cold War. Use Dev Tools for Black Ops 4 source capture.");
        if (!CoDAssets::GamePackageCache) throw std::runtime_error("Terrain package cache unavailable");
        CoDAssets::GamePackageCache->WaitForPackageCacheLoad();
        const auto Base=CoDAssets::GameInstance->GetMainModuleAddress();
        const auto PE=Read(Base,4096);const auto PEOffset=At<uint32_t>(PE,60);
        if (At<uint32_t>(PE,PEOffset+8)!=0x6a03ba27 || At<uint32_t>(PE,PEOffset+24+56)!=0x1f958a00)
            throw std::runtime_error("This Cold War build has not been validated for terrain baking");
        const auto Header=Read(Terrain->AssetPointer,296);const auto Count=At<uint32_t>(Header,8);
        if (!Count || Count>32) throw std::runtime_error("Unsupported terrain mapping count");
        const auto Roots=Read(At<uint64_t>(Header,16),Count*472);
        fs::create_directories(Directory);
        Bytes Tiles,Layers;bool Stable=false;
        for (unsigned Attempt=0;Attempt<100 && !Stable;++Attempt) {
            // The current frame's lists are empty during its reset phase.
            // Tight retries can all land inside that same phase.
            Sleep(5);
            const auto Frame=At<uint64_t>(Read(Base+0x17c43698,8),0);
            const auto TF=Read(Frame+0x28a780,80),LF=Read(Frame+0x28b8a0,40);
            const auto TC=At<uint32_t>(TF,64),LC=At<uint32_t>(LF,32);
            if (TC<Count || TC>2560 || !LC || LC>4096) continue;
            Tiles=Read(At<uint64_t>(TF,8),TC*316);Layers=Read(At<uint64_t>(LF,0),LC*128);
            Stable=Tiles==Read(At<uint64_t>(TF,8),TC*316) && Layers==Read(At<uint64_t>(LF,0),LC*128)
                && TF==Read(Frame+0x28a780,80) && LF==Read(Frame+0x28b8a0,40);
        }
        if (!Stable) throw std::runtime_error("Terrain is changing too quickly to capture; keep the view still and retry");
        // Validate root records against the independent GPU records before
        // assuming their order. No session addresses or map names are stored here.
        json Mappings=json::array();std::set<uint32_t> Controls;
        for (uint32_t I=0;I<Count;++I) {
            Bytes R(Roots.begin()+I*472,Roots.begin()+(I+1)*472),T(Tiles.begin()+I*316,Tiles.begin()+(I+1)*316);
            const auto W=At<uint16_t>(R,0x100),H=At<uint16_t>(R,0x102);
            if (!W || !H || W%32 || H%32 || W>8192 || H>8192 || At<float>(T,136)!=W || At<float>(T,140)!=H)
                throw std::runtime_error("Terrain CPU/GPU mapping mismatch");
            for (int J=0;J<9;++J) if (At<float>(R,0x5c+J*4)!=(J%4==0?1.f:0.f))
                throw std::runtime_error("Rotated terrain mappings are not supported");
            const float Cell=At<float>(R,0xf0),X=At<float>(R,0xe8),Y=At<float>(R,0xec);
            if (!(Cell>0 && Cell<=1024)) throw std::runtime_error("Invalid terrain cell size");
            for (int Off:{300,304,308,312}) {const auto V=At<uint32_t>(T,Off);Controls.insert(V&16383);Controls.insert((V>>14)&16383);}
            const auto SharedCount=At<uint64_t>(R,0x18);
            if (SharedCount!=6144) throw std::runtime_error("Unsupported terrain grid index layout");
            const auto IndexPath=Directory/("indices_"+std::to_string(I)+".bin");
            Save(IndexPath,Read(At<uint64_t>(R,0x20),SharedCount*2));
            const auto TilePath=Directory/("tile_"+std::to_string(I)+".bin");Save(TilePath,T);
            Mappings.push_back({{"mapping",I},{"width",W},{"height",H},{"origin",{X,Y}},{"cell",Cell},
                {"z_translation",-At<float>(R,0x58)},{"camera",{X-At<float>(T,144),Y-At<float>(T,148)}},
                {"tile",TilePath.generic_string()},{"indices",IndexPath.generic_string()}});
        }
        const auto ImageCount=At<uint32_t>(Header,48);
        if (!ImageCount || ImageCount>4096) throw std::runtime_error("Invalid terrain image table");
        const auto Pointers=Read(At<uint64_t>(Header,56),ImageCount*8),IDs=Read(At<uint64_t>(Header,72),ImageCount*4);
        json Textures=json::array();std::set<uint32_t> Seen;
        for (uint32_t I=0;I<ImageCount;++I) {
            const auto ID=At<uint32_t>(IDs,I*4);
            if (!ID || ID>=16384 || !Seen.insert(ID).second) throw std::runtime_error("Invalid or duplicate terrain image binding");
            auto Entry=CaptureImage(At<uint64_t>(Pointers,I*8),Directory/("texture_"+std::to_string(ID)+".bin"),Controls.count(ID)!=0);
            Entry["id"]=ID;Textures.push_back(Entry);
        }
        const auto DistortionPointer=At<uint64_t>(Read(Base+0x1a188058,8),0);
        const auto Distortion=CaptureImage(DistortionPointer,Directory/"distortion.bin",true);
        const auto ShaderOwner=At<uint64_t>(Read(Base+0x182aa760,8),0);
        const auto Owner=Read(ShaderOwner,24);
        if (At<uint64_t>(Owner,0)!=0x60e23a45408923cb || At<uint64_t>(Owner,8)!=1) throw std::runtime_error("Unsupported terrain composition shader");
        const auto ShaderDescriptor=Read(At<uint64_t>(Read(At<uint64_t>(Owner,16),8),0),40);
        const auto ShaderSize=At<uint32_t>(ShaderDescriptor,24);
        if (ShaderSize<32 || ShaderSize>1024*1024) throw std::runtime_error("Invalid terrain shader size");
        Save(Directory/"composition.dxil",Read(At<uint64_t>(ShaderDescriptor,16),ShaderSize));
        Layers.resize(Layers.size()+256*128);Save(Directory/"layers.bin",Layers);
        if (Header!=Read(Terrain->AssetPointer,296) || Roots!=Read(At<uint64_t>(Header,16),Count*472)
            || Pointers!=Read(At<uint64_t>(Header,56),ImageCount*8) || IDs!=Read(At<uint64_t>(Header,72),ImageCount*4))
            throw std::runtime_error("Map changed during terrain capture");
        SaveJson(Directory/"inputs.json",{{"schema",1},{"name",Terrain->AssetName},{"mappings",Mappings},{"textures",Textures},
            {"distortion",Distortion},{"shader",(Directory/"composition.dxil").generic_string()},{"layers",(Directory/"layers.bin").generic_string()}});
    }
}
