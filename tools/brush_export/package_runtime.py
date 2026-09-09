"""Build the portable brush_export folder beside Greyhound from local Python dependencies.
Developer packaging step only. End users need neither Python nor pip installed.
"""
import argparse,hashlib,importlib,json,shutil,sys
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--destination',required=True,type=Path);a=p.parse_args()
    # Fail before touching the installed bundle if the developer interpreter
    # lacks the dependencies needed to package a complete matching runtime.
    modules={name:importlib.import_module(name) for name in ('numpy','scipy')}
    source=Path(__file__).resolve().parent;dest=a.destination.resolve();dest.mkdir(parents=True,exist_ok=True)
    for name in ('pipeline','export_brushes.py','tool_materials.gdt','bo3_reference.json'):
        s=source/name;d=dest/name
        if s.is_dir():shutil.copytree(s,d,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
        else:shutil.copy2(s,d)
    runtime=dest/'runtime';runtime.mkdir(exist_ok=True);base=Path(sys.base_prefix)
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
    files={str(f.relative_to(dest)).replace('\\','/'):hashlib.sha256(f.read_bytes()).hexdigest() for f in dest.rglob('*') if f.is_file() and 'runtime' not in f.relative_to(dest).parts and '__pycache__' not in f.parts and f.name!='manifest.json'}
    (dest/'manifest.json').write_text(json.dumps(dict(version=1,python=sys.version.split()[0],dependencies=versions,files=files),indent=2))
    print(json.dumps(dict(destination=str(dest),dependencies=versions,files=len(files))))

if __name__=='__main__':main()
