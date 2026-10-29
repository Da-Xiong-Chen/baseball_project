import sys,json,tempfile,unittest,hashlib
from pathlib import Path
sys.path[:0]=[str(Path(__file__).resolve().parents[1]/'scripts'),str(Path(__file__).parent)]
from stage_season_update import stage
from test_season_intake import game

class IncrementalTests(unittest.TestCase):
    def setup_inputs(self,tmp):
        p=Path(tmp);a=p/'base';b=p/'incoming'
        for root in (a,b):(root/'2025').mkdir(parents=True)
        (a/'2025/old.json').write_text(json.dumps(game()),encoding='utf8')
        return p,a,b
    def test_idempotent_content_and_no_removed_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,a,b=self.setup_inputs(tmp)
            (b/'2025/new.json').write_text(json.dumps(game(2)),encoding='utf8')
            x=stage(a,b,p/'v1',[2025]);y=stage(p/'v1/rebas',b,p/'v2',[2025])
            self.assertEqual(x['dataset_id'],y['dataset_id']);self.assertEqual(len(x['source_manifest']),2)
            self.assertFalse(x['models_validated'])
            with self.assertRaises(ValueError):stage(a,b,p/'v1',[2025])
    def test_correction_requires_acceptance_and_keeps_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,a,b=self.setup_inputs(tmp);g=game();g['homeTeam']='C'
            (b/'2025/change.json').write_text(json.dumps(g),encoding='utf8')
            before=(a/'2025/old.json').read_bytes()
            with self.assertRaises(ValueError):stage(a,b,p/'rejected',[2025])
            r=stage(a,b,p/'accepted',[2025],True)
            self.assertEqual(len(r['changes']['corrected']),1);self.assertEqual((a/'2025/old.json').read_bytes(),before)
    def test_missing_season_and_duplicate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,a,b=self.setup_inputs(tmp)
            with self.assertRaises(ValueError):stage(a,b,p/'missing',[2025,2026])
            (b/'2025/1.json').write_text(json.dumps(game(2)),encoding='utf8')
            (b/'2025/2.json').write_text(json.dumps(game(2)),encoding='utf8')
            with self.assertRaises(ValueError):stage(a,b,p/'duplicate',[2025])

    def test_unknown_event_actor_cannot_pass_a_valid_pa(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,a,b=self.setup_inputs(tmp);g=game(2)
            g['awayPAList'][0]['events'][0]['pitcherName']='unknown'
            (b/'2025/new.json').write_text(json.dumps(g),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'event pitcher'):stage(a,b,p/'bad',[2025])
            self.assertFalse((p/'bad').exists())
            g['awayPAList'][0]['events'][0]['pitcherName']=''
            (b/'2025/new.json').write_text(json.dumps(g),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'event pitcher'):stage(a,b,p/'blank',[2025])

    def test_measurement_exception_is_bound_to_exact_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,a,b=self.setup_inputs(tmp);g=game(2);g['awayPAList'][0]['events'][0]['velocity']='invalid'
            file=b/'2025/new.json';file.write_text(json.dumps(g),encoding='utf8')
            accepted=[{'file':'2025/002.json','sha256':hashlib.sha256(file.read_bytes()).hexdigest(),'issue':'invalid_pitch_velocity'}]
            r=stage(a,b,p/'ok',[2025],accepted=accepted);self.assertTrue(r['raw_values_unchanged'])
            g['homeTeam']='D';file.write_text(json.dumps(g),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'audit failed'):stage(a,b,p/'bad',[2025],accepted=accepted)

    def test_interrupted_build_and_live_lock_are_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            p,a,b=self.setup_inputs(tmp);(p/'out.building').mkdir()
            with self.assertRaises(FileExistsError):stage(a,b,p/'out',[2025])
            (p/'locked.lock').write_text('existing')
            with self.assertRaises(FileExistsError):stage(a,b,p/'locked',[2025])
            self.assertEqual((p/'locked.lock').read_text(),'existing')

if __name__=='__main__':unittest.main()
