from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import source_registry


class SourceRegistryTests(unittest.TestCase):
    def run_registry(self,frames,boxes,cutoff):
        with tempfile.TemporaryDirectory(dir=ROOT/'output') as temp:
            root=Path(temp)
            for rel,rows in frames.items():
                path=root/rel;path.parent.mkdir(parents=True,exist_ok=True)
                pd.DataFrame(rows,columns=['ID','Name','Team Name','POS','G']).to_csv(path,index=False)
            b=pd.DataFrame(boxes,columns=['name','raw_name','team','date']);b.date=pd.to_datetime(b.date)
            source_registry.fielding_registry.cache_clear()
            with patch.object(source_registry,'DATA',root),patch.object(source_registry,'load',return_value=(None,None,b)):
                result=source_registry.fielding_registry(cutoff)
            source_registry.fielding_registry.cache_clear();return result

    def test_literal_ids_in_different_sources_never_join_by_themselves(self):
        frames={'ldkrsi/fieldings_2024.csv':[['42','A','Ta','SS',10]],'cpbl/positions_2025.csv':[['42','B','Tb','C',20]]}
        boxes=[['rebas:CPBL:a','A','Ta','2024-04-01'],['rebas:CPBL:b','B','Tb','2025-04-01']]
        positions,report=self.run_registry(frames,boxes,'2026-01-01')
        self.assertEqual(positions[('rebas:CPBL:a','SS')],7)
        self.assertEqual(positions[('rebas:CPBL:b','C')],20)
        self.assertEqual({row['source_namespace'] for row in report['links']},{'ldkrsi','cpbl'})

    def test_future_evidence_and_same_year_full_season_are_not_used(self):
        frames={'ldkrsi/fieldings_2023.csv':[['1','A','Ta','SS',10]],'cpbl/positions_2025.csv':[['2','B','Tb','C',20]]}
        boxes=[['rebas:CPBL:a','A','Ta','2024-12-01'],['rebas:CPBL:b','B','Tb','2025-01-01']]
        positions,report=self.run_registry(frames,boxes,'2024-06-01')
        self.assertTrue(positions.empty)
        self.assertEqual(report['links'][0]['status'],'unmatched')
        self.assertEqual(set(report['source_hashes']),{'ldkrsi:2023'})

    def test_same_name_team_ambiguity_stays_unresolved(self):
        frames={'ldkrsi/fieldings_2024.csv':[['1','A','Ta','SS',10]]}
        boxes=[['rebas:CPBL:a','A','Ta','2024-04-01'],['rebas:CPBL:b','A','Ta','2024-04-01']]
        positions,report=self.run_registry(frames,boxes,'2025-01-01')
        self.assertTrue(positions.empty);self.assertEqual(report['links'][0]['status'],'ambiguous')

    def test_conflicting_identity_under_one_provider_key_does_not_merge_people(self):
        frames={'ldkrsi/fieldings_2024.csv':[['1','A','Ta','SS',10],['1','B','Tb','C',20]]}
        boxes=[['rebas:CPBL:a','A','Ta','2024-04-01'],['rebas:CPBL:b','B','Tb','2024-04-01']]
        positions,report=self.run_registry(frames,boxes,'2025-01-01')
        self.assertTrue(positions.empty);self.assertTrue(all(row['status']=='ambiguous' for row in report['links']))


if __name__=='__main__':unittest.main()
