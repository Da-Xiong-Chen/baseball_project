import json,tempfile,unittest
from pathlib import Path
from scripts.export_player_numbers import build
class NumberExportTests(unittest.TestCase):
 def extract(self,players,date='2025-04-01'):
  with tempfile.TemporaryDirectory() as folder:
   game={'date':date,'homeTeam':'A','awayTeam':'B','homeBatterBox':players,'homePitcherBox':[],'awayBatterBox':[],'awayPitcherBox':[]}
   Path(folder,'game.json').write_text(json.dumps(game),encoding='utf-8')
   return build(Path(folder))
 def player(self,name,number,pid=1): return {'playerName':name,'playerNumber':number,'playerId':pid}
 def test_zero_strings(self):
  self.assertEqual(self.extract([self.player('Zero','0'),self.player('Double','00',2)])['teams']['A'],{'Double':'00','Zero':'0'})
 def test_conflict_excluded(self):
  data=self.extract([self.player('Same','1'),self.player('Same','2')]);self.assertEqual(data['teams'],{});self.assertEqual(len(data['excluded']),1)
 def test_identity_excluded(self):
  self.assertEqual(len(self.extract([self.player('Same','1',1),self.player('Same','1',2)])['excluded']),1)
 def test_other_season_rejected(self):
  with self.assertRaises(ValueError): self.extract([],date='2024-04-01')
 def test_missing_number_rejected(self):
  with self.assertRaises(ValueError): self.extract([self.player('Missing',None)])
