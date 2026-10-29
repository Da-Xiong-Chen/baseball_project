"""Real PA boundaries: a mid-PA replacement is not a pre-PA action."""
import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parents[1]/'src')]
import server,engine,timing_backtest
from historical_actors import at_start,decorate

class OpeningActorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pa=engine.load()[0];cls.rows=decorate(cls.pa);cls.changed=cls.rows[cls.rows.mid_pa_actor_change]
    def test_all_changed_pas_use_opening_actor_without_rewriting_observed_summary(self):
        self.assertGreaterEqual(len(self.changed),24)
        for row in self.changed.itertuples():
            original=self.pa[self.pa.pa_id==row.pa_id].iloc[0];sit=engine.situation(row.pa_id)
            self.assertEqual(sit['row']['pitcher'],row.start_pitcher)
            self.assertEqual(sit['row']['batter'],row.start_batter)
            self.assertEqual(self.pa[self.pa.pa_id==row.pa_id].iloc[0].pitcher,original.pitcher)
            if not original.is_ph:self.assertEqual(sit['due'],row.start_batter)
    def test_mid_pa_pitching_change_is_not_revealed_as_an_initial_switch(self):
        pid='2025-125-a019';source=self.pa[self.pa.pa_id==pid].iloc[0];opening=at_start(source)
        self.assertNotEqual(source.pitcher,opening.pitcher)
        def result(s,m,ml,actual):return dict(actual=actual,situation={'pitcher':s['row']['pitcher']})
        with patch.object(server,'model_for',return_value=None),patch.object(server.mlmodel,'for_date',return_value=None),patch.object(server,'build_result',side_effect=result):
            r=server.replay_result(pid,'ph')
        self.assertEqual(r['actual']['pitcher'],opening.pitcher)
        self.assertEqual(r['actual']['final_pitcher'],source.pitcher)
        self.assertTrue(r['actual']['mid_pa_actor_change'])
    def test_next_pa_incumbent_is_previous_final_pitcher_and_stints_stay_separate(self):
        d=timing_backtest.decision_points();pa=self.pa.sort_values(['game','inning','half','seq'])
        prior=pa.groupby(['game','fld_team']).pitcher.shift();lookup=dict(zip(pa.pa_id,prior))
        self.assertTrue(all(r.inc==lookup[r.pa_id] for r in d.itertuples()))
        for r in d.itertuples():
            self.assertEqual(r.pitcher,r.start_pitcher)
        mixed=d[d.mid_pa_actor_change]
        self.assertGreater(len(mixed),0)
        for r in mixed.itertuples():
            following=d[(d.game==r.game)&(d.fld_team==r.fld_team)&(d.inc==r.final_pitcher)&(d.seq>r.seq)]
            if r.pitcher!=r.final_pitcher and len(following):
                self.assertNotEqual(following.iloc[0].inc_stint_id,r.stint_id)

if __name__=='__main__':unittest.main()
