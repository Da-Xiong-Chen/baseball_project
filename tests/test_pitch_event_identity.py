"""Pitch descriptions use per-event participants and reject invalid counts."""
import sys,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pitch_change

class PitchEventIdentityTests(unittest.TestCase):
    def tearDown(self):pitch_change.observations.cache_clear()
    def records(self,codes=('B','H')):
        pitches=pd.DataFrame([dict(game='2025-001',date=pd.Timestamp('2025-04-01'),pa_id='x',j=j,
            pitcher=['rebas:CPBL:old','rebas:CPBL:new'][min(j,1)],bhand='L',balls=min(j,3),strikes=0,
            code=code,ptype='FF') for j,code in enumerate(codes)])
        boxes=pd.DataFrame([dict(role='P',game='2025-001',name=name,date=pd.Timestamp('2025-04-01')) for name in pitches.pitcher.unique()])
        with patch('load.load',return_value=(None,pitches,boxes)):
            pitch_change.observations.cache_clear();return pitch_change.observations()
    def test_mid_pa_pitcher_change_keeps_each_actual_pitch(self):
        data=self.records()
        self.assertEqual(data['rebas:CPBL:old'][0]['counts'][0,0],1)
        self.assertEqual(data['rebas:CPBL:new'][0]['counts'][3,0],1)
        self.assertEqual(sum(int(a['counts'].sum()) for group in data.values() for a in group),2)
    def test_fifth_ball_is_not_made_usable_by_clipped_count(self):
        data=self.records(('B',)*5)
        self.assertEqual(sum(int(a['counts'].sum()) for group in data.values() for a in group),0)
        self.assertEqual(sum(a['excluded']['ambiguous_count'] for group in data.values() for a in group),5)
    def test_missing_raw_data_is_reported_before_name_lookup(self):
        with patch('pitch_change.observations',return_value={}),self.assertRaisesRegex(ValueError,'尚未下載 Rebas'):
            pitch_change.pitch_change.__wrapped__('任一投手',2025,'2025-05-01')

if __name__=='__main__':unittest.main()
