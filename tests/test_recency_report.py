import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('recency_report',Path(__file__).resolve().parents[1]/'scripts/report_recency_experiment.py')
report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)


class RecencyReportTests(unittest.TestCase):
    def test_cluster_ratio_and_determinism(self):
        # Equal per-pitch gain despite unequal game sizes must stay constant.
        a=report.paired_summary([1,10],[10,100],42,200)
        self.assertEqual(a,report.paired_summary([1,10],[10,100],42,200))
        self.assertAlmostEqual(a['paired_gain_per_10000_pitches'],1000)
        for value in a['game_bootstrap_ci95']:self.assertAlmostEqual(value,1000)

    def test_signed_zero_interval_and_negative_effect(self):
        z=report.paired_summary([0,0],[1,2],1,100)
        self.assertFalse(z['interval_excludes_zero'])
        n=report.paired_summary([-1,-2],[1,2],1,100)
        self.assertLess(n['game_bootstrap_ci95'][1],0)

    def test_malformed_inputs_rejected(self):
        for difference,counts in [([],[]),([1],[0]),([1],[1,2]),([float('nan')],[1])]:
            with self.assertRaises(ValueError):report.paired_summary(difference,counts,1,100)


if __name__=='__main__':unittest.main()
