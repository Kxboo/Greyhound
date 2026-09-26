#pragma once

// Read-only evidence for unresolved BO4 trigger/primitive dispatch. Captures
// selected function bytes, not a full process dump; no game code is executed.
inline bool CaptureBO4CollisionHandlers(const std::string& Path)
{
    const uint64_t Base=CoDAssets::GameInstance->GetMainModuleAddress();
    const auto Hex=[](uint64_t V){return Strings::Format("0x%llX",V);};
    const auto Read=[&](uint64_t Address,uint64_t Size)->std::vector<int8_t>{
        uintptr_t N=0;std::unique_ptr<int8_t[]> B(CoDAssets::GameInstance->Read(Address,Size,N));
        if(!B || N!=Size)return {};return {B.get(),B.get()+N};
    };
    const auto Save=[&](const void* Data,uint32_t Size,const std::string& File){
        BinaryWriter W;if(!W.Create(FileSystems::CombinePath(Path,File)))return false;
        W.Write(reinterpret_cast<const int8_t*>(Data),Size);W.Close();return true;
    };
    auto Headers=Read(Base,4096);if(Headers.empty())return false;
    const auto* Dos=reinterpret_cast<const IMAGE_DOS_HEADER*>(Headers.data());
    if(Dos->e_magic!=IMAGE_DOS_SIGNATURE || Dos->e_lfanew<0 || Dos->e_lfanew>2048)return false;
    const auto* Nt=reinterpret_cast<const IMAGE_NT_HEADERS64*>(Headers.data()+Dos->e_lfanew);
    if(Nt->Signature!=IMAGE_NT_SIGNATURE || Nt->FileHeader.NumberOfSections>24)return false;
    const auto* Sections=IMAGE_FIRST_SECTION(Nt);
    struct Region{uint32_t Rva;std::vector<int8_t> Bytes;};
    std::vector<std::pair<uint32_t,uint32_t>> ExecutableRanges;
    std::vector<Region> Code,Data;std::vector<IMAGE_RUNTIME_FUNCTION_ENTRY> Functions;
    nlohmann::json Report={{"schema","greyhound-bo4-collision-handlers-v4"},{"module_base",Hex(Base)},
        {"labels",nlohmann::json::array()},{"references",nlohmann::json::array()},
        {"functions",nlohmann::json::array()}};
    for(unsigned I=0;I<Nt->FileHeader.NumberOfSections;++I){
        const auto& S=Sections[I];const bool Exec=(S.Characteristics&IMAGE_SCN_MEM_EXECUTE)!=0;
        if(Exec)ExecutableRanges.emplace_back(S.VirtualAddress,S.Misc.VirtualSize);
        const std::string Name(reinterpret_cast<const char*>(S.Name),strnlen(reinterpret_cast<const char*>(S.Name),8));
        if(Name==".pdata"){
            auto B=Read(Base+S.VirtualAddress,S.Misc.VirtualSize);
            if(!B.empty()){
                const size_t Count=B.size()/sizeof(IMAGE_RUNTIME_FUNCTION_ENTRY);
                Functions.resize(Count);std::memcpy(Functions.data(),B.data(),Count*sizeof(IMAGE_RUNTIME_FUNCTION_ENTRY));
                Report["runtime_function_table_bytes"]=B.size();Report["runtime_function_padding_bytes"]=B.size()%sizeof(IMAGE_RUNTIME_FUNCTION_ENTRY);
            }
        } else if(Exec || Name==".rdata" || Name==".data") {
            // Initialized data contains handler tables; avoid the huge zero-fill
            // section tail. Executable sections are scanned in memory only.
            const uint64_t Size=Exec?S.Misc.VirtualSize:(std::min)(S.Misc.VirtualSize,S.SizeOfRawData);
            if(!Size || Size>(96ull<<20))continue;
            auto B=Read(Base+S.VirtualAddress,Size);if(B.empty())continue;
            (Exec?Code:Data).push_back({S.VirtualAddress,std::move(B)});
        }
    }
    std::sort(Functions.begin(),Functions.end(),[](const auto& A,const auto& B){return A.BeginAddress<B.BeginAddress;});
    std::map<uint64_t,std::string> Labels;
    for(const auto* Label:{"trigger_box_new","trigger_multiple_new","trigger_use_new","trigger_damage_new","info_volume",
                          "trigger_box","cylinder","Cylinder","capsule","Capsule","solid","playerClip"}){
        const auto Len=std::strlen(Label)+1;bool Found=false;
        for(const auto& R:Data)for(size_t I=0;I+Len<=R.Bytes.size();++I)
            if((I==0 || R.Bytes[I-1]==0) && !std::memcmp(R.Bytes.data()+I,Label,Len)){
                Labels[Base+R.Rva+I]=Label;Report["labels"].push_back({{"name",Label},{"rva",Hex(R.Rva+I)}});Found=true;
            }
        if(!Found)Report["labels"].push_back({{"name",Label},{"status","not_in_initialized_data"}});
    }
    std::set<uint32_t> Saved;std::vector<std::pair<uint64_t,unsigned>> Pending;
    for(const auto& R:Data)for(size_t I=0;I+8<=R.Bytes.size();I+=8){
        uint64_t P=0;std::memcpy(&P,R.Bytes.data()+I,8);if(!Labels.count(P))continue;
        nlohmann::json Ref={{"label",Labels[P]},{"kind","absolute_pointer_table"},{"rva",Hex(R.Rva+I)}};
        const size_t Start=I>=64?I-64:0,Size=(std::min)(size_t(192),R.Bytes.size()-Start);
        const auto File=Strings::Format("handler_table_%X.bin",R.Rva+uint32_t(Start));Save(R.Bytes.data()+Start,uint32_t(Size),File);
        Ref["file"]=File;Ref["file_rva"]=Hex(R.Rva+Start);
        Ref["pointed_strings"]=nlohmann::json::array();
        for(size_t J=Start;J+8<=Start+Size;J+=8){
            uint64_t V=0;std::memcpy(&V,R.Bytes.data()+J,8);
            for(const auto& D:Data)if(V>=Base+D.Rva && V-Base-D.Rva<D.Bytes.size()){
                const size_t At=size_t(V-Base-D.Rva);size_t L=0;bool Plain=true;
                while(At+L<D.Bytes.size() && D.Bytes[At+L] && L<96){if(uint8_t(D.Bytes[At+L])<32 || uint8_t(D.Bytes[At+L])>126)Plain=false;++L;}
                if(Plain && L>0 && L<96 && At+L<D.Bytes.size())Ref["pointed_strings"].push_back({{"rva",Hex(R.Rva+J)},{"text",std::string(reinterpret_cast<const char*>(D.Bytes.data()+At),L)}});
            }
        }
        Report["references"].push_back(Ref);
        for(size_t J=I;J<(std::min)(I+32,R.Bytes.size()-7);J+=8){uint64_t F=0;std::memcpy(&F,R.Bytes.data()+J,8);Pending.emplace_back(F,0);}
    }
    for(const auto& R:Code)for(size_t I=0;I+7<=R.Bytes.size();++I){
        const auto* B=reinterpret_cast<const uint8_t*>(R.Bytes.data()+I);
        if((B[0]&0xF8)!=0x48 || (B[1]!=0x8D && B[1]!=0x8B) || (B[2]&0xC7)!=5)continue;
        int32_t D=0;std::memcpy(&D,B+3,4);const uint64_t P=Base+R.Rva+I+7+D;
        if(!Labels.count(P))continue;
        Report["references"].push_back({{"label",Labels[P]},{"kind","rip_relative_instruction_candidate"},{"rva",Hex(R.Rva+I)}});
        Pending.emplace_back(Base+R.Rva+I,0);
    }
    for(size_t I=0;I<Pending.size() && Saved.size()<128;++I){
        const auto Address=Pending[I].first;const auto Depth=Pending[I].second;
        if(Address<Base || Address-Base>0xffffffffull)continue;const auto Rva=uint32_t(Address-Base);
        auto It=std::upper_bound(Functions.begin(),Functions.end(),Rva,[](uint32_t V,const auto& F){return V<F.BeginAddress;});
        uint32_t Begin=Rva;
        if(It!=Functions.begin()){--It;if(Rva<It->EndAddress)Begin=It->BeginAddress;}
        uint32_t Size=0;
        for(const auto& C:ExecutableRanges)if(Begin>=C.first && Begin-C.first<C.second)
            Size=(std::min)(uint32_t(4096-(Begin&4095)),C.second-(Begin-C.first));
        if(!Size || !Saved.insert(Begin).second)continue;
        auto B=Read(Base+Begin,Size);if(B.empty())continue;
        auto Again=Read(Base+Begin,B.size());if(B!=Again)continue;
        const auto File=Strings::Format("handler_%X.bin",Begin);if(!Save(B.data(),uint32_t(B.size()),File))return false;
        Report["functions"].push_back({{"rva",Hex(Begin)},{"end_rva",Hex(Begin+Size)},
            {"file",File},{"depth",Depth},{"scope","code_window_not_function_extent"},{"readback_unchanged",true}});
        // Potential direct calls are only leads. The offline disassembler must
        // validate instruction boundaries before treating any as a real edge.
        if(Depth<2)for(size_t J=0;J+5<=B.size();++J)if(uint8_t(B[J])==0xE8){
            int32_t D=0;std::memcpy(&D,B.data()+J+1,4);Pending.emplace_back(Base+Begin+J+5+D,Depth+1);
        }
    }
    Report["function_limit_reached"]=Saved.size()>=128;
    std::ofstream Out(FileSystems::CombinePath(Path,"collision_handlers.json"));Out<<Report.dump(2);return bool(Out);
}
