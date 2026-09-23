# PyCoD binary model I/O

MIT-licensed PyCoD, copied from the PyCoD directory of the user's
BetterBetterBlenderCOD installation on 2026-09-22. The Python modules and license
are preserved unchanged. Upstream: https://github.com/SE2Dev/PyCoD.

The spline baker constructs static Model/Mesh/Face data directly and calls
WriteFile_Bin(version=6), the same writer used by export_xmodel.py in that add-on.
There is no Blender dependency and no intermediate XMODEL_EXPORT file. Every
written binary is read back to verify geometry, winding, material references,
corner normals, UVs, colors and root weights before installation.
CAST vertices are multiplied by 0.3937007874 before binary serialization;
captured placement origins remain in game inches and generated GDT scale is 1.

The complete package is retained because its shared reader imports the
animation modules even while reading a model. The bundled pure-Python LZ4
fallback works without python-lz4; if python-lz4 is present it compresses the
same XMODEL_BIN payload more compactly.
