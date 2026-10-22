"""Regression tests for monotone conversion and cutoff-safe training labels."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from model import Model, valid_slope
from mlmodel import training_pitches, MLModel
import mlmodel
from roster import defense_check


class CalibrationTests(unittest.TestCase):
    def test_reference_is_chronological_and_invariant_to_file_order(self):
        rows=pd.DataFrame({'pa_id':['old','away','home','future'],
            'date':pd.to_datetime(['2025-04-01','2025-08-31','2025-08-31','2025-09-01']),
            'game':['g1','g2','g2','g3'],'inning':[9,6,6,1],
            'half':['home','away','home','away'],'seq':[99,20,1,0]})
        expected=['away','home']
        for seed in range(5):
            actual=mlmodel.calibration_reference(rows.sample(frac=1,random_state=seed),'2025-09-01',2)
            self.assertEqual(list(actual.pa_id),expected)
    def test_loading_a_missing_weight_never_silently_trains(self):
        mlmodel.get.cache_clear()
        with patch('mlmodel.os.path.exists',return_value=False),patch('mlmodel.train') as train:
            with self.assertRaisesRegex(FileNotFoundError,'不會自動訓練'):
                mlmodel.get('2025-05-01')
            train.assert_not_called()
        mlmodel.get.cache_clear()
    def test_cached_predictions_preserve_order_duplicates_and_offset(self):
        class Simulator:
            calls=0
            def values(self,q):
                self.calls+=1
                return {'gbt':np.asarray([{'A':1.,'B':2.}[b] for b in q.batter])}
        sim=Simulator();m=MLModel('2025-01-01',sim,.1)
        a=('A','L','P');b=('B','R','P')
        np.testing.assert_allclose(m.abs_many([a,b,a]),[.9,1.9,.9])
        np.testing.assert_allclose(m.abs_many([b,a]),[1.9,.9])
        self.assertEqual(sim.calls,1)
    def test_missing_fielding_is_unknown_not_a_claim_of_illegality(self):
        with patch('roster.can_play',return_value=False):
            status,message=defense_check('Out','SS','In',[],cutoff='2025-09-01')
        self.assertEqual(status,'unknown')
        self.assertIn('需人工確認',message)
    def test_negative_local_uses_parent_without_absolute_value(self):
        self.assertEqual(valid_slope(-.025, .08, .09), .08)
        self.assertEqual(valid_slope(None, np.nan, .09), .09)
        self.assertEqual(valid_slope(0, .08), 0)
        with self.assertRaises(ValueError):
            valid_slope(-1, np.inf, None)

    def test_model_lookup_uses_same_hierarchy(self):
        m = Model.__new__(Model)
        key = ('9', 'away', 1, 6, 1)
        m.slope_fine = pd.Series({key: -.0250555})
        m.slope_coarse = pd.Series({key[:3]: .07})
        m.slope_all = .09
        self.assertEqual(m.run_to_win(9, 'away', 2, 1, 6, 1), .07)

    def test_training_replaces_future_derived_labels(self):
        prepared = pd.DataFrame({'pa_id':['past','future'], 'j':[0,0],
                                 'date':pd.to_datetime(['2025-04-01','2025-06-01']), 'rv':[999,999]})
        labels = pd.DataFrame({'pa_id':['past'], 'j':[0], 'rv':[.123]})
        with patch('mlmodel.pitches_before', return_value=labels) as fetch:
            result = training_pitches(prepared, '2025-05-01')
        fetch.assert_called_once_with('2025-05-01')
        self.assertEqual(result.pa_id.tolist(), ['past'])
        self.assertEqual(result.rv.tolist(), [.123])

    def test_duplicate_labels_fail_instead_of_multiplying_training_rows(self):
        prepared = pd.DataFrame({'pa_id':['past'], 'j':[0], 'date':pd.to_datetime(['2025-04-01'])})
        labels = pd.DataFrame({'pa_id':['past','past'], 'j':[0,0], 'rv':[.1,.2]})
        with patch('mlmodel.pitches_before', return_value=labels), self.assertRaises(pd.errors.MergeError):
            training_pitches(prepared, '2025-05-01')
