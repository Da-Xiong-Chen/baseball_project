"""Release checks fail for broken project paths and stale exported indexes."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('prepare_site', Path(__file__).resolve().parents[1] / 'scripts/prepare_site.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseSiteTest(unittest.TestCase):
    def test_project_subpath_accepts_query_and_rejects_root_and_escape(self):
        with tempfile.TemporaryDirectory() as folder:
            site = Path(folder) / 'site'
            site.mkdir()
            (site / 'app.js').write_text('')
            (Path(folder) / 'private.txt').write_text('private')
            self.assertEqual(release.local_asset(site, 'app.js?v=2'), site / 'app.js')
            for url in ['/app.js', '../private.txt', '%2e%2e/private.txt', 'missing.js']:
                with self.assertRaises(ValueError, msg=url):
                    release.local_asset(site, url)
            self.assertIsNone(release.local_asset(site, 'https://example.org/source'))
            self.assertIsNone(release.local_asset(site, 'data:image/svg+xml,svg'))

    def test_actual_release_is_complete_and_excludes_qa_and_raw_inputs(self):
        files = release.inspect_site(release.ROOT / 'docs')
        relative = {p.relative_to(release.ROOT / 'docs').as_posix() for p in files}
        self.assertIn('licenses/ldkrsi-MIT.txt', relative)
        self.assertIn('data/model.json', relative)
        self.assertIn('data/replay/games.json', relative)
        self.assertFalse(any(p.startswith('qa/') or p.endswith(('.csv', '.pkl')) for p in relative))

    def test_missing_index_reference_and_duplicate_id_block_release(self):
        with tempfile.TemporaryDirectory() as folder:
            site = Path(folder)
            (site / 'data/replay').mkdir(parents=True)
            (site / 'data/pitch-change/2025').mkdir(parents=True)
            (site / '.nojekyll').touch()
            (site / 'index.html').write_text('<main id="main"></main>')
            (site / 'data/replay/games.json').write_text('[{"game":"2025-1"}]')
            with self.assertRaisesRegex(ValueError, '2025-1'):
                release.inspect_site(site)
            (site / 'data/replay/2025-1.json').write_text('{}')
            index = site / 'data/pitch-change/2025/index.json'
            index.write_text('{"pitchers":{"P":"missing.json"}}')
            with self.assertRaisesRegex(ValueError, 'missing.json'):
                release.inspect_site(site)
            index.write_text('{"pitchers":{}}')
            (site / 'data/bad.json').write_text('{"score":NaN}')
            with self.assertRaisesRegex(ValueError, 'Invalid JSON number'):
                release.inspect_site(site)
            (site / 'data/bad.json').write_text('{}')
            (site / 'index.html').write_text('<main id="main"><div id="main"></div></main>')
            with self.assertRaisesRegex(ValueError, 'Duplicate HTML IDs'):
                release.inspect_site(site)

    def test_existing_output_is_never_overwritten(self):
        with self.assertRaisesRegex(ValueError, 'already exists'):
            release.prepare(release.ROOT / 'docs', release.ROOT / 'output/qa')
        with self.assertRaisesRegex(ValueError, 'subdirectory'):
            release.prepare(release.ROOT / 'docs', release.ROOT / 'docs')
