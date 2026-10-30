"""One validated season/date contract. Defaults reproduce the sealed v5 dataset.

A different configuration is an isolated research batch until models and exports
with the same runtime_id are built; it is never permission to reuse later models.
"""
from dataclasses import asdict, dataclass
from datetime import date
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class Runtime:
    data_seasons: tuple = (2024, 2025)
    season: int = 2025
    cutoff: str = '2026-01-01'
    history_date: str = '2025-09-20'
    replay_cutoffs: tuple = tuple(f'2025-{m:02d}-01' for m in range(3, 11))
    schema_version: int = 1

    def __post_init__(self):
        if self.schema_version != 1:raise ValueError('Unsupported runtime schema')
        if (not self.data_seasons or any(type(y) is not int or not 1900 <= y <= 2200 for y in self.data_seasons)
                or tuple(sorted(set(self.data_seasons))) != self.data_seasons or self.season not in self.data_seasons):
            raise ValueError('Seasons must be explicit, unique, sorted integers')
        cutoff,history=map(date.fromisoformat,(self.cutoff,self.history_date))
        if history.year != self.season or cutoff <= history or cutoff.year not in (self.season,self.season+1):
            raise ValueError('History date and exclusive cutoff do not match the season')
        if not self.replay_cutoffs or tuple(sorted(set(self.replay_cutoffs))) != self.replay_cutoffs:
            raise ValueError('Replay cutoffs must be ordered and unique')
        for value in self.replay_cutoffs:
            day=date.fromisoformat(value)
            if day.day != 1 or day.year != self.season or day >= cutoff:
                raise ValueError('Replay models must be month-start, before the full cutoff')
        if self.history_date < self.replay_cutoffs[0]:raise ValueError('History date has no earlier model')

    def payload(self):
        return json.loads(json.dumps(asdict(self)))

    @property
    def runtime_id(self):
        return hashlib.sha256(json.dumps(self.payload(),sort_keys=True,separators=(',',':')).encode()).hexdigest()

    def month_for(self,value):
        day=date.fromisoformat(value)
        month=day.replace(day=1).isoformat()
        if value >= self.cutoff or month not in self.replay_cutoffs:
            raise ValueError('No cutoff-safe model for this date')
        return month

    def assets(self):
        y=self.season;day=self.history_date
        return {'default_lineups':f'data/default-lineups-{y}.json','numbers':f'data/player-numbers-{y}.json',
                'history_context':f'data/history-context-{day}.json','fielding_plans':f'data/fielding-plans-{day}.json',
                'timing':f'data/timing-{y}.json','day_index':f'data/replay/day-{day}/index.json'}

    def public(self):
        return {**self.payload(),'runtime_id':self.runtime_id,'assets':self.assets(),'cutoff_inclusive':False}


DEFAULT=Runtime()


@lru_cache(maxsize=1)
def settings():
    path=os.environ.get('BASEBALL_RUNTIME_CONFIG')
    if not path:return DEFAULT
    data=json.loads(Path(path).read_text(encoding='utf8'))
    if set(data)-set(asdict(DEFAULT)):raise ValueError('Unknown runtime configuration field')
    for key in ('data_seasons','replay_cutoffs'):
        if key in data:data[key]=tuple(data[key])
    return Runtime(**data)


def check_model_runtime(context):
    """Legacy v5 is explicitly limited to the default dataset/date contract."""
    actual=context.get('runtime_id')
    expected=settings().runtime_id
    if actual != expected and not (actual is None and settings()==DEFAULT):
        raise ValueError('Runtime configuration and trained batch differ; build a compatible research batch')
