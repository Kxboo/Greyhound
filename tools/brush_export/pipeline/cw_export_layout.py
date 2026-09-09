"""Publish user-facing prefabs separately from metadata and capture diagnostics."""
import json
import shutil
from pathlib import Path
from cw_collision_names import hash63


def map_name(key, supplied=''):
    candidates = [supplied.replace('\\', '/')] + [
        f'maps/zm/{name}.d3dbsp' for name in
        ('zm_platinum', 'zm_silver', 'zm_gold', 'zm_tungsten')]
    for candidate in candidates:
        if candidate.endswith('.d3dbsp') and hash63(candidate) == key:
            return Path(candidate).stem
    return f'cw_map_{key:016x}'


def publish(staged, destination):
    destination.mkdir(parents=True, exist_ok=True)
    files = list(staged.iterdir())
    # Preflight every target before moving anything; never overwrite an export.
    targets = [(f, destination / f.name if f.suffix == '.map' else
                destination / 'metadata' / f.name) for f in files]
    if (destination / 'README.txt').exists() or any(t.exists() for _, t in targets):
        raise ValueError('Export destination already contains published files')
    (destination / 'metadata').mkdir(exist_ok=True)
    for source, target in targets:
        shutil.move(str(source), str(target))
    report = json.loads((destination / 'metadata/export_report.json').read_text())
    lines = [f"Cold War Radiant export: {report['map']}", '',
             'PREFABS - import only the categories you need:']
    descriptions = {'brushes_clips': 'Clip families, including nosight_noclip, missile/physics/AI and unresolved clip fallbacks',
                    'other_brushes': 'Traversal and other non-clip tools; review before including',
                    'volumes': 'Named volumes', 'triggers': 'Trigger entities'}
    for category, prefab in report['prefabs'].items():
        lines.append(f"  {prefab['file']} - {descriptions.get(category, category)}")
    lines += ['', 'All prefabs use world coordinates. Insert at 0 0 0, rotation 0 0 0, scale 1.',
              'metadata/ - export report, source properties, type assignments and entity data.',
              'diagnostics/ - captured source data, conversion logs and intermediate geometry.',
              'This export does not compile a BO3 map or port gameplay scripts.']
    (destination / 'README.txt').write_text('\n'.join(lines)+'\n', encoding='utf-8')
