-- Stock functions the decompiled dump got wrong (lost returns, lost branches). Each runs right after its module loads.
-- The dump is all a modder has to go on, so when a scan blames stock code that can't be right, the repair goes here.
-- Keys are lowercase module names.
return {
	-- the dump merged its first statements, so the table refers to itself and never gets set. No sets = no sounds
	["ui.uieditor.soundsets"] = function ()
		SoundSet = SoundSet or {}
	end,
	["ui.lui.luielement"] = function ()
		LUI.UIElement.new = function ( state )
			local element = ConstructLUIElement( state or LUI.UIElement.m_defaultAnimationState )
			LUI.UIElement.setClass( element, LUI.UIElement )
			element:setLayoutCached( false )
			element.anyChildUsesUpdateState = false
			if state then
				element:registerAnimationState( "default", state )
				element:animateToState( "default" )
			end
			return element
		end
	end
}
