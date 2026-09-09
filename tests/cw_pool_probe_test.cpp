#include "../src/WraithXCOD/WraithXCOD/CWPoolProbe.h"
#include <cassert>
void put(std::vector<uint8_t>& B, size_t O, uint64_t V) { memcpy(B.data()+O, &V, 8); }
int main() {
    using CWPoolProbe::Plan;
    std::vector<uint8_t> B(64);
    put(B,0,0x10000); put(B,8,0x20000); put(B,16,0x20000);
    put(B,24,0x800000000000ull); put(B,40,0x30000);
    auto R=Plan(B,32);
    assert(R.Slots==2 && R.Candidates.size()==2);
    assert(R.Candidates[0].Offset==8 && R.Candidates[1].Slot==1);
    assert(Plan(B,0).Candidates.empty() && Plan(B,65).Candidates.empty());
    B.resize(63); assert(Plan(B,32).Candidates.empty());
    B.assign(300*16,0);
    for(size_t i=0;i<300;i++) put(B,i*16+8,0x10000+i*4096);
    R=Plan(B,16); assert(R.Slots==256 && R.Candidates.size()==256);
    B.assign(65536,0);
    for(size_t i=1;i<300;i++) put(B,i*8,0x10000+i*4096);
    R=Plan(B,65536); assert(R.LimitReached && R.Candidates.size()==256);
    B.assign(64,0); put(B,0,0x10020);
    auto O=CWPoolProbe::FreeSlots(B,32,0x10000,0x10000,0);
    assert(O.Valid && O.Free.size()==2);
    put(B,32,0x10000); assert(!CWPoolProbe::FreeSlots(B,32,0x10000,0x10000,0).Valid);
    assert(!CWPoolProbe::FreeSlots(B,32,0x10000,0x10001,0).Valid);
    assert(!CWPoolProbe::FreeSlots(B,32,0x10000,0,1).Valid);
    CWPoolProbe::Graph G;
    B.assign(24,0); put(B,0,0x20000); put(B,8,0x20000); put(B,16,0x30000);
    G.Scan(B,0x10000,1);
    assert(G.Edges.size()==3 && G.Queue.size()==2 && G.Edges[0].Offset==0);
    G.Scan(B,0x20000,2); assert(G.Edges.size()==6 && G.Queue.size()==2);
    G.Scan(B,0x30000,3); assert(G.Edges.size()==6);
    B.assign(600*8,0); for(size_t i=0;i<600;i++)put(B,i*8,0x100000+i*8);
    G.Scan(B,0x40000,2); assert(G.NodeLimitReached && G.Queue.size()==G.NodeLimit);
    for(int i=0;i<40;i++)G.Scan(B,0x40000,2);
    assert(G.EdgeLimitReached && G.Edges.size()==G.EdgeLimit);
}
