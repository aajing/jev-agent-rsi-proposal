"""Build-time lock; copy to task-owner tests before any research agent runs."""
import hashlib
import json
from pathlib import Path
import sys


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
    return h.hexdigest()


def freeze(destination,roots):
    files={}
    for root in roots:
        root=Path(root)
        if not root.exists():raise ValueError(f'Missing immutable runtime root: {root}')
        paths=sorted(root.rglob('*')) if root.is_dir() else [root]
        for path in paths:
            # HF download metadata is not an evaluation asset; Python bytecode IS locked.
            if '.cache' in path.parts:continue
            if path.is_symlink():files[str(path)]={'kind':'symlink','target':str(path.readlink())}
            elif path.is_file():files[str(path)]={'kind':'file','bytes':path.stat().st_size,'sha256':sha(path)}
    Path(destination).write_text(json.dumps({'schema_version':1,'roots':roots,'files':files},sort_keys=True,indent=2)+'\n')

if __name__=='__main__':freeze(sys.argv[1],sys.argv[2:])
