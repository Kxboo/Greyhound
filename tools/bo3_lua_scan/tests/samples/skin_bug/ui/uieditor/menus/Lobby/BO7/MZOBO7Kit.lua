-- MZO BO7 menus: shared kit. Builds a generated layout (MZOBO7LobbyLayout.lua and its parts) into a menu and gives
-- every BO7-style screen the same hover / click / page / scroll / text helpers, plus the COMING SOON overlay for
-- features that aren't in the mod yet (the design stays, the overlay says it's not live). Hand-written.

CoD.MZOBO7Kit = CoD.MZOBO7Kit or {}
local K = CoD.MZOBO7Kit

K.FONTS = {
	R = "fonts/hyperspace_race_regular.otf",
	B = "fonts/hyperspace_race_bold.otf",
	K = "fonts/hyperspace_race_heavy.otf",
	C = "fonts/kairos_sans_w1g_cn.ttf",
	CM = "fonts/kairos_sans_w1g_cn_medium.ttf",
	CB = "fonts/kairos_sans_w1g_cn_bold.ttf",
	M = "fonts/vinmonopro_medium.otf",
	N = "fonts/notosans_semicondensedmedium.ttf"
}
K.CYAN = 0x62d5f1
K.BLUE = 0x4aa3e0
K.WHITE = 0xe8ecef
K.YELLOW = 0xf2d43c

function K.report( msg )
	pcall( function ()
		require( "ui.util.MZO_DllPaths" ).log_mark( "BO7 " .. tostring( msg ) )
	end )
end

-- ms clock for timing marks (the same one the lobby's "slow" marks use)
function K.now()
	local ok, t = pcall( Engine.milliseconds )
	return ok and t or 0
end

function K.rgbOf( c )
	return math.floor( c / 65536 ) % 256 / 255, math.floor( c / 256 ) % 256 / 255, c % 256 / 255
end

function K.setRGB( e, c )
	if e then
		e:setRGB( K.rgbOf( c ) )
	end
end

-- the layout parts named in CoD.MZOBO7Layout[index], joined in order (cached: the tables are data only)
K.joined = K.joined or {}
function K.layout( index )
	if K.joined[index] then
		return K.joined[index]
	end
	local all = {}
	local names = CoD.MZOBO7Layout and CoD.MZOBO7Layout[index] or {}
	for i = 1, #names do
		local part = CoD.MZOBO7Layout[names[i]] or {}
		for j = 1, #part do
			all[#all + 1] = part[j]
		end
	end
	K.joined[index] = all
	return all
end

-- builds a layout into parent. Returns els[id] -> element (each with .mzoD = its layout entry and .bo7alpha),
-- hovers[hitId] -> { elements shown while that hit is hovered }, groups[id] -> clipped list entry (its children sit
-- in els[id .. "_inner"], which scrolls), pages[pg] = { el = one full-screen element per page, hits = its hit
-- areas }, and hits = every hit area in build order. Hit areas are added last so they're on top.
function K.build( parent, layout )
	local t0 = K.now()
	local els, hovers, hitDefs, groups, pages, hits = {}, {}, {}, {}, {}, {}
	local function parentOf( d )
		if d.grp then
			return els[d.grp .. "_inner"]
		end
		if not d.pg then
			return parent
		end
		local pg = pages[d.pg]
		if not pg then
			local el = LUI.UIElement.new()
			el:setLeftRight( true, true, 0, 0 )
			el:setTopBottom( true, true, 0, 0 )
			parent:addElement( el )
			pg = { el = el, hits = {} }
			pages[d.pg] = pg
		end
		return pg.el
	end
	for i = 1, #layout do
		local d = layout[i]
		local e
		if d.k == "grp" then
			local box = LUI.UIElement.new()
			box:setLeftRight( true, false, d.l, d.r )
			box:setTopBottom( true, false, d.t, d.b )
			pcall( function ()
				box:setUseStencil( true )
			end )
			local inner = LUI.UIElement.new()
			inner:setLeftRight( true, false, 0, d.r - d.l )
			inner:setTopBottom( true, false, 0, d.ch )
			box:addElement( inner )
			parentOf( d ):addElement( box )
			els[d.id] = box
			els[d.id .. "_inner"] = inner
			groups[d.id] = d
		elseif d.k == "hit" then
			hitDefs[#hitDefs + 1] = d
		elseif d.k == "img" then
			e = LUI.UIImage.new()
			if d.img then
				e:setImage( RegisterImage( d.img ) )
			end
		elseif d.k == "txt" then
			e = LUI.UIText.new()
			e:setTTF( K.FONTS[d.f] or K.FONTS.R )
			if d.al == 1 then
				e:setAlignment( Enum.LUIAlignment.LUI_ALIGNMENT_CENTER )
			elseif d.al == 2 then
				e:setAlignment( Enum.LUIAlignment.LUI_ALIGNMENT_RIGHT )
			else
				e:setAlignment( Enum.LUIAlignment.LUI_ALIGNMENT_LEFT )
			end
			e:setText( d.text )
		end
		if e then
			e:setLeftRight( true, false, d.l, d.r )
			e:setTopBottom( true, false, d.t, d.b )
			if d.rgb then
				e:setRGB( K.rgbOf( d.rgb ) )
			end
			e.mzoD = d
			e.bo7alpha = d.a or 1
			e:setAlpha( d.hidden and 0 or e.bo7alpha )
			pcall( e.setHandleMouse, e, false )
			parentOf( d ):addElement( e )
			els[d.id] = e
			if d.hover then
				hovers[d.hover] = hovers[d.hover] or {}
				table.insert( hovers[d.hover], e )
			end
		end
	end
	for i = 1, #hitDefs do
		local d = hitDefs[i]
		local e = LUI.UIElement.new()
		e:setLeftRight( true, false, d.l, d.r )
		e:setTopBottom( true, false, d.t, d.b )
		e.mzoD = d
		parentOf( d ):addElement( e )
		els[d.id] = e
		hits[#hits + 1] = e
		if d.pg and pages[d.pg] then
			table.insert( pages[d.pg].hits, e )
		end
	end
	K.buildMs = ( K.buildMs or 0 ) + K.now() - t0
	K.buildCount = ( K.buildCount or 0 ) + #layout
	return els, hovers, groups, pages, hits
end

local function mouse( e, on )
	pcall( e.setHandleMouse, e, on )
end
K.mouse = mouse

-- shows page `name` (nil = none) out of the page ids in `ids` and hides the rest of that set; hidden pages' hit
-- areas stop taking the mouse (K.hit turns them on, so call this after wiring). A hit switched off with K.enable
-- stays off.
function K.showPage( pages, name, ids )
	for i = 1, #ids do
		local p = pages[ids[i]]
		if p then
			local on = ids[i] == name
			p.el:setAlpha( on and 1 or 0 )
			p.shown = on
			for h = 1, #p.hits do
				mouse( p.hits[h], on and not p.hits[h].mzoOff )
			end
		end
	end
end

-- a hit area on / off (off: no mouse, its hover look dropped) without touching its page
function K.enable( els, hovers, id, on )
	local e = els[id]
	if not e then
		return
	end
	e.mzoOff = not on
	mouse( e, on )
	local list = hovers[id]
	if list and not on then
		for i = 1, #list do
			list[i]:setAlpha( 0 )
		end
	end
end

-- shows / hides elements by id (their own alpha when shown); hit areas among them follow (K.enable)
function K.setShown( els, hovers, ids, on )
	for i = 1, #ids do
		local e = els[ids[i]]
		if e then
			if e.mzoD and e.mzoD.k == "hit" then
				K.enable( els, hovers, ids[i], on )
			else
				e:setAlpha( on and e.bo7alpha or 0 )
			end
		end
	end
end

-- ids of the layout entries starting with prefix: the always-shown ones (no hover, not hidden) and hit areas
function K.ids( layout, prefix )
	local out = {}
	local n = string.len( prefix )
	for i = 1, #layout do
		local d = layout[i]
		if string.sub( d.id, 1, n ) == prefix and not d.hover and not d.hidden and d.k ~= "grp" then
			out[#out + 1] = d.id
		end
	end
	return out
end

-- every layout id starting with prefix (hover and hidden ones too), e.g. to move a whole prompt
function K.allIds( layout, prefix )
	local out = {}
	local n = string.len( prefix )
	for i = 1, #layout do
		if string.sub( layout[i].id, 1, n ) == prefix then
			out[#out + 1] = layout[i].id
		end
	end
	return out
end

-- moves elements dx BO3 units right of where the layout put them
function K.shift( els, ids, dx )
	for i = 1, #ids do
		local e = els[ids[i]]
		if e and e.mzoD and e.mzoD.k ~= "grp" then
			e:setLeftRight( true, false, e.mzoD.l + dx, e.mzoD.r + dx )
		end
	end
end

-- scrolling for a clipped list from K.build: moves its inner element by whole steps and keeps the thumb (an id or
-- a list of ids, its pieces) in step. rows = hit ids inside the list; the ones scrolled out of view stop taking the
-- mouse. Returns scrollBy( steps ), scrollTo( offset ), page() (a page down, back to the top from the end),
-- refresh() and setCount( rows actually filled ).
function K.scroller( els, g, thumbId, rows )
	local inner = els[g.id .. "_inner"]
	local thumbs = {}
	local ids = type( thumbId ) == "table" and thumbId or { thumbId }
	for i = 1, #ids do
		if els[ids[i]] then
			thumbs[#thumbs + 1] = els[ids[i]]
		end
	end
	local vis = g.b - g.t
	local ch = g.ch
	local count = #rows
	local off = 0
	local function maxOff()
		return math.max( 0, ch - vis )
	end
	local function apply()
		pcall( function ()
			inner:beginAnimation( "scroll", 120 )
		end )
		inner:setTopBottom( true, false, -off, ch - off )
		local th = vis >= ch and g.trb - g.trt or ( g.trb - g.trt ) * vis / ch
		local top = g.trt + ( maxOff() > 0 and ( g.trb - g.trt - th ) * off / maxOff() or 0 )
		for i = 1, #thumbs do
			pcall( function ()
				thumbs[i]:beginAnimation( "scroll", 120 )
			end )
			thumbs[i]:setTopBottom( true, false, top, top + th )
		end
		for i = 1, #rows do
			local r = els[rows[i]]
			if r then
				local y = ( i - 1 ) * g.step - off
				mouse( r, i <= count and not r.mzoOff and y > -g.step / 2 and y + g.step < vis + g.step / 2 )
			end
		end
	end
	local function scrollTo( o )
		o = math.max( 0, math.min( maxOff(), o ) )
		if o == off then
			return false
		end
		off = o
		apply()
		return true
	end
	apply()
	return {
		scrollBy = function ( n )
			return scrollTo( off + n * g.step )
		end,
		scrollTo = scrollTo,
		page = function ()
			if off >= maxOff() then
				return scrollTo( 0 )
			end
			return scrollTo( off + math.floor( vis / g.step ) * g.step )
		end,
		refresh = apply,
		setCount = function ( n )
			count = math.max( 0, math.min( #rows, n ) )
			ch = math.max( vis, count * g.step )
			off = math.min( off, maxOff() )
			apply()
		end
	}
end

-- mouse wheel on a whole menu (same binding as the MZO career menus)
function K.onWheel( menu, controller, fn )
	pcall( function ()
		local up, down = Enum.LUIButton.LUI_KEY_PCKEY_0, Enum.LUIButton.LUI_KEY_PCKEY_1
		if Enum.LUIButton.LUI_KEY_PCKEY_MWHEELUP then
			up, down = Enum.LUIButton.LUI_KEY_PCKEY_MWHEELUP, Enum.LUIButton.LUI_KEY_PCKEY_MWHEELDOWN
		end
		menu:AddButtonCallbackFunction( menu, controller, up, "MWHEELUP", function ()
			return fn( -1 )
		end )
		menu:AddButtonCallbackFunction( menu, controller, down, "MWHEELDOWN", function ()
			return fn( 1 )
		end )
	end )
end

-- a keyboard key (BO3 key name, e.g. "G") and optionally a pad button (Enum.LUIButton name, e.g. "LUI_KEY_RB")
-- calling fn() on a whole menu. fn returns false to let the key through (e.g. while the BO7 lobby is hidden).
-- Keys: stock CoD.Menu.AddButtonCallbackFunction runs a key press as a press of the PAD BUTTON it was registered
-- with (HandleButtonPress( menu, controller, button )), and stores nothing under LUI_KEY_NONE, so a keyboard-only
-- key registered that way never fired (every MZO hotkey, 2026-11-03). We watch the same KeyPressBits.<key> model
-- the stock code does and call fn ourselves, with its checks (menu not covered by another, input not disabled).
function K.onKey( menu, controller, key, pad, fn )
	-- the key and the pad button can both come in for one press (PC may also send ENTER / arrows as pad buttons):
	-- run fn once per 120 ms
	local last = -1000
	local function cb()
		local now = 0
		pcall( function ()
			now = Engine.milliseconds()
		end )
		if now > 0 and now - last < 120 then
			return true
		end
		last = now
		local ok, used = pcall( fn )
		return not ok or used ~= false
	end
	local function label()
		return true
	end
	pcall( function ()
		local root = Engine.GetModelForController( controller )
		local bits = Engine.GetModel( root, "KeyPressBits" ) or Engine.CreateModel( root, "KeyPressBits" )
		-- the engine fills KeyPressBits.<key> only for keys that have a model
		local model = Engine.GetModel( bits, key )
		if not model then
			model = Engine.CreateModel( bits, key )
			Engine.SetModelValue( model, 0 )
		end
		menu:subscribeToModel( model, function ( m )
			local value = Engine.GetModelValue( m ) or 0
			if menu.occludedBy or menu.m_disableAllButtonActions
				or not CoD.BitUtility.IsBitwiseAndNonZero( value, Enum.LUIButtonFlags.FLAG_DOWN ) then
				return
			end
			if cb() then
				Engine.SetModelValue( m, 0 )
			end
		end, false )
	end )
	if pad and Enum.LUIButton[pad] then
		pcall( function ()
			menu:AddButtonCallbackFunction( menu, controller, Enum.LUIButton[pad], nil, cb, label, false )
		end )
	end
end

-- BO7's menu sounds (uin_main_*, aliases in share/raw/sound/aliases/_mzo_sounds.csv, wavs in
-- sound_assets/_OwensAssets/_mzo/bo7_ui): hover / select / back / tab / popup / error / pop_open / pop_close / ...
K.SOUND_PREFIX = "mzo_bo7_ui_"
function K.sound( name )
	pcall( Engine.PlaySound, K.SOUND_PREFIX .. name )
end

-- mouse hover / click on a hit area: shows its hover elements, calls onOver( on ) and onClick(); plays BO7's hover
-- sound when the mouse comes onto it and the select sound on a click
function K.hit( els, hovers, id, onClick, onOver )
	local e = els[id]
	if not e then
		return
	end
	local function show( on )
		if on and e.mzoOff then
			return
		end
		if on and not e.mzoHovered and onClick then
			K.sound( "hover" )
		end
		e.mzoHovered = on
		local list = hovers[id]
		if list then
			for i = 1, #list do
				list[i]:setAlpha( on and list[i].bo7alpha or 0 )
			end
		end
		if onOver then
			pcall( onOver, on )
		end
	end
	mouse( e, true )
	-- BO3 drives mouse hover through the element's Over / LoseOver clips (as CoD.MZOCareerUI.attachHoverClips)
	e.currentState = "DefaultState"
	e.clipsPerState = {
		DefaultState = {
			DefaultClip = function ()
				show( false )
			end,
			Over = function ()
				show( true )
			end,
			LoseOver = function ()
				show( false )
			end
		}
	}
	e:registerEventHandler( "mouseenter", function ()
		show( true )
		return false
	end )
	e:registerEventHandler( "mouseleave", function ()
		show( false )
		return false
	end )
	local function click()
		if onClick and not e.mzoOff then
			K.sound( "select" )
			local ok, err = pcall( onClick )
			if not ok then
				K.report( "click " .. tostring( id ) .. ": " .. tostring( err ) )
			end
			return true
		end
		return false
	end
	e:registerEventHandler( "leftmouseup", function ( element, event )
		if event and event.inside then
			return click()
		end
		return false
	end )
	e:registerEventHandler( "button_action", click )
end

-- text ----------------------------------------------------------------------------------------------------------

-- an image by name; MZO's own (i_mtl_) images get the career menus' normal-image material, as the old lobby did
function K.setImage( e, name )
	if not e or not name then
		return
	end
	e:setImage( RegisterImage( name ) )
	if string.sub( name, 1, 6 ) == "i_mtl_" then
		pcall( function ()
			CoD.MZOCareerUI.applyNormalImageMaterial( e )
		end )
	end
end

function K.setText( e, text )
	if e then
		e:setText( tostring( text or "" ) )
	end
end

local function textWidth( e )
	local w = 0
	pcall( function ()
		w = e:getTextWidth() or 0
	end )
	return w
end
K.textWidth = textWidth

-- sets the text and, when it is wider than maxW, shrinks the font (a UIText's size is its height) around the
-- layout line's middle so it fits
function K.fitText( e, text, maxW )
	if not e or not e.mzoD then
		return
	end
	local d = e.mzoD
	e:setTopBottom( true, false, d.t, d.b )
	e:setText( tostring( text or "" ) )
	local w = textWidth( e )
	if maxW and w > maxW and w > 0 then
		local h = ( d.b - d.t ) * maxW / w
		local mid = ( d.t + d.b ) / 2
		e:setTopBottom( true, false, mid - h / 2, mid + h / 2 )
	end
end

-- one line in several colours written into the run pieces <id>_0, _1 ... from the layout (3 or more):
-- parts = { { text, rgb } }, dy = move the line down (BO3 units)
function K.setRuns( els, id, parts, dy )
	local first = els[id .. "_0"]
	if not first or not first.mzoD then
		return
	end
	local x = first.mzoD.l
	dy = dy or 0
	for i = 0, 7 do
		local e = els[id .. "_" .. i]
		if not e then
			break
		end
		if e.mzoD then
			local p = parts[i + 1]
			local d = e.mzoD
			e:setText( p and tostring( p[1] ) or "" )
			if p and p[2] then
				K.setRGB( e, p[2] )
			end
			local w = p and textWidth( e ) or 0
			e:setLeftRight( true, false, x, x + w + 30 )
			e:setTopBottom( true, false, d.t + dy, d.b + dy )
			x = x + w
		end
	end
end

-- right-aligned pieces <id>_0.._n (the last piece ends where the layout's last piece ends)
function K.setRunsRight( els, id, parts )
	local last = els[id .. "_" .. ( #parts - 1 )]
	if not last or not last.mzoD then
		return
	end
	local x = last.mzoD.r
	for i = #parts - 1, 0, -1 do
		local e = els[id .. "_" .. i]
		if e and e.mzoD then
			e:setText( tostring( parts[i + 1][1] ) )
			if parts[i + 1][2] then
				K.setRGB( e, parts[i + 1][2] )
			end
			local w = textWidth( e )
			e:setLeftRight( true, false, x - w - 30, x )
			x = x - w
		end
	end
end

-- splits text into two lines that fit maxW, measured on element e (left as it was). The second line is cut
-- with "..." if the text needs more.
function K.wrap( e, text, maxW )
	text = tostring( text or "" )
	if not e then
		return text, ""
	end
	local before = e.mzoD and e.mzoD.text or ""
	local function fits( s )
		e:setText( s )
		return textWidth( e ) <= maxW
	end
	local words = {}
	for w in string.gmatch( text, "%S+" ) do
		words[#words + 1] = w
	end
	local lines = { "", "" }
	local li = 1
	for i = 1, #words do
		local try = lines[li] == "" and words[i] or lines[li] .. " " .. words[i]
		if fits( try ) or lines[li] == "" then
			lines[li] = try
		elseif li == 1 then
			li = 2
			lines[2] = words[i]
		else
			local cut = lines[2] .. "..."
			while not fits( cut ) and string.len( lines[2] ) > 1 do
				lines[2] = string.sub( lines[2], 1, -2 )
				cut = lines[2] .. "..."
			end
			lines[2] = cut
			break
		end
	end
	e:setText( before )
	return lines[1], lines[2]
end

-- a challenge line as run parts: the first number in the BO7 blue, the rest white
function K.numberParts( line, rgb, numRgb )
	local a, b = string.find( line, "%d[%d,]*" )
	if not a then
		return { { line, rgb } }
	end
	return { { string.sub( line, 1, a - 1 ), rgb }, { string.sub( line, a, b ), numRgb },
		{ string.sub( line, b + 1 ), rgb } }
end

-- progress: a bar element from the layout stretched from its left edge to frac of `full` (BO3 units)
function K.setFill( e, frac, full )
	if not e or not e.mzoD then
		return
	end
	frac = math.max( 0, math.min( 1, tonumber( frac ) or 0 ) )
	e:setLeftRight( true, false, e.mzoD.l, e.mzoD.l + full * frac )
	e:setAlpha( frac > 0 and e.bo7alpha or 0 )
end

-- COMING SOON ---------------------------------------------------------------------------------------------------

local function plain( parent, l, t, r, b, rgb, a, image )
	local e = LUI.UIImage.new()
	e:setLeftRight( true, false, l, r )
	e:setTopBottom( true, false, t, b )
	if image then
		e:setImage( RegisterImage( image ) )
	end
	K.setRGB( e, rgb )
	e:setAlpha( a )
	mouse( e, false )
	parent:addElement( e )
	return e
end

local function label( parent, l, t, r, b, text, font, rgb, align )
	local e = LUI.UIText.new()
	e:setLeftRight( true, false, l, r )
	e:setTopBottom( true, false, t, b )
	e:setTTF( K.FONTS[font] )
	e:setAlignment( align or Enum.LUIAlignment.LUI_ALIGNMENT_CENTER )
	e:setText( text )
	K.setRGB( e, rgb )
	mouse( e, false )
	parent:addElement( e )
	return e
end
K.plain, K.label = plain, label

-- the overlay over a design whose feature isn't in the mod yet (BO3 units, as the layout). style "panel": the
-- design dimmed under BO7's locked-card stripes, COMING SOON in the middle (sub = a line under it); style "tag": a
-- small SOON badge in the top-right corner (tiles, rows). Returns the overlay element (alpha it with its page).
function K.comingSoon( parent, l, t, r, b, style, sub )
	local root = LUI.UIElement.new()
	root:setLeftRight( true, false, 0, 0 )
	root:setTopBottom( true, false, 0, 0 )
	mouse( root, false )
	parent:addElement( root )
	if style == "tag" then
		local w = 40
		plain( root, r - w - 4, t + 4, r - 4, t + 16, 0x07080b, 0.85 )
		plain( root, r - w - 4, t + 4, r - w - 2, t + 16, K.CYAN, 0.9 )
		label( root, r - w, t + 6, r - 6, t + 14, "SOON", "B", K.CYAN )
		return root
	end
	plain( root, l, t, r, b, 0x07080b, 0.72 )
	plain( root, l, t, r, b, 0x2c3138, 0.35, "i_mzo_zmm7_lobby_tok_locked_stripes" )
	local mid = ( t + b ) / 2
	local w = math.min( r - l - 20, 170 )
	local cx = ( l + r ) / 2
	plain( root, cx - w / 2, mid - 17, cx + w / 2, mid + ( sub and 21 or 15 ), 0x11141c, 0.95 )
	plain( root, cx - w / 2, mid - 17, cx - w / 2 + 26, mid - 15, K.CYAN, 0.9 )
	label( root, cx - w / 2, mid - 10, cx + w / 2, mid + 6, "COMING SOON", "K", 0xf0f2f4 )
	if sub then
		label( root, cx - w / 2, mid + 8, cx + w / 2, mid + 17, sub, "C", 0xa8aeb6 )
	end
	return root
end

-- slides a layout element by dy (BO3 units) over ms, snaps back and repeats while on (false stops it at rest).
-- BO7 scrolls tiled patterns with a UV offset; BO3 can't, so a pre-tiled image one pattern step taller than its
-- clip (a kit group) slides one step: the snap back is seamless
function K.slideLoop( e, dy, ms, on )
	if not e or not e.mzoD then
		return
	end
	local d = e.mzoD
	local function rest()
		e:setTopBottom( true, false, d.t, d.b )
	end
	e.mzoSlide = on
	if not e.mzoSlideWired then
		e.mzoSlideWired = true
		e:registerEventHandler( "transition_complete_mzo_slide", function ( element, event )
			rest()
			if element.mzoSlide and not event.interrupted then
				element:beginAnimation( "mzo_slide", element.mzoSlideMs, false, false, CoD.TweenType.Linear )
				element:setTopBottom( true, false, d.t + element.mzoSlideDy, d.b + element.mzoSlideDy )
			end
		end )
	end
	e.mzoSlideDy, e.mzoSlideMs = dy, ms
	if not on then
		e:beginAnimation( "mzo_slide_stop", 1 )
	end
	rest()
	if on then
		e:beginAnimation( "mzo_slide", ms, false, false, CoD.TweenType.Linear )
		e:setTopBottom( true, false, d.t + dy, d.b + dy )
	end
end

-- a short message under the top bar ("WEAPONS: COMING SOON"), fading out after a moment
function K.toast( menu, text )
	if not menu then
		return
	end
	local t = menu.mzoBO7Toast
	if not t then
		t = LUI.UIElement.new()
		t:setLeftRight( true, false, 427, 853 )
		t:setTopBottom( true, false, 82, 106 )
		mouse( t, false )
		local bg = plain( t, 0, 0, 426, 24, 0x161a22, 0.96 )
		local edge = plain( t, 0, 0, 30, 2, K.CYAN, 0.9 )
		t.mzoText = label( t, 10, 6, 416, 18, "", "M", 0xf0f2f4 )
		t.mzoParts = { bg, edge }
		t:setAlpha( 0 )
		menu:addElement( t )
		menu.mzoBO7Toast = t
		t:registerEventHandler( "transition_complete_mzo_toast_hold", function ( element, event )
			if not event.interrupted then
				element:beginAnimation( "mzo_toast_out", 300, false, false, CoD.TweenType.Linear )
				element:setAlpha( 0 )
			end
		end )
	end
	menu:addElement( t )
	t.mzoText:setText( tostring( text or "" ) )
	pcall( function ()
		t:completeAnimation()
	end )
	t:setAlpha( 1 )
	pcall( function ()
		t:beginAnimation( "mzo_toast_hold", 1600, false, false, CoD.TweenType.Linear )
		t:setAlpha( 1 )
	end )
	K.report( "toast: " .. tostring( text ) )
end

-- a click handler that only says the feature is on its way
function K.soon( menu, what )
	return function ()
		K.toast( menu, Engine.ToUpper( tostring( what ) ) .. ": COMING SOON" )
	end
end

-- menu switches -------------------------------------------------------------------------------------------------
-- BO7's FadeCover (OBAcquisitionSelectBase, OBAcquisitionStashSelect): a black quad fades in over 150 ms (ease in),
-- the content changes under it, it fades out over 200 ms (ease out). Nothing is drawn while Lua builds a menu, so
-- the cover goes up first: the click answers at once and the build's frames are black, not a frozen old menu.
--   K.swap( menu, fn, label, holdMs )  cover, fn() (the switch; synchronous inside as before), reveal. A swap inside
--                                      fn just runs. holdMs = stay black that long after fn (the lobby attaches a
--                                      little after its model changes). false = dropped (a click under the cover)
--   K.nav( menu, fn )                  a click handler for that
--   K.back( menu, controller )         GoBack under the cover
--   K.open( menu, controller, name )   OpenOverlay under the cover
--   K.reveal( menu )                   a switch that has already happened: black now, then the fade out
-- Logged per switch: "BO7 swap <label> <ms> ms, build <ms> ms <n> elements, pipe <n> calls <ms> ms".
K.COVER_MS, K.REVEAL_MS = 150, 200
K.LOBBY_HOLD_MS = 200
local HOLD_MS = 16
local FADE_STUCK_MS = 3000
local fade = {}

local function fadeReset()
	if fade.el then
		pcall( fade.el.close, fade.el )
	end
	fade.el, fade.phase, fade.fn = nil, nil, nil
end

local function fadeReport()
	local stat = fade.stat
	fade.stat = nil
	if not stat then
		return
	end
	local h = CoD.MZOHook
	K.report( "swap " .. tostring( stat.label ) .. " " .. stat.ms .. " ms, build " .. ( K.buildMs or 0 ) .. " ms "
		.. ( K.buildCount or 0 ) .. " elements, pipe " .. ( h and ( h.pipe_n or 0 ) - stat.pipeN or 0 ) .. " calls "
		.. ( h and ( h.pipe_ms or 0 ) - stat.pipeMs or 0 ) .. " ms" )
end

-- stays black for a frame (or holdMs) so the fade out starts on a fresh frame: an animation begun right after a long
-- build would count the build's time as played and show nothing
local function fadeHold( e, ms )
	fade.phase = "hold"
	e:beginAnimation( "mzo_fade_hold", ms or HOLD_MS )
	e:setAlpha( 1 )
end

local function fadeCoverDone( e )
	local fn = fade.fn
	local holdMs = fade.holdMs
	fade.fn, fade.holdMs = nil, nil
	fade.phase = "swap"
	local h = CoD.MZOHook
	K.buildMs, K.buildCount = 0, 0
	local stat = { label = fade.label, pipeN = h and h.pipe_n or 0, pipeMs = h and h.pipe_ms or 0 }
	local t0 = K.now()
	local ok, err = pcall( fn )
	stat.ms = K.now() - t0
	fade.stat = stat
	if not ok then
		K.report( "swap " .. tostring( fade.label ) .. ": " .. tostring( err ) )
	end
	fadeHold( e, holdMs )
end

local function fadeElement( menu )
	if fade.el and fade.el:getParent() then
		return fade.el
	end
	fade.el = nil
	local root = menu
	while root and root:getParent() do
		root = root:getParent()
	end
	-- a menu still being created has no parent yet: the root seen last
	if root and root ~= menu then
		fade.root = root
	end
	if not fade.root then
		return nil
	end
	local e = LUI.UIImage.new()
	e:setLeftRight( true, true, -1280, 1280 )
	e:setTopBottom( true, true, -720, 720 )
	e:setRGB( 0, 0, 0 )
	e:setAlpha( 0 )
	e:setPriority( 1000000 )
	mouse( e, false )
	e:registerEventHandler( "transition_complete_mzo_fade_cover", function ( element, event )
		if not event.interrupted then
			fadeCoverDone( element )
		end
	end )
	e:registerEventHandler( "transition_complete_mzo_fade_hold", function ( element, event )
		if not event.interrupted then
			fade.phase = "reveal"
			element:beginAnimation( "mzo_fade_reveal", K.REVEAL_MS, false, true, CoD.TweenType.Linear )
			element:setAlpha( 0 )
		end
	end )
	e:registerEventHandler( "transition_complete_mzo_fade_reveal", function ( element, event )
		if not event.interrupted then
			fadeReset()
			fadeReport()
		end
	end )
	fade.root:addElement( e )
	fade.el = e
	return e
end

function K.swap( menu, fn, label, holdMs )
	if fade.phase == "swap" then
		fn()
		return true
	end
	if fade.phase == "cover" or fade.phase == "hold" then
		if K.now() - ( fade.t0 or 0 ) < FADE_STUCK_MS then
			return false
		end
		K.report( "fade stuck in " .. fade.phase .. " (" .. tostring( fade.label ) .. "), reset" )
		fadeReset()
	end
	local ok = pcall( function ()
		local e = fadeElement( menu )
		if not e then
			error( "no root" )
		end
		e:beginAnimation( "mzo_fade_cover", K.COVER_MS, true, false, CoD.TweenType.Linear )
		e:setAlpha( 1 )
		fade.phase, fade.fn, fade.holdMs, fade.label = "cover", fn, holdMs, label or ( menu and menu.menuName )
		fade.t0 = K.now()
	end )
	-- no cover possible: the switch must still happen
	if not ok then
		fadeReset()
		fn()
	end
	return true
end

function K.nav( menu, fn, label )
	return function ()
		K.swap( menu, fn, label )
	end
end

function K.back( menu, controller )
	return K.swap( menu, function ()
		GoBack( menu, controller )
	end, "back from " .. tostring( menu and menu.menuName ) )
end

-- fallback() if it can't open
function K.open( menu, controller, name, fallback )
	K.swap( menu, function ()
		local ok, err = pcall( OpenOverlay, menu, name, controller, "", "" )
		if not ok then
			K.report( "open " .. tostring( name ) .. ": " .. tostring( err ) )
			if fallback then
				fallback()
			end
		end
	end, name )
	return true
end

function K.reveal( menu )
	if fade.phase == "cover" or fade.phase == "swap" or fade.phase == "hold" then
		return
	end
	pcall( function ()
		local e = fadeElement( menu )
		if e then
			e:setAlpha( 1 )
			fade.t0 = K.now()
			fadeHold( e )
		end
	end )
end

-- BO7's SOCIAL (MZOBO7Social) over menu; the stock Social_Main if it can't open
function K.openSocial( menu, controller )
	K.swap( menu, function ()
		local ok, opened = pcall( function ()
			require( "ui.uieditor.menus.Lobby.BO7.MZOBO7Social" )
			return CoD.MZOBO7Social.Open( menu, controller )
		end )
		if not ( ok and opened ) then
			K.report( "social open: " .. tostring( opened ) )
			OpenOverlay( menu, "Social_Main", controller, "", "" )
		end
	end, "MZOBO7Social" )
end

-- BO3's VOICE & MUTING options (MZO's voice channels: BO3 has no party / game channels); the PC page on PC
function K.openVoice( menu, controller )
	local name = "StartMenu_Options_Voice"
	pcall( function ()
		if IsPC() then
			name = "StartMenu_Options_Voice_PC"
		end
	end )
	local ok, err = pcall( function ()
		require( "ui.uieditor.menus.StartMenu." .. name )
		OpenPopup( menu, name, controller, "", "" )
	end )
	if not ok then
		K.report( "voice options: " .. tostring( err ) )
		K.toast( menu, "VOICE OPTIONS: COULD NOT OPEN" )
	end
end

-- BO3's calling card picker (the same overlay MZO's career uses)
function K.openCallingCards( menu, controller )
	K.open( menu, controller, "CallingCards", function ()
		K.toast( menu, "CALLING CARDS: COULD NOT OPEN" )
	end )
end

-- SETTINGS > PATCH NOTES (MZOBO7PatchNotes) over menu; a toast if it can't open
function K.openPatchNotes( menu, controller )
	K.swap( menu, function ()
		local ok, opened = pcall( function ()
			require( "ui.uieditor.menus.Lobby.BO7.MZOBO7PatchNotes" )
			return CoD.MZOBO7PatchNotes.Open( menu, controller )
		end )
		if not ( ok and opened ) then
			K.report( "patch notes open: " .. tostring( opened ) )
			K.toast( menu, "PATCH NOTES: COULD NOT OPEN" )
		end
	end, "MZOBO7PatchNotes" )
end

-- swaps menu for the overlay `name` on the same parent (BO7's progression tabs are separate MZO menus: LEVEL UNLOCKS
-- / PRESTIGE / PRESTIGE MASTER), so back still leads to the parent. false = no parent (nothing changed)
function K.switchTo( menu, controller, name )
	local parent = menu and menu.occludedMenu
	if not parent then
		return false
	end
	K.swap( menu, function ()
		GoBack( menu, controller )
		local ok, err = pcall( OpenOverlay, parent, name, controller, "", "" )
		if not ok then
			K.report( "switch to " .. tostring( name ) .. ": " .. tostring( err ) )
		end
	end, name )
	return true
end
