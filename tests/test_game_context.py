import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from game_context import observed_pitch_count
import roster
import fatigue


class GameContextTests(unittest.TestCase):
    def test_raw_count_includes_unusable_pitches_but_not_current_or_future_pa(self):
        game={'awayBatterBox':[], 'awayPitcherBox':[], 'homeBatterBox':[],
              'homePitcherBox':[{'playerName':'A','playerId':'a'},{'playerName':'B','playerId':'b'}],
              'awayPAList':[
                  {'pitcherName':'B','events':[{'type':'PITCH','pitcherName':'A','coordY':None},
                                             {'type':'PITCH','pitcherName':'B'}, {'type':'OTHER'}]},
                  {'pitcherName':'A','events':[{'type':'PITCH','pitcherName':'A'}]*10}]}
        self.assertEqual(observed_pitch_count(game,'away',1,'a'),1)
        self.assertEqual(observed_pitch_count(game,'away',1,'b'),1)
        self.assertEqual(observed_pitch_count(game,'away',0,'a'),0)

    def test_same_name_pitcher_ambiguity_is_not_attributed(self):
        game={'awayBatterBox':[], 'awayPitcherBox':[], 'homeBatterBox':[],
              'homePitcherBox':[{'playerName':'A','playerId':'a'},{'playerName':'A','playerId':'b'}],
              'awayPAList':[{'pitcherName':'A','events':[{'type':'PITCH','pitcherName':'A'}]}]}
        self.assertEqual(observed_pitch_count(game,'away',1,'a'),0)

    def test_unknown_positions_are_not_fabricated_except_explicit_dh_assumption(self):
        empty=pd.Series(dtype=float,index=pd.MultiIndex.from_tuples([],names=['name','POS']))
        with patch.object(roster,'position_games',return_value=empty),patch.object(roster,'can_play',return_value=False):
            positions=roster.assign_positions(['A','B','C'],'2025-05-01')
        self.assertLessEqual(len(positions),1)
        self.assertTrue(all(p=='DH' for p in positions.values()))

    def test_unknown_position_requires_confirmation_not_impossibility_claim(self):
        status,message=roster.defense_check('A','UNKNOWN','B',[],'2025-05-01')
        self.assertEqual(status,'warn')
        self.assertIn('守位未知',message)

    def test_fatigue_support_never_turns_unknown_into_fatigue_free(self):
        with patch.object(fatigue,'starter_curve',return_value=[(85,0),(95,.02),(105,.04)]):
            self.assertEqual(fatigue.support(None,True)['status'],'unknown-pitch-count')
            self.assertFalse(fatigue.support(None,True)['before_policy_onset'])
            self.assertEqual(fatigue.support(105,True,3)['status'],'starter-extrapolation')
            self.assertEqual(fatigue.support(30,False)['status'],'reliever-warning-only')
            self.assertFalse(fatigue.support(15,False)['causal_effect_validated'])

    def test_no_high_count_bin_is_different_from_supported_extrapolation(self):
        with patch.object(fatigue,'starter_curve',return_value=[(85,0)]):
            self.assertEqual(fatigue.support(95,True)['status'],'starter-no-supported-high-count-bin')


if __name__=='__main__':unittest.main()
