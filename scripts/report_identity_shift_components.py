"""Explain inspected v4/v5 examples from saved, separately computed components.

This is a component audit, not a causal ablation or a performance claim.
"""
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/identity-integration-20261025'

def main():
    paths=[OUT/f'shift-components-v{v}.json' for v in (4,5)]
    before,after=[json.loads(p.read_text(encoding='utf8'))['results'] for p in paths]
    ids={r['incumbent'] for r in after};observations={i:{} for i in ids}
    for file in sorted((ROOT/'data/rebas').glob('*/*.json')):
        game=json.loads(file.read_text(encoding='utf8'))
        for side in ('home','away'):
            for p in game[side+'PitcherBox']:
                key='rebas:CPBL:'+p.get('playerId','')
                if key in ids:observations[key].setdefault(p['playerName'],[]).append(game['date'])
    rows=[]
    for old,new in zip(before,after):
        if old['pa_id']!=new['pa_id']:raise ValueError('Different observations')
        a,b=old['bullpen'][0],new['bullpen'][0]
        components={k:{'v4':a[k],'v5':b[k],'delta':b[k]-a[k]} for k in ('階層式','機器學習','疲勞調整','預估失分')}
        expected=.5*(components['階層式']['delta']+components['機器學習']['delta'])+components['疲勞調整']['delta']
        residual=expected-components['預估失分']['delta']
        if abs(residual)>1e-12:raise ValueError('Unexplained component residual')
        aliases={n:{'first':min(ds),'last':max(ds),'games':len(ds)} for n,ds in observations[new['incumbent']].items()}
        reason=('未知投手手別改為雙側平均；舊版缺手別不再被當成同／異側對戰。' if not new['inc_hand'] else
                '同一來源 ID 的跨年異名合併；逐球傾向、個人歷史球抽樣與重新訓練的樹會改變。' if len(aliases)>1 else
                '逐球實際參與者修正：打席開始打者與完成打席打者分開，不能提前使用打席中才上場者。')
        rows.append({'pa_id':new['pa_id'],'pitcher_id':new['incumbent'],'source_aliases':aliases,
                     'opening_batter_before':old['due'],'opening_batter_after':new['due'],
                     'pitch_count_unchanged':old['pitch_count']==new['pitch_count'],
                     'run_to_win_unchanged':old['slope']==new['slope'],
                     'components':components,'reconstruction_residual':residual,'explanation':reason})
    report={'passed':True,'scope':'Four inspected large-change examples; not a causal attribution of every changed rank.',
            'inputs':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},'examples':rows,
            'interpretation':'Identity/event corrections justify changed inputs. Re-training and sampling contribute jointly; no isolated improvement is claimed.'}
    (OUT/'verification/decision-shift-components.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print('Component reconstruction passed:',len(rows))

if __name__=='__main__':main()
