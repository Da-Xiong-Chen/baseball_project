"""Regression tests for the published 2026 replay API on a raw-free checkout."""
from dataclasses import replace
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
import server
from runtime_config import DEFAULT


class PublishedReplayApiTests(unittest.TestCase):
    def setUp(self):
        self.runtime = replace(DEFAULT, season=2026, data_seasons=(2024, 2025, 2026),
                               cutoff='2027-01-01', history_date='2026-10-04',
                               replay_cutoffs=tuple(f'2026-{month:02d}-01' for month in range(3, 11)))
        self.replay = ROOT / 'docs/data/replay'
        self.pid = '2026-010-a034'

    def replay_api(self, pid, date, decision='pen'):
        pa = pd.DataFrame({'pa_id': [pid], 'date': pd.to_datetime([date])})
        with TemporaryDirectory() as scratch, patch.object(server, 'settings', return_value=self.runtime), \
                patch.object(server.mlmodel, 'path_for', return_value=Path(scratch)/'missing.pkl'), \
                patch.object(server, 'load', return_value=(pa, None, None)), \
                patch.object(server, 'replay_result', side_effect=AssertionError('Unexpected recompute')):
            return server.api('/api/replay', {'pa': [pid], 'decision': [decision]}, None)

    def test_published_game_at_month_cutoff_uses_historical_numbers(self):
        expected = json.loads((self.replay/'day-2026-04-01'/f'{self.pid}.json').read_bytes())
        for decision in ('ph', 'pen'):
            with self.subTest(decision=decision):
                result = self.replay_api(self.pid, '2026-04-01', decision)
                self.assertEqual(result['model_cutoff'], '2026-04-01')
                self.assertEqual(result['ml_cutoff'], '2026-04-01')
                reference = expected[decision] or expected['ph']
                self.assertEqual(result['batch_id'], expected['batch_id'])
                self.assertEqual(result['situation'], reference['situation'])
                self.assertEqual(result['bullpen'], reference['bullpen'])
                self.assertEqual(result['replay_context']['decision'], decision)

    def test_unpublished_day_requires_its_month_weight(self):
        with self.assertRaisesRegex(ValueError, '2026-04-02 尚未發布回放'):
            self.replay_api('2026-011-a000', '2026-04-02')
        with self.assertRaisesRegex(ValueError, '回放類型'):
            self.replay_api(self.pid, '2026-04-01', 'invalid')

    def test_with_a_month_weight_the_api_can_recompute(self):
        date = '2026-04-01'
        pa = pd.DataFrame({'pa_id': [self.pid], 'date': pd.to_datetime([date])})
        with TemporaryDirectory() as scratch:
            weight = Path(scratch)/'configured.pkl'
            weight.touch()
            with patch.object(server, 'settings', return_value=self.runtime), \
                    patch.object(server.mlmodel, 'path_for', return_value=weight), \
                    patch.object(server, 'load', return_value=(pa, None, None)), \
                    patch.object(server, 'replay_result', return_value={'recomputed': True}) as raw:
                self.assertEqual(server.api('/api/replay', {'pa':[self.pid], 'decision':['pen']}, None),
                                 {'recomputed': True})
                raw.assert_called_once_with(self.pid, 'pen')

    def test_changed_batch_payload_is_not_returned(self):
        with TemporaryDirectory() as scratch:
            root = Path(scratch)
            day = root/'day-2026-04-01'
            day.mkdir()
            for name in ('dates.json', 'day-2026-04-01/index.json'):
                (root/name).write_bytes((self.replay/name).read_bytes())
            (day/f'{self.pid}.json').write_text('{}', encoding='utf8')
            with patch.object(server, 'settings', return_value=self.runtime):
                with self.assertRaisesRegex(ValueError, '雜湊驗證'):
                    server.published_replay(self.pid, '2026-04-01', 'ph', root)


if __name__ == '__main__':
    unittest.main()
