import sys
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import mlmodel
from load import load
from identity import key


class MLIdentityTest(unittest.TestCase):
    def test_cached_queries_match_uncached_and_keep_same_name_ids_separate(self):
        m=mlmodel.get(mlmodel.FULL)
        b=load()[0].iloc[0]
        rows=[(b.batter,b.bhand,'林子崴〔gdEku〕'),(b.batter,b.bhand,'林子崴〔yhCr〕')]
        ids=[(key(n,m.sim.identities['batter']),bh,key(p,m.sim.identities['pitcher'])) for n,bh,p in rows]
        raw=m.sim.values(pd.DataFrame(ids,columns=['batter','bhand','pitcher']))['gbt']-m.offset
        np.testing.assert_allclose(m.abs_many(rows),raw,rtol=0,atol=1e-12)
        np.testing.assert_allclose(m.abs_many([ids[1],ids[0],ids[1]]),raw[[1,0,1]],rtol=0,atol=1e-12)
        self.assertNotIn('林子崴',m.sim.identities['pitcher'])
        self.assertIn(('gdEku','R'),m.sim.own)
        self.assertIn(('yhCr','R'),m.sim.own)
        self.assertEqual(len(m.abs_many([])),0)


if __name__=='__main__':unittest.main()
