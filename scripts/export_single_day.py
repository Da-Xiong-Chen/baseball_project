"""Build an isolated static replay package from an explicitly trained monthly model."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path

from training_source import fingerprint, inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verified-intake', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    os.environ['BASEBALL_STATIC_OUT'] = str(out)
    authority = out.parent / 'batch-context.json'
    os.environ['BASEBALL_BATCH_CONTEXT'] = str(authority)

    from export_history_day import DATE, OUT, export
    from export_history_context import build
    from load import DATA, load
    from historical_actors import decorate
    from identity import labels
    import mlmodel
    from batch_contract import metadata
    from fatigue import starter_curve
    from pitch_change import compare, observations
    from runtime_config import settings
    from timing_backtest import MIN_INNING, THRESHOLD

    runtime = settings()
    intake = json.loads(args.verified_intake.read_bytes())
    files = inventory(DATA, runtime.data_seasons)
    raw = {key.removeprefix('rebas/'): value for key, value in files.items() if key.startswith('rebas/')}
    if intake['seasons'] != list(runtime.data_seasons) or raw != {
            row['file']: row['sha256'] for row in intake['source_manifest']}:
        raise ValueError('Replay inputs differ from the verified intake')
    month = runtime.month_for(DATE)
    weight = Path(mlmodel.path_for(month))
    model = mlmodel._load_weight(weight, month)
    if not (model.training_samples['last_date'] < month <= DATE
            and model.calibration_reference['last_date'] < month):
        raise ValueError('Monthly model includes future training or calibration data')
    context = dict(training_version=5, engine_contract=5, runtime_id=runtime.runtime_id,
                   input_id=fingerprint(files), models=[dict(name=weight.name, cutoff=month,
                   sha256=sha256(weight.read_bytes()).hexdigest())])
    context['batch_id'] = fingerprint(context)
    with authority.open('x', encoding='utf8') as stream:
        json.dump(context, stream, indent=2)
    export()
    index_path = OUT / 'index.json'
    index = json.loads(index_path.read_bytes())
    pa, pitches, boxes = load()
    pregame = build(pa, pitches, boxes, DATE)
    pregame.update(players=labels(DATE), fatigue_curve=starter_curve(DATE), date=DATE)
    from server import clean

    def write(filename, payload):
        path = OUT / filename
        with path.open('x', encoding='utf8') as stream:
            json.dump(clean({**payload, **metadata()}), stream, ensure_ascii=False,
                      allow_nan=False, separators=(',', ':'))

    write('context.json', pregame)
    marks, schedule = {}, []
    pitch_names = {p['name'] for team in pregame['teams'].values() for p in team['pitchers']}
    cols = ['pa_id', 'inning', 'half', 'outs', 'bases', 'bat_team', 'fld_team',
            'bat_score', 'fld_score', 'batter', 'pitcher', 'start_batter', 'start_pitcher',
            'mid_pa_actor_change', 'is_ph', 'result', 'WPA']
    daily = decorate(pa[pa['date'].dt.strftime('%Y-%m-%d') == DATE])
    for gid, game in daily.groupby('game'):
        game = game.sort_values(['inning', 'half', 'seq'])
        away, home = (game[game['half'] == half] for half in ('away', 'home'))
        schedule.append(dict(game=gid, date=DATE, away=away['bat_team'].iat[0],
                             home=home['bat_team'].iat[0], ph=int(game['is_ph'].sum()),
                             away_score=int((away['bat_score'] + away['runs']).max()),
                             home_score=int((home['bat_score'] + home['runs']).max())))
        write(gid + '.json', dict(date=DATE, game=gid, pas=game[cols], players=labels(DATE, inclusive=True)))
        marks[gid] = {}
        for row in game.itertuples():
            bundle = json.loads((OUT / index['files'][row.pa_id]).read_bytes())
            ph, pen = bundle['ph'], bundle['pen'] or bundle['ph']
            bench = [r for r in ph['candidates'] if r['角色'] == '代打']
            eligible = [r for r in bench if r['守備'] in ('ok', 'warn')]
            arms = [r for r in pen['bullpen']['rows'] if r['角色'] == '牛棚']
            for result in (ph, pen):
                pitch_names.add(result['situation']['pitcher'])
                pitch_names.update(r['投手'] for r in result['bullpen']['rows'])
            if row.inning < MIN_INNING:
                continue
            bat = max(eligible, key=lambda r: r['相對現任'], default=None)
            arm = arms[0] if arms else None
            marks[gid][row.pa_id] = [
                arm['守方勝率增減'] if arm else None, arm['投手'] if arm else None,
                pen['replay_context']['incumbent_pitcher'],
                bat['相對現任'] if bat else None, bat['球員'] if bat else None,
                ph['situation']['due'], int(bool(bench))]
    write('timing.json', dict(schema_version=2, date=DATE, season=runtime.season,
                             threshold=THRESHOLD, min_inning=MIN_INNING, games=marks))
    records = observations()
    # Small per-pitcher files keep the comparison lazy in the browser.
    pitch_root = OUT / 'pitch'
    pitch_root.mkdir()
    pitcher_files = {}
    for pitcher in sorted(pitch_names):
        key = sha256(pitcher.encode()).hexdigest()[:24] + '.json'
        pitcher_files[pitcher] = key
        hands = {hand: compare(records.get(pitcher, []), pitcher, runtime.season, DATE, hand)
                 for hand in ('ALL', 'L', 'R')}
        write('pitch/' + key, dict(schema_version=2, snapshots=[dict(effective_from=DATE, hands=hands)]))
    write('pitch/index.json', dict(schema_version=2, season=runtime.season, pitchers=pitcher_files))
    index.update(season=runtime.season, schedule=schedule,
                 training_last_date=model.training_samples['last_date'],
                 calibration_last_date=model.calibration_reference['last_date'])
    pending = index_path.with_suffix('.next')
    pending.write_text(json.dumps(index, ensure_ascii=False, allow_nan=False, indent=2)+'\n', encoding='utf8')
    pending.replace(index_path)
    print(json.dumps(dict(date=DATE, games=len(schedule), pa=index['pa_count'],
                         pitcher_changes=index['pitcher_changes'], pitcher_snapshots=len(pitcher_files))))


if __name__ == '__main__':
    main()
