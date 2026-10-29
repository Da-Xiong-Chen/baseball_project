"""Broken latest-document targets must block the PR gate."""
from pathlib import Path
import contextlib
import io
import json
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from check_repository import check_links
import run_ci


class RepositoryCheckTests(unittest.TestCase):
    def test_encoded_paths_duplicate_anchors_and_external_links(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'說明.md').write_text('# 最新工作稿\n## A.B\n## A.B\n', encoding='utf8')
            (root/'README.md').write_text('[最新](%E8%AA%AA%E6%98%8E.md#最新工作稿)\n[second](說明.md#ab-1)\n[外部](https://example.org)', encoding='utf8')
            result = check_links(root, ['README.md'])
            self.assertEqual(result['errors'], []); self.assertEqual(result['local_links'], 2)

    def test_missing_file_heading_escape_and_document_are_failures(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'target.md').write_text('# Current', encoding='utf8')
            (root/'README.md').write_text('[a](missing.md)\n[b](target.md#old)\n[c](../outside)', encoding='utf8')
            self.assertEqual(len(check_links(root, ['README.md', 'absent.md'])['errors']), 4)

    def test_examples_in_fenced_code_do_not_become_release_links(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'README.md').write_text('```md\n[sample](not-created.md)\n```\n# Current\n[ok](#current)', encoding='utf8')
            result = check_links(root, ['README.md'])
            self.assertFalse(result['errors']); self.assertEqual(result['local_links'], 1)

    def test_failed_check_blocks_ci_and_restores_existing_fixture(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'tests/fixtures').mkdir(parents=True)
            fixture=root/'tests/fixtures/qa_scenarios.json'; fixture.write_bytes(b'original developer fixture')
            def failure(*args, **kwargs):
                fixture.write_bytes(b'generated test content')
                return SimpleNamespace(returncode=7, stdout=b'failure details must remain visible')
            with patch.object(run_ci,'ROOT',root), patch.object(sys,'argv',['run_ci']), \
                    patch.object(run_ci.subprocess,'run',side_effect=failure) as command, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(run_ci.main(),7)
            self.assertEqual(command.call_count,1)
            self.assertEqual(fixture.read_bytes(),b'original developer fixture')
            self.assertIn('failure details',output.getvalue())
            report=json.loads(next((root/'output/ci-validation').glob('*/summary.json')).read_text())
            self.assertNotIn('passed',report)
            self.assertEqual(report['steps'][0]['exit_code'],7)


if __name__ == '__main__': unittest.main()
