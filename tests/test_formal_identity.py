"""Identity and missing-feature behavior that affects production model meaning."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import identity
from load import _numeric, _resolve_pitch_hands
from ml_compare import features
from model import Model, CELLS


class FormalIdentityTests(unittest.TestCase):
    def test_event_actor_hand_uses_own_dated_evidence_and_not_future(self):
        pa=pd.DataFrame({'date':pd.to_datetime(['2025-04-01','2025-06-01']),
            'pitcher':['oldP','newP'],'phand':['L','R'],'batter':['oldB','newB'],'bhand':['R','L']})
        p=pd.DataFrame({'date':pd.to_datetime(['2025-04-02','2025-04-02']),
            'pitcher':['oldP','newP'],'batter':['oldB','newB'],'phand':[None,None],'bhand':[None,None]})
        _resolve_pitch_hands(pa,p)
        self.assertEqual((p.loc[0,'phand'],p.loc[0,'bhand']),('L','R'))
        self.assertIsNone(p.loc[1,'phand']);self.assertIsNone(p.loc[1,'bhand'])
        self.assertEqual(p.loc[0,'phand_source'],'dated_own_player_evidence')

    def test_source_id_has_no_name_collision_and_rejects_malformed_ids(self):
        for raw in (True,[],None,' '):self.assertIsNone(identity.source_key(raw))
        g={}
        for side,pid in [('away','a'),('home','h')]:
            g[side+'BatterBox']=[{'playerId':pid,'playerName':'同名'}];g[side+'PitcherBox']=[]
        roster=identity.game_rosters(g)
        self.assertEqual(identity.participant_key(roster,'away','batter','同名'),'rebas:CPBL:a')
        self.assertEqual(identity.participant_key(roster,'home','batter','同名'),'rebas:CPBL:h')

    def test_labels_and_compatibility_resolution_are_date_and_team_scoped(self):
        boxes=pd.DataFrame({'date':pd.to_datetime(['2024-01-01','2025-01-01','2024-01-01']),
            'game':['g1','g2','g1'],'name':['rebas:CPBL:a','rebas:CPBL:a','rebas:CPBL:h'],
            'raw_name':['同名','改名','同名'],'team':['A','C','H'],'role':['B','B','B']})
        identity.labels.cache_clear()
        with patch('load.load',return_value=(None,None,boxes)):
            old=identity.labels('2025-01-01');new=identity.labels('2025-01-02')
            self.assertEqual(old['rebas:CPBL:a'],'同名〔A〕');self.assertEqual(new['rebas:CPBL:a'],'改名')
            with self.assertRaises(ValueError):identity.resolve_player('同名','2025-01-01')
            self.assertEqual(identity.resolve_player('同名','2025-01-01',team='A'),'rebas:CPBL:a')
            with self.assertRaises(ValueError):identity.resolve_player('改名','2025-01-01')
        identity.labels.cache_clear()

    def test_invalid_numeric_values_stay_missing(self):
        for value in ('12+','122f',' ',True,'nan',None):self.assertTrue(np.isnan(_numeric(value)))
        self.assertEqual(_numeric('145'),145)

    def test_velocity_imputation_is_independent_of_other_query_rows(self):
        row={'x':1.,'y':2.,'velo':np.nan,'ptype':'UNKNOWN','pitcher':'new',
             'bhand':'L','phand':'R','platoon':'異側','balls':0,'strikes':0,'outs':0,'bases':0}
        table=pd.Series([140.],index=pd.MultiIndex.from_tuples([('trained','FF')]))
        types=pd.Series({'FF':140.});types.attrs['training_global_mean']=139.
        one=pd.DataFrame([row]);mixed=pd.DataFrame([row,{**row,'velo':169.}])
        a=features(one,pd.DataFrame(index=one.index),table,types)
        b=features(mixed,pd.DataFrame(index=mixed.index),table,types)
        self.assertEqual(a.loc[0,'velo'],139.);self.assertEqual(b.loc[0,'velo'],139.)

    def test_unknown_hands_average_supported_scenarios_without_claiming_right(self):
        m=Model.__new__(Model);m.k={'sigma2':1.,'bat':100.}
        zeros=np.zeros(len(CELLS));uniform=np.ones(len(CELLS))/len(CELLS)
        m._lookup_cache={'league':{'同側':np.ones(len(CELLS)),'異側':zeros},'neutral':np.ones(len(CELLS))*.5,
            'bat_all':{},'bat_cell':{},'pit':{},'mix':{},'mix_n':{},'phand':{},
            'league_mix':{(ph,bh):uniform for ph in ('L','R') for bh in ('L','R')}}
        result=m.matchup('B','U','P')
        expected=np.mean([m.matchup('B',bh,'P',_pitch_hand=ph)['per_pa'] for bh in ('L','R') for ph in ('L','R')])
        self.assertAlmostEqual(result['per_pa'],expected)
        self.assertEqual(result['n'],0);self.assertTrue(np.isfinite(result['se_pa']))


if __name__=='__main__':unittest.main()
