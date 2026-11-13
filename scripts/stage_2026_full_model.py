"""Seal a trained full-season model and export an isolated static evaluation grid."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys

from training_source import fingerprint, inventory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def reject_constant(value):
    raise ValueError(f'Invalid numeric constant in model export: {value}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', required=True, type=Path)
    parser.add_argument('--verified-intake', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(ROOT/'output'):
        parser.error('Use an isolated output/ subdirectory')
    out.mkdir(parents=True,exist_ok=False)
    models = out/'models'
    models.mkdir()
    os.environ.update(BASEBALL_MODEL_DIR=str(models), BASEBALL_BATCH_CONTEXT=str(out/'batch-context.json'),
                      BASEBALL_STATIC_OUT=str(out/'data'))

    from load import DATA, load
    import mlmodel
    from runtime_config import settings
    from export_static import export_model

    runtime = settings()
    if runtime.data_seasons != (2024,2025,2026) or runtime.cutoff != '2027-01-01':
        parser.error('Use the 2024–2026 runtime with the 2027-01-01 exclusive cutoff')
    intake = json.loads(args.verified_intake.read_bytes())
    files = inventory(DATA,runtime.data_seasons)
    source = {name.removeprefix('rebas/'):digest for name,digest in files.items() if name.startswith('rebas/')}
    if intake['seasons'] != list(runtime.data_seasons) or source != {
            row['file']:row['sha256'] for row in intake['source_manifest']}:
        raise ValueError('Full-season training sources differ from the verified intake')
    raw = args.model.read_bytes()
    verified = mlmodel._load_weight(args.model,runtime.cutoff)
    if not (verified.training_samples['last_date'] < runtime.cutoff and
            verified.calibration_reference['last_date'] < runtime.cutoff):
        raise ValueError('Model cutoff failed')
    target = Path(mlmodel.path_for(runtime.cutoff))
    shutil.copyfile(args.model,target)
    digest = sha256(raw).hexdigest()
    if sha256(target.read_bytes()).hexdigest() != digest:
        raise ValueError('Weight changed while being staged')
    context = {'training_version':mlmodel.TRAINING_VERSION,'engine_contract':5,'runtime_id':runtime.runtime_id,
               'input_id':fingerprint(files),'models':[{'name':target.name,'cutoff':runtime.cutoff,'sha256':digest}]}
    context['batch_id'] = fingerprint(context)
    (out/'batch-context.json').write_text(json.dumps(context,indent=2),encoding='utf8')
    export_model()
    output = out/'data/model.json'
    payload = json.loads(output.read_bytes(),parse_constant=reject_constant)
    if (payload['batch_id']!=context['batch_id'] or payload['runtime']['runtime_id']!=runtime.runtime_id or
            payload['cutoff']!=runtime.cutoff or len(payload['teams'])!=6):
        raise ValueError('Exported evaluation grid does not match the model batch')
    grid = payload['ml']['grid']
    hitters = payload['ml']['hitters']
    if not grid or not hitters or any(len(row)!=len(hitters) or any(v is None for v in row) for row in grid.values()):
        raise ValueError('Incomplete matchup grid')
    pa = load()[0]
    seasons = {str(y):{'games':int(rows.game.nunique()),'pa':len(rows)} for y,rows in pa.groupby('season')}
    receipt = {'context':context,'seasons':seasons,'training_samples':verified.training_samples,
               'calibration_dates':[verified.calibration_reference[k] for k in ('first_date','last_date')],
               'teams':len(payload['teams']),'hitters':len(hitters),'pitchers':len(grid),
               'export_sha256':sha256(output.read_bytes()).hexdigest()}
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2,allow_nan=False),encoding='utf8')
    print(json.dumps(receipt,ensure_ascii=False,indent=2),flush=True)


if __name__ == '__main__':
    main()
