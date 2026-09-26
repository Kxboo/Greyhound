#include "games/cold_war/terrain/CWShaderContainer.h"
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <iterator>
#include <map>
#include <vector>

static void Word(std::vector<uint8_t>& B, size_t O, uint32_t V)
{
    std::memcpy(B.data() + O, &V, 4);
}

int main(int argc, char** argv)
{
    using namespace CWShaderContainer;
    std::vector<uint8_t> Good(72);
    std::memcpy(Good.data(), "DXBC", 4);
    Word(Good, 24, 72); Word(Good, 28, 1); Word(Good, 32, 36);
    std::memcpy(Good.data()+36, "DXIL", 4); Word(Good, 40, 28);
    Word(Good, 44, 0x10060); Word(Good, 48, 7);
    std::memcpy(Good.data()+52, "DXIL", 4);
    Word(Good, 60, 16); Word(Good, 64, 4); Word(Good, 68, 0xDEC04342);
    const auto Vertex = Read(Good.data(), Good.size());
    assert(Vertex.Valid && Vertex.Kind == 1 && std::strcmp(Vertex.Stage(), "vertex") == 0);
    for (size_t Size = 0; Size < Good.size(); ++Size)
        assert(!Read(Good.data(), Size).Valid);
    auto Bad = Good; Word(Bad, 32, 0xfffffff0);
    assert(!Read(Bad.data(), Bad.size()).Valid);
    Bad = Good; Word(Bad, 60, 0xfffffff0);
    assert(!Read(Bad.data(), Bad.size()).Valid);
    Bad = Good; Word(Bad, 40, 0xffffffff);
    assert(!Read(Bad.data(), Bad.size()).Valid);
    Bad = Good; Word(Bad, 28, 0xffffffff);
    assert(!Read(Bad.data(), Bad.size()).Valid);
    Bad = Good; Word(Bad, 68, 0);
    assert(!Read(Bad.data(), Bad.size()).Valid);
    auto Tail = Good; Tail.push_back(0xab);
    assert(Read(Tail.data(), Tail.size()).ContainerBytes == 72);
    Word(Good, 44, 0x50060);
    assert(std::strcmp(Read(Good.data(), Good.size()).Stage(), "compute") == 0);
    std::map<std::string, size_t> Stages;
    for (int Arg = 1; Arg < argc; ++Arg)
    {
        // Source capture paths can exceed MAX_PATH. Only scan the supplied
        // shader directory, not unrelated nested package-evidence directories.
        const auto Root = std::filesystem::absolute(argv[Arg]);
#ifdef _WIN32
        const std::filesystem::path NativeRoot(L"\\\\?\\" + Root.wstring());
#else
        const auto& NativeRoot = Root;
#endif
        for (const auto& Entry : std::filesystem::directory_iterator(NativeRoot))
        {
            if (!Entry.is_regular_file() || Entry.path().filename().string().find(".dxil.bin") == std::string::npos)
                continue;
            std::ifstream File(Entry.path(), std::ios::binary);
            std::vector<uint8_t> Bytes((std::istreambuf_iterator<char>(File)), {});
            const auto Shader = Read(Bytes.data(), Bytes.size());
            if (!Shader.Valid) { std::cerr << "Rejected " << Entry.path() << '\n'; return 1; }
            ++Stages[Shader.Stage()];
        }
    }
    std::cout << "Malformed/truncated containers rejected; trailing descriptor bytes preserved.\n";
    for (const auto& Stage : Stages) std::cout << Stage.first << ": " << Stage.second << '\n';
}
