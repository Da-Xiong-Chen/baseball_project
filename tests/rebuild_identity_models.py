"""Force local ID-model rebuild; no network or Git operations."""
import os
import pickle
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
import mlmodel

for cutoff in [mlmodel.FULL]+mlmodel.REPLAY_MONTHS:
    model=mlmodel.train(cutoff)
    path=mlmodel.path_for(cutoff)
    temporary=path+f'.{os.getpid()}.tmp'
    with open(temporary,'wb') as stream:
        pickle.dump(model,stream)
    os.replace(temporary,path)
