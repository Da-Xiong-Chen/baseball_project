import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import load as data
import engine
import fatigue
import roster
import mlmodel


class DecisionDateTests(unittest.TestCase):
    def test_future_changes_do_not_change_training_labels(self):
        frames = data.load()
        data.pitches_before.cache_clear()
        baseline = data.pitches_before('2025-05-01')['rv'].to_numpy().copy()
        altered = frames[1].copy()
        future = altered['date'] >= pd.Timestamp('2025-05-01')
        altered.loc[future, ['runs_to_end', 'runs', 'rv']] = 999
        # The full-data rv column must not enter the training labels either.
        altered['rv'] = -777
        data.pitches_before.cache_clear()
        with patch.object(data, 'load', return_value=(frames[0], altered, frames[2])):
            np.testing.assert_allclose(data.pitches_before('2025-05-01')['rv'], baseline, equal_nan=True)
        data.pitches_before.cache_clear()

    def test_hands_pools_and_fatigue_ignore_future_rows(self):
        frames = data.load()
        cutoff = '2025-05-01'
        engine._hands.cache_clear(); roster.hitter_pool.cache_clear(); roster.reliever_pool.cache_clear(); fatigue.starter_curve.cache_clear()
        before = (engine._hands(cutoff), roster.hitter_pool(cutoff), roster.reliever_pool(cutoff), fatigue.starter_curve(cutoff))
        pa, p, boxes = [f.copy() for f in frames]
        pa.loc[pa.date >= cutoff, ['bhand','phand']] = 'X'
        boxes.loc[boxes.date >= cutoff, ['name','role']] = ['FUTURE','P']
        changed = (pa,p,boxes)
        engine._hands.cache_clear(); roster.hitter_pool.cache_clear(); roster.reliever_pool.cache_clear(); fatigue.starter_curve.cache_clear()
        with patch.object(engine,'load',return_value=changed), patch.object(roster,'load',return_value=changed), patch.object(fatigue,'load',return_value=changed):
            after = (engine._hands(cutoff), roster.hitter_pool(cutoff), roster.reliever_pool(cutoff), fatigue.starter_curve(cutoff))
        for a,b in zip(before[0],after[0]): pd.testing.assert_series_equal(a,b)
        self.assertEqual(before[1:],after[1:])
        engine._hands.cache_clear(); roster.hitter_pool.cache_clear(); roster.reliever_pool.cache_clear(); fatigue.starter_curve.cache_clear()

    def test_current_season_fielding_file_is_never_read_in_replay(self):
        roster.position_games.cache_clear()
        with patch.object(roster.pd,'read_csv', wraps=pd.read_csv) as read:
            roster.position_games('2025-09-27')
            self.assertTrue(all('positions_2025' not in str(c.args[0]) for c in read.call_args_list))

    def test_missing_fielding_is_unknown_not_crash(self):
        roster.position_games.cache_clear()
        with patch.object(roster.os.path,'exists',return_value=False):
            self.assertEqual(roster.positions_of('unknown','2025-08-01'),{})
            self.assertFalse(roster.can_play('unknown','SS','2025-08-01'))
        roster.position_games.cache_clear()

    def test_roster_does_not_read_players_who_only_appear_later_today(self):
        boxes = pd.DataFrame([dict(team='A',name='FUTURE',role='B',date=pd.Timestamp('2025-05-01'),game='g',order=1,PA=4)])
        with patch.object(roster,'load',return_value=(None,None,boxes)):
            self.assertEqual(roster.active_roster('A',pd.Timestamp('2025-05-01'),'g'),([],[]))

    def test_out_of_season_model_never_uses_later_month(self):
        for day in ['2024-12-31','2026-06-01']:
            with self.assertRaises(ValueError): mlmodel.for_date(day)
        self.assertIsNone(engine.value_score(1,[]))

if __name__ == '__main__': unittest.main()
