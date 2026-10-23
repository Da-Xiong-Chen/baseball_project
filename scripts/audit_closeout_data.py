"""Read-only input-quality and provenance audit for a reproducible local run."""
from pathlib import Path
import hashlib
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from load import load, _game_files
from identity import IDENTITIES


def main():
    pa,p,boxes=load()
    fatal=[]
    if pa.pa_id.duplicated().any():fatal.append('duplicate_pa_id')
    if p.duplicated(['pa_id','j']).any():fatal.append('duplicate_pitch_key')
    if not p.pa_id.isin(pa.pa_id).all():fatal.append('orphan_pitch')
    if not pa.outs.between(0,2).all():fatal.append('illegal_pa_outs')
    if not pa.bases.between(0,7).all():fatal.append('illegal_bases')
    if not (pa[['bat_score','fld_score']].ge(0).all().all()):fatal.append('negative_score')
    inputs={}
    for file in [*map(Path,_game_files()),*sorted((ROOT/'data/ldkrsi').glob('*.csv')),*sorted((ROOT/'data/cpbl').glob('*.csv'))]:
        inputs[file.relative_to(ROOT).as_posix()]={'bytes':file.stat().st_size,'sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
    names={}
    for file in map(Path,_game_files()):
        raw=json.loads(file.read_text(encoding='utf-8'))
        for key in ('awayBatterBox','homeBatterBox','awayPitcherBox','homePitcherBox'):
            for player in raw.get(key,[]):
                ident=player.get('playerId') or player.get('playerID') or player.get('id')
                if ident is not None:names.setdefault(player['playerName'],set()).add(str(ident))
    unresolved={n:sorted(ids) for n,ids in names.items() if len(ids)>1 and not all(i in IDENTITIES for i in ids)}
    if unresolved:fatal.append('unresolved_same_name_ids')
    report={'schema_version':1,'games':int(pa.game.nunique()),'pa':len(pa),'pitches':len(p),'box_rows':len(boxes),
            'fatal':fatal,'missing':{'RE24':int(pa.RE24.isna().sum()),'WPA':int(pa.WPA.isna().sum()),
             'pitch_cell':int(p.cell.isna().sum()),'pitch_xy':int(p[['x','y']].isna().any(axis=1).sum())},
            'unknown_hands':{'batter':int((~pa.bhand.isin(['L','R','S'])).sum()),'pitcher':int((~pa.phand.isin(['L','R'])).sum())},
            'name_id_conflicts':{n:sorted(ids) for n,ids in names.items() if len(ids)>1},
            'resolved_id_labels':{i:v[1] for i,v in IDENTITIES.items()}, 'unresolved_conflicts':unresolved,
            'identity_limit':'engine keys names; ambiguous IDs require review, never automatic merging',
            'inputs':inputs}
    out=ROOT/'output/closeout';out.mkdir(parents=True,exist_ok=True)
    (out/'input-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='inputs'},ensure_ascii=False),flush=True)
    if fatal:raise SystemExit(1)


if __name__=='__main__':main()
