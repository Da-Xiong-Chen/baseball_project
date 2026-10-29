"""Export dated identity display helpers from the audited formal loader."""
import json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from source_registry import fielding_registry
from batch_contract import metadata
from export_player_numbers import build

def main():
    out=Path(os.environ.get('BASEBALL_STATIC_OUT',ROOT/'docs/data'));out.mkdir(parents=True,exist_ok=True)
    _,audit=fielding_registry('2026-01-01')
    players={}
    for row in audit['links']:
        if row['source_namespace']=='cpbl' and row['player_key'] and row['source_id'].isdigit() and len(row['source_id'])==10:
            players.setdefault(row['player_key'],set()).add(row['source_id'])
    values={'cpbl-players.json':dict(source='https://www.cpbl.com.tw/team/person',
        policy=audit['policy'],players={k:sorted(v) for k,v in players.items()},**metadata()),
        'player-numbers-2025.json':dict(build(ROOT/'data/rebas/2025'),**metadata())}
    for name,data in values.items():
        (out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print('Exported identity-keyed official links and jersey numbers',flush=True)

if __name__=='__main__':main()
