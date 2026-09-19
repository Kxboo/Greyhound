
import sys as _tool_sys
from pathlib import Path as _ToolPath
REPO_ROOT = next(p for p in _ToolPath(__file__).resolve().parents if (p / "build-greyhound.ps1").is_file())
TOOLS_ROOT = REPO_ROOT / "tools"
_tool_sys.path.insert(0, str(TOOLS_ROOT))
import tool_bootstrap as _tool_bootstrap
_tool_bootstrap.activate(TOOLS_ROOT / "tool_bootstrap.py")
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    'placement_organizer', REPO_ROOT /
    'tools/cold_war/capture/organize_cw_placements.py')
organizer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(organizer)


class PlacementOrganizationTests(unittest.TestCase):
    def fixture(self, root):
        source = root / 'run_01'
        source.mkdir()
        (source / 'fx_anm_catalog.json').write_text(json.dumps({
            'map_hash': '0x123', 'files': ['static_models.json', 'extra.json']}))
        (source / 'static_models.json').write_text(json.dumps([{
            'Name': 'test', 'Properties': {'file': 'static_models.json'},
            'SourcePlacementFile': 'static_models.json'}]))
        (source / 'extra.json').write_text('{}')
        (source / 'diagnostics').mkdir()
        (source / 'diagnostics/raw.json').write_bytes(b'{ "file": "static_models.json" }\n')
        (source / 'diagnostics/raw.bin').write_bytes(bytes(range(256)))
        return source

    def inventory(self, root):
        return {p.relative_to(root).as_posix(): p.read_bytes()
                for p in root.rglob('*') if p.is_file()}

    def test_copy_preserves_source_and_rewrites_only_public_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = self.fixture(root)
            before = self.inventory(source)
            catalog = organizer.organize(source, root / 'organized')
            organizer.verify(root / 'organized', catalog)
            self.assertEqual(self.inventory(source), before)
            output = json.loads((root / 'organized/models/static.json').read_text())
            self.assertEqual(output[0]['SourcePlacementFile'], 'models/static.json')
            self.assertEqual(output[0]['Properties']['file'], 'static_models.json')
            self.assertEqual((root / 'organized/diagnostics/raw.json').read_bytes(),
                             before['diagnostics/raw.json'])
            metadata = json.loads((root / 'organized/metadata/fx_anm_catalog.json').read_text())
            self.assertEqual(metadata['files'], ['models/static.json', 'metadata/extra.json'])

    def test_in_place_has_one_run_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = self.fixture(root)
            catalog = organizer.organize_in_place(source)
            self.assertEqual(list(root.iterdir()), [source])
            self.assertFalse((source / 'static_models.json').exists())
            self.assertTrue((source / 'models/static.json').is_file())
            self.assertEqual(organizer.organize_in_place(source), catalog)

    def test_malformed_json_leaves_original_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = self.fixture(root)
            (source / 'extra.json').write_text('{')
            before = self.inventory(source)
            with self.assertRaises(json.JSONDecodeError): organizer.organize_in_place(source)
            self.assertEqual(self.inventory(source), before)
            self.assertEqual(list(root.iterdir()), [source])

    def test_publish_failure_rolls_back_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = self.fixture(root)
            before = self.inventory(source); rename = Path.rename
            def fail_publish(path, target):
                if path.name == 'organized': raise OSError('simulated rename failure')
                return rename(path, target)
            with patch.object(Path, 'rename', fail_publish):
                with self.assertRaises(OSError): organizer.organize_in_place(source)
            self.assertEqual(self.inventory(source), before)
            self.assertEqual(list(root.iterdir()), [source])

    def test_collision_is_rejected_before_output_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = self.fixture(root)
            (source / 'models').mkdir()
            (source / 'models/static.json').write_text('[]')
            with self.assertRaisesRegex(ValueError, 'collision'):
                organizer.organize(source, root / 'output')
            self.assertFalse((root / 'output').exists())

    def test_mutating_source_aborts_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); source = self.fixture(root); verify = organizer.verify
            def change_source(directory, catalog):
                verify(directory, catalog)
                (source / 'extra.json').write_text('{"new": true}')
            with patch.object(organizer, 'verify', change_source):
                with self.assertRaisesRegex(ValueError, 'Source changed'):
                    organizer.organize_in_place(source)
            self.assertTrue((source / 'static_models.json').exists())
            self.assertFalse((source / 'catalog.json').exists())


if __name__ == '__main__': unittest.main()
