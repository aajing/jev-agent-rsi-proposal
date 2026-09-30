#!/usr/bin/env python3
"""Stage a standalone task. Private records are an explicit task-owner option.

The default staged tree remains public and cannot run Judge. Never publish a
staged tree made with --include-private. No model or GPU is used here.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parents[1]
FAMILIES=('u_book_flight','u_multi_layouts','u_form_sequence','u_read_table',
 'd_invoice','d_contract','d_chart','d_version','x_expense','x_calendar','x_alert','x_fulfillment',
 'sokoban','key_maze','minesweeper','fifteen_puzzle')


def copy_tree(source,destination):
    destination.mkdir(parents=True,exist_ok=True)
    for p in sorted(source.rglob('*')):
        relative=p.relative_to(source)
        if any(part.startswith('.') or part=='__pycache__' for part in relative.parts):continue
        if p.is_symlink():raise ValueError('Symlinks are not accepted in staged source or assets')
        if p.is_file():
            target=destination/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)


def check_records(path,count,split):
    rows=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len(rows)!=16*count or len({r['id'] for r in rows})!=len(rows):raise ValueError(f'{split}: incomplete or duplicate IDs')
    for family in FAMILIES:
        for tier in ('hard','harder'):
            if sum(r['family']==family and r['tier']==tier and r['split']==split for r in rows)!=count//2:raise ValueError(f'{split}: family/tier count mismatch')
    return len(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--include-private',action='store_true',help='Task-owner use only: include private hidden records; resulting tree MUST NOT be published')
    args=parser.parse_args();out=args.output.resolve()
    if out.exists():raise ValueError('Output must be a new directory')
    totals={split:check_records(ROOT/'data/public'/f'{split}.jsonl',n,split) for split,n in [('practice',8),('validation',2)]}
    if args.include_private:totals['hidden']=check_records(ROOT/'data/private/hidden.jsonl',6,'hidden')
    if not (ROOT/'assets/vendor/miniwob/miniwob/book-flight-nodelay.html').is_file():raise ValueError('Pinned MiniWoB assets are missing')
    copy_tree(ROOT/'harbor',out)
    bundle=out/'environment/bundle';bundle.mkdir(parents=True)
    copy_tree(ROOT/'jevbench',bundle/'jevbench');copy_tree(ROOT/'assets',bundle/'assets')
    copy_tree(ROOT/'configs',bundle/'configs')
    copy_tree(ROOT/'scripts',bundle/'scripts')
    (bundle/'data/public').mkdir(parents=True)
    for split in ('practice','validation'):shutil.copy2(ROOT/'data/public'/f'{split}.jsonl',bundle/'data/public'/f'{split}.jsonl')
    shutil.copy2(ROOT/'baseline_prompts.json',bundle/'baseline_prompts.json')
    copy_tree(bundle,out/'tests/trusted')
    private=out/'tests/private';private.mkdir(mode=0o700)
    if args.include_private:
        shutil.copy2(ROOT/'data/private/hidden.jsonl',private/'hidden.jsonl');(private/'hidden.jsonl').chmod(0o600)
        (private/'judge_ledger.jsonl').write_text('');(private/'judge_ledger.jsonl').chmod(0o600)
    files={}
    for p in sorted((out/'tests/trusted').rglob('*')):
        if p.is_file():files[str(p.relative_to(out/'tests'))]=hashlib.sha256(p.read_bytes()).hexdigest()
    if args.include_private:files['private/hidden.jsonl']=hashlib.sha256((private/'hidden.jsonl').read_bytes()).hexdigest()
    (out/'tests/input_manifest.json').write_text(json.dumps({'schema_version':1,'files':files},indent=2,sort_keys=True)+'\n')
    status={'status':'staged_not_gpu_validated','split_counts':totals,'includes_private_hidden':args.include_private,
            'publishable_tree':not args.include_private,'runtime_lock':'pending_Docker_build_and_host_extraction',
            'provenance':'fixed_Work_run_requires_separate_task_owner_or_Harness_logs'}
    (out/'STAGING_STATUS.json').write_text(json.dumps(status,indent=2)+'\n')
    print(json.dumps(status,sort_keys=True))

if __name__=='__main__':main()
