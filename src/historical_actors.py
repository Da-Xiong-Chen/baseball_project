"""Separate PA-opening participants from the observed completion summary.

Training PA targets remain untouched. Replays use first-pitch actors when a
PA has pitches; pitchless PAs retain their source summary. The next PA inherits
the previous PA's final pitcher, not the previous PA's opening pitcher.
"""
from functools import lru_cache
from load import load

@lru_cache(maxsize=1)
def first_pitches():
    return load()[1].sort_values('j',kind='stable').drop_duplicates('pa_id').set_index('pa_id')

@lru_cache(maxsize=128)
def game_pitches(game):
    pitches=load()[1]
    return pitches[pitches.game==game]

def at_start(row):
    result=row.copy();first=first_pitches()
    if row['pa_id'] in first.index:
        pitch=first.loc[row['pa_id']]
        for field in ('batter','pitcher','catcher','bhand','phand'):
            # Explicit unknown actor/hand stays unknown; do not substitute the final actor.
            result[field]=pitch[field]
    return result

def decorate(frame):
    out=frame.copy();first=first_pitches()
    for field in ('batter','pitcher','catcher','bhand','phand'):
        values=out.pa_id.map(first[field])
        out['start_'+field]=values.where(out.pa_id.isin(first.index),out[field])
    out['mid_pa_actor_change']=out.apply(lambda r:any(r[f]!=r['start_'+f] for f in ('batter','pitcher','catcher')),axis=1)
    return out
