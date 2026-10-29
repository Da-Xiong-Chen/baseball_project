"""Shared identity for one immutable trained/exported batch."""
from pathlib import Path
from functools import lru_cache
import hashlib,json,os

ROOT=Path(__file__).resolve().parents[1]
ENGINE_CONTRACT=5


def ensure_available():
    journal=ROOT/'output/promotion-journal.json'
    if journal.exists():
        raise RuntimeError('資料批次更新尚未完成，請先執行批次恢復，再重新啟動')


def context_path():
    return Path(os.environ.get('BASEBALL_BATCH_CONTEXT',ROOT/'models/active-batch.json'))


@lru_cache(maxsize=16)
def _read_context(path,stamp,size):
    data=json.loads(Path(path).read_text(encoding='utf8'))
    authority={k:v for k,v in data.items() if k!='batch_id'}
    expected=hashlib.sha256(json.dumps(authority,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    if data.get('batch_id')!=expected or data.get('engine_contract')!=ENGINE_CONTRACT or data.get('training_version')!=5:
        raise ValueError('批次來源識別不一致')
    return data


def context():
    ensure_available();path=context_path();stat=path.stat()
    return _read_context(str(path),stat.st_mtime_ns,stat.st_size)


def metadata():
    c=context()
    return dict(training_version=c['training_version'],engine_contract=ENGINE_CONTRACT,batch_id=c['batch_id'])


@lru_cache(maxsize=64)
def _weight_hash(path,stamp,size):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def weight_identity(path,cutoff):
    c=context();row=next((r for r in c['models'] if r['name']==Path(path).name and r['cutoff']==cutoff),None)
    if row is None:raise ValueError('模型不屬於目前批次')
    stat=Path(path).stat()
    if _weight_hash(str(path),stat.st_mtime_ns,stat.st_size)!=row['sha256']:
        raise ValueError('模型權重與批次雜湊不一致')
    return c['batch_id'],stat.st_mtime_ns
