"""Build a new staging site without overwriting the currently exported data."""
from pathlib import Path
import json
import shutil

ROOT=Path(__file__).resolve().parents[1]
STAGE=ROOT/'output/closeout/staging-site'


if __name__=='__main__':
    if STAGE.exists():
        print('Existing staging site retained:',STAGE)
    else:
        shutil.copytree(ROOT/'docs',STAGE,ignore=shutil.ignore_patterns('qa'))
        print('Created staging site:',STAGE)
    audit=ROOT/'output/closeout/input-audit.json'
    if audit.exists():
        d=json.loads(audit.read_text(encoding='utf-8'))
        if d['fatal']:raise SystemExit('Input audit has unresolved fatal errors')
    (ROOT/'output/closeout/staging-status.json').write_text(json.dumps({'status':'building',
        'site':str(STAGE),'data':str(STAGE/'data'),'current_docs_data_replaced':False},indent=2),encoding='utf-8')
