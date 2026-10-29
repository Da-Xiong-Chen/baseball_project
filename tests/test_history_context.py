import os
import unittest,sys,json
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from export_history_context import build
class HistoryContextTest(unittest.TestCase):
 def test_future_rows_do_not_change_prior_workload(self):
  boxes=pd.DataFrame([dict(game='a',date=pd.Timestamp('2025-09-18'),team='T',name='P',role='P',NP=20,PA=0),dict(game='b',date=pd.Timestamp('2025-09-19'),team='T',name='P',role='P',NP=30,PA=0)])
  pa=pd.DataFrame(columns=['date','pitcher','batter','result']);pa['date']=pd.to_datetime(pa['date']);p=pd.DataFrame(columns=['date','pitcher','whiff']);p['date']=pd.to_datetime(p['date'])
  before=build(pa,p,boxes);future=boxes.iloc[-1].copy();future['game']='future';future['date']=pd.Timestamp('2025-09-20');future['NP']=150
  after=build(pa,p,pd.concat([boxes,pd.DataFrame([future])],ignore_index=True));self.assertEqual(before,after);row=before['teams']['T']['pitchers'][0];self.assertEqual(row['consecutive_days_before'],2);self.assertEqual(row['workload3'],50);self.assertEqual(row['rest_days'],0)
 def test_exported_logs_are_strictly_before_target_day(self):
  data=json.loads((Path(os.environ.get('BASEBALL_STATIC_OUT',ROOT/'docs/data'))/'history-context-2025-09-20.json').read_text(encoding='utf-8'));self.assertEqual(len(data['teams']),6)
  for team in data['teams'].values():
   for row in team['pitchers']+team['hitters']:
    self.assertLess(row['last_date'],data['date']);self.assertTrue(all(x['date']<data['date'] for x in row['log']))
