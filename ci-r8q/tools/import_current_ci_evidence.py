"""Import only successful main CI evidence for the release's exact commit.

Run in GitHub Actions with GH_TOKEN, GITHUB_REPOSITORY and GITHUB_SHA. No stale
artifact IDs, previous-commit fallbacks, ROM inputs or compiler binaries are used.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = '.github/workflows/r8q-ci.yml'
ARTIFACTS = ('R8Q-POLICY-CONTEXT-EVIDENCE','R8Q-VINTF-EVIDENCE')
LIMIT = 128 * 1024**2
REQUIRED = {'ci-results/policy/result.json','context-results/result.json',
            'vintf-results/gate.json','vintf-results/results.json','vintf-results/tool-lock.json'}


def gh_bytes(path, limit=LIMIT):
    # GitHub's artifact size is checked before download and the received size
    # is checked again. The CLI handles GitHub's authenticated storage redirect.
    result = subprocess.run(['gh','api',path],capture_output=True,timeout=120)
    if result.returncode:
        raise RuntimeError('GitHub API request failed; no previous-run fallback is permitted')
    if len(result.stdout)>limit:
        raise ValueError('GitHub response exceeds the 128 MiB bound')
    return result.stdout


def api(path):
    return json.loads(gh_bytes(path,4*1024**2))


def validate_run(run, sha):
    return (run.get('head_sha')==sha and run.get('head_branch')=='main'
            and run.get('path')==WORKFLOW and run.get('status')=='completed'
            and run.get('conclusion')=='success')


def choose_run(runs, sha):
    eligible=[run for run in runs if validate_run(run,sha)]
    return max(eligible,key=lambda run:run['id']) if eligible else None


def report_path(artifact_name, name):
    parts=PurePosixPath(name).parts
    if artifact_name=='R8Q-POLICY-CONTEXT-EVIDENCE':
        if len(parts)==3 and parts[:2]==('ci-results','policy') and Path(name).suffix in {'.json','.log'}:
            return name
        if len(parts)==2 and parts[0]=='context-results' and Path(name).suffix in {'.json','.txt'}:
            return name
    elif artifact_name=='R8Q-VINTF-EVIDENCE':
        # upload-artifact strips the sole vintf-results root directory.
        if len(parts)==1 and Path(name).suffix=='.json':
            return 'vintf-results/'+name
        if len(parts)==2 and parts[0]=='vintf-results' and Path(name).suffix=='.json':
            return name
    return None


def decode_reports(artifact_name, blob):
    if artifact_name not in ARTIFACTS or len(blob)>LIMIT:
        raise ValueError('Unexpected or oversized evidence artifact')
    reports={};seen=set();expanded=0
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        if len(archive.infolist())>2000:
            raise ValueError('Too many evidence members')
        for entry in archive.infolist():
            name=entry.filename
            if (name in seen or name.startswith('/') or '\\' in name or '\0' in entry.orig_filename
                    or any(part in {'.','..'} for part in name.rstrip('/').split('/'))):
                raise ValueError('Duplicate or unsafe evidence path')
            seen.add(name)
            mode=entry.external_attr>>16
            if mode&0o170000==0o120000 or entry.flag_bits&1:
                raise ValueError('Symlink or encrypted evidence is forbidden')
            expanded+=entry.file_size
            if expanded>LIMIT:
                raise ValueError('Expanded evidence exceeds 128 MiB')
            if entry.is_dir():continue
            destination=report_path(artifact_name,name)
            if destination is None:continue
            if entry.file_size>8*1024**2:
                raise ValueError('Individual report exceeds 8 MiB')
            data=archive.read(entry)
            data.decode('utf-8')
            if b'\0' in data:raise ValueError('Non-text report')
            if destination in reports:raise ValueError('Duplicate destination report')
            reports[destination]=data
    return reports


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--wait-seconds',type=int,default=600)
    args=parser.parse_args()
    if not 0<=args.wait_seconds<=600:raise ValueError('Wait bound must be 0..600 seconds')
    repo=os.environ.get('GITHUB_REPOSITORY','')
    sha=os.environ.get('GITHUB_SHA','')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo) or not re.fullmatch('[0-9a-f]{40}',sha):
        raise ValueError('Exact GitHub repository and commit are required')
    prefix='repos/'+repo+'/'
    deadline=time.monotonic()+args.wait_seconds
    while True:
        runs=api(prefix+'actions/workflows/r8q-ci.yml/runs?branch=main&head_sha='+sha+'&per_page=100')['workflow_runs']
        run=choose_run(runs,sha)
        if run:break
        if time.monotonic()>=deadline:
            raise RuntimeError('No successful r8q-ci main run exists for this exact commit; release remains blocked')
        print('Waiting for successful main CI at exact release commit '+sha,flush=True)
        time.sleep(min(20,max(0,deadline-time.monotonic())))
    run_id=run['id']
    current=api(prefix+'actions/runs/'+str(run_id))
    if not validate_run(current,sha):raise ValueError('CI run changed before artifact import')
    artifacts=api(prefix+'actions/runs/'+str(run_id)+'/artifacts?per_page=100')['artifacts']
    collected={};provenance=[];downloaded=0
    for name in ARTIFACTS:
        matching=[a for a in artifacts if a['name']==name and not a.get('expired')]
        if len(matching)!=1:raise ValueError('Required current-run evidence missing or duplicated: '+name)
        artifact=matching[0]
        if not 0<artifact['size_in_bytes']<=LIMIT:raise ValueError('Artifact size bound exceeded')
        blob=gh_bytes(prefix+'actions/artifacts/'+str(artifact['id'])+'/zip')
        downloaded+=len(blob)
        if downloaded>LIMIT:raise ValueError('Total downloaded evidence exceeds 128 MiB')
        for path,data in decode_reports(name,blob).items():
            if path in collected:raise ValueError('Evidence artifacts overlap')
            collected[path]=data
        provenance.append(dict(name=name,id=artifact['id'],bytes=len(blob),sha256=hashlib.sha256(blob).hexdigest()))
    if not REQUIRED<=set(collected):raise ValueError('Required policy/context/VINTF reports missing')
    if not validate_run(api(prefix+'actions/runs/'+str(run_id)),sha):
        raise ValueError('CI run changed during artifact import')
    # Validate the complete archive set before writing any imported report.
    for relative,data in collected.items():
        destination=ROOT/relative
        cursor=ROOT
        for part in Path(relative).parts:
            cursor=cursor/part
            if cursor.is_symlink():raise ValueError('Destination symlink forbidden')
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes(data)
    provenance_path=ROOT/'ci-results/imported-ci-evidence.json'
    provenance_path.write_text(json.dumps(dict(commit=sha,run_id=run_id,workflow=WORKFLOW,
        branch='main',conclusion='success',artifacts=provenance,imported_reports=sorted(collected)),indent=2)+'\n')
    print('Imported exact-commit policy/context/VINTF evidence from successful run '+str(run_id))


if __name__=='__main__':main()
