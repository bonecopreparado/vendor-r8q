"""Resolve a successful exact-source memory build; never pin expiring artifact IDs."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
import fetch_verified_kernel as trusted
sys.path.insert(0,str(trusted.ROOT/'tools'))
SOURCE_COMMIT = '0fc3f65af331c896e5404e2e7b12c8e78cc3dd72'

BRANCH = 'r8q-vold-log-kernel'
WORKFLOW = '.github/workflows/r8q-memory-kernel-review.yml'
ARTIFACT = 'R8Q-VOLD-LOG-KERNEL-OFFLINE-REVIEW'


def valid_run(run):
    return (all(run.get(key)==value for key,value in dict(head_sha=SOURCE_COMMIT,
        head_branch=BRANCH,path=WORKFLOW,status='completed',conclusion='success').items())
        and run.get('repository',{}).get('full_name')==trusted.REPO)


def select_artifact(rows):
    matches = [r for r in rows if r.get('name')==ARTIFACT and r.get('expired') is False]
    if len(matches)!=1:
        raise ValueError('Expected one unexpired memory kernel artifact')
    row=matches[0]
    if (not re.fullmatch('sha256:[0-9a-f]{64}',row.get('digest',''))
        or type(row.get('id')) is not int or row['id']<=0
        or type(row.get('size_in_bytes')) is not int or not 0<row['size_in_bytes']<=512*1024**2):
        raise ValueError('Memory kernel artifact identity/digest/size is invalid')
    return row


def resolve():
    chosen=None
    pending=False
    # API pages are bounded and filtered by immutable commit and exact branch.
    # A missing/expired dependency fails clearly; no unrelated latest build is used.
    for page in range(1,6):
        runs=trusted.api('actions/workflows/r8q-memory-kernel-review.yml/runs?head_sha='+SOURCE_COMMIT+
                         '&branch='+BRANCH+'&per_page=100&page='+str(page))['workflow_runs']
        for candidate in sorted(runs,key=lambda r:r.get('run_attempt',0),reverse=True):
            run=trusted.api('actions/runs/'+str(candidate['id']))
            if (run.get('head_sha')==SOURCE_COMMIT and run.get('head_branch')==BRANCH
                and run.get('path')==WORKFLOW and run.get('status')in ('queued','in_progress','waiting')):
                pending=True
            if not valid_run(run):continue
            try: artifact=select_artifact(trusted.api('actions/runs/'+str(run['id'])+'/artifacts?per_page=100')['artifacts'])
            except ValueError:continue
            chosen=(run,artifact);break
        if chosen or len(runs)<100:break
    return chosen,pending


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--wait-minutes',type=int,choices=range(31),default=0)
    args=parser.parse_args()
    deadline=time.monotonic()+args.wait_minutes*60
    while True:
        chosen,pending=resolve()
        if chosen or not pending or time.monotonic()>=deadline:break
        print('Waiting for the exact-source memory kernel workflow; no substitute is accepted.',flush=True)
        time.sleep(min(30,max(0,deadline-time.monotonic())))
    if chosen is None:
        raise ValueError('No successful unexpired exact-source memory build. Re-run its source workflow; do not substitute another kernel.')
    run,artifact=chosen
    args.output.mkdir(parents=True,exist_ok=False)
    archive=args.output/'kernel-artifact.zip'
    environment=os.environ.copy();environment.pop('GH_DEBUG',None);environment['GH_HOST']='github.com'
    with archive.open('xb')as stream:
        result=subprocess.run(['gh','api','repos/'+trusted.REPO+'/actions/artifacts/'+str(artifact['id'])+'/zip'],
            stdout=stream,stderr=subprocess.PIPE,env=environment,timeout=300)
    if result.returncode:raise ValueError('Memory artifact download failed; credentials were not logged')
    digest=artifact['digest'].split(':',1)[1]
    if archive.stat().st_size!=artifact['size_in_bytes'] or trusted.sha_file(archive)!=digest:
        raise ValueError('Downloaded kernel artifact differs from GitHub digest/size')
    evidence=trusted.extract_verified(archive,args.output)
    provenance=dict(status='VERIFIED_SOURCE_KERNEL_RUN_AND_LINKED_FILES',source_run=run['html_url'],
        source_commit=SOURCE_COMMIT,artifact_id=artifact['id'],artifact_zip_sha256=digest,
        kernel_sha256=evidence['kernel_sha256'],embedded_config_sha256=evidence['embedded_config_sha256'])
    (args.output/'PROVENANCE.json').write_text(json.dumps(provenance,indent=2)+'\n')
    archive.unlink()
    print(json.dumps(provenance,indent=2))


if __name__=='__main__':main()
