CoD.TestEmptyModel = InheritFrom( LUI.UIElement )
CoD.TestEmptyModel.new = function ( menu, controller )
	local self = LUI.UIElement.new()
	local root = Engine.GetModelForController( controller )
	self:subscribeToModel( Engine.CreateModel( root, "testValue" ), function ( model )
		self:setAlpha( tonumber( Engine.GetModelValue( model ) ) or 0 )
	end )
	return self
end
