"""Dated compatibility aliases, kept outside the frozen model-training surface."""
import pandas as pd
from identity import IDENTITIES,source_key,resolve_player as resolve_identity
from load import load

def legacy_aliases(rows):
    keys=set(rows.name);out={}
    for raw_id,(raw_name,old_label) in IDENTITIES.items():
        key=source_key(raw_id)
        if key in keys and (rows[(rows.name==key)].raw_name==raw_name).any():out[old_label]=key
    return out

def resolve_player(value,cutoff=None,team=None,role=None):
    try:return resolve_identity(value,cutoff=cutoff,team=team,role=role)
    except ValueError:
        if not isinstance(value,str):raise
        rows=load()[2]
        if cutoff:rows=rows[rows.date<pd.Timestamp(cutoff)]
        if team:rows=rows[rows.team==team]
        if role:rows=rows[rows.role==role]
        key=legacy_aliases(rows).get(value)
        if key:return key
        raise
