import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from identity import normalize_game


class IdentityTests(unittest.TestCase):
    def test_same_name_different_team_ids_remain_distinct_in_pa_and_events(self):
        game={'awayTeam':'樂天桃猿','homeTeam':'統一7-ELEVEn獅',
              'awayPitcherBox':[{'playerName':'林子崴','playerId':'yhCr'}],
              'homePitcherBox':[{'playerName':'林子崴','playerId':'gdEku'}],
              'awayPAList':[{'pitcherName':'林子崴','batterName':'B','events':[{'pitcherName':'林子崴'}]}],
              'homePAList':[{'pitcherName':'林子崴','batterName':'H','events':[]}]}
        normalize_game(game)
        self.assertEqual(game['awayPAList'][0]['pitcherName'],'林子崴〔統一〕')
        self.assertEqual(game['homePAList'][0]['pitcherName'],'林子崴〔樂天〕')
        self.assertEqual(game['awayPAList'][0]['events'][0]['pitcherName'],'林子崴〔統一〕')
        self.assertEqual(normalize_game(game),game)
