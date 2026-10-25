"""Dated, auditable cross-source fielding identity links.

Provider IDs retain separate namespaces. A unique name/team observation anchors
an ID link only within the permitted evidence period; conflicts remain unknown.
This is historical fielding evidence, not registration or current eligibility.
"""
from collections import defaultdict
from functools import lru_cache
import hashlib
from pathlib import Path

import pandas as pd

from load import DATA, load

TEAM={'中信':'中信兄弟','統一':'統一7-ELEVEn獅','樂天':'樂天桃猿','富邦':'富邦悍將',
      '味全':'味全龍','台鋼':'台鋼雄鷹','Lamigo':'樂天桃猿'}


@lru_cache(maxsize=64)
def fielding_registry(cutoff=None):
    year=pd.Timestamp(cutoff).year if cutoff else 9999
    boxes=load()[2]
    if cutoff:boxes=boxes[boxes.date<pd.Timestamp(cutoff)]
    all_evidence=boxes[['name','raw_name','team','date']].drop_duplicates()
    by_year=defaultdict(list);by_team_name=defaultdict(list)
    for row in all_evidence.itertuples():
        by_year[(row.date.year,row.team,row.raw_name)].append((row.name,row.date))
        by_team_name[(row.team,row.raw_name)].append((row.name,row.date))
    inputs=[]
    if year>2025:inputs.append(('cpbl',2025,1.,Path(DATA)/'cpbl/positions_2025.csv'))
    inputs.extend(('ldkrsi',y,w,Path(DATA)/f'ldkrsi/fieldings_{y}.csv')
                  for y,w in ((2024,.7),(2023,.4)) if y<year)
    rows=[];hashes={}
    for namespace,season,weight,path in inputs:
        if not path.exists():continue
        hashes[f'{namespace}:{season}']=hashlib.sha256(path.read_bytes()).hexdigest()
        frame=pd.read_csv(path,dtype={'ID':str},encoding='utf-8-sig')
        for row in frame.to_dict('records'):
            if row['POS']=='P':continue
            team=TEAM.get(row['Team Name'],row['Team Name'])
            evidence=(by_year.get((season,team,row['Name']),[]) if season>=2024
                      else by_team_name.get((team,row['Name']),[]))
            candidates=sorted({key for key,_ in evidence})
            rows.append(dict(source_namespace=namespace,source_id=str(row['ID']),source_year=season,
                             source_name=row['Name'],source_team=team,position=row['POS'],
                             games=float(row['G']),weight=weight,candidates=candidates,
                             first_evidence=str(min(day for _,day in evidence).date()) if evidence else None))
    anchors=defaultdict(set)
    anchor_records=defaultdict(list)
    for row in rows:
        token=(row['source_namespace'],row['source_id'])
        anchors[token].update(row['candidates'])
        if row['candidates']:
            evidence={key:row[key] for key in ('source_year','source_name','source_team','first_evidence','candidates')}
            if evidence not in anchor_records[token]:anchor_records[token].append(evidence)
    mapped=[];review=[]
    for row in rows:
        matches=anchors[(row['source_namespace'],row['source_id'])]
        if len(matches)==1:
            key=next(iter(matches))
            mapped.append(dict(name=key,POS=row['position'],G_w=row['games']*row['weight']))
            review.append({**row,'player_key':key,'anchor_records':anchor_records[(row['source_namespace'],row['source_id'])],
                           'status':'unique_dated_name_team_anchor',
                           'official_identity_or_registration_claim':False})
        else:
            review.append({**row,'player_key':None,'status':'ambiguous' if matches else 'unmatched',
                           'official_identity_or_registration_claim':False})
    frame=pd.DataFrame(mapped,columns=['name','POS','G_w'])
    positions=frame.groupby(['name','POS']).G_w.sum() if not frame.empty else pd.Series(dtype=float,index=pd.MultiIndex.from_tuples([],names=['name','POS']))
    return positions,{'cutoff':cutoff,'source_hashes':hashes,'links':review,
                      'policy':'separate provider namespace; unique dated name/team anchors; no name-only or literal-ID joins'}
