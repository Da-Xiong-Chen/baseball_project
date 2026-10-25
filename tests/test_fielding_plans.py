import os
import sys,unittest,json,hashlib
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from roster import FIELD_POS,fielding_rearrangement

class FieldingPlanTests(unittest.TestCase):
    def setUp(self):
        self.positions={p:p for p in FIELD_POS+['DH']}
        self.allowed={(p,p) for p in FIELD_POS}|{('1B','3B'),('New','1B')}
    def test_requires_a_complete_evidence_based_assignment_and_preserves_dh(self):
        with patch('roster.can_play',side_effect=lambda n,p,d:(n,p) in self.allowed) as check:
            plan=fielding_rearrangement(self.positions,'3B','New','2025-09-20')
            self.assertEqual(plan['incoming_position'],'1B');self.assertEqual(plan['retained_dh'],'DH')
            self.assertEqual(plan['moves'],[dict(player='1B',from_position='1B',to_position='3B')])
            self.assertTrue(plan['requires_confirmation'])
            self.assertTrue(all(c.args[2]=='2025-09-20' for c in check.call_args_list))
    def test_no_plan_when_any_slot_unverified_or_dh_would_need_to_field(self):
        for allowed in [self.allowed-{('C','C')},{('DH','3B'),('New','DH')}]:
            with patch('roster.can_play',side_effect=lambda n,p,d:(n,p) in allowed):
                self.assertIsNone(fielding_rearrangement(self.positions,'3B','New','2025-09-20'))
    def test_rejects_incomplete_duplicate_positions_existing_player_and_missing_cutoff(self):
        self.assertIsNone(fielding_rearrangement({'A':'CF'},'A','New','2025-09-20'))
        self.assertIsNone(fielding_rearrangement(self.positions,'3B','1B','2025-09-20'))
        self.assertIsNone(fielding_rearrangement(self.positions,'DH','New','2025-09-20'))
        self.assertIsNone(fielding_rearrangement(self.positions,'3B','New',None))
    def test_exported_plans_reproduce_from_prior_evidence_without_changing_eligibility(self):
        root=Path(__file__).resolve().parents[1]
        from engine import situation
        data=json.loads((Path(os.environ.get('BASEBALL_STATIC_OUT',root/'docs/data'))/'fielding-plans-2025-09-20.json').read_text(encoding='utf8'))
        day=Path(os.environ.get('BASEBALL_STATIC_OUT',root/'docs/data'))/'replay/day-2025-09-20';index=json.loads((day/'index.json').read_text(encoding='utf8'))
        self.assertEqual(hashlib.sha256((day/'index.json').read_bytes()).hexdigest(),data['replay_index_sha256'])
        self.assertEqual(len(data['plans']),data['counts']['pas_with_plan']);self.assertGreater(len(data['plans']),0)
        for pid,choices in data['plans'].items():
            s=situation(pid);r=json.loads((day/index['files'][pid]).read_text(encoding='utf8'))['ph']
            for name,p in choices.items():
                self.assertEqual(p,fielding_rearrangement(s['positions'],s['due'],name,'2025-09-20'))
                self.assertEqual(next(x for x in r['candidates'] if x['球員']==name)['守備'],'unknown')

if __name__=='__main__':unittest.main()
