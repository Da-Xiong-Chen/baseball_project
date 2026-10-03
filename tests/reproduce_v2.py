"""在已下載公開資料的 .qa-reproduction 中重新訓練、匯出並核對 v2。

先使用全新 venv 安裝 requirements.txt，將 download_data.py 複製到該
目錄執行。此驗證不使用原專案的 pickle，不修改原有資料或匯出內容。
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPRO = ROOT / '.qa-reproduction'
OUT = ROOT / 'output/decision_v2/reproduction.json'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    for year in ('2024', '2025'):
        files = list((REPRO / 'data/rebas' / year).glob('*.json'))
        if len(files) != 360:
            raise RuntimeError(f'{year} 公開資料尚未下載完成：{len(files)} 場')
    for year in ('2023', '2024'):
        if not (REPRO / 'data/ldkrsi' / f'fieldings_{year}.csv').exists():
            raise RuntimeError('守位資料尚未下載完成')
    if list((REPRO / 'models').glob('*.pkl')):
        raise RuntimeError('驗收目錄已有 pickle；本命令要求從無模型的隔離目錄重建')
    (REPRO / 'src').mkdir(exist_ok=True)
    source = list((ROOT / 'src').glob('*.py')) + [ROOT / 'server.py']
    for path in source:
        destination = REPRO / 'src' / path.name if path.parent.name == 'src' else REPRO / path.name
        shutil.copy2(path, destination)
    report = dict(python=sys.version,isolated_prefix=sys.prefix,
                  source_sha256={str(p.relative_to(ROOT)):digest(p) for p in source},
                  public_data_files=720,private_fielding_used=False,existing_pickles_used=False)
    mismatches=[]
    for path in (REPRO / 'data/rebas').rglob('*.json'):
        previous=ROOT / path.relative_to(REPRO)
        if not previous.exists() or digest(path)!=digest(previous):
            mismatches.append(str(path.relative_to(REPRO)))
    report['raw_data_mismatches']=mismatches
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps({**report,'status':'training'},ensure_ascii=False,indent=2),encoding='utf8')
    subprocess.run([sys.executable,'-u','src/mlmodel.py'],cwd=REPRO,check=True)
    subprocess.run([sys.executable,'-u','src/export_static.py'],cwd=REPRO,check=True)
    maximum=0.0
    def compare(a,b,location):
        nonlocal maximum
        if isinstance(a,dict):
            assert isinstance(b,dict) and a.keys()==b.keys(), location
            for key in a:compare(a[key],b[key],location+'/'+key)
        elif isinstance(a,list):
            assert isinstance(b,list) and len(a)==len(b),location
            for i,(x,y) in enumerate(zip(a,b)):compare(x,y,location+'/'+str(i))
        elif isinstance(a,(int,float)) and not isinstance(a,bool):
            assert isinstance(b,(int,float)),location
            error=abs(a-b);maximum=max(maximum,error)
            assert error<0.0001,(location,a,b)
        else:
            assert a==b,(location,a,b)
    paths=[Path('model.json')]+[p.relative_to(ROOT/'docs/data') for p in (ROOT/'docs/data/replay').glob('*.json')]
    for relative in paths:
        compare(json.loads((ROOT/'docs/data'/relative).read_text(encoding='utf8')),
                json.loads((REPRO/'docs/data'/relative).read_text(encoding='utf8')),str(relative))
    report.update(status='passed',compared_json_files=len(paths),max_numeric_error=maximum,
                  rebuilt_models=len(list((REPRO/'models').glob('*.pkl'))))
    OUT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
