import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from pitch_change import Settings, add_pa, appearance, compare, observations, pitch_change


class PitchChangeTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(recent_games=1, baseline_games=1, min_games=1,
                                 min_pitches=1, min_stratum=1, bootstrap=100)
        self.b = appearance('2025-001', '2025-04-01', 'P')
        self.r = appearance('2025-002', '2025-04-02', 'P')
        # Two count strata with identical within-stratum rates but different mixtures.
        self.b['counts'][0] = [60, 20, 0, 0]
        self.b['counts'][2] = [5, 15, 0, 0]
        self.r['counts'][0] = [15, 5, 0, 0]
        self.r['counts'][2] = [20, 60, 0, 0]

    def result(self, records=None, **kwargs):
        return compare(records or [self.b, self.r], 'P', 2025, '2025-04-03',
                       settings=self.settings, **kwargs)

    def test_composition_is_not_pitch_change(self):
        row = self.result()['rows'][1]
        self.assertAlmostEqual(row['raw'][1]-row['raw'][0], .30)
        self.assertAlmostEqual(row['delta_pp'], 0)
        self.assertEqual(row['interval'], None)  # one-game degenerate resampling

    def test_fixed_baseline_weights(self):
        self.r['counts'][0] = [12, 8, 0, 0]
        self.r['counts'][2] = [16, 64, 0, 0]
        self.assertAlmostEqual(self.result()['rows'][1]['delta_pp'], 13)

    def test_future_data_does_not_change_any_response_field(self):
        future = appearance('2025-003', '2025-04-03', 'P')
        future['counts'][:] = 1000
        self.assertEqual(self.result(), self.result([self.b, self.r, future]))

    def test_windows_selected_before_hand_filter(self):
        future = appearance('2025-003', '2025-04-02', 'P')
        future['counts'][12] = [10, 0, 0, 0]
        d = self.result([self.b, self.r, future], hand='L')
        self.assertEqual(d['windows']['recent']['selected_games'], 1)
        self.assertEqual(d['windows']['recent']['effective_games'], 0)
        self.assertEqual(d['rows'][0]['delta_pp'], None)

    def test_support_coverage_gate(self):
        self.r['counts'][2] = 0
        d = self.result()
        self.assertEqual(d['coverage'][0], .8)
        self.b['counts'][1] = [50, 0, 0, 0]
        self.assertEqual(self.result()['status'], 'insufficient')

    def test_unknown_type_is_counted_and_gated(self):
        self.r['unknown'][0] = 10
        d = self.result()
        self.assertAlmostEqual(d['windows']['recent']['unknown_rate'], 10/110)
        self.assertEqual(d['status'], 'insufficient')

    def test_missing_coordinates_are_usable(self):
        a = appearance('x', '2025-04-01', 'P')
        add_pa(a, dict(batterHand='L', events=[dict(type='PITCH', pitchCode='H', pitchType='FF')]))
        self.assertEqual(a['counts'].sum(), 1)

    def test_impossible_count_rejects_entire_pa(self):
        a = appearance('x', '2025-04-01', 'P')
        add_pa(a, dict(batterHand='L', events=[dict(type='PITCH', pitchCode='B', pitchType='FF')]*5))
        self.assertEqual(a['counts'].sum(), 0)
        self.assertEqual(a['excluded']['ambiguous_count'], 5)

    def test_unknown_hand_is_not_assumed_right(self):
        a = appearance('x', '2025-04-01', 'P')
        add_pa(a, dict(batterHand='S', events=[dict(type='PITCH', pitchCode='H', pitchType='FF')]))
        self.assertEqual(a['counts'].sum(), 0)
        self.assertEqual(a['excluded']['unknown_hand'], 1)

    def test_mid_pa_pitcher_attribution_is_not_guessed(self):
        a = appearance('x', '2025-04-01', 'P')
        add_pa(a, dict(batterHand='L', events=[dict(type='PITCH', pitchCode='H', pitchType='FF', pitcherName='Other')]))
        self.assertEqual(a['counts'].sum(), 0)
        self.assertEqual(a['excluded']['pitcher_mismatch'], 1)

    def test_empty_history_has_nulls_not_zero_estimates(self):
        d = compare([], 'P', 2025, '2025-01-01')
        self.assertEqual(d['status'], 'insufficient')
        self.assertTrue(all(row['adjusted'] == [None, None] for row in d['rows']))
        json.dumps(d, allow_nan=False)

    def test_bootstrap_reproducible_with_real_variation(self):
        records = []
        for i in range(15):
            a = appearance(str(i), f'2025-04-{i+1:02}', 'P')
            a['counts'][0] = [20+i, 40-i, 10, 5]
            records.append(a)
        self.settings = replace(Settings(), min_stratum=1)
        d = compare(records, 'P', 2025, '2025-05-01', settings=self.settings)
        self.assertEqual(d['bootstrap']['valid'], 1000)
        self.assertIsNotNone(d['rows'][0]['interval'])
        self.assertEqual(d, compare(records, 'P', 2025, '2025-05-01', settings=self.settings))

    @unittest.skipUnless((ROOT/'docs/data/pitch-change/2025/index.json').exists(), 'requires exported data')
    def test_export_api_and_date_boundary_parity(self):
        index = json.loads((ROOT/'docs/data/pitch-change/2025/index.json').read_text(encoding='utf8'))
        # An actual pitcher, beginning/middle/end snapshots, and all three hand filters.
        name = next(iter(index['pitchers']))
        file = ROOT/'docs/data/pitch-change/2025'/index['pitchers'][name]
        snapshots = json.loads(file.read_text(encoding='utf8'))['snapshots']
        sys.path.insert(0, str(ROOT))
        from server import api
        for snap in (snapshots[0], snapshots[len(snapshots)//2], snapshots[-1]):
            cutoff = snap['effective_from']
            for hand in ('ALL', 'L', 'R'):
                d = api('/api/pitch-change', dict(pitcher=[name],season=['2025'],cutoff=[cutoff],hand=[hand]),None)
                self.assertEqual(d, snap['hands'][hand])
                self.assertTrue(all(g['date'] < cutoff for w in d['windows'].values() for g in w['games']))


if __name__ == '__main__':
    unittest.main()
