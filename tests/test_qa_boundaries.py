import sys
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from pitch_change import Settings, appearance, add_pa, compare
from server import validate_evaluation


class BoundaryTests(unittest.TestCase):
    def test_all_count_hand_indices_and_mapping(self):
        a=appearance('x','2025-01-01','P')
        add_pa(a,dict(batterHand='R',events=[dict(type='PITCH',pitchCode=c,pitchType='FF') for c in ['B','B','B','S','S','F','H']]))
        self.assertEqual(a['counts'][23,0],2) # F and H are both thrown at 3-2; the second S is at 3-1.
        self.assertEqual(a['counts'][22,0],1)
        self.assertEqual(a['counts'].sum(),7)

    def test_two_strike_foul_bunt_is_terminal(self):
        a=appearance('x','2025-01-01','P')
        add_pa(a,dict(batterHand='L',events=[dict(type='PITCH',pitchCode=c,pitchType='FF') for c in ['S','S','FOUL_BUNT','H']]))
        self.assertEqual(a['counts'].sum(),0)
        self.assertEqual(a['excluded']['ambiguous_count'],4)

    def test_legal_walk_and_strikeout(self):
        for codes in [['B']*4,['S']*3]:
            a=appearance('x','2025-01-01','P')
            add_pa(a,dict(batterHand='L',events=[dict(type='PITCH',pitchCode=c,pitchType='FF') for c in codes]))
            self.assertEqual(a['counts'].sum(),len(codes))

    def test_settings_reject_invalid_windows(self):
        for kw in [dict(recent_games=0),dict(min_stratum=-1),dict(bootstrap=-1),dict(min_coverage=0),dict(max_unknown=2)]:
            with self.assertRaises(ValueError):Settings(**kw)

    def test_doubleheader_excluded_on_cutoff_and_included_next_day(self):
        games=[appearance(str(i),'2025-04-01','P') for i in range(2)]
        d=compare(games,'P',2025,'2025-04-01')
        self.assertEqual(d['windows']['recent']['selected_games'],0)
        self.assertEqual(compare(games,'P',2025,'2025-04-02')['windows']['recent']['selected_games'],2)

    def test_no_cross_season_fill(self):
        games=[appearance(str(i),'2024-10-01','P') for i in range(20)]
        d=compare(games,'P',2025,'2026-01-01')
        self.assertEqual(d['last_observed'],None)

    def test_support_and_unknown_threshold_boundaries(self):
        b=appearance('a','2025-04-01','P');r=appearance('b','2025-04-02','P')
        s=Settings(recent_games=1,baseline_games=1,min_games=1,min_pitches=1,bootstrap=0)
        for a in (b,r):a['counts'][0,0]=10
        self.assertEqual(compare([b,r],'P',2025,'2025-04-03',settings=s)['status'],'ready')
        r['counts'][0,0]=9
        self.assertEqual(compare([b,r],'P',2025,'2025-04-03',settings=s)['rows'][0]['delta_pp'],None)
        for a in (b,r):a['counts'][0,0]=95;a['unknown'][0]=5
        self.assertEqual(compare([b,r],'P',2025,'2025-04-03',settings=s)['status'],'ready')
        r['unknown'][0]=6
        self.assertEqual(compare([b,r],'P',2025,'2025-04-03',settings=s)['status'],'insufficient')

    def test_missing_bootstrap_support_disables_interval(self):
        games=[]
        for i in range(10):
            a=appearance(str(i),f'2025-04-{i+1:02}','P')
            a['counts'][0,0]=100
            if i in (0,5):a['counts'][1,1]=10
            games.append(a)
        s=Settings(baseline_games=5,min_pitches=1,min_stratum=1,min_coverage=.1)
        d=compare(games,'P',2025,'2025-05-01',settings=s)
        self.assertLess(d['bootstrap']['valid'],900)
        self.assertTrue(all(row['interval'] is None for row in d['rows']))


class InputTests(unittest.TestCase):
    def setUp(self):
        self.body=dict(inning=7,half='home',outs=1,bases=3,bat_score=2,fld_score=3,bat_team='A',fld_team='B',pitcher='P',due='H',due_pos='DH',bench=[])
        self.mock=patch('server.rosters',return_value={'A':{'hitters':[{'name':n} for n in ['H','I','J']], 'pitchers':[]},'B':{'hitters':[],'pitchers':[{'name':'P'}]}})
        self.mock.start();self.addCleanup(self.mock.stop)

    def test_valid_and_empty_bench(self):validate_evaluation(self.body)

    def test_invalid_input_contract(self):
        for kw in [dict(bat_score=-1),dict(outs=3),dict(bases=8),dict(inning=1.5),dict(pitch_count=161),dict(fld_team='A'),dict(bench=['H']),dict(bench=['unknown']),dict(next_batters=['H','H','I']),dict(pitcher='unknown')]:
            with self.subTest(kw=kw), self.assertRaises(ValueError):validate_evaluation({**self.body,**kw})

if __name__=='__main__':unittest.main()
