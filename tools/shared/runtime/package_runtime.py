"""Build the game-organized tools folder beside Greyhound from local Python dependencies.
Developer packaging step only. End users need neither Python nor pip installed.
"""

# Support direct execution and the isolated packaged Python runtime.
import sys as _tool_sys
from pathlib import Path as _ToolPath
TOOLS_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "tool_bootstrap.py").is_file())
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(__file__)
REPO_ROOT = TOOLS_ROOT.parent
import argparse,hashlib,importlib,json,shutil,sys,tempfile
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--destination',required=True,type=Path);a=p.parse_args()
    # Fail before touching the installed bundle if the developer interpreter
    # lacks the dependencies needed to package a complete matching runtime.
    modules={name:importlib.import_module(name) for name in ('numpy','scipy')}
    source=TOOLS_ROOT;dest=a.destination.resolve()
    if dest==source or dest.is_relative_to(source) or source.is_relative_to(dest):
        raise ValueError('Runtime destination must be separate from the source tools tree')
    dest.mkdir(parents=True,exist_ok=True)
    installed=[]
    for name in ('cold_war','black_ops_4','black_ops_3','shared','tool_bootstrap.py'):
        entry=source/name
        for s in ([entry] if entry.is_file() else sorted(entry.rglob('*'))):
            if not s.is_file() or '__pycache__' in s.parts or s.suffix in ('.pyc','.cpp'):continue
            relative=s.relative_to(source);d=dest/relative;d.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(s,d);installed.append(relative.as_posix())
    runtime=dest/'runtime'
    # Upgrade the previous installed layout without duplicating its large Python tree.
    legacy_runtime=dest/'brush_export/runtime'
    if legacy_runtime.is_dir() and not runtime.exists():
        if not legacy_runtime.resolve().is_relative_to(dest):raise ValueError('Runtime link escapes destination')
        legacy_runtime.rename(runtime)
    runtime.mkdir(exist_ok=True);base=Path(sys.base_prefix)
    for pattern in ('python.exe','python3*.dll','vcruntime*.dll','LICENSE*'):
        for f in base.glob(pattern):shutil.copy2(f,runtime/f.name)
    shutil.copytree(base/'DLLs',runtime/'DLLs',dirs_exist_ok=True)
    shutil.copytree(base/'Lib',runtime/'Lib',dirs_exist_ok=True,ignore=shutil.ignore_patterns('site-packages','__pycache__','test','tests','idlelib','tkinter','turtledemo','ensurepip'))
    packages=runtime/'Lib/site-packages';packages.mkdir(parents=True,exist_ok=True)
    versions={}
    for name in ('numpy','scipy'):
        module=modules[name];root=Path(module.__file__).resolve().parent.parent;versions[name]=module.__version__
        for child in root.iterdir():
            if child.name==name or child.name==name+'.libs' or (child.name.startswith(name+'-') and child.name.endswith('.dist-info')):
                shutil.copytree(child,packages/child.name,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','tests'))
    # Isolate the runtime from the user's Python installation and environment.
    (runtime/f'python{sys.version_info.major}{sys.version_info.minor}._pth').write_text('.\nDLLs\nLib\nLib/site-packages\n',encoding='utf-8')
    files={name:hashlib.sha256((dest/name).read_bytes()).hexdigest() for name in sorted(installed)}
    (dest/'manifest.json').write_text(json.dumps(dict(version=2,layout='game-first',python=sys.version.split()[0],dependencies=versions,files=files),indent=2))
    # Preserve legacy/local files outside the active tools tree during upgrades.
    # Only named former tool roots are moved; user captures are never traversed.
    legacy=[dest/name for name in ('brush_export','capture','core','organize_export.py') if (dest/name).exists()]
    archive=None
    if legacy:
        for path in legacy:
            if not path.resolve().is_relative_to(dest):raise ValueError('Legacy tool link escapes destination')
        archive=Path(tempfile.mkdtemp(prefix=dest.name+'-legacy-layout-',dir=dest.parent))
        if not archive.resolve().is_relative_to(dest.parent):raise ValueError('Invalid legacy archive')
        for path in legacy:path.rename(archive/path.name)
    print(json.dumps(dict(destination=str(dest),dependencies=versions,files=len(files),legacy_archive=str(archive) if archive else None)))

if __name__=='__main__':main()
