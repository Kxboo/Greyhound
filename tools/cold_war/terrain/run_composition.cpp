// Execute an unchanged captured terrain composition shader on a separate WARP
// device. All bindings are explicit fixture files; this never touches the game.
// With --serve, setup happens once; each stdin line "GENERIC_BIN<TAB>OUTPUT_DIR"
// dispatches one tile with those constants and answers "ok <ms>" (or "error ...").
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <wrl.h>
#include <json.hpp>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <vector>
#include <array>
#include <stdexcept>
#include <cstring>
#include <chrono>
#include <string>
#include <sstream>
using Microsoft::WRL::ComPtr;
using json = nlohmann::json;
namespace fs = std::filesystem;
void check(HRESULT h) { if(FAILED(h)) throw std::runtime_error("HRESULT " + std::to_string((unsigned)h)); }
std::vector<char> load(const fs::path& p) {
    std::ifstream f(p, std::ios::binary|std::ios::ate);
    if(!f) throw std::runtime_error("Cannot read " + p.string());
    auto n=f.tellg(); std::vector<char> b((size_t)n); f.seekg(0); f.read(b.data(),n);
    if(!f) throw std::runtime_error("Short read " + p.string()); return b;
}
int main(int argc,char** argv) { try {
    const bool serve=argc==3 && std::string(argv[2])=="--serve";
    if(argc!=2 && !serve) throw std::runtime_error("Expected fixture.json [--serve]");
    fs::path manifest=fs::absolute(argv[1]), base=manifest.parent_path();
    auto bytes=load(manifest); auto j=json::parse(bytes.begin(),bytes.end());
    unsigned width=j.at("width"), height=j.at("height");
    if(!width||!height||width%8||height%8||width>4096||height>4096) throw std::runtime_error("Invalid dispatch size");
    auto shader=load(base/j.at("shader").get<std::string>());
    ComPtr<IDXGIFactory4> factory; check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)));
    ComPtr<IDXGIAdapter> adapter; check(factory->EnumWarpAdapter(IID_PPV_ARGS(&adapter)));
    ComPtr<ID3D12Device> device; check(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(&device)));
    D3D12_COMMAND_QUEUE_DESC qd={}; qd.Type=D3D12_COMMAND_LIST_TYPE_COMPUTE;
    ComPtr<ID3D12CommandQueue> queue; check(device->CreateCommandQueue(&qd,IID_PPV_ARGS(&queue)));
    ComPtr<ID3D12CommandAllocator> allocator; check(device->CreateCommandAllocator(qd.Type,IID_PPV_ARGS(&allocator)));
    ComPtr<ID3D12GraphicsCommandList> list; check(device->CreateCommandList(0,qd.Type,allocator.Get(),nullptr,IID_PPV_ARGS(&list)));
    std::vector<ComPtr<ID3D12Resource>> resources;
    auto buffer=[&](uint64_t n,D3D12_HEAP_TYPE heap,D3D12_RESOURCE_STATES state,const void* data) {
        D3D12_HEAP_PROPERTIES hp={}; hp.Type=heap;
        D3D12_RESOURCE_DESC d={}; d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER; d.Width=n; d.Height=1;
        d.DepthOrArraySize=1; d.MipLevels=1; d.SampleDesc.Count=1; d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
        ComPtr<ID3D12Resource> r; check(device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,state,nullptr,IID_PPV_ARGS(&r)));
        if(data) { void* p; D3D12_RANGE none={0,0}; check(r->Map(0,&none,&p)); memcpy(p,data,(size_t)n);r->Unmap(0,nullptr); }
        resources.push_back(r); return r;
    };
    auto transition=[&](ID3D12Resource* r,D3D12_RESOURCE_STATES from,D3D12_RESOURCE_STATES to) {
        D3D12_RESOURCE_BARRIER b={};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;b.Transition.pResource=r;
        b.Transition.StateBefore=from;b.Transition.StateAfter=to;b.Transition.Subresource=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
        list->ResourceBarrier(1,&b);
    };
    auto texture=[&](unsigned w,unsigned h,DXGI_FORMAT format,bool output,const std::vector<char>& data,unsigned mips=1) {
        D3D12_HEAP_PROPERTIES hp={}; hp.Type=D3D12_HEAP_TYPE_DEFAULT;
        D3D12_RESOURCE_DESC d={};d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;d.Width=w;d.Height=h;
        d.DepthOrArraySize=1;d.MipLevels=(UINT16)mips;d.Format=format;d.SampleDesc.Count=1;
        d.Flags=output?D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS:D3D12_RESOURCE_FLAG_NONE;
        ComPtr<ID3D12Resource> r;check(device->CreateCommittedResource(&hp,D3D12_HEAP_FLAG_NONE,&d,
            output?D3D12_RESOURCE_STATE_UNORDERED_ACCESS:D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(&r)));
        if(!output) {
            if(!mips||mips>15)throw std::runtime_error("Invalid mip count");
            std::vector<D3D12_PLACED_SUBRESOURCE_FOOTPRINT> foot(mips);
            std::vector<UINT> rows(mips);std::vector<UINT64> rowBytes(mips);UINT64 n;
            device->GetCopyableFootprints(&d,0,mips,0,foot.data(),rows.data(),rowBytes.data(),&n);
            uint64_t expected=0;for(unsigned mip=0;mip<mips;++mip)expected+=rowBytes[mip]*rows[mip];
            if(data.size()!=expected) throw std::runtime_error("Texture payload mismatch: expected "+std::to_string(expected)+", got "+std::to_string(data.size()));
            std::vector<char> padded((size_t)n);uint64_t sourceOffset=0;
            for(unsigned mip=0;mip<mips;++mip) {
                for(unsigned y=0;y<rows[mip];++y)memcpy(padded.data()+foot[mip].Offset+y*foot[mip].Footprint.RowPitch,
                    data.data()+sourceOffset+y*rowBytes[mip],(size_t)rowBytes[mip]);
                sourceOffset+=rows[mip]*rowBytes[mip];
            }
            auto upload=buffer(n,D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ,padded.data());
            for(unsigned mip=0;mip<mips;++mip) {
                D3D12_TEXTURE_COPY_LOCATION src={},dest={};src.pResource=upload.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;src.PlacedFootprint=foot[mip];
                dest.pResource=r.Get();dest.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;dest.SubresourceIndex=mip;
                list->CopyTextureRegion(&dest,0,0,0,&src,nullptr);
            }
            transition(r.Get(),D3D12_RESOURCE_STATE_COPY_DEST,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        }
        resources.push_back(r);return r;
    };
    constexpr UINT N=16384, FLOAT_BASE=0, UINT_BASE=N, TILE=N*2, LAYER=TILE+1,
        WEATHER=TILE+2, WEATHER_TEX=TILE+3, WEATHER_BLEND=TILE+4, WEATHER_INDEX=TILE+5, DISTORT=TILE+6, OUTPUT=TILE+7;
    D3D12_DESCRIPTOR_HEAP_DESC hd={};hd.NumDescriptors=OUTPUT+3;hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_CBV_SRV_UAV;hd.Flags=D3D12_DESCRIPTOR_HEAP_FLAG_SHADER_VISIBLE;
    ComPtr<ID3D12DescriptorHeap> heap;check(device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&heap)));
    auto stride=device->GetDescriptorHandleIncrementSize(hd.Type);
    auto cpu=[&](UINT index){auto h=heap->GetCPUDescriptorHandleForHeapStart();h.ptr+=uint64_t(index)*stride;return h;};
    auto gpu=[&](UINT index){auto h=heap->GetGPUDescriptorHandleForHeapStart();h.ptr+=uint64_t(index)*stride;return h;};
    auto texSrv=[&](UINT index,ID3D12Resource* r,DXGI_FORMAT format){
        D3D12_SHADER_RESOURCE_VIEW_DESC d={};d.Format=format;d.ViewDimension=D3D12_SRV_DIMENSION_TEXTURE2D;
        d.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;d.Texture2D.MipLevels=r?r->GetDesc().MipLevels:1;
        device->CreateShaderResourceView(r,&d,cpu(index));
    };
    for(UINT i=0;i<N;++i) {texSrv(FLOAT_BASE+i,nullptr,DXGI_FORMAT_R32G32B32A32_FLOAT);texSrv(UINT_BASE+i,nullptr,DXGI_FORMAT_R32_UINT);}
    auto structure=[&](UINT index,const char* key,UINT element,std::size_t empty){
        auto b=j.contains(key)?load(base/j.at(key).get<std::string>()):std::vector<char>(empty);
        if(b.empty()||b.size()%element)throw std::runtime_error(std::string("Invalid structured buffer ")+key);
        auto r=buffer(b.size(),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ,b.data());
        D3D12_SHADER_RESOURCE_VIEW_DESC d={};d.ViewDimension=D3D12_SRV_DIMENSION_BUFFER;d.Shader4ComponentMapping=D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING;
        d.Buffer.NumElements=(UINT)b.size()/element;d.Buffer.StructureByteStride=element;device->CreateShaderResourceView(r.Get(),&d,cpu(index));
    };
    structure(TILE,"tile",316,316);structure(LAYER,"layers",128,128*300);structure(WEATHER,"weather",96,96*256);structure(WEATHER_TEX,"weather_textures",32,32*256);
    std::vector<char> zero(16);auto black=texture(1,1,DXGI_FORMAT_R32G32B32A32_FLOAT,false,zero);
    auto fixedTexture=[&](UINT index,const char* key) {
        if(j.contains(key)) {
            const auto& entry=j.at(key);auto fmt=(DXGI_FORMAT)entry.at("format").get<unsigned>();
            auto r=texture(entry.at("width"),entry.at("height"),fmt,false,
                load(base/entry.at("file").get<std::string>()),entry.value("mips",1u));
            texSrv(index,r.Get(),fmt);
        } else texSrv(index,black.Get(),DXGI_FORMAT_R32G32B32A32_FLOAT);
    };
    fixedTexture(WEATHER_BLEND,"weather_blend");fixedTexture(WEATHER_INDEX,"weather_index");
    if(j.contains("distortion")) {
        const auto& entry=j.at("distortion");
        auto fmt=(DXGI_FORMAT)entry.at("format").get<unsigned>();
        auto distort=texture(entry.at("width"),entry.at("height"),fmt,false,
            load(base/entry.at("file").get<std::string>()),entry.value("mips",1u));
        texSrv(DISTORT,distort.Get(),fmt);
    } else {
        // Neutral only for controlled fixtures and the earlier baseline.
        std::array<float,4> neutral={.5f,.5f,0,1};std::vector<char> neutralBytes(16);memcpy(neutralBytes.data(),neutral.data(),16);
        auto distort=texture(1,1,DXGI_FORMAT_R32G32B32A32_FLOAT,false,neutralBytes);texSrv(DISTORT,distort.Get(),DXGI_FORMAT_R32G32B32A32_FLOAT);
    }
    for(auto& entry:j.at("textures")) {
        unsigned id=entry.at("id"),w=entry.at("width"),h=entry.at("height");bool integer=entry.at("type")=="uint";
        if(id>=N)throw std::runtime_error("Descriptor out of range");
        auto fmt=(DXGI_FORMAT)entry.value("format",(unsigned)(integer?DXGI_FORMAT_R32_UINT:DXGI_FORMAT_R32G32B32A32_FLOAT));
        auto r=texture(w,h,fmt,false,load(base/entry.at("file").get<std::string>()),entry.value("mips",1u));texSrv((integer?UINT_BASE:FLOAT_BASE)+id,r.Get(),fmt);
    }
    std::array<ComPtr<ID3D12Resource>,3> targets,readbacks;
    std::array<D3D12_PLACED_SUBRESOURCE_FOOTPRINT,3> outputFoot;
    std::array<UINT64,3> outputSize;
    for(unsigned i=0;i<3;++i) {
        targets[i]=texture(width,height,DXGI_FORMAT_R32G32B32A32_FLOAT,true,{});
        D3D12_UNORDERED_ACCESS_VIEW_DESC ud={};ud.ViewDimension=D3D12_UAV_DIMENSION_TEXTURE2D;ud.Format=DXGI_FORMAT_R32G32B32A32_FLOAT;
        device->CreateUnorderedAccessView(targets[i].Get(),nullptr,&ud,cpu(OUTPUT+i));
        auto d=targets[i]->GetDesc();UINT rows;UINT64 rowBytes;
        device->GetCopyableFootprints(&d,0,1,0,&outputFoot[i],&rows,&rowBytes,&outputSize[i]);
        readbacks[i]=buffer(outputSize[i],D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST,nullptr);
    }
    auto constants=[&](const char* key,unsigned minimum){auto b=load(base/j.at(key).get<std::string>());if(b.size()<minimum)throw std::runtime_error("Short constants");b.resize((b.size()+255)&~255);return buffer(b.size(),D3D12_HEAP_TYPE_UPLOAD,D3D12_RESOURCE_STATE_GENERIC_READ,b.data());};
    auto generic=constants("generic",256),scene=constants("scene",2656);
    const auto genericSize=generic->GetDesc().Width;
    hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_SAMPLER;hd.NumDescriptors=256;
    ComPtr<ID3D12DescriptorHeap> samplers;check(device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&samplers)));
    auto scpu=samplers->GetCPUDescriptorHandleForHeapStart();auto ss=device->GetDescriptorHandleIncrementSize(hd.Type);
    for(unsigned i=0;i<256;++i) { D3D12_SAMPLER_DESC d={};d.Filter=D3D12_FILTER_MIN_MAG_MIP_LINEAR;
        d.AddressU=d.AddressV=d.AddressW=D3D12_TEXTURE_ADDRESS_MODE_WRAP;d.MaxLOD=D3D12_FLOAT32_MAX;d.MaxAnisotropy=1;d.ComparisonFunc=D3D12_COMPARISON_FUNC_ALWAYS;
        device->CreateSampler(&d,scpu);scpu.ptr+=ss; }
    D3D12_DESCRIPTOR_RANGE ranges[11]={};D3D12_ROOT_PARAMETER params[13]={};
    UINT regs[]={56,58,70,71,72,73,256,256,0,0,256},spaces[]={6,6,6,6,6,6,1,4,0,0,1};
    UINT offsets[]={TILE,LAYER,WEATHER,WEATHER_TEX,WEATHER_BLEND,WEATHER_INDEX,FLOAT_BASE,UINT_BASE,DISTORT,OUTPUT,0};
    for(unsigned i=0;i<11;++i) {
        ranges[i].RangeType=i==10?D3D12_DESCRIPTOR_RANGE_TYPE_SAMPLER:(i==9?D3D12_DESCRIPTOR_RANGE_TYPE_UAV:D3D12_DESCRIPTOR_RANGE_TYPE_SRV);
        ranges[i].NumDescriptors=(i==6||i==7||i==10)?UINT_MAX:(i==9?3:1);ranges[i].BaseShaderRegister=regs[i];ranges[i].RegisterSpace=spaces[i];
        params[i].ParameterType=D3D12_ROOT_PARAMETER_TYPE_DESCRIPTOR_TABLE;params[i].DescriptorTable.NumDescriptorRanges=1;params[i].DescriptorTable.pDescriptorRanges=&ranges[i];
    }
    params[11].ParameterType=params[12].ParameterType=D3D12_ROOT_PARAMETER_TYPE_CBV;
    params[11].Descriptor.ShaderRegister=4;params[12].Descriptor.ShaderRegister=2;
    D3D12_STATIC_SAMPLER_DESC statics[3]={};
    for(auto& d:statics) {d.Filter=D3D12_FILTER_MIN_MAG_MIP_LINEAR;d.AddressU=d.AddressV=d.AddressW=D3D12_TEXTURE_ADDRESS_MODE_CLAMP;
        d.ComparisonFunc=D3D12_COMPARISON_FUNC_ALWAYS;d.MaxLOD=D3D12_FLOAT32_MAX;d.MaxAnisotropy=1;}
    statics[0].ShaderRegister=0;statics[0].MaxLOD=0;
    statics[1].ShaderRegister=2;statics[1].AddressU=statics[1].AddressV=statics[1].AddressW=D3D12_TEXTURE_ADDRESS_MODE_WRAP;
    statics[2].ShaderRegister=12;statics[2].RegisterSpace=5;
    D3D12_ROOT_SIGNATURE_DESC rd={};rd.NumParameters=13;rd.pParameters=params;rd.NumStaticSamplers=3;rd.pStaticSamplers=statics;
    ComPtr<ID3DBlob> sig,error;HRESULT hr=D3D12SerializeRootSignature(&rd,D3D_ROOT_SIGNATURE_VERSION_1,&sig,&error);
    if(FAILED(hr)&&error)std::cerr<<(char*)error->GetBufferPointer();check(hr);
    ComPtr<ID3D12RootSignature> root;check(device->CreateRootSignature(0,sig->GetBufferPointer(),sig->GetBufferSize(),IID_PPV_ARGS(&root)));
    D3D12_COMPUTE_PIPELINE_STATE_DESC pd={};pd.pRootSignature=root.Get();pd.CS={shader.data(),shader.size()};
    ComPtr<ID3D12PipelineState> pipeline;check(device->CreateComputePipelineState(&pd,IID_PPV_ARGS(&pipeline)));
    ComPtr<ID3D12Fence> fence;check(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)));
    UINT64 fenceValue=0;HANDLE event=CreateEvent(nullptr,FALSE,FALSE,nullptr);
    auto submit=[&]{
        check(list->Close());ID3D12CommandList* lists[]={list.Get()};queue->ExecuteCommandLists(1,lists);
        check(queue->Signal(fence.Get(),++fenceValue));check(fence->SetEventOnCompletion(fenceValue,event));
        if(WaitForSingleObject(event,60000)!=WAIT_OBJECT_0)throw std::runtime_error("WARP dispatch timed out");
        check(device->GetDeviceRemovedReason());
    };
    // Texture uploads were recorded during setup; run them once.
    submit();
    // Outputs stay UAV between tiles; each tile copies them out and restores the state.
    auto dispatch=[&](const fs::path& out){
        check(allocator->Reset());check(list->Reset(allocator.Get(),nullptr));
        list->SetPipelineState(pipeline.Get());list->SetComputeRootSignature(root.Get());
        ID3D12DescriptorHeap* heaps[]={heap.Get(),samplers.Get()};list->SetDescriptorHeaps(2,heaps);
        for(unsigned i=0;i<10;++i)list->SetComputeRootDescriptorTable(i,gpu(offsets[i]));
        list->SetComputeRootDescriptorTable(10,samplers->GetGPUDescriptorHandleForHeapStart());
        list->SetComputeRootConstantBufferView(11,generic->GetGPUVirtualAddress());list->SetComputeRootConstantBufferView(12,scene->GetGPUVirtualAddress());
        list->Dispatch(width/8,height/8,1);
        for(unsigned i=0;i<3;++i) {
            transition(targets[i].Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
            D3D12_TEXTURE_COPY_LOCATION src={},dst={};src.pResource=targets[i].Get();src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
            dst.pResource=readbacks[i].Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dst.PlacedFootprint=outputFoot[i];
            list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
            transition(targets[i].Get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
        }
        submit();
        fs::create_directories(out);
        for(unsigned i=0;i<3;++i) {
            void* p;D3D12_RANGE range={0,(SIZE_T)outputSize[i]};check(readbacks[i]->Map(0,&range,&p));
            std::ofstream f(out/("vt"+std::to_string(i)+".f32"),std::ios::binary);
            for(unsigned y=0;y<height;++y)f.write((char*)p+outputFoot[i].Offset+y*outputFoot[i].Footprint.RowPitch,width*16);
            D3D12_RANGE written={0,0};readbacks[i]->Unmap(0,&written);
            if(!f)throw std::runtime_error("Output write failed");
        }
    };
    if(serve) {
        std::cout<<"ready\n"<<std::flush;
        std::string line;
        while(std::getline(std::cin,line)) {
            if(!line.empty()&&line.back()=='\r')line.pop_back();
            if(line.empty()||line=="quit")break;
            const auto t0=std::chrono::steady_clock::now();
            try {
                const auto split=line.find('\t');
                if(split==std::string::npos)throw std::runtime_error("Expected GENERIC_BIN<TAB>OUTPUT_DIR");
                auto b=load(fs::path(line.substr(0,split)));
                if(b.size()<256||b.size()>genericSize)throw std::runtime_error("Invalid generic constants");
                void* p;D3D12_RANGE none={0,0};check(generic->Map(0,&none,&p));
                memset(p,0,(size_t)genericSize);memcpy(p,b.data(),b.size());generic->Unmap(0,nullptr);
                dispatch(fs::path(line.substr(split+1)));
                std::cout<<"ok "<<std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-t0).count()<<"\n"<<std::flush;
            } catch(const std::exception& e) {std::cout<<"error "<<e.what()<<"\n"<<std::flush;}
        }
        CloseHandle(event);return 0;
    }
    dispatch(base/j.at("output_directory").get<std::string>());
    CloseHandle(event);
    std::cout<<"Provided DXIL executed on WARP: "<<width<<"x"<<height<<", three float4 outputs\n";
    return 0;
} catch(const std::exception& e) {std::cerr<<e.what()<<"\n";return 1;} }
