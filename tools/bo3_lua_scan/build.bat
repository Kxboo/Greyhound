@echo off
rem Builds bin\lua51.exe and bin\luac51.exe from vendor\lua51 (Lua 5.1, MIT, see vendor\lua51\COPYRIGHT).
rem Needs Visual Studio's C tools. Only needed if bin\ is missing: the release ships the two exes.
setlocal
set "HERE=%~dp0"
if not defined VCINSTALLDIR (
    call "%ProgramFiles%\Microsoft Visual Studio\18\Community\VC\Auxiliary\Build\vcvars64.bat" >nul 2>nul
)
where cl >nul 2>nul || (echo cl.exe not found: run this from a Visual Studio developer prompt & exit /b 1)
set "OBJ=%TEMP%\bo3_lua_scan_obj"
if not exist "%OBJ%" mkdir "%OBJ%"
if not exist "%HERE%bin" mkdir "%HERE%bin"
pushd "%OBJ%"
del /q *.obj >nul 2>nul
cl /nologo /O2 /MT /c /DLUA_BUILD_AS_EXE "%HERE%vendor\lua51\src\*.c" >nul || (popd & echo compile failed & exit /b 1)
set "CORE=lapi.obj lcode.obj ldebug.obj ldo.obj ldump.obj lfunc.obj lgc.obj llex.obj lmem.obj lobject.obj lopcodes.obj lparser.obj lstate.obj lstring.obj ltable.obj ltm.obj lundump.obj lvm.obj lzio.obj"
set "LIBS=lauxlib.obj lbaselib.obj ldblib.obj liolib.obj lmathlib.obj loadlib.obj loslib.obj lstrlib.obj ltablib.obj linit.obj"
link /nologo /OUT:"%HERE%bin\lua51.exe" lua.obj %CORE% %LIBS% >nul || (popd & echo link failed & exit /b 1)
link /nologo /OUT:"%HERE%bin\luac51.exe" luac.obj print.obj %CORE% %LIBS% >nul || (popd & echo link failed & exit /b 1)
popd
echo built bin\lua51.exe and bin\luac51.exe
