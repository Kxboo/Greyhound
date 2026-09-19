#include "../src/WraithXCOD/WraithXCOD/CWFXAnimationPlacements.h"
#include <iostream>
using namespace CWFXAnimationPlacements;
void Check(bool B){if(!B)throw std::runtime_error("FX/animation reference test failed");}
int main(){try{
    const auto Entities=json::array({{{"EntityId","e1"},{"Properties",{{"previewanim1","walk_anim"},{"origin",{1,2,3}},{"custom","retain me"}}}},
        {{"EntityId","e2"},{"Properties",{{"script_firefx","explosion_fx_05"}}}}});
    const auto Static=json::array({{{"Name","ordinary"}},{{"Name","p9_fxanm_door"},{"Position",{{"X",12.5}}}}});
    const auto Models=json::array({{{"Name","ordinary"},{"SourceEntityId","e1"}},{{"Name","ordinary"},{"SourceEntityId","e2"}}});
    auto R=Build(Static,Models,Entities);
    Check(R["animation_model_placements"].size()==2);
    Check(R["animation_model_placements"][0]["SourcePlacementIndex"]==1);
    Check(R["animation_model_placements"][0]["Position"]["X"]==12.5);
    Check(R["animation_model_placements"][1]["AttachedEntityProperties"]["custom"]=="retain me");
    Check(R["animation_entity_references"].size()==1&&R["fx_entity_references"].size()==1);
    Check(R["named_animation_references"][0]["Name"]=="walk_anim");
    Check(R["named_animation_references"][0]["SourceEntityId"]=="e1");
    Check(!ModelHint("ordinary_anim")&&ModelHint("P9_FXANIM_DOOR"));
    std::cout<<"FX/animation placement tests passed\n";return 0;
}catch(const std::exception& E){std::cerr<<E.what()<<"\n";return 1;}}
