-- Aetherium Compass Widget (Top Center)
-- Uses: i_mtl_ui_hud_compass_theme_aetherium
-- Implements horizontal tickertape compass

CoD.AetheriumCompass = InheritFrom( LUI.UIElement )
CoD.AetheriumCompass.new = function ( menu, controller )
	local self = LUI.UIElement.new()

	self:setUseStencil( false )
	self:setClass( CoD.AetheriumCompass )
	self.id = "AetheriumCompass"
	self.soundSet = "default"
	self:setLeftRight( true, false, 0, 1280 )
	self:setTopBottom( true, false, 0, 720 )
	self.anyChildUsesUpdateState = true

	-- Compass Background Image (decorative frame)
	self.compass_image = LUI.UIImage.new()
	self.compass_image:setLeftRight(true, false, 239, 1055)
	self.compass_image:setTopBottom(true, false, -24, 131)
	self.compass_image:setImage( RegisterImage( "i_mtl_ui_hud_compass_theme_aetherium" ) )
	self.compass_image:setAlpha( 1 )
	self:addElement( self.compass_image )

	-- Horizontal Compass Tickertape (scrolls based on player rotation)
	-- Positioned to overlay the compass frame background
	self.HorizontalCompass = LUI.UIImage.new()
	self.HorizontalCompass:setLeftRight(true, false, 337, 957)  -- Centered within frame (620px wide)
	self.HorizontalCompass:setTopBottom(true, false, 32, 55)   -- Centered vertically within frame
	self.HorizontalCompass:setupHorizontalCompass( 0.75 )         -- MUST be called before setImage
	self.HorizontalCompass:setImage( RegisterMaterial( "sat_hud_horizontal_compass" ) )  -- Vanilla compass material
	self.HorizontalCompass:setShaderVector( 0, 0.6, 0, 0, 0 )     -- Shader parameters
	self.HorizontalCompass:setAlpha( 0.8 )
	self:addElement( self.HorizontalCompass )

	pcall( require, "ui.uieditor.widgets.HUD.AetheriumWidgets.BO7.MZOBO7Hud" )
	if CoD.MZOBO7Hud then
		CoD.MZOBO7Hud.Compass( self, controller )
	end
	return self
end
