import importlib.util
from pathlib import Path
import tempfile
import unittest

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('evaluation_resume',ROOT/'scripts/evaluate_identity_batch.py')
evaluation=importlib.util.module_from_spec(spec);spec.loader.exec_module(evaluation)


class EvaluationResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'output');self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name);self.path=self.folder/'2025-03.csv'
        self.raw=pd.DataFrame({'pa_id':['pa1'],'game':['g1'],'date':pd.to_datetime(['2025-03-30']),
                              'bat_team':['A'],'batter':['B'],'pitcher':['P'],'RE24':[.125]})
        self.frame=pd.DataFrame({'pa_id':['pa1'],'game':['g1'],'date':['2025-03-30'],'month':['2025-03'],
            'team':['A'],'y':[.125],'hierarchy':[.1],'gbt':[.2],'prediction':[.15],'batter':['B'],'pitcher':['P'],
            'alias_actor':[False],'changed_pa_event_actor':[False]})

    def validate(self):
        self.frame.to_csv(self.path,index=False)
        return evaluation.validate_month(self.path,self.raw,evaluation.digest(self.path),set(),set())

    def test_unchanged_checkpoint_is_reusable(self):
        self.assertEqual(self.validate().pa_id.tolist(),['pa1'])

    def test_same_count_wrong_target_is_rejected(self):
        self.frame.loc[0,'y']=.126
        with self.assertRaisesRegex(ValueError,'target differs'):self.validate()

    def test_same_count_wrong_identity_is_rejected(self):
        self.frame.loc[0,'pitcher']='Another'
        with self.assertRaisesRegex(ValueError,'pitcher differs'):self.validate()

    def test_modified_checkpoint_hash_and_false_ensemble_are_rejected(self):
        self.frame.to_csv(self.path,index=False)
        with self.assertRaisesRegex(ValueError,'hash differs'):
            evaluation.validate_month(self.path,self.raw,'not-the-hash',set(),set())
        self.frame.loc[0,'prediction']=.18
        with self.assertRaisesRegex(ValueError,'ensemble differs'):self.validate()

    def test_subgroup_flags_must_match_raw_identity(self):
        self.frame.loc[0,'alias_actor']=True
        with self.assertRaisesRegex(ValueError,'subgroup differs'):self.validate()

    def test_lock_does_not_overwrite_another_evaluation(self):
        lock=self.folder/'evaluation.lock';lock.write_text('existing')
        with self.assertRaises(FileExistsError):
            with evaluation.evaluation_lock(self.folder):pass
        self.assertEqual(lock.read_text(),'existing')


if __name__=='__main__':unittest.main()
