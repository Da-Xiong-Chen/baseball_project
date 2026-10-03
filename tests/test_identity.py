import sys
import unittest
from pathlib import Path
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from identity import aliases, game_identity, resolve_game
from load import load
from model import fit
from qualification import annotate


class IdentityTests(unittest.TestCase):
    def test_game_mapping_does_not_guess_same_team_collision(self):
        g = dict(awayBatterBox=[dict(playerName='Same',playerId='A'),dict(playerName='Same',playerId='B')],
                 awayPitcherBox=[],homeBatterBox=[],homePitcherBox=[dict(playerName='Same',playerId='C')])
        identity = game_identity(g)
        self.assertIsNone(resolve_game(identity['away'],'Same'))
        self.assertEqual(resolve_game(identity['home'],'Same'),'C')
        self.assertIsNone(resolve_game(identity['home'],'Missing'))

    def test_id_survives_transfer_and_name_aliases_never_merge(self):
        f = pd.DataFrame(dict(player_id=['A','A','B'], name=['Old','New','New'], team=['T1','T2','T3']))
        self.assertEqual(aliases(f,'player_id','name'), {'Old':'A'})
        self.assertEqual(f.groupby('player_id').size().to_dict(), {'A':2,'B':1})

    def test_real_pitchers_are_separate_in_features_and_mix(self):
        pa,p,boxes = load()
        self.assertFalse(pa[['batter_id','pitcher_id']].isna().any().any())
        m = fit('2025-07-01')
        for player_id in ('gdEku','yhCr'):
            expected = p[(p.date < '2025-07-01') & (p.pitcher_id == player_id) & p.cell.notna()]
            # rv validity may further reduce training depth.
            self.assertGreater(m.pit_all.loc[player_id,'n'],0)
            self.assertLessEqual(m.pit_all.loc[player_id,'n'],len(expected))
            self.assertIn(player_id,m.mix.index.get_level_values(0))
            self.assertEqual(m.identities['pitcher'][f'林子崴〔{player_id}〕'],player_id)
        self.assertNotIn('林子崴',m.identities['pitcher'])
        self.assertNotIn('林子崴',m.pit_all.index)
        self.assertEqual(m.pitch_mix('林子崴','R')[1],0)
        self.assertNotEqual(m.pitch_mix('林子崴〔gdEku〕','R')[1],m.pitch_mix('林子崴〔yhCr〕','R')[1])

    def test_backend_unknown_cutoff_never_uses_future_depth(self):
        r=dict(model_cutoff='2025-04-01',situation={'pitcher':'P'},candidates=[{'球員':'B','角色':'現任'}],
               bullpen={'next':['B'],'rows':[{'投手':'P','角色':'場上'}]})
        depth=dict(policy={'min_pa':1,'min_outs':0,'min_np':1},cutoffs={})
        result=annotate(r,depth)
        self.assertFalse(result['candidates'][0]['可列入排名'])
        self.assertFalse(result['bullpen']['rows'][0]['可列入排名'])


if __name__=='__main__': unittest.main()
