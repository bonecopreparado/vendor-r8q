"""Fetch a successful pinned kernel run, verify the ZIP and all linked files."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import urllib.request
import zipfile

REPO='bonecopreparado/vendor-r8q'
BRANCH='r8q-susfs22-compile-20261114'
WORKFLOW='.github/workflows/r8q-susfs22-compile.yml'
ARTIFACT='R8Q-SUSFS22-NFLOG-OFFLINE-REVIEW-NOT-FLASHABLE'
COMPLETE_BRANCH='r8q-p1r4-scheduler-20261115'
COMPLETE_WORKFLOW='.github/workflows/r8q-p1r4-singlezip.yml'
KERNEL_JOB='Compile pinned NFLOG and SUSFS kernel'
ROOT=Path(__file__).resolve().parents[2]


def sha_file(path):
    with path.open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def validate_run(run,commit,same_run=False):
    expected=dict(head_sha=commit,head_branch=COMPLETE_BRANCH if same_run else BRANCH,
                  path=COMPLETE_WORKFLOW if same_run else WORKFLOW)
    if not same_run:expected.update(status='completed',conclusion='success')
    if any(run.get(key)!=value for key,value in expected.items())or run.get('repository',{}).get('full_name')!=REPO:
        raise ValueError('Kernel workflow/run/repository identity or success differs')
    if same_run and run.get('status')not in ('in_progress','completed'):
        raise ValueError('Unexpected complete-build run status')


def validate_kernel_job(jobs):
    matches=[job for job in jobs if job.get('name')==KERNEL_JOB]
    if len(matches)!=1 or matches[0].get('status')!='completed'or matches[0].get('conclusion')!='success':
        raise ValueError('The current run has no successful completed kernel job')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ValueError('Unexpected metadata redirect; credentials were not forwarded')


def api(path):
    token=os.environ.get('GH_TOKEN')
    if not token:raise ValueError('GitHub token with actions:read is required')
    request=urllib.request.Request('https://api.github.com/repos/'+REPO+'/'+path,
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                 'X-GitHub-Api-Version':'2022-11-28'})
    with urllib.request.build_opener(NoRedirect).open(request,timeout=60)as response:
        data=response.read(2*1024**2+1)
    if len(data)>2*1024**2:raise ValueError('Metadata exceeds bound')
    return json.loads(data)


def extract_verified(archive,output):
    with zipfile.ZipFile(archive)as package:
        entries=package.infolist()
        if len(entries)>256 or sum(row.file_size for row in entries)>512*1024**2:
            raise ValueError('Kernel artifact exceeds bounds')
        names=[row.filename for row in entries]
        for row in entries:
            p=PurePosixPath(row.filename)
            if p.is_absolute()or '..'in p.parts or '\\'in row.filename or stat.S_ISLNK(row.external_attr>>16):
                raise ValueError('Unsafe kernel artifact member')
        for name in ('Image','vmlinux','System.map','summary.json'):
            if names.count(name)!=1:raise ValueError('Missing/duplicate linked artifact: '+name)
        if package.getinfo('summary.json').file_size>1024**2:raise ValueError('Oversized kernel summary')
        summary=json.loads(package.read('summary.json'))
        if summary.get('independent_linked_image_verification_passed')is not True:
            raise ValueError('The source workflow did not verify its actual embedded configuration')
        for name in ('Image','vmlinux','System.map'):
            expected=summary.get('outputs',{}).get(name,{})
            if package.getinfo(name).file_size!=expected.get('bytes'):
                raise ValueError('Linked file size differs: '+name)
            digest=hashlib.sha256()
            # Read/hash vmlinux and System.map without extracting their larger
            # bytes. Only Image/summary are needed for the subsequent ROM build.
            with package.open(name)as source:
                target=(output/name).open('xb')if name=='Image'else None
                try:
                    while data:=source.read(1024**2):
                        digest.update(data)
                        if target is not None:target.write(data)
                finally:
                    if target is not None:target.close()
            if digest.hexdigest()!=expected.get('sha256'):
                raise ValueError('Linked file SHA differs: '+name)
        with (output/'summary.json').open('x')as stream:stream.write(json.dumps(summary,indent=2)+'\n')
    sys.path.insert(0,str(ROOT/'tools/kernel_nflog/susfs22'))
    import verify_linked
    return verify_linked.verify((output/'Image').read_bytes(),summary)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',type=int,required=True)
    parser.add_argument('--expected-commit',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--same-run',action='store_true',help='Use the completed kernel dependency of the pinned complete-ROM workflow')
    args=parser.parse_args()
    if args.run_id<=0 or not re.fullmatch('[0-9a-f]{40}',args.expected_commit):parser.error('Expected positive run ID and full source commit')
    run=api('actions/runs/'+str(args.run_id))
    validate_run(run,args.expected_commit,args.same_run)
    if args.same_run:
        validate_kernel_job(api('actions/runs/'+str(args.run_id)+'/jobs?filter=latest&per_page=100')['jobs'])
    rows=api('actions/runs/'+str(args.run_id)+'/artifacts?per_page=100')['artifacts']
    matches=[row for row in rows if row['name']==ARTIFACT and not row['expired']]
    if len(matches)!=1:raise ValueError('Expected one current kernel artifact in this run')
    artifact=matches[0]
    digest=artifact.get('digest','')
    if not re.fullmatch('sha256:[0-9a-f]{64}',digest)or not 0<artifact['size_in_bytes']<=512*1024**2:
        raise ValueError('Artifact digest/size unavailable or outside bounds')
    args.output.mkdir(parents=True,exist_ok=False)
    archive=args.output/'kernel-artifact.zip'
    environment=os.environ.copy();environment.pop('GH_DEBUG',None);environment['GH_HOST']='github.com'
    with archive.open('xb')as stream:
        result=subprocess.run(['gh','api','repos/'+REPO+'/actions/artifacts/'+str(artifact['id'])+'/zip'],
            stdout=stream,stderr=subprocess.PIPE,env=environment,timeout=300)
    if result.returncode:raise ValueError('GitHub artifact download failed; API credentials/responses were not logged')
    if archive.stat().st_size!=artifact['size_in_bytes']or sha_file(archive)!=digest.split(':',1)[1]:
        raise ValueError('Downloaded artifact ZIP differs from GitHub digest/size')
    evidence=extract_verified(archive,args.output)
    provenance=dict(status='VERIFIED_SOURCE_KERNEL_RUN_AND_LINKED_FILES',source_run=run['html_url'],
        source_commit=args.expected_commit,artifact_id=artifact['id'],artifact_zip_sha256=digest.split(':',1)[1],
        kernel_sha256=evidence['kernel_sha256'],embedded_config_sha256=evidence['embedded_config_sha256'])
    (args.output/'PROVENANCE.json').write_text(json.dumps(provenance,indent=2)+'\n')
    archive.unlink()
    print(json.dumps(provenance,indent=2))


if __name__=='__main__':main()
