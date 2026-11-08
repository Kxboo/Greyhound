local locked = getmetatable( _G ) ~= nil
local function write_file()
	local io = require( "io" )
	return io
end
CoD.TestLinkerGlobal = { locked = locked, write_file = write_file }
