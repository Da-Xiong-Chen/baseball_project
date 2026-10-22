"""A simulated interruption must leave the previous local data usable."""
import sys
from pathlib import Path
import tempfile
import unittest
import json,hashlib
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from closeout_batch import ROOT,contract,promote_data
import closeout_batch as batch


class BatchTests(unittest.TestCase):
    def test_mixed_versions_are_rejected(self):
        for r in ({},{'training_version':2,'engine_contract':3},{'training_version':3}):
            with self.assertRaises(ValueError):contract(r,'snapshot')
        contract({'training_version':4,'engine_contract':4,'batch_id':'batch'},'snapshot')
        with self.assertRaisesRegex(ValueError,'Different batch'):
            contract({'training_version':4,'engine_contract':4,'batch_id':'other'},'snapshot','batch')

    def test_interruption_restores_original_and_preserves_stage(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'output') as folder:
            root=Path(folder);old=root/'data';new=root/'stage';backup=root/'backup'
            old.mkdir();new.mkdir();(old/'version').write_text('old');(new/'version').write_text('new')
            with self.assertRaisesRegex(RuntimeError,'Controlled'):
                promote_data(new,old,backup,fail_after_backup=True)
            self.assertEqual((old/'version').read_text(),'old')
            self.assertEqual((new/'version').read_text(),'new')
            self.assertFalse(backup.exists())
            promote_data(new,old,backup)
            self.assertEqual((old/'version').read_text(),'new')
            self.assertEqual((backup/'version').read_text(),'old')


class WholeBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'output')
        self.root=Path(self.temp.name);self.patch=patch.object(batch,'ROOT',self.root);self.patch.start()
        self.validation=patch.object(batch,'validate_data',return_value={'tested_fixture':True});self.validation.start()
        self.stage=self.root/'stage';self.weights=self.root/'candidate';self.weights.mkdir()
        (self.root/'models').mkdir();(self.root/'server.py').write_text('# same source')
        for site,label in [(self.root/'docs','old'),(self.stage,'new')]:
            (site/'data/replay').mkdir(parents=True)
            (site/'.nojekyll').touch();(site/'index.html').write_text('<script src="app.js"></script>')
            (site/'app.js').write_text('// same executable source')
            (site/'data/replay/games.json').write_text('[]')
            (site/'data/snapshot.json').write_text(json.dumps({'value':label,'training_version':4}))
        self.context={'training_version':4,'engine_contract':4,'models':[]}
        for name in ['a_v4.pkl','b_v4.pkl']:
            p=self.weights/name;p.write_bytes(('NEW_'+name).encode())
            self.context['models'].append({'name':name,'sha256':batch.digest(p)})
        self.context['batch_id']=hashlib.sha256(json.dumps(self.context,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        (self.root/'models/a_v4.pkl').write_bytes(b'OLD_A')
        (self.root/'models/active-batch.json').write_text('{"old":true}')
        receipts={}
        for key in ['decisions','history_day','timing','calibration']:
            p=self.root/(key+'.json');p.write_text(json.dumps({'passed':True,'batch_id':self.context['batch_id']}));receipts[key]=p
        batch.seal(self.stage,self.context,self.weights,receipts)

    def tearDown(self):
        self.validation.stop();self.patch.stop();self.temp.cleanup()

    def assert_old(self):
        self.assertEqual(json.loads((self.root/'docs/data/snapshot.json').read_text())['value'],'old')
        self.assertEqual((self.root/'models/a_v4.pkl').read_bytes(),b'OLD_A')
        self.assertFalse((self.root/'models/b_v4.pkl').exists())
        self.assertEqual((self.root/'models/active-batch.json').read_text(),'{"old":true}')
        self.assertFalse((self.root/'output/promotion-journal.json').exists())

    def test_same_version_changed_payload_is_rejected_without_resigning(self):
        manifest=self.stage/'data/batch-manifest.json';before=manifest.read_bytes()
        (self.stage/'data/snapshot.json').write_text('{"value":"changed","training_version":4}')
        with self.assertRaisesRegex(ValueError,'checksum mismatch'):batch.verify_manifest(self.stage,self.weights)
        self.assertEqual(manifest.read_bytes(),before)

    def test_actual_root_weights_and_context_are_checked(self):
        batch.promote_revision(self.stage,self.weights,self.root/'backup')
        (self.root/'models/a_v4.pkl').write_bytes(b'CORRUPTED')
        with self.assertRaisesRegex(ValueError,'Active weight checksum'):
            batch.verify_manifest(self.root/'docs',self.root/'models',active=True)

    def test_copy_failure_restores_site_and_all_weights(self):
        original=batch.shutil.copy2
        def refused(source,target,*args,**kwargs):
            if str(target).endswith('.next'):raise PermissionError('simulated write denied')
            return original(source,target,*args,**kwargs)
        with patch.object(batch.shutil,'copy2',side_effect=refused):
            with self.assertRaises(PermissionError):batch.promote_revision(self.stage,self.weights,self.root/'backup')
        self.assert_old()

    def test_failure_after_install_restores_everything(self):
        def fail(step):
            if step=='site_installed':raise RuntimeError('controlled late failure')
        with self.assertRaisesRegex(RuntimeError,'controlled'):
            batch.promote_revision(self.stage,self.weights,self.root/'backup',hook=fail)
        self.assert_old();self.assertTrue(self.stage.exists())

    def test_unfinished_journal_can_be_recovered_on_next_run(self):
        def interrupted(step):
            if step=='weight:1':raise SystemExit('simulated process death')
        with patch.object(batch,'recover',return_value=False):
            with self.assertRaises(SystemExit):batch.promote_revision(self.stage,self.weights,self.root/'backup',hook=interrupted)
        self.assertTrue((self.root/'output/promotion-journal.json').exists())
        batch.recover();self.assert_old()
