CoD.TestUIText = InheritFrom( LUI.UIElement )
CoD.TestUIText.new = function ( menu, controller )
	local self = LUI.UIElement.new()
	local first = LUI.UIText.new()
	self:addElement( first )
	local second = LUI.UIText.new()
	second:addElementBefore( first )
	return self
end
