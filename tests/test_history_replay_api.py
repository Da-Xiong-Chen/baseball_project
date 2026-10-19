"""Real-data regression: pitching replay must compare the previous incumbent."""
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
import server


class HistoryReplayTests(unittest.TestCase):
    def test_changed_pitcher_has_two_distinct_decision_contexts(self):
        pa=server.load()[0]
        game=pa[pa.game=='2025-340'].sort_values(['inning','half','seq'])
        previous={}
        for row in game.itertuples():
            old=previous.get(row.fld_team,row.pitcher);previous[row.fld_team]=row.pitcher
            if old!=row.pitcher:
                batting=server.replay_result(row.pa_id,'ph');pitching=server.replay_result(row.pa_id,'pen')
                self.assertEqual(batting['situation']['pitcher'],row.pitcher)
                self.assertEqual(pitching['situation']['pitcher'],old)
                self.assertEqual(pitching['actual']['pitcher'],row.pitcher)
                self.assertTrue(pitching['replay_context']['pitcher_changed'])
                self.assertLessEqual(pitching['ml_cutoff'],pitching['model_cutoff'])
                break
        else:self.fail('Expected at least one real pitching change')

    def test_first_pa_has_no_invented_pitching_change(self):
        result=server.replay_result('2025-340-a000','pen')
        self.assertFalse(result['replay_context']['pitcher_changed'])
        self.assertEqual(result['situation']['pitcher'],result['actual']['pitcher'])

    def test_unknown_pa_and_decision_are_rejected(self):
        with self.assertRaises(ValueError):server.replay_result('2025-340-a000','unknown')
        with self.assertRaises(ValueError):server.replay_result('2025-999-a999','ph')


if __name__=='__main__':unittest.main()
