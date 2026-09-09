#include "../src/WraithXCOD/WraithXCOD/ModelBatchSelection.h"
#include <cassert>
#include <iostream>
int main()
{
    using namespace ModelBatchSelection;
    const auto Missing=(std::numeric_limits<size_t>::max)();
    assert(Select({})==Missing);
    assert(Select({{10,0,false,false,false}})==Missing);
    // Duplicate names still produce one candidate; a manual success takes priority.
    assert(Select({{10,0,true,false,true},{20,1,true,true,false}})==1);
    // A placeholder cannot displace the loaded copy.
    assert(Select({{10,0,false,false,false},{20,1,true,false,true}})==1);
    // Sorting the pool doesn't change the selected address.
    assert(Select({{20,0,true,false,true},{10,1,true,false,true}})==1);
    assert(Select({{10,0,true,false,true},{20,1,true,false,true}})==0);
    // A loaded duplicate beats a candidate carrying a previous export error.
    assert(Select({{10,0,true,false,false},{20,1,true,false,true}})==1);
    // Aliased pointers remain one selected entry, with a stable first-index tie break.
    assert(Select({{10,0,true,false,true},{10,1,true,false,true}})==0);
    std::cout << "PASS: missing, unavailable, duplicate, manual-success, placeholder, order, error, alias\n";
}
