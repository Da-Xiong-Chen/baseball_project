"""Export optional dated defensive rearrangements; never alter rankings or timing markers."""
import argparse,json,sys,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src')]
from engine import situation
from roster import fielding_rearrangement
from batch_contract import metadata

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);a=ap.parse_args()
    day=ROOT/'docs/data/replay/day-2025-09-20';index=json.loads((day/'index.json').read_text(encoding='utf8'))
    plans={};counts={'unknown_pas':0,'unknown_late_pas':0,'pas_with_plan':0,'late_pas_with_plan':0,'candidate_plans':0}
    for pid,name in index['files'].items():
        payload=json.loads((day/name).read_text(encoding='utf8'));r=payload['ph']
        if any(c['守備'] in ['ok','warn'] for c in r['candidates'] if c['角色']=='代打'):continue
        s=situation(pid);late=int(s['row']['inning'])>=6;counts['unknown_pas']+=1;counts['unknown_late_pas']+=int(late)
        choices={}
        for c in r['candidates']:
            if c['角色']!='代打' or c['守備']!='unknown':continue
            plan=fielding_rearrangement(s['positions'],s['due'],c['球員'],'2025-09-20')
            if plan:choices[c['球員']]=plan
        if choices:
            plans[pid]=choices;counts['pas_with_plan']+=1;counts['late_pas_with_plan']+=int(late);counts['candidate_plans']+=len(choices)
    result=dict(schema_version=1,**metadata(),date='2025-09-20',status='conditional_only',
                source='2023–2024 ldkrsi fielding history; cutoff-safe catcher pitch history',
                replay_index_sha256=hashlib.sha256((day/'index.json').read_bytes()).hexdigest(),counts=counts,plans=plans)
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(counts))
if __name__=='__main__':main()
