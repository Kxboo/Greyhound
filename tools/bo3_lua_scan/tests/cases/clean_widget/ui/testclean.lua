CoD.TestClean = InheritFrom( LUI.UIElement )
CoD.TestClean.new = function ( menu, controller )
	local self = LUI.UIElement.new()
	self:setClass( CoD.TestClean )
	self:setLeftRight( true, false, 0, 100 )
	self:setTopBottom( true, false, 0, 20 )
	local image = LUI.UIImage.new()
	image:setImage( RegisterImage( "$white" ) )
	self:addElement( image )
	local text = LUI.UIText.new()
	text:setText( Engine.Localize( "TEST" ) )
	self:addElement( text )
	local root = Engine.GetModelForController( controller )
	self:subscribeToModel( Engine.CreateModel( root, "testValue" ), function ( model )
		local value = Engine.GetModelValue( model )
		if value then
			text:setText( tostring( value ) )
		end
	end )
	return self
end
