"""Prove unchanged simulators and transform every recorded rolling prediction.

With identical simulators, absolute predictions move by -delta(offset), and
relative predictions by -delta(rel_bias). Within-cutoff candidate differences
are invariant. This proof permits reuse of the original full timing population,
but never reuse of old absolute predictions or old evaluation metrics.
"""
from pathlib import Path
import hashlib,json,pickle,sys
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import mlmodel
from load import load

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    out=ROOT/'output/revision-20261021'
    authority=json.loads((out/'training-manifest.json').read_text(encoding='utf8'))
    source=ROOT/'output/closeout/rolling-predictions.csv'
    d=pd.read_csv(source);pa=load()[0];proof=[]
    for row in authority['models']+authority['experiments']:
        oldpath=(ROOT/'models/closeout-candidate' if row['name'].startswith('regularized') else ROOT/'models')/row['name'].replace('_v4','_v3')
        assert sha(oldpath)==row['source_v3_sha256']
        with oldpath.open('rb') as f:old=mlmodel._Unpickler(f).load()
        with (ROOT/'models/revision-20261021'/row['name']).open('rb') as f:new=mlmodel._Unpickler(f).load()
        # Full simulator identity includes trees, tendencies, sample rows and RV.
        assert vars(old.sim).keys()==vars(new.sim).keys()
        fields={}
        for key,value in vars(old.sim).items():
            other=vars(new.sim)[key]
            if key=='models':
                assert value.keys()==other.keys()
                for name,estimator in value.items():
                    assert vars(estimator).keys()==vars(other[name]).keys()
                    for attr,item in vars(estimator).items():
                        assert pickle.dumps(item)==pickle.dumps(vars(other[name])[attr]),(name,attr)
                        fields[f'{key}/{name}/{attr}']=hashlib.sha256(pickle.dumps(item)).hexdigest()
            else:
                assert pickle.dumps(value)==pickle.dumps(other),key
                fields[key]=hashlib.sha256(pickle.dumps(value)).hexdigest()
        simsha=hashlib.sha256(json.dumps(fields,sort_keys=True).encode()).hexdigest()
        rows=list(pa[pa.date<pd.Timestamp(row['cutoff'])][['batter','bhand','pitcher']].drop_duplicates().sample(12,random_state=20261021).itertuples(index=False,name=None))
        delta=new.offset-old.offset;bias=new.rel_bias-old.rel_bias
        a=old.abs_many(rows);b=new.abs_many(rows)
        absolute_error=float(np.max(abs(b-(a-delta))))
        ra=old.rel_many(rows);rb=new.rel_many(rows)
        relative_error=float(np.max(abs(rb-(ra-bias))))
        contrast_error=float(np.max(abs((b-b[0])-(a-a[0]))))
        assert max(absolute_error,relative_error,contrast_error)<1e-12
        month=str(row['cutoff'])[:7];mask=d.month==month
        for column in d.columns:
            if row['name'].startswith('regularized'):
                weight=float(column.split('_w')[1]) if column.startswith('reg_w') else None
            else:
                weight=float(column.split('_w')[1]) if column.startswith('s') and '_w' in column else .5 if column.startswith('sample') else None
            if weight is not None:d.loc[mask,column]-=weight*delta
        proof.append(dict(name=row['name'],simulator_sha256=simsha,offset_shift=delta,relative_bias_shift=bias,
                          absolute_error=absolute_error,relative_error=relative_error,contrast_error=contrast_error,queries=len(rows)))
    d.to_csv(out/'recalibrated-predictions.csv',index=False)
    report=dict(passed=True,batch_id=authority['batch_id'],models=proof,rolling_rows=len(d),
        original_predictions_sha256=sha(source),corrected_predictions_sha256=sha(out/'recalibrated-predictions.csv'),
        timing_reuse_proof='Identical full simulators; common calibration shifts cancel in all within-cutoff candidate differences. No ranking or threshold changes; replay absolute values rebuilt separately.',
        timing_csv_sha256=sha(ROOT/'output/timing_backtest.csv'))
    (out/'calibration-impact.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
