"""Descriptive, date-safe pitch mix comparison. Independent of ranking models."""
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np

from load import PITCH_GROUP, GROUPS, STRIKE_CODES, FOUL_CODES
from identity import game_identity, resolve_game, display

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = 1


@dataclass(frozen=True)
class Settings:
    recent_games: int = 5
    baseline_games: int = 10
    min_games: int = 5
    min_pitches: int = 100
    min_stratum: int = 10
    min_coverage: float = .8
    max_unknown: float = .05
    bootstrap: int = 1000
    seed: int = 2025

    def __post_init__(self):
        for key in ('recent_games', 'baseline_games', 'min_games', 'min_pitches', 'min_stratum'):
            value = getattr(self, key)
            if type(value) is not int or value < 1:
                raise ValueError(f'{key} must be a positive integer')
        if type(self.bootstrap) is not int or self.bootstrap < 0:
            raise ValueError('bootstrap must be a nonnegative integer')
        if not 0 < self.min_coverage <= 1 or not 0 <= self.max_unknown <= 1:
            raise ValueError('invalid coverage or unknown threshold')


def appearance(game, day, pitcher):
    return dict(game=game, date=day, pitcher=pitcher,
                counts=np.zeros((24, 4), dtype=int), unknown=np.zeros(2, dtype=int),
                excluded=Counter())


def add_pa(a, pa):
    """Reject an ambiguous PA rather than silently clipping impossible counts."""
    events = [e for e in pa.get('events', []) if e.get('type') == 'PITCH']
    if any(e.get('pitcherName', a['pitcher']) != a['pitcher'] for e in events):
        a['excluded']['pitcher_mismatch'] += len(events)
        return  # mid-PA attribution is ambiguous; don't assign another pitcher's pitches
    hand = pa.get('batterHand')
    if hand not in ('L', 'R'):
        a['excluded']['unknown_hand'] += len(events)
        return
    hi = ('L', 'R').index(hand)
    balls = strikes = 0
    rows = []
    for j, e in enumerate(events):
        code = e.get('pitchCode')
        if balls > 3 or strikes > 2 or code not in STRIKE_CODES | FOUL_CODES | {'B', 'H', 'BUNT'}:
            a['excluded']['ambiguous_count'] += len(events)
            return
        rows.append((hi * 12 + balls * 3 + strikes, PITCH_GROUP.get(e.get('pitchType'))))
        if code == 'B':
            balls += 1
        elif code in STRIKE_CODES or (code == 'FOUL_BUNT' and strikes == 2):
            strikes += 1
        elif code in FOUL_CODES and strikes < 2:
            strikes += 1
        if code in {'H', 'BUNT'} and j != len(events) - 1:
            a['excluded']['ambiguous_count'] += len(events)
            return
    for s, group in rows:
        if group is None:
            a['unknown'][hi] += 1
        else:
            a['counts'][s, GROUPS.index(group)] += 1


@lru_cache(maxsize=1)
def observations():
    out, seen = {}, set()
    for path in sorted((ROOT / 'data/rebas').glob('*/*.json')):
        with path.open(encoding='utf8') as f:
            g = json.load(f)
        if not isinstance(g, dict) or 'seq' not in g:
            continue  # never read a combined season export as game data
        day = g['date'][:10]
        game = f"{day[:4]}-{int(g['seq']):03d}"
        if game in seen:
            continue
        seen.add(game)
        local = {}
        identities = game_identity(g)
        for side in ('away', 'home'):
            for p in g.get(side + 'PitcherBox', []):
                name = p['playerName']
                label = display(name, p.get('playerId'))
                local.setdefault(label, appearance(game, day, name))
            for p in g.get(side + 'PAList', []):
                name = p['pitcherName']
                other = 'home' if side == 'away' else 'away'
                player_id = resolve_game(identities[other], name)
                if player_id is None:
                    continue
                label = display(name, player_id)
                add_pa(local.setdefault(label, appearance(game, day, name)), p)
        for name, a in local.items():
            out.setdefault(name, []).append(a)
    return out


def compare(records, pitcher, season, cutoff, hand='ALL', settings=Settings()):
    cutoff = date.fromisoformat(cutoff).isoformat()
    if hand not in ('ALL', 'L', 'R'):
        raise ValueError('hand must be ALL, L or R')
    season = int(season)
    if not 1900 <= season <= 2100:
        raise ValueError('invalid season')
    # Select appearances BEFORE handedness filtering; dates are strictly exclusive.
    games = sorted([a for a in records if a['date'][:4] == str(season) and a['date'] < cutoff],
                   key=lambda a: (a['date'], a['game']))
    recent = games[-settings.recent_games:]
    baseline = games[max(0, len(games)-settings.recent_games-settings.baseline_games):max(0, len(games)-settings.recent_games)]
    ix = np.arange(24) if hand == 'ALL' else np.arange(12) + (12 if hand == 'R' else 0)

    def window(items):
        tensors = np.array([a['counts'][ix] for a in items], dtype=int).reshape((-1, len(ix), 4))
        counts = tensors.sum(axis=0)
        unknown = sum(int(a['unknown'].sum() if hand == 'ALL' else a['unknown'][('L', 'R').index(hand)]) for a in items)
        n = int(counts.sum())
        reasons = Counter()
        for a in items:
            reasons.update(a['excluded'])
        return tensors, counts, dict(games=[dict(game=a['game'], date=a['date']) for a in items],
            selected_games=len(items), effective_games=int((tensors.sum(axis=(1, 2)) > 0).sum()),
            valid_pitches=n, unknown_type=unknown, unknown_rate=unknown / (n+unknown) if n+unknown else None,
            excluded=dict(reasons))

    bt, bc, bm = window(baseline)
    rt, rc, rm = window(recent)
    bn, rn = bc.sum(axis=1), rc.sum(axis=1)
    common = (bn >= settings.min_stratum) & (rn >= settings.min_stratum)
    covered = [float(v[common].sum() / v.sum()) if v.sum() else 0 for v in (bn, rn)]
    weights = bn[common] / bn[common].sum() if common.any() else np.array([])
    reasons = []
    for label, meta, coverage in zip(('基準期', '近期'), (bm, rm), covered):
        if meta['effective_games'] < settings.min_games:
            reasons.append(f'{label}有效出賽不足 {settings.min_games} 場')
        if meta['valid_pitches'] < settings.min_pitches:
            reasons.append(f'{label}有效球數不足 {settings.min_pitches} 球')
        if coverage < settings.min_coverage:
            reasons.append(f'{label}共同條件涵蓋率不足 {settings.min_coverage:.0%}')
        if meta['unknown_rate'] is not None and meta['unknown_rate'] > settings.max_unknown:
            reasons.append(f'{label}未知球種比例超過 {settings.max_unknown:.0%}')
    adjusted = []
    for c in (bc, rc):
        adjusted.append((c[common] / c[common].sum(axis=1)[:, None] * weights[:, None]).sum(axis=0)
                        if common.any() else None)
    ci = [None] * 4
    valid = 0
    if not reasons and settings.bootstrap > 0:
        rng = np.random.default_rng(settings.seed)
        draws = []
        for tensor in (bt, rt):
            # Resample whole appearances, holding support and baseline weights fixed.
            sampled = tensor[rng.integers(len(tensor), size=(settings.bootstrap, len(tensor)))].sum(axis=1)[:, common]
            denom = sampled.sum(axis=2)
            ok = (denom > 0).all(axis=1)
            value = (np.divide(sampled, denom[:, :, None], out=np.zeros_like(sampled, dtype=float),
                               where=denom[:, :, None] > 0) * weights[None, :, None]).sum(axis=1)
            draws.append((ok, value))
        ok = draws[0][0] & draws[1][0]
        valid = int(ok.sum())
        if valid >= settings.bootstrap * .9:
            limits = np.quantile((draws[1][1]-draws[0][1])[ok] * 100, [.025, .975], axis=0)
            for k in range(4):
                if bc[:, k].sum() + rc[:, k].sum() >= 10 and limits[1, k]-limits[0, k] > 1e-8:
                    ci[k] = [float(limits[0, k]), float(limits[1, k])]
    rows = []
    for k, group in enumerate(GROUPS):
        delta = float((adjusted[1][k]-adjusted[0][k])*100) if common.any() else None
        label = '樣本不足，僅供描述'
        if not reasons and delta is not None:
            label = '調整後差異較小' if abs(delta) < 5 else '估計變動尚不足以判斷'
            if abs(delta) >= 5 and ci[k]:
                label = ('值得留意增加' if delta > 0 else '值得留意減少') if ci[k][0]*ci[k][1] > 0 else '差異方向仍不明確'
        rows.append(dict(group=group, raw=[float(c[:, k].sum()/c.sum()) if c.sum() else None for c in (bc, rc)],
                         adjusted=[float(a[k]) if a is not None else None for a in adjusted], delta_pp=delta,
                         interval=ci[k], interpretation=label))
    strata = [dict(hand='L' if int(ix[s]) < 12 else 'R', balls=int(ix[s]) % 12 // 3,
                   strikes=int(ix[s]) % 3, baseline=int(bn[s]), recent=int(rn[s]),
                   included=bool(common[s]), weight=float(bn[s]/bn[common].sum()) if common[s] else None)
              for s in range(len(ix))]
    return dict(schema_version=SCHEMA, pitcher=pitcher, season=season, cutoff=cutoff, hand=hand,
                settings=asdict(settings), source='Rebas Open Data (ODC-By)',
                status='insufficient' if reasons else 'ready', reasons=reasons,
                windows=dict(baseline=bm, recent=rm), coverage=covered, strata=strata, rows=rows,
                bootstrap=dict(requested=settings.bootstrap, valid=valid),
                last_observed=games[-1]['date'] if games else None)


@lru_cache(maxsize=256)
def pitch_change(pitcher, season, cutoff, hand='ALL'):
    records = observations()
    if not records:
        raise ValueError('尚未下載 Rebas 原始資料，請執行 python download_data.py')
    if pitcher not in records:
        raise ValueError('找不到此投手的資料')
    return compare(records[pitcher], pitcher, season, cutoff, hand)
