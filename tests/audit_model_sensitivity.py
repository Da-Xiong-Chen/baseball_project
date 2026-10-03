"""Local snapshot audit: weight sensitivity is not accuracy or a confidence interval."""
import json
import math
import sys
import copy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from qualification import annotate
WEIGHTS = (0, .25, .5, .75, 1)


def inspect(rows, pen):
    name = '投手' if pen else '球員'
    eligible = [x for x in rows if pen or x.get('守備') != 'bad']
    if len(eligible) < 2:
        return None
    if any(x.get('機器學習') is None for x in eligible):
        return None
    scores = {}
    for weight in WEIGHTS:
        values = {x[name]: (1-weight)*x['階層式'] + weight*x['機器學習']
                  + (x.get('疲勞調整', 0) if pen else 0) for x in eligible}
        assert all(math.isfinite(v) for v in values.values())
        best = min(values.values()) if pen else max(values.values())
        # Rounded exports can tie; retain all near-tied leaders, without claiming equivalence.
        scores[str(weight)] = sorted(n for n, v in values.items() if abs(v-best) <= 1e-6)
    common = set(scores['0'])
    for leaders in scores.values():
        common.intersection_update(leaders)
    current = next(x for x in eligible if x['角色'] == ('場上' if pen else '現任'))
    disagrees = sum((x['階層式']-current['階層式']) *
                   (x['機器學習']-current['機器學習']) < 0
                   for x in eligible if x is not current)
    return dict(leaders=scores, common_leader=bool(common),
                candidate_model_disagreements=disagrees, eligible_count=len(eligible))


def main():
    cases = {'offense': [], 'defense': []}
    gated = {'offense': [], 'defense': []}
    depth = json.loads((ROOT/'docs/data/qualification.json').read_text(encoding='utf8'))
    fallback = low = warnings = 0
    for file in sorted((ROOT/'docs/data/replay').glob('*.json')):
        if file.name == 'games.json':
            continue
        payload = json.loads(file.read_text(encoding='utf8'))
        for pa_id, result in payload['results'].items():
            assert result['ml_cutoff'] <= result['model_cutoff'] <= result['situation']['date']
            for x in result['candidates']:
                fallback += x.get('投手對此側樣本') == 0
                low += x['樣本球數'] < 500
                warnings += bool(x.get('資料警示'))
            for mode, rows in [('offense', result['candidates']), ('defense', result['bullpen']['rows'])]:
                finding = inspect(rows, mode == 'defense')
                if finding:
                    cases[mode].append(dict(pa_id=pa_id, **finding))
                pen = mode == 'defense'
                qualified = annotate(copy.deepcopy(result), depth)
                gated_rows = qualified['bullpen']['rows'] if pen else qualified['candidates']
                eligible = [x for x in gated_rows if x['可列入排名']]
                current = next(x for x in rows if x['角色'] == ('場上' if pen else '現任'))
                if any(x['角色'] == current['角色'] for x in eligible):
                    checked = inspect(eligible, pen)
                    if checked:
                        gated[mode].append(dict(pa_id=pa_id, **checked))
    summary = {mode: dict(comparable_cases=len(items),
                         no_common_leader=sum(not x['common_leader'] for x in items),
                         cases_with_model_disagreement=sum(x['candidate_model_disagreements'] > 0 for x in items))
               for mode, items in cases.items()}
    gated_summary = {mode: dict(comparable_cases=len(items),no_common_leader=sum(not x['common_leader'] for x in items),cases_with_model_disagreement=sum(x['candidate_model_disagreements'] > 0 for x in items)) for mode, items in gated.items()}
    report = dict(weights=WEIGHTS, summary=summary, qualified_summary=gated_summary,
                  offense_candidate_rows_with_pitcher_fallback=fallback,
                  offense_candidate_rows_under_500_pitches=low,
                  offense_candidate_rows_with_data_warning=warnings,
                  interpretation='Weight sweep of fixed historical predictions; no retraining, no causal claims, no accuracy estimate. Fatigue held fixed; raw offense run values used, positive common slope preserves ordering.',
                  cases=cases)
    out = ROOT/'output/decision_v3/model-sensitivity.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: v for k,v in report.items() if k != 'cases'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
