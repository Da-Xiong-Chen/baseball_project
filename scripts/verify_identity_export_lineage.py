"""Verify original export receipts plus the explicitly checked replay upgrade.

Never rewrite the older receipt to make a changed source tree appear unchanged.
"""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/identity-integration-20261025'

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf8'))

def main():
    stage=OUT/'staging-site/data';upgrade=read(OUT/'verification/replay-actor-upgrade.json')
    parent=OUT/'exports/model-replays.json'
    if upgrade['parent_receipt_sha256']!=digest(parent) or not upgrade['passed']:
        raise ValueError('Replay upgrade lost its original authority')
    if upgrade['current_engine_sha256']!=digest(ROOT/'src/engine.py'):
        raise ValueError('Replay engine changed after verified upgrade')
    checked={};steps=[]
    for receipt in sorted((OUT/'exports').glob('*.json')):
        r=read(receipt)
        if 'files' not in r:continue
        for rel,original in r['files'].items():
            expected=upgrade['files'].get(rel,original) if receipt==parent else original
            if digest(stage/rel)!=expected:raise ValueError('Unexplained changed export: '+rel)
            checked[rel]=expected
        steps.append({'receipt':receipt.name,'sha256':digest(receipt),'original_source_authority':r['authority'],'files':len(r['files'])})
    for key in ('decisions','history_day','timing','calibration'):
        r=read(OUT/'verification'/f'{key}-receipt.json')
        if r.get('passed') is not True:raise ValueError('Numerical verification failed: '+key)
    extras=sorted(p.relative_to(stage).as_posix() for p in stage.rglob('*.json') if p.relative_to(stage).as_posix() not in checked)
    if set(extras)-{'model-evaluation.json'}:raise ValueError('Unaccounted export assets: '+str(extras))
    evaluation=read(stage/'model-evaluation.json')
    if evaluation.get('status')!='evaluated' or evaluation.get('training_version')!=5:raise ValueError('Evaluation incomplete')
    result={'passed':True,'original_receipts':steps,'explicit_upgrade':digest(OUT/'verification/replay-actor-upgrade.json'),
            'checked_json_files':len(checked),'fixed_evaluation_sha256':digest(stage/'model-evaluation.json'),
            'policy':'Original source tokens retained; opening-actor correction independently verified; final values checked by four recomputation receipts.'}
    (OUT/'verification/export-lineage.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('Export lineage verified:',len(set(checked)|{'model-evaluation.json'}),'JSON files')

if __name__=='__main__':main()
