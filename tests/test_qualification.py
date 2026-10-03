import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from export_qualification import profile


class QualificationTest(unittest.TestCase):
    def test_two_ids_with_the_same_name_are_not_merged_into_personal_depth(self):
        def game(date, identity):
            return dict(date=date,awayBatterBox=[],homeBatterBox=[],homePitcherBox=[],
                        awayPitcherBox=[dict(playerName='Same',playerId=identity,IPOuts=60)])
        games=[game('2025-03-31','A'),game('2025-04-01','B')]
        self.assertEqual(profile(games,'2025-04-01')['pitchers']['Same'][0],60)
        after=profile(games,'2025-04-02')
        self.assertNotIn('Same',after['pitchers'])
        self.assertEqual(after['ambiguous'],['Same'])

    def test_own_counts_cutoff_and_integer_outs(self):
        def game(date, pa, outs):
            return dict(date=date,awayBatterBox=[dict(playerName='A',PA=pa),dict(playerName='B',PA=2)],
                        homeBatterBox=[],awayPitcherBox=[dict(playerName='P',IPOuts=outs)],homePitcherBox=[])
        games=[game('2025-03-31',99,59),game('2025-04-01',1,1)]
        before=profile(games,'2025-04-01')
        self.assertEqual(before['hitters']['A'][0],99)
        self.assertEqual(before['hitters']['B'][0],2)
        self.assertEqual(before['pitchers']['P'][0],59)
        after=profile(games,'2025-04-02')
        self.assertEqual(after['hitters']['A'][0],100)
        self.assertEqual(after['pitchers']['P'][0],60)


if __name__=='__main__': unittest.main()
