import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('intake',Path(__file__).resolve().parents[1]/'scripts/audit_season_intake.py')
intake=importlib.util.module_from_spec(spec);spec.loader.exec_module(intake)


def game(seq=1,day='2025-04-01'):
    g=dict(seq=seq,date=day,awayTeam='A',homeTeam='B')
    for side,pid in [('away','a'),('home','b')]:
        player=dict(playerName='同名',playerId=pid)
        g[side+'BatterBox']=[player];g[side+'PitcherBox']=[player]
        g[side+'PAList']=[dict(inning=1,outs=0,bases=0,batterName='同名',pitcherName='同名',
            awayScores=0,homeScores=0,endAwayScores=0,endHomeScores=0,endOuts=1,endBases=0,
            batterHand='L',pitcherHand='R',catcherName='同名',isPH=False,paOrder=1,WPA=0,RE24=0,homeWE=.5,
            events=[dict(type='PITCH',pitchCode='B',pitchType='',coordX='',coordY='',catcherName='同名')])]
    return g


class IntakeTests(unittest.TestCase):
    def run_audit(self,games,seasons=(2025,)):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'2025').mkdir()
            for i,g in enumerate(games):(root/'2025'/f'{i}.json').write_text(json.dumps(g),encoding='utf8')
            return intake.audit(root,seasons)

    def test_separate_game_box_ids_and_report_missing_measurements(self):
        r=self.run_audit([game()]);self.assertTrue(r['structural_passed'])
        self.assertEqual(r['same_name_multiple_ids']['同名'],['a','b'])
        self.assertEqual(r['seasons'][0]['unresolved_pa_names'],{})
        self.assertEqual(r['seasons'][0]['missing_pitch_values']['coordY'],2)
        self.assertFalse(r['model_ready'])

    def test_missing_year_and_duplicate_game_fail_closed(self):
        self.assertFalse(self.run_audit([],seasons=(2026,))['structural_passed'])
        self.assertFalse(self.run_audit([game(),game()])['structural_passed'])

    def test_wrong_year_and_invalid_outs_fail(self):
        self.assertFalse(self.run_audit([game(day='2026-01-01')])['structural_passed'])
        g=game();g['awayPAList'][0]['outs']=3
        self.assertFalse(self.run_audit([g])['structural_passed'])

    def test_ambiguous_same_team_name_needs_review(self):
        g=game();g['awayBatterBox'].append(dict(playerName='同名',playerId='a2'))
        r=self.run_audit([g]);self.assertEqual(r['seasons'][0]['unresolved_pa_names']['batterName'],1)
        self.assertFalse(r['model_ready'])

    def test_invalid_event_and_nonfinite_measurement_rejected(self):
        for event in [None,dict(type='PITCH'),dict(type='PITCH',pitchCode='B',pitchType='FF',coordX='nan',coordY=1,catcherName='同名')]:
            g=game();g['awayPAList'][0]['events']=[event]
            self.assertFalse(self.run_audit([g])['structural_passed'])

    def test_identity_alias_history_keeps_dates(self):
        a=game();b=game(seq=2,day='2025-04-02')
        b['awayBatterBox'][0]=dict(playerName='改名',playerId='a')
        b['awayPitcherBox'][0]=dict(playerName='改名',playerId='a')
        b['awayPAList'][0]['batterName']='改名';b['homePAList'][0]['pitcherName']='改名'
        r=self.run_audit([a,b]);self.assertTrue(r['structural_passed'])
        self.assertEqual(r['identity_registry']['a']['names']['改名']['first_seen'],'2025-04-02')


if __name__=='__main__':unittest.main()
