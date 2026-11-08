CoD.TestHavok = {}
CoD.TestHavok.flags = function ( a, b )
	return a & 1 << b > 0, a | b, a >> 1
end
