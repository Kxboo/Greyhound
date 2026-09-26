#pragma once
#include <fstream>
#include <map>
#include <set>
#include <vector>
#include <cctype>
#include <memory>
#include <cstring>

// BO4-only source arrays verified on IX and Alpha Omega. Visual material
// identity comes from GfxSurface+0x48; collision side indices are NOT materials.
template<class PoolsType, class ResolveName, class ReadMaterial, class Notify>
bool CaptureBO4BrushVisuals(const PoolsType& Pools,const std::string& Directory,
    const std::string& Output,ResolveName Resolve,ReadMaterial MaterialAt,Notify Progress)
{
    const auto Hex=[](uint64_t V){return Strings::Format("0x%llX",V);};
    const auto U32=[](const int8_t* B,size_t O){uint32_t V;std::memcpy(&V,B+O,4);return V;};
    const auto U64=[](const int8_t* B,size_t O){uint64_t V;std::memcpy(&V,B+O,8);return V;};
    const auto Stable=[&](uint64_t P,uint64_t N)->std::unique_ptr<int8_t[]> {
        if(P<0x10000 || P>=0x800000000000ull || !N || N>(256ull<<20))return nullptr;
        uintptr_t A=0,B=0;
        std::unique_ptr<int8_t[]> X(CoDAssets::GameInstance->Read(P,N,A)),Y(CoDAssets::GameInstance->Read(P,N,B));
        if(!X || !Y || A!=N || B!=N || std::memcmp(X.get(),Y.get(),size_t(N)))return nullptr;
        return X;
    };
    const auto StableHeaders=[&](uint64_t P,uint64_t N,uint32_t Stride,bool Images)->std::unique_ptr<int8_t[]> {
        if(P<0x10000 || P>=0x800000000000ull || !N || N>(256ull<<20) || N%Stride)return nullptr;
        uintptr_t A=0,B=0;
        std::unique_ptr<int8_t[]> X(CoDAssets::GameInstance->Read(P,N,A)),Y(CoDAssets::GameInstance->Read(P,N,B));
        if(!X || !Y || A!=N || B!=N)return nullptr;
        for(uint64_t J=0;J<N;++J){const uint32_t O=uint32_t(J%Stride);
            // These exact fields changed during the sealed Alpha capture while
            // every identity, geometry descriptor and source array stayed fixed.
            if(Images?((O>=8 && O<16)||(O>=0x78 && O<0x7C)):(O>=0x1B8 && O<0x1BC))continue;
            if(X[J]!=Y[J])return nullptr;
        }
        return X;
    };
    const auto Save=[&](const std::string& Name,const int8_t* Data,uint64_t Bytes){
        std::ofstream F(FileSystems::CombinePath(Directory,Name),std::ios::binary);
        if(!F)return false;F.write(reinterpret_cast<const char*>(Data),Bytes);return bool(F);
    };
    FileSystems::CreateDirectory(Directory);
    nlohmann::json Doc={{"schema","bo4-brush-render-capture-v1"},{"status","incomplete"},
        {"arrays",nlohmann::json::object()},{"materials",nlohmann::json::array()},
        {"scope","Original render material identities and explicit UVs. Collision filters are separate. No BO3 GDT or shader equivalence asserted."}};
    const auto Publish=[&](){std::ofstream F(FileSystems::CombinePath(Directory,"render_capture.json"));F<<Doc.dump(2);return bool(F);};
    const auto Fail=[&](const std::string& Why){Doc["error"]=Why;Publish();return false;};
    const auto& G=Pools[14];const auto& M=Pools[6];const auto& I=Pools[9];
    if(G.AssetSize!=6832 || G.AssetsLoaded!=1 || M.AssetSize!=312 || I.AssetSize!=136)return Fail("BO4 visual pool widths/count differ");
    auto GH=StableHeaders(G.PoolPtr,uint64_t(G.AssetSize)*G.PoolSize,G.AssetSize,false);
    auto MH=Stable(M.PoolPtr,uint64_t(M.AssetSize)*M.PoolSize);
    auto IH=StableHeaders(I.PoolPtr,uint64_t(I.AssetSize)*I.PoolSize,I.AssetSize,true);
    if(!GH || !MH || !IH)return Fail("Source pool headers unreadable or changed");
    Doc["header_stability"]={{"gfxworld","Paired byte equality except mutable u32+0x1B8; all geometry descriptors and identity compared"},
        {"images","Paired byte equality except mutable qword+8 and flags u32+0x78; image identity, format, dimensions, mip descriptor and free-chain links compared"},
        {"materials","Full paired byte equality"}};
    if(!Save("material_pool_headers.bin",MH.get(),uint64_t(M.AssetSize)*M.PoolSize) || !Save("image_pool_headers.bin",IH.get(),uint64_t(I.AssetSize)*I.PoolSize))return Fail("Source pool header write failed");
    const auto FreeSlots=[&](const auto& P,const int8_t* Raw,std::set<uint32_t>& Free){
        uint64_t At=P.PoolFreeHeadPtr;
        while(At){
            if(At<P.PoolPtr || At-P.PoolPtr>=uint64_t(P.AssetSize)*P.PoolSize || (At-P.PoolPtr)%P.AssetSize)return false;
            uint32_t Slot=uint32_t((At-P.PoolPtr)/P.AssetSize);if(!Free.insert(Slot).second)return false;
            At=U64(Raw,size_t(Slot)*P.AssetSize);
        }
        return Free.size()+P.AssetsLoaded==P.PoolSize;
    };
    std::set<uint32_t> GF,MF,IF;
    if(!FreeSlots(G,GH.get(),GF) || !FreeSlots(M,MH.get(),MF) || !FreeSlots(I,IH.get(),IF))return Fail("Invalid free chains");
    uint32_t Slot=0;while(GF.count(Slot))++Slot;
    const auto H=GH.get()+uint64_t(Slot)*G.AssetSize;
    Doc["map_hash"]=Hex(U64(H,0)&0xfffffffffffffff);
    if(!Save("gfxworld_header.bin",H,G.AssetSize))return Fail("Header write failed");
    struct Array {const char* Name;uint32_t CountOffset,PointerOffset,Stride;};
    const Array Arrays[]={{"positions",0xF8,0x100,12},{"attributes",0xF8,0x128,20},
        {"indices",0x150,0x158,2},{"surfaces",0x18,0x3F8,96},{"brush_models",0x180,0x188,80}};
    std::map<std::string,std::unique_ptr<int8_t[]>> Data;
    std::map<std::string,uint32_t> Counts;
    for(const auto& A:Arrays){
        const auto N=U32(H,A.CountOffset);const auto P=U64(H,A.PointerOffset);
        auto B=Stable(P,uint64_t(N)*A.Stride);const std::string File=std::string(A.Name)+".bin";
        if(!B || !Save(File,B.get(),uint64_t(N)*A.Stride))return Fail(std::string("Render array unavailable: ")+A.Name);
        Doc["arrays"][A.Name]={{"file",File},{"pointer",Hex(P)},{"count",N},{"stride",A.Stride},{"status","captured_stable"}};
        Counts[A.Name]=N;Data[A.Name]=std::move(B);
    }
    std::set<uint64_t> Materials;
    for(uint32_t S=0;S<Counts["surfaces"];++S)Materials.insert(U64(Data["surfaces"].get()+uint64_t(S)*96,0x48));
    const auto InfoPath=FileSystems::CombinePath(Output,"_mat_info"),ImageRoot=FileSystems::CombinePath(Output,"_images");
    FileSystems::CreateDirectory(InfoPath);FileSystems::CreateDirectory(ImageRoot);
    const auto Alias=[](const std::string& Name){
        std::string Out;for(unsigned char C:Name)Out+=(std::isalnum(C)||C=='_'||C=='-')?char(C):'_';
        return Out;
    };
    std::map<std::string,uint64_t> Aliases;uint32_t Done=0;
    for(uint64_t P:Materials){
        nlohmann::json Row={{"pointer",Hex(P)},{"status","unresolved"},{"name_resolved",false},{"images",nlohmann::json::array()}};
        if(P<M.PoolPtr || P-M.PoolPtr>=uint64_t(M.AssetSize)*M.PoolSize || (P-M.PoolPtr)%M.AssetSize || MF.count(uint32_t((P-M.PoolPtr)/M.AssetSize)))return Fail("Render material is not an occupied material slot");
        const auto B=MH.get()+P-M.PoolPtr;const uint64_t Hash=U64(B,0)&0xfffffffffffffff;
        Row["hash"]=Hex(Hash);Row["slot"]=(P-M.PoolPtr)/M.AssetSize;Row["identity_proven"]=true;
        const std::string Name=Resolve(Hash);Row["source_name"]=Name;Row["name_resolved"]=!Name.empty();
        const auto HeaderFile=Strings::Format("material_%llx.bin",Hash);
        if(!Save(HeaderFile,B,312))return Fail("Material header write failed");Row["header_file"]=HeaderFile;
        std::string Target=Alias(Name);if(Target.empty())Target="source_material_"+Strings::Format("%llx",Hash);
        std::string Lower=Strings::ToLower(Target);
        if(Aliases.count(Lower) && Aliases[Lower]!=Hash)Target+="_"+Strings::Format("%llx",Hash);
        Aliases[Strings::ToLower(Target)]=Hash;Row["material"]=Target;
        Row["name_alias_policy"]=Name.empty()?"Exact original material hash alias; original text name is unresolved. No substitute material or guessed name.":"Filename-safe source-name alias; source identity and hash retained. No substitute visual material.";
        Row["source_hash_alias"]=Name.empty();
        const uint32_t N=uint8_t(B[0x130]);auto Bindings=N?Stable(U64(B,0x38),uint64_t(N)*32):nullptr;
        if(N && !Bindings){Row["reason"]="material_bindings_unstable";Doc["materials"].push_back(Row);continue;}
        if(N){const auto File=Strings::Format("material_%llx_bindings.bin",Hash);if(!Save(File,Bindings.get(),uint64_t(N)*32))return Fail("Binding write failed");Row["bindings_file"]=File;}
        XMaterial_t Material(N);Material.MaterialName=Target;Material.MaterialSourceName=Name;
        const auto Tech=U64(B,0x30);auto TechHeader=Tech?Stable(Tech,168):nullptr;
        if(TechHeader){const auto TH=U64(TechHeader.get(),0)&0xfffffffffffffff;const auto TN=Resolve(TH);Material.TechsetName=TN.empty()?Strings::Format("xtechset_%llx",TH):TN;Row["techset_hash"]=Hex(TH);Row["techset_name"]=TN;}
        bool Complete=true;
        std::map<std::string,uint64_t> ImageAliases;
        for(uint32_t J=0;J<N;++J){
            const auto T=Bindings.get()+J*32;const auto IP=U64(T,0);
            if(IP<I.PoolPtr || IP-I.PoolPtr>=uint64_t(I.AssetSize)*I.PoolSize || (IP-I.PoolPtr)%I.AssetSize || IF.count(uint32_t((IP-I.PoolPtr)/I.AssetSize)))return Fail("Material image is not an occupied image slot");
            const auto IB=IH.get()+IP-I.PoolPtr;const auto ImageHash=U64(IB,0x20)&0xfffffffffffffff;
            const auto ImageName=Resolve(ImageHash);auto ImageAlias=Alias(ImageName);
            if(ImageAlias.empty())ImageAlias=Strings::Format("ximage_%llx",ImageHash);
            if(ImageAliases.count(Strings::ToLower(ImageAlias)) && ImageAliases[Strings::ToLower(ImageAlias)]!=ImageHash)ImageAlias+="_"+Strings::Format("%llx",ImageHash);
            ImageAliases[Strings::ToLower(ImageAlias)]=ImageHash;
            uint16_t Width=0,Height=0;std::memcpy(&Width,IB+0x68,2);std::memcpy(&Height,IB+0x6A,2);
            const uint32_t NM=uint8_t(IB[0x7D]);auto Mips=(NM && NM<=32)?Stable(U64(IB,0x30),NM*40):nullptr;
            if(Mips)for(uint32_t K=0;K<NM;++K){uint16_t W,V;std::memcpy(&W,Mips.get()+K*40+36,2);std::memcpy(&V,Mips.get()+K*40+38,2);if(W>Width){Width=W;Height=V;}}
            const uint32_t Semantic=U32(T,8);auto Usage=ImageUsageType::Unknown;
            if(Semantic==0xA0AB1041)Usage=ImageUsageType::DiffuseMap;
            else if(Semantic==0x59D30D0F)Usage=ImageUsageType::NormalMap;
            else if(Semantic==0xEC443804)Usage=ImageUsageType::SpecularMap;
            Material.Images.emplace_back(Usage,Semantic,IP,ImageAlias);
            float BindingUV[4];std::memcpy(BindingUV,T+16,16);
            Row["images"].push_back({{"pointer",Hex(IP)},{"hash",Hex(ImageHash)},{"source_name",ImageName},{"image_name",ImageAlias},
                {"binding_float4_raw",{BindingUV[0],BindingUV[1],BindingUV[2],BindingUV[3]}},
                {"semantic",Hex(U32(T,8))},{"width",Width},{"height",Height},{"file","_images/"+Target+"/"+ImageAlias+".png"}});
            if(U32(T,8)==0xA0AB1041)Row["texture_size"]={Width,Height};
        }
        if(!Row.contains("texture_size")){Complete=false;Row["reason"]="diffuse_texture_dimensions_unavailable";}
        {
            const auto Destination=FileSystems::CombinePath(ImageRoot,Target);FileSystems::CreateDirectory(Destination);
            CoDAssets::ExportMaterialImageNames(Material,InfoPath);
            CoDAssets::ExportMaterialImages(Material,Destination,".png",ImageFormat::Standard_PNG,InfoPath);
            const auto InfoFile=FileSystems::CombinePath(InfoPath,Target+".txt");std::ifstream Info(InfoFile,std::ios::binary|std::ios::ate);
            if(!Info || Info.tellg()<=0)Complete=false;
            Row["metadata_file"]="_mat_info/"+Target+".txt";
            for(auto& Image:Row["images"]){
                std::ifstream File(FileSystems::CombinePath(Output,Image["file"].template get<std::string>()),std::ios::binary|std::ios::ate);
                const bool Present=File && File.tellg()>0;Image["status"]=Present?"exported":"missing";Complete=Complete&&Present;
            }
        }
        auto After=Stable(P,312);if(!After || std::memcmp(After.get(),B,312))Complete=false;
        if(N){auto AfterBindings=Stable(U64(B,0x38),uint64_t(N)*32);if(!AfterBindings || std::memcmp(AfterBindings.get(),Bindings.get(),uint64_t(N)*32))Complete=false;}
        for(uint32_t J=0;J<N;++J){
            const auto IP=U64(Bindings.get()+J*32,0);auto Now=StableHeaders(IP,136,136,true);
            // Image stream residency may change; the asset identity, format,
            // dimensions and mip table must still identify the captured image.
            const auto Before=IH.get()+IP-I.PoolPtr;
            if(!Now || U64(Now.get(),0x20)!=U64(Before,0x20) || U64(Now.get(),0x30)!=U64(Before,0x30) || std::memcmp(Now.get()+0x64,Before+0x64,8) || Now[0x7D]!=Before[0x7D])Complete=false;
        }
        Row["status"]=Complete?"complete":"unresolved";if(!Complete && !Row.contains("reason"))Row["reason"]="original_material_dependencies_incomplete_or_changed";Doc["materials"].push_back(Row);
        Progress(10+uint32_t(++Done*10/Materials.size()),"BO4: saving original render materials and images...");
        if(!Publish())return false;
    }
    auto FinalHeader=StableHeaders(G.PoolPtr+uint64_t(Slot)*G.AssetSize,G.AssetSize,G.AssetSize,false);
    if(!FinalHeader || U64(FinalHeader.get(),0)!=U64(H,0))return Fail("Map identity changed during image export");
    for(const auto& A:Arrays)if(U32(FinalHeader.get(),A.CountOffset)!=U32(H,A.CountOffset) || U64(FinalHeader.get(),A.PointerOffset)!=U64(H,A.PointerOffset))return Fail("Render source descriptors changed during image export");
    Doc["status"]="captured";Doc["material_count"]=Materials.size();
    return Publish();
}
