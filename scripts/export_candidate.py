#!/usr/bin/env python3
"""Copy the complete fixed-Work envelope into the final submission artifact.

This is artifact conversion, not proof that the fixed Work procedure occurred.
Keep the original Work directory in task-owner/Harness experiment evidence.
"""
import argparse
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work-artifact',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    artifact=json.loads(args.work_artifact.read_text())
    if artifact.get('schema_version')!=1 or artifact.get('status')!='work_complete' or artifact.get('completed_rounds')!=3 or not isinstance(artifact.get('revision_log'),list):raise ValueError('A completed three-round Work artifact is required')
    prompts=artifact.get('prompts')
    if not isinstance(prompts,dict) or set(prompts)!={'policy','evolver','memory'} or any(not isinstance(x,str) for x in prompts.values()):raise ValueError('Invalid final prompt strings')
    if args.output.exists():raise ValueError('Refusing to overwrite candidate file')
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(artifact,sort_keys=True,ensure_ascii=False)+'\n')
    print(json.dumps({'status':'exported_complete_work_envelope','inference_performed':False,'provenance_verified':False}))

if __name__=='__main__':main()
