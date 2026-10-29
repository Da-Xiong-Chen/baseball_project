"""Source drift, clean-checkout preparation and checkpoint reuse contracts."""
from pathlib import Path
from types import SimpleNamespace
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import train_identity_batch as driver
from training_source import create_manifest, verify_source, snapshot, digest


class TrainingSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'output')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        for year in (2024, 2025):
            folder = self.data / 'rebas' / str(year)
            folder.mkdir(parents=True)
            (folder / 'game.json').write_text(json.dumps({'seq': 1, 'date': f'{year}-04-01'}))
        self.manifest = self.root / 'source.json'
        create_manifest(self.data, [2024, 2025], self.manifest)
        self.args = SimpleNamespace(data_root=self.data, source_manifest=self.manifest,
            models=self.root / 'models', reports=self.root / 'reports', dry_run=False,
            resume=True, cutoff='2025-05-01', workers=1, threads=1)

    def checkpoint(self):
        authority, source_id = driver.source_authority(self.args)
        self.args.models.mkdir(); self.args.reports.mkdir()
        driver.atomic_json(self.args.reports / 'training-source.json', {'source_id': source_id, **authority})
        target = self.args.models / driver.name(self.args.cutoff)
        target.write_bytes(b'fixture-only-not-a-trained-model')
        driver.atomic_json(self.args.reports / (target.stem + '.json'), {
            'source_id': source_id, 'sha256': digest(target), 'cutoff': self.args.cutoff,
            'name': target.name, 'training_version': 5, 'engine_contract': 5, 'status': 'complete'})
        return source_id

    def test_modified_added_deleted_or_duplicate_game_rejects_resume_before_any_worker(self):
        for kind in ('modified', 'added', 'deleted', 'duplicate'):
            with self.subTest(kind=kind):
                path = self.data / 'rebas/2025/game.json'
                before = path.read_bytes()
                extra = path.with_name('extra.json')
                if kind == 'modified': path.write_text('{"seq":1,"date":"2025-04-02"}')
                if kind == 'deleted': path.unlink()
                if kind in ('added', 'duplicate'):
                    extra.write_text(json.dumps({'seq': 2 if kind == 'added' else 1, 'date': '2025-04-01'}))
                try:
                    with patch.object(driver.subprocess, 'Popen') as launch:
                        with self.assertRaises(ValueError): driver.controller(self.args)
                        launch.assert_not_called()
                    self.assertFalse(self.args.reports.exists())
                finally:
                    path.write_bytes(before)
                    extra.unlink(missing_ok=True)

    def test_matching_checkpoint_reused_but_new_manifest_cannot_reuse_old_checkpoint(self):
        source_id = self.checkpoint()
        with patch.object(driver.subprocess, 'Popen') as launch, contextlib.redirect_stdout(io.StringIO()):
            driver.controller(self.args)
            launch.assert_not_called()
        state = json.loads((self.args.reports / 'progress.json').read_text())
        self.assertTrue(state['jobs'][self.args.cutoff]['reused'])
        self.assertEqual(state['source_id'], source_id)
        (self.data / 'rebas/2025/game.json').write_text('{"seq":1,"date":"2025-04-02"}')
        self.manifest = self.root / 'new-source.json'
        create_manifest(self.data, [2024, 2025], self.manifest)
        self.args.source_manifest = self.manifest
        with patch.object(driver.subprocess, 'Popen') as launch:
            with self.assertRaisesRegex(ValueError, 'source changed'): driver.controller(self.args)
            launch.assert_not_called()

    def test_snapshot_is_separate_and_source_drift_cannot_mutate_it(self):
        target = snapshot(self.data, self.manifest, [2024, 2025], self.root / 'snapshot')
        original = (target / 'rebas/2025/game.json').read_bytes()
        (self.data / 'rebas/2025/game.json').write_text('{"seq":1,"date":"2025-04-02"}')
        self.assertEqual((target / 'rebas/2025/game.json').read_bytes(), original)
        verify_source(target, self.manifest, [2024, 2025])
        with self.assertRaises(ValueError): snapshot(self.data, self.manifest, [2024, 2025], target)

    def test_clean_checkout_prepare_and_dry_run_never_need_ignored_historical_files(self):
        manifest = self.root / 'cli-source.json'
        base = [sys.executable, '-X', 'utf8', str(ROOT / 'scripts/train_identity_batch.py'), '--data-root', str(self.data),
                '--source-manifest', str(manifest)]
        env = {k: v for k, v in os.environ.items() if k not in ('BASEBALL_RUNTIME_CONFIG', 'BASEBALL_DATA_ROOT')}
        prepare = subprocess.run(base + ['--prepare-source'], cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(prepare.returncode, 0, prepare.stderr)
        dry = subprocess.run(base + ['--dry-run', '--models', str(self.args.models), '--reports', str(self.args.reports)],
            cwd=self.root, env=env, capture_output=True, text=True)
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertEqual(json.loads(dry.stdout)['status'], 'validated_only')
        self.assertFalse(self.args.models.exists()); self.assertFalse(self.args.reports.exists())
        retry = subprocess.run(base + ['--prepare-source'], cwd=self.root, env=env, capture_output=True, text=True)
        self.assertNotEqual(retry.returncode, 0)  # frozen source manifest cannot be overwritten

    def test_worker_snapshot_paths_allowed_but_source_outputs_cannot_overlap(self):
        self.args.data_root = self.args.reports / 'input-snapshot'
        driver.output_paths(self.args, allow_snapshot=True)
        with self.assertRaises(ValueError): driver.output_paths(self.args)
        self.args.data_root = self.data; self.args.models = self.args.reports
        with self.assertRaises(ValueError): driver.output_paths(self.args)


    def test_worker_trains_from_verified_snapshot_and_refuses_changed_inputs(self):
        for mutate in (False, True):
            with self.subTest(mutate=mutate):
                work=self.root/('mutated' if mutate else 'clean');work.mkdir()
                args=SimpleNamespace(**vars(self.args));args.models=work/'models';args.reports=work/'reports'
                args.models.mkdir();args.reports.mkdir()
                authority,sid=driver.source_authority(args)
                frozen=args.reports/'training-input.json';driver.atomic_json(frozen,authority['input'])
                args.data_root=snapshot(self.data,frozen,[2024,2025],args.reports/'input-snapshot')
                args.source_manifest=frozen;args.worker=args.cutoff;args.source_id=sid
                driver.atomic_json(args.reports/'training-source.json',{'source_id':sid,**authority})
                observed=[]
                def train(cutoff):
                    observed.append(os.environ['BASEBALL_DATA_ROOT'])
                    if mutate:(args.data_root/'rebas/2025/game.json').write_text('{"seq":1,"date":"2025-04-02"}')
                    return SimpleNamespace(training_samples={},calibration_reference={})
                with patch.dict(sys.modules,{'mlmodel':SimpleNamespace(train=train)}),patch.dict(os.environ),contextlib.redirect_stdout(io.StringIO()):
                    if mutate:
                        with self.assertRaisesRegex(ValueError,'Training input changed'):driver.worker(args)
                    else:driver.worker(args)
                self.assertEqual(observed,[str(args.data_root)])
                self.assertEqual((args.models/driver.name(args.cutoff)).exists(),not mutate)

    def test_loader_reads_explicit_data_root_in_fresh_process(self):
        env={**os.environ,'BASEBALL_DATA_ROOT':str(self.data)}
        code="import sys;sys.path.insert(0,sys.argv[1]);import load;print(load.DATA)"
        run=subprocess.run([sys.executable,'-X','utf8','-c',code,str(ROOT/'src')],env=env,capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr);self.assertEqual(run.stdout.strip(),str(self.data))

if __name__ == '__main__': unittest.main()
