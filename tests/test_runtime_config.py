import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from runtime_config import Runtime,DEFAULT,check_model_runtime
from unittest.mock import patch

class RuntimeTests(unittest.TestCase):
    def test_default_and_exclusive_model_boundary(self):
        self.assertEqual(DEFAULT.month_for('2025-09-20'),'2025-09-01')
        self.assertEqual(DEFAULT.assets()['day_index'],'data/replay/day-2025-09-20/index.json')
        for day in ('2024-09-20','2025-02-28','2026-01-01'):
            with self.assertRaises(ValueError):DEFAULT.month_for(day)
    def test_invalid_configuration(self):
        for kwargs in ({'data_seasons':(2025,2024)},{'season':2026},{'history_date':'2026-09-20'},
                       {'cutoff':'2025-09-01'},{'replay_cutoffs':('2025-03-02',)},
                       {'data_seasons':(True,2025)}):
            with self.assertRaises(ValueError):Runtime(**kwargs)
    def test_alternate_year_cannot_use_default_weights(self):
        other=Runtime(data_seasons=(2024,),season=2024,cutoff='2025-01-01',history_date='2024-09-20',
                      replay_cutoffs=('2024-06-01','2024-09-01'))
        with patch('runtime_config.settings',return_value=other):
            with self.assertRaises(ValueError):check_model_runtime({})
            check_model_runtime({'runtime_id':other.runtime_id})
        check_model_runtime({})
        self.assertNotEqual(DEFAULT.runtime_id,other.runtime_id)

if __name__=='__main__':unittest.main()
