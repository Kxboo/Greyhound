-- bo3_lua_scan run pass: runs a mod's Lua on the real stock LUI code (from a Lua dump), with stand-ins for what the
-- engine does natively. Run by scan.py: lua51.exe harness.lua <config.lua>. Writes one JSON object per line on stdout,
-- each behind the MARK prefix so anything else printed can't be taken for a result.
-- Scanned code is sandboxed: no file writes, no DLLs, no processes (see "sandbox" below).

local MARK = "\1BO3SCAN "
local real_io, real_stdout, real_exit = io, io.stdout, os.exit
local INSTRUCTION_LIMIT = 40000000 -- per call into scanned code; past this it's reported as a hang

local config = dofile( arg[1] )
local TOOL_DIR = string.match( arg[0], "^(.*)[/\\]" ) or "."

---------------------------------------------------------------------------------------------------------------------
-- output
---------------------------------------------------------------------------------------------------------------------
local function json( value )
	local t = type( value )
	if t == "table" then
		local out = {}
		if #value > 0 or next( value ) == nil then
			for i = 1, #value do
				out[i] = json( value[i] )
			end
			return "[" .. table.concat( out, "," ) .. "]"
		end
		for k, v in pairs( value ) do
			out[#out + 1] = json( tostring( k ) ) .. ":" .. json( v )
		end
		return "{" .. table.concat( out, "," ) .. "}"
	elseif t == "string" then
		return '"' .. string.gsub( value, '[%c"\\\128-\255]', function ( c )
			return string.format( "\\u%04x", string.byte( c ) )
		end ) .. '"'
	elseif t == "number" or t == "boolean" then
		return tostring( value )
	end
	return "null"
end

local function emit( record )
	real_stdout:write( MARK, json( record ), "\n" )
end

---------------------------------------------------------------------------------------------------------------------
-- naming: real function names from the source text, as the traceback only knows some
---------------------------------------------------------------------------------------------------------------------
local line_cache = {}

local function source_lines( path )
	local lines = line_cache[path]
	if lines then
		return lines
	end
	lines = {}
	local f = real_io.open( path, "r" )
	if f then
		for line in f:lines() do
			lines[#lines + 1] = line
		end
		f:close()
	end
	line_cache[path] = lines
	return lines
end

local function function_name( path, line_defined, fallback )
	if line_defined == 0 then
		return "main chunk"
	end
	local text = source_lines( path )[line_defined] or ""
	local name = string.match( text, "function%s+([%w_%.:]+)%s*%(" )
		or string.match( text, "([%w_%.:%[%]\"']+)%s*=%s*function" )
	if name then
		return name
	end
	return fallback and fallback ~= "" and fallback or ( "anonymous at line " .. line_defined )
end

local function normal( path )
	return string.lower( string.gsub( path, "\\", "/" ) )
end

local TARGETS, BUILDABLE = {}, {}
for _, path in ipairs( config.targets ) do
	TARGETS[normal( path )] = path
	BUILDABLE[normal( path )] = path
end
-- the other files of the mod: they run too, as a widget in one often calls code in another, but only an error with a
-- scanned file on its stack is reported
for _, path in ipairs( config.context or {} ) do
	BUILDABLE[normal( path )] = path
end

-- the stack at the error, innermost first, without the harness itself
local function frames_from( level )
	local frames = {}
	while #frames < 24 do
		local info = debug.getinfo( level, "Sln" )
		if not info then
			break
		end
		level = level + 1
		if info.what ~= "C" and info.source ~= nil and string.sub( info.source, 1, 1 ) == "@" then
			local path = string.sub( info.source, 2 )
			if not string.find( path, "harness.lua", 1, true ) then
				frames[#frames + 1] = {
					file = path,
					line = info.currentline,
					defined = info.linedefined,
					func = function_name( path, info.linedefined, info.name ),
					target = TARGETS[normal( path )] ~= nil
				}
			end
		end
	end
	return frames
end

local hook_lib = debug
local handler_frames
local function on_error( message )
	-- level 2 = where the error was raised
	handler_frames = frames_from( 2 )
	return tostring( message )
end

-- runs fn( ... ) under the error handler and the hang limit. Returns ok, message, frames
local function guarded( fn, ... )
	local args = { n = select( "#", ... ), ... }
	handler_frames = nil
	hook_lib.sethook( function ()
		error( "hang: gave up after " .. INSTRUCTION_LIMIT .. " instructions (an endless loop?)", 2 )
	end, "", INSTRUCTION_LIMIT )
	local ok, message = xpcall( function ()
		return fn( unpack( args, 1, args.n ) )
	end, on_error )
	hook_lib.sethook()
	return ok, message, handler_frames
end

---------------------------------------------------------------------------------------------------------------------
-- stand-ins for engine values
---------------------------------------------------------------------------------------------------------------------
-- Stub = "a value only the running game knows". Anything can be done to it, so live data can't cause false errors.
local Stub
local stub_meta = {}
stub_meta.__index = function ( self, key )
	return Stub
end
stub_meta.__newindex = function ()
end
stub_meta.__call = function ()
	return Stub
end
stub_meta.__tostring = function ()
	return "?"
end
stub_meta.__concat = function ( a, b )
	return ( type( a ) == "table" and "?" or tostring( a ) ) .. ( type( b ) == "table" and "?" or tostring( b ) )
end
for _, op in ipairs( { "__add", "__sub", "__mul", "__div", "__mod", "__pow", "__unm" } ) do
	stub_meta[op] = function ()
		return 0
	end
end
stub_meta.__lt = function ()
	return false
end
stub_meta.__le = function ()
	return false
end
Stub = setmetatable( {}, stub_meta )
local STUB_ID = "BO3SCAN_STUB"

-- what a native function returns, judged by its name
local function native_result( name )
	if string.find( name, "^Is" ) or string.find( name, "^Has" ) or string.find( name, "^Can" )
		or string.find( name, "^Should" ) or string.find( name, "^Was" ) or string.find( name, "^Are" )
		or string.find( name, "^is%u" ) or string.find( name, "^has%u" ) or string.find( name, "^can%u" ) then
		return function ()
			return false
		end
	end
	if string.find( name, "Count$" ) or string.find( name, "Num" ) or string.find( name, "Size$" )
		or string.find( name, "Width" ) or string.find( name, "Height" ) or string.find( name, "Time$" )
		or string.find( name, "Index$" ) or string.find( name, "Ms$" ) then
		return function ()
			return 0
		end
	end
	return function ()
		return Stub
	end
end

-- models: a tree of plain tables. Every path exists here: which ones exist in a game is live data
local Models = {}
local function new_model( path )
	return { bo3scan_model = true, path = path, children = {}, value = nil }
end
local model_root = new_model( "" )

local function child_model( parent, path )
	local node = parent
	if type( node ) ~= "table" or not node.bo3scan_model then
		node = model_root
	end
	for part in string.gmatch( tostring( path or "" ), "[^%.]+" ) do
		node.children[part] = node.children[part] or new_model( node.path .. "." .. part )
		node = node.children[part]
	end
	return node
end
Models.child = child_model

-- subscriptions the scanned code made, so they can be fired with fake data afterwards
local subscriptions = {}

---------------------------------------------------------------------------------------------------------------------
-- engine globals
---------------------------------------------------------------------------------------------------------------------
local index = dofile( config.index )

local ENGINE_SPECIAL = {
	GetModel = function ( parent, path )
		return child_model( parent, path )
	end,
	CreateModel = function ( parent, path )
		return child_model( parent, path )
	end,
	GetModelForController = function ( controller )
		return child_model( model_root, "PerController" .. tostring( controller ) )
	end,
	GetGlobalModel = function ()
		return model_root
	end,
	UnsubscribeAndFreeModel = function ()
	end,
	SetModelValue = function ( model, value )
		if type( model ) == "table" then
			model.value = value
		end
	end,
	-- an empty model gives no value at all, not nil: tonumber( Engine.GetModelValue( m ) ) is an error in the real game
	GetModelValue = function ( model )
		if type( model ) == "table" and model.value ~= nil then
			return model.value
		end
	end,
	GetModelPath = function ( model )
		return type( model ) == "table" and model.path or ""
	end,
	Localize = function ( text )
		return tostring( text )
	end,
	ToUpper = function ( text )
		return string.upper( tostring( text ) )
	end,
	ToLower = function ( text )
		return string.lower( tostring( text ) )
	end,
	CurrentGameTime = function ()
		return 0
	end,
	milliseconds = function ()
		return 0
	end,
	GetDvarString = function ()
		return ""
	end,
	DvarString = function ()
		return ""
	end,
	DvarInt = function ()
		return 0
	end,
	DvarFloat = function ()
		return 0
	end,
	DvarBool = function ()
		return false
	end,
	StructTableLookupString = function ()
		return ""
	end
}

Engine = {}
for name in pairs( index.engine ) do
	Engine[name] = native_result( name )
end
for name, fn in pairs( ENGINE_SPECIAL ) do
	Engine[name] = fn
end
for _, name in ipairs( config.extra_engine or {} ) do
	Engine[name] = Engine[name] or native_result( name )
end

-- every Enum.<Group>.<NAME> stock uses reads as a stable number
local function counted_enum( known )
	local next_value = 1
	local values = {}
	return setmetatable( {}, {
		__index = function ( self, key )
			if values[key] == nil then
				values[key] = next_value
				next_value = next_value + 1
			end
			return values[key]
		end
	} )
end
Enum = setmetatable( {}, {
	__index = function ( self, group )
		local e = counted_enum()
		rawset( self, group, e )
		return e
	end
} )

for name in pairs( index.native_globals ) do
	if _G[name] == nil then
		_G[name] = Stub
	end
end
-- a shipped game, not a development build: stock's EnableGlobals would otherwise clear _G's __index, which the autoload
-- below lives on
Dvar = setmetatable( { cg_development = { get = function ()
	return false
end } }, { __index = function ()
	return Stub
end } )
hpairs = pairs
RegisterImage = function ( name )
	return tostring( name )
end
RegisterMaterial = RegisterImage
DebugPrint = function ()
end
print = function ()
end

---------------------------------------------------------------------------------------------------------------------
-- sandbox: scanned code never reaches the disk, a process or a DLL
---------------------------------------------------------------------------------------------------------------------
local fake_io = {
	open = function ()
		return nil, "bo3_lua_scan: file access is off during a scan"
	end,
	lines = function ()
		return function ()
		end
	end,
	write = function ()
	end,
	read = function ()
	end,
	stdout = Stub,
	stderr = Stub
}
io = fake_io
package.loaded.io = fake_io
local real_clock = os.clock
os = { time = os.time, date = os.date, clock = real_clock, getenv = function ()
	return nil
end, tmpname = function ()
	return ""
end, remove = function ()
	return nil, "off"
end, rename = function ()
	return nil, "off"
end, execute = function ()
	return 0
end, exit = function ()
end }
package.loaded.os = os
package.loadlib = function ()
	return nil, "bo3_lua_scan: DLLs are off during a scan"
end
local real_dofile = dofile
dofile, loadfile = nil, nil

-- require: the mod's file first, then the stock dump, as the game's zones work
local dofile_real = real_dofile
local function find_module( name )
	local rel = string.gsub( name, "%.", "/" ) .. ".lua"
	local function exists( path )
		local f = real_io.open( path, "r" )
		if f then
			f:close()
			return true
		end
	end
	for _, root in ipairs( { config.root, config.stock } ) do
		if exists( root .. "/" .. rel ) then
			return root .. "/" .. rel
		end
	end
	-- compiled Lua can't run here. Mods keep the original as <name>og.luac and override <name>: the stock source is it
	if exists( config.root .. "/" .. string.gsub( rel, "%.lua$", ".luac" ) ) then
		local stock = config.stock .. "/" .. string.gsub( rel, "og%.lua$", ".lua" )
		if exists( stock ) then
			return stock
		end
	end
end
Models.find_module = find_module

local real_loadstring = loadstring

local function load_source( path )
	local f = real_io.open( path, "rb" )
	if not f then
		return nil, "can't read " .. path
	end
	local text = string.gsub( f:read( "*a" ), "^\239\187\191", "" )
	f:close()
	if not BUILDABLE[normal( path )] then
		-- decompiler damage in the stock dump, not in the game's real code
		text = string.gsub( text, "goto%s+basicblock_%d+:?", "" )
	end
	return real_loadstring( text, "@" .. path )
end

-- scanned code gets no way out of the stand-ins: bytecode and the debug library could reach the real io
loadstring = function ( text, name )
	if type( text ) == "string" and string.sub( text, 1, 1 ) == "\27" then
		return nil, "bo3_lua_scan: bytecode is off during a scan"
	end
	return real_loadstring( text, name )
end
load = nil
debug = { traceback = debug.traceback, getinfo = debug.getinfo }
package.loaded.debug = debug

---------------------------------------------------------------------------------------------------------------------
-- native element behaviour
---------------------------------------------------------------------------------------------------------------------
-- a real element's shape, as LUI.UIElement.setClass expects: the metatable's __newindex table holds the fields and its
-- own metatable points at the class
function ConstructLUIElement()
	-- its own m_eventHandlers: setClass would otherwise chain the class's table to itself
	local store = setmetatable( { m_eventHandlers = {} }, { __index = LUI and LUI.UIElement or nil } )
	return setmetatable( {}, { __index = store, __newindex = store } )
end

local NATIVE_ELEMENT = {
	addElementToC = function ( self, child )
		child.bo3scan_parent = self
	end,
	addElementBeforeInC = function ( self, sibling )
		self.bo3scan_parent = sibling.bo3scan_parent
	end,
	addElementAfterInC = function ( self, sibling )
		self.bo3scan_parent = sibling.bo3scan_parent
	end,
	getParent = function ( self )
		return self.bo3scan_parent
	end,
	getFirstChild = function ()
	end,
	getNextSibling = function ()
	end,
	getPreviousSibling = function ()
	end,
	getLastChild = function ()
	end,
	getNumChildren = function ()
		return 0
	end,
	removeAllChildren = function ()
	end,
	subscribeToModel = function ( self, model, fn, call_now )
		local sub = { element = self, model = model, fn = fn }
		subscriptions[#subscriptions + 1] = sub
		-- the engine calls it right away, with whatever the model has (usually nothing yet)
		if call_now ~= false and type( fn ) == "function" then
			fn( model )
		end
		return sub
	end,
	removeSubscription = function ( self, sub )
		if type( sub ) == "table" then
			sub.removed = true
		end
	end,
	unsubscribeFromAllModelsInC = function ()
	end,
	getModel = function ( self, controller, path )
		local model = self.bo3scan_model_value
		if path and model then
			return child_model( model, path )
		end
		return model
	end,
	setModelInC = function ( self, model )
		self.bo3scan_model_value = model
	end,
	setText = nil,
	setTextInC = function ( self, text )
		self.bo3scan_text = text
	end,
	getTextFromC = function ( self )
		return self.bo3scan_text or ""
	end,
	getTextWidth = function ()
		return 10
	end,
	getTextWidthAndHeight = function ()
		return 10, 10
	end,
	getLocalLeftRight = function ()
		return 0, 10
	end,
	getLocalTopBottom = function ()
		return 0, 10
	end,
	getLocalRect = function ()
		return 0, 0, 10, 10
	end,
	getRect = function ()
		return 0, 0, 10, 10
	end,
	getImageDimensions = function ()
		return 16, 16
	end,
	getWidth = function ()
		return 10
	end,
	getHeight = function ()
		return 10
	end,
	isInFocus = function ()
		return false
	end,
	close = nil
}

local function install_native_methods()
	local element = LUI.UIElement
	for name in pairs( index.methods ) do
		if element[name] == nil then
			element[name] = NATIVE_ELEMENT[name] or native_result( name )
		end
	end
	for name, fn in pairs( NATIVE_ELEMENT ) do
		if element[name] == nil or index.methods[name] then
			element[name] = fn
		end
	end
	for _, name in ipairs( config.extra_methods or {} ) do
		element[name] = element[name] or native_result( name )
	end
end

---------------------------------------------------------------------------------------------------------------------
-- boot: what the game has loaded before any mod file runs
---------------------------------------------------------------------------------------------------------------------
-- rawset: the moment lui.lua makes LUI.UIElement, its native methods must exist for the rest of boot
local function boot_require( name )
	local ok, message, frames = guarded( require, name )
	if not ok then
		emit( { kind = "boot", module = name, message = message, frames = frames } )
	end
end

-- zones find a file whatever its case, and a file being loaded just reads as loaded: a loop isn't an error in the game
local module_state, module_value = {}, {}
local STOCK_FIXES = dofile_real( TOOL_DIR .. "/stock_fixes.lua" )

require = function ( name )
	local key = string.lower( tostring( name ) )
	if module_state[key] then
		return module_value[key]
	end
	if package.loaded[name] ~= nil then
		return package.loaded[name]
	end
	local path = find_module( name )
	if not path then
		error( "module '" .. tostring( name ) .. "' not found: no such file in the mod or the stock dump", 2 )
	end
	local chunk, err = load_source( path )
	module_state[key] = "loading"
	if not chunk then
		if BUILDABLE[normal( path )] then
			error( err, 0 )
		end
		-- a stock file the dump mangled: it loads as empty, and the run says so
		emit( { kind = "stock_unreadable", file = path, message = err } )
		return nil
	end
	if BUILDABLE[normal( path )] then
		module_value[key] = chunk( name )
	else
		-- a stock file failing on a stand-in or on dump damage isn't the scanned code's fault: keep what it set up
		local ok, result = xpcall( function ()
			return chunk( name )
		end, function ( message )
			return tostring( message )
		end )
		if ok then
			module_value[key] = result
		else
			emit( { kind = "stock_unreadable", file = path, message = result } )
		end
	end
	module_state[key] = "done"
	if key == "ui.lui.luielement" and LUI and LUI.UIElement then
		install_native_methods()
	end
	if STOCK_FIXES[key] then
		STOCK_FIXES[key]()
	end
	return module_value[key]
end

-- a stock file's own sanity check while it loads (enum counts, say) can only trip on the stand-ins
local real_error = error
error = function ( message, level )
	local caller = hook_lib.getinfo( 2, "S" )
	if caller and caller.what == "main" and not BUILDABLE[normal( string.sub( caller.source, 2 ) )] then
		return
	end
	real_error( message, ( level or 1 ) + 1 )
end

-- what any running game has loaded by now: a stock global, CoD.<name> or LUI.<name> loads its file when first read.
-- Names stock never defines stay nil, so a typo still fails
local function autoload( map, tbl, key )
	local module = map[key]
	if not module or module_state[string.lower( module )] then
		return nil
	end
	require( module )
	return rawget( tbl, key )
end

local function autoloading( tbl, map )
	return setmetatable( tbl, { __index = function ( self, key )
		return autoload( map, self, key )
	end } )
end

-- tables the engine makes: stock only ever adds to them (DataSources.X = ...)
for name, map in pairs( index.implicit_tables ) do
	rawset( _G, name, autoloading( {}, map ) )
end

local GLOBAL_TABLES = { CoD = index.cod_files, LUI = index.lui_files }
setmetatable( _G, {
	__index = function ( self, key )
		return autoload( index.global_files, self, key )
	end,
	__newindex = function ( self, key, value )
		if GLOBAL_TABLES[key] and type( value ) == "table" and not getmetatable( value ) then
			autoloading( value, GLOBAL_TABLES[key] )
		end
		rawset( self, key, value )
	end
} )

for _, name in ipairs( config.boot ) do
	boot_require( name )
end
if LUI and LUI.UIElement then
	install_native_methods()
end
emit( { kind = "booted" } )

---------------------------------------------------------------------------------------------------------------------
-- the scan
---------------------------------------------------------------------------------------------------------------------
local report_seen = {}

local function report( stage, target, message, frames )
	frames = frames or {}
	local top
	for _, frame in ipairs( frames ) do
		if frame.target then
			top = frame
			break
		end
	end
	-- nothing of the scanned files on the stack: stock code tripping over a stand-in, or another file of the mod
	if not top then
		emit( { kind = "environment", stage = stage, target = target, message = message } )
		return
	end
	local key = message .. "|" .. ( top and ( top.file .. top.line ) or target )
	if report_seen[key] then
		report_seen[key] = report_seen[key] + 1
		return
	end
	report_seen[key] = 1
	emit( { kind = "finding", stage = stage, target = target, message = message, frames = frames } )
end

-- a pcall can hide a real bug from the game's log and from this scan: note what it catches in scanned files
pcall = function ( fn, ... )
	local args = { n = select( "#", ... ), ... }
	local caught
	local results = { xpcall( function ()
		return fn( unpack( args, 1, args.n ) )
	end, function ( message )
		caught = frames_from( 2 )
		return message
	end ) }
	if not results[1] then
		report( "pcall", "", tostring( results[2] ), caught )
	end
	return unpack( results, 1, table.maxn( results ) )
end

local function module_name( path )
	local rel = string.sub( path, #config.root + 2 )
	return ( string.gsub( string.gsub( rel, "%.lua$", "" ), "[/\\]", "." ) )
end

local function source_of( fn )
	if type( fn ) ~= "function" then
		return nil
	end
	local info = hook_lib.getinfo( fn, "S" )
	if info and string.sub( info.source, 1, 1 ) == "@" then
		return BUILDABLE[normal( string.sub( info.source, 2 ) )]
	end
end

local function fake_menu()
	local ok, menu = pcall( function ()
		return CoD.Menu.NewForUIEditor( "bo3_lua_scan" )
	end )
	if ok and menu then
		return menu
	end
	return LUI.UIElement.new()
end

-- fires every subscription made since `from`, with number data and then with no data
local function fire_subscriptions( target, from, label )
	if not config.fire then
		return
	end
	local last = #subscriptions
	for pass = 1, 2 do
		local value = 1
		if pass == 2 then
			value = nil
		end
		for i = from, last do
			local sub = subscriptions[i]
			if sub and not sub.removed and type( sub.fn ) == "function" and type( sub.model ) == "table" then
				sub.model.value = value
				local ok, message, frames = guarded( sub.fn, sub.model )
				if not ok then
					report( pass == 1 and "callback" or "callback_nil", target, message, frames )
				end
			end
		end
	end
end

local function run_builder( target, label, build )
	local from = #subscriptions + 1
	local ok, result, frames = guarded( build )
	if not ok then
		report( "build", target, result, frames )
	end
	if ok and type( result ) == "table" and result.setModel then
		local fake = child_model( model_root, "bo3scan_widget" )
		local model_ok, message, model_frames = guarded( result.setModel, result, fake, 0 )
		if not model_ok then
			report( "callback", target, message, model_frames )
		end
	end
	fire_subscriptions( target, from, label )
end

-- 1: load each file, the scanned ones first
local to_load = {}
for _, path in ipairs( config.targets ) do
	to_load[#to_load + 1] = path
end
for _, path in ipairs( config.context or {} ) do
	to_load[#to_load + 1] = path
end
for _, path in ipairs( to_load ) do
	local rel_ok = string.sub( normal( path ), 1, #config.root ) == normal( config.root )
	local chunk, err = load_source( path )
	if not chunk then
		if TARGETS[normal( path )] then
			emit( { kind = "finding", stage = "syntax", target = path, message = err, frames = {} } )
		end
	elseif rel_ok and find_module( module_name( path ) ) then
		local ok, message, frames = guarded( require, module_name( path ) )
		if not ok then
			report( "load", path, message, frames )
		end
	else
		local ok, message, frames = guarded( chunk )
		if not ok then
			report( "load", path, message, frames )
		end
	end
end

-- 2: build everything they defined, and fire what it subscribed to
local built = 0
local seen_builders = {}
for name, value in pairs( CoD or {} ) do
	if type( value ) == "table" then
		local new = rawget( value, "new" )
		local target = source_of( new )
		if target and not seen_builders[new] then
			seen_builders[new] = true
			built = built + 1
			run_builder( target, "CoD." .. tostring( name ) .. ".new", function ()
				return new( fake_menu(), 0, 1 )
			end )
		end
	end
end
for name, value in pairs( LUI and LUI.createMenu or {} ) do
	local target = source_of( value )
	if target and not seen_builders[value] then
		seen_builders[value] = true
		built = built + 1
		run_builder( target, "LUI.createMenu." .. tostring( name ), function ()
			return value( 0 )
		end )
	end
end

emit( { kind = "done", built = built, files = #to_load, subscriptions = #subscriptions } )
real_stdout:flush()
real_exit( 0 )
