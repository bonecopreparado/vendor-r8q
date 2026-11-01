#!/usr/bin/env python3
"""Run official AOSP host checkvintf against the exact P0 metadata export.

Tool discovery is recorded and content-pinned in tool-lock.json. A downloaded
tool from another Android API is diagnostic only and cannot satisfy this gate.
The process can succeed while compatibility is BLOCKED: see gate.json, never
infer ROM readiness from the CI job color or this script's exit code.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[2]
CI='https://ci.android.com/builds'
INPUT_SHA256='f17ddd9728493043147ab5506a4123e1c613e0570943962904e789ce08030432'


class OfficialRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        parsed=urllib.parse.urlsplit(newurl);host=parsed.hostname or ''
        if parsed.scheme!='https' or not (host=='ci.android.com' or host.endswith('.googleapis.com') or host.endswith('.googleusercontent.com')):
            raise ValueError('Unexpected official artifact redirect host')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


OPENER=urllib.request.build_opener(OfficialRedirects())


def fetch(url,limit=8*1024**2):
    with OPENER.open(url,timeout=45) as response:
        data=response.read(limit+1)
        if len(data)>limit:raise ValueError('Unexpected large discovery document')
        return data


def props(blob):
    return dict(re.findall(r'^([^#=\r\n]+)=(.*)$',blob.decode(errors='replace'),re.M))


def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def dump(path,data):path.write_text(json.dumps(data,indent=2)+'\n')


def discover(out):
    attempts=[];fallback=None
    for branch in ['aosp-android17-release','aosp-android-latest-release','aosp-main']:
        url=f'{CI}/branches/{branch}/status.json'
        try:
            blob=fetch(url);status=json.loads(blob)
            (out/(branch+'-status.json')).write_bytes(blob)
            targets=[t for t in status['targets'] if 'x86_64' in t.get('name','') and 'phone' in t.get('name','') and 'userdebug' in t.get('name','')]
            targets.sort(key=lambda t:(t['name']!='aosp_cf_x86_64_only_phone-userdebug',t['name']))
            for t in targets[:3]:
                target=t['name'];bid=str(t['last_known_good_build'])
                if not re.fullmatch(r'[0-9]+',bid) or not re.fullmatch(r'[A-Za-z0-9_.-]+',target):raise ValueError('Invalid official build identity')
                propurl=f'{CI}/submitted/{bid}/{target}/latest/raw/build.prop'
                propblob=fetch(propurl);p=props(propblob)
                release=p.get('ro.system.build.version.release',p.get('ro.build.version.release',''))
                sdk=p.get('ro.system.build.version.sdk',p.get('ro.build.version.sdk',''))
                row=dict(branch=branch,build_id=bid,target=target,build_prop_url=propurl,
                         build_prop_sha256=hashlib.sha256(propblob).hexdigest(),release=release,sdk=sdk,
                         build_fingerprint=p.get('ro.system.build.fingerprint',p.get('ro.build.fingerprint','')))
                attempts.append(row)
                if fallback is None:fallback=(row,propblob)
                if release=='17' and sdk=='37':
                    dump(out/'discovery.json',attempts);(out/'official-build.prop').write_bytes(propblob)
                    return row
        except (OSError,ValueError,KeyError,TypeError) as exc:
            attempts.append(dict(branch=branch,error=type(exc).__name__))
    dump(out/'discovery.json',attempts)
    if fallback:
        (out/'official-build.prop').write_bytes(fallback[1]);return fallback[0]
    raise RuntimeError('No official AOSP otatools build could be discovered')


def download_tools(row,out):
    url=f"{CI}/submitted/{row['build_id']}/{row['target']}/latest/raw/otatools.zip"
    archive=out/'otatools.zip';size=0
    with OPENER.open(url,timeout=45) as response,archive.open('xb') as f:
        while data:=response.read(1024*1024):
            size+=len(data)
            if size>2*1024**3:raise ValueError('Official otatools archive exceeded limit')
            f.write(data)
    actual=digest(archive)
    if row.get('sha256') and actual!=row['sha256']:raise ValueError('Official otatools differs from reviewed lock SHA256')
    lock=dict(row,url=url,bytes=size,sha256=actual,source='official ci.android.com artifact via HTTPS',
              pin_scope='reviewed lock verified' if row.get('sha256') else 'discovered once and locked for this execution; do not call this a pre-reviewed version pin')
    dest=out/'otatools';dest.mkdir()
    with zipfile.ZipFile(archive) as z:
        names=[i for i in z.infolist() if i.filename=='bin/checkvintf' or i.filename.startswith('lib64/')]
        if not any(i.filename=='bin/checkvintf' for i in names):raise ValueError('Official otatools has no host checkvintf')
        for info in names:
            relative=Path(info.filename)
            if relative.is_absolute() or '..' in relative.parts or (info.external_attr>>16)&0o170000==0o120000:raise ValueError('Unsafe tools archive member')
            if info.is_dir():continue
            target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True)
            with z.open(info) as src,target.open('wb') as dst:shutil.copyfileobj(src,dst,1024*1024)
            target.chmod(0o755 if relative==Path('bin/checkvintf') else 0o644)
    binary=dest/'bin/checkvintf';lock['checkvintf_sha256']=digest(binary)
    dump(out/'tool-lock.json',lock)
    archive.unlink()  # Preserve hashes and exact binary/libs, not the entire ~500 MiB ZIP.
    return binary,lock


def unpack_inputs(out):
    bundle=ROOT/'ci-r8q/inputs/checkvintf-inputs.tar.gz'
    if digest(bundle)!=INPUT_SHA256:raise ValueError('Exact P0 metadata bundle identity changed')
    dest=out/'input';dest.mkdir()
    with tarfile.open(bundle,'r:gz') as archive:
        total=0
        for entry in archive:
            p=Path(entry.name)
            if p.is_absolute() or '..' in p.parts or entry.issym() or entry.islnk():raise ValueError('Unsafe metadata bundle')
            total+=entry.size
            if total>32*1024**2:raise ValueError('Metadata bundle exceeded bound')
            if entry.isdir():continue
            if not entry.isfile():raise ValueError('Unsupported metadata member')
            data=archive.extractfile(entry).read();target=dest/p
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
    base=dest/'checkvintf-inputs';manifest=json.loads((base/'manifest.json').read_text())
    for row in manifest['files']:
        if digest(base/'root'/row['host'])!=row['sha256']:raise ValueError('Metadata SHA mismatch: '+row['host'])
    if digest(base/'kernel.config')!=manifest['kernel']['config_sha256']:raise ValueError('Kernel config SHA mismatch')
    return base,manifest,digest(bundle)


def execute(binary,args,name,out):
    argv=[str(binary)]+list(map(str,args))
    env=os.environ|{'LD_LIBRARY_PATH':str(binary.parent.parent/'lib64')}
    try:
        p=subprocess.run(argv,capture_output=True,text=True,timeout=90,env=env)
        row=dict(name=name,argv=argv,exit=p.returncode,stdout=p.stdout,stderr=p.stderr)
    except (OSError,subprocess.TimeoutExpired) as exc:
        row=dict(name=name,argv=argv,exit=None,error=type(exc).__name__)
    dump(out/(name+'.json'),row)
    print(name,'exit',row['exit'],flush=True)
    return row


def classify_results(matching,runs):
    """Interpret Android17 check_vintf.cpp sysexits without hiding tool failures.

    --help legitimately returns EX_USAGE(64). Full checks return EX_OK(0),
    EX_DATAERR(65) for an incompatibility, or EX_SOFTWARE(70) when metadata
    could not be loaded/combined or another VINTF operation returned an error.
    A 70 is not proof of a plain compatibility mismatch. Signals and invalid
    invocation are execution failures, never ordinary known incompatibilities.
    """
    full=next(r for r in runs if r['name']=='full-metadata-with-candidate-kernel')
    broken=[r['name'] for r in runs if r['exit'] is None or r['exit']<0]
    if broken:return dict(status='BLOCKED_TOOL_EXECUTION_FAILURE',execution_failures=broken)
    if not matching:return dict(status='BLOCKED_TOOL_VERSION_MISMATCH')
    rc=full['exit'];tokens=full.get('stdout','').splitlines()
    if rc==0 and 'COMPATIBLE' in tokens:return dict(status='HOST_CHECK_PASSED_WITH_RUNTIME_LIMITS')
    if rc==65 and 'INCOMPATIBLE' in tokens:return dict(status='BLOCKED_VINTF_INCOMPATIBLE')
    if rc==70:return dict(status='BLOCKED_VINTF_METADATA_ERROR')
    return dict(status='BLOCKED_TOOL_EXECUTION_FAILURE',execution_failures=[full['name']],unexpected_full_exit=rc)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=Path('vintf-results'))
    ap.add_argument('--tool-lock',type=Path,default=ROOT/'ci-r8q/pins/official-otatools.json');args=ap.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    gate=dict(status='BLOCKED_NOT_EXECUTED',release_ready=False,boot_confirmed=False)
    try:
        base,manifest,bundle_sha=unpack_inputs(out)
        if args.tool_lock.is_file():
            row=json.loads(args.tool_lock.read_text())
            if not re.fullmatch(r'[0-9]+',str(row['build_id'])) or not re.fullmatch(r'[A-Za-z0-9_.-]+',row['target']) or not re.fullmatch(r'[a-f0-9]{64}',row['sha256']):
                raise ValueError('Invalid reviewed official tool lock')
        else:row=discover(out)
        binary,lock=download_tools(row,out)
        root=base/'root';properties=[]
        for key,value in manifest['properties'].items():properties+=['--property',key+'='+value]
        maps=[]
        for part in ['system','system_ext','product','vendor','odm','apex']:
            (root/part).mkdir(exist_ok=True);maps+=['--dirmap','/'+part+':'+str(root/part)]
        runs=[execute(binary,['--help'],'help',out),
              execute(binary,['--dump-file-list']+properties,'required-paths',out),
              execute(binary,['--check-one','--dirmap','/system:'+str(root/'system'),'--dirmap','/system_ext:'+str(root/'system_ext'),'--dirmap','/product:'+str(root/'product'),'--dirmap','/apex:'+str(root/'apex')]+properties,'framework-consistency',out),
              execute(binary,['--check-one','--dirmap','/vendor:'+str(root/'vendor'),'--dirmap','/odm:'+str(root/'odm'),'--dirmap','/apex:'+str(root/'apex')]+properties,'device-consistency',out),
              execute(binary,['--check-compat']+maps+properties,'full-metadata-no-kernel',out),
              execute(binary,['--check-compat']+maps+properties+['--kernel',manifest['kernel']['release']+':'+str(base/'kernel.config')],'full-metadata-with-candidate-kernel',out)]
        pairs=[('framework-manifest-vendor-matrix',root/'system/etc/vintf/manifest.xml',root/'vendor/etc/vintf/compatibility_matrix.xml'),
               ('vendor-manifest-framework-base-matrix',root/'vendor/etc/vintf/manifest.xml',root/'system/etc/vintf/compatibility_matrix.device.xml')]
        for name,a,b in pairs:
            if a.is_file() and b.is_file():runs.append(execute(binary,[a,b],name,out))
        matching=lock['release']=='17' and lock['sdk']=='37'
        full=next(r for r in runs if r['name']=='full-metadata-with-candidate-kernel')
        gate.update(classify_results(matching,runs))
        gate.update(tool_android17_api37=matching,input_bundle_sha256=bundle_sha,full_check_exit=full['exit'],
                    tool_lock=lock,input_limits=manifest['limitations'],runs=[dict(name=r['name'],exit=r['exit']) for r in runs],
                    interpretation=['Full --check-compat combines checkCompatibility, checkDeprecation and additional HAL checks; there is no standalone deprecation CLI flag.',
                                    'Legacy manifest/matrix pair runs check only those literal documents, without combining fragments; they are targeted diagnostics.',
                                    'The no-kernel run skips runtime kernel checks; the kernel run uses actual P0 embedded version/config, never CI host uname.',
                                    'Host metadata success does not establish Android OEM libvintf behavior, service ABI, SELinux load or boot.'])
        dump(out/'results.json',dict(gate=gate,runs=runs))
    except (OSError,ValueError,RuntimeError,KeyError,zipfile.BadZipFile,tarfile.TarError) as exc:
        gate.update(status='BLOCKED_TOOL_OR_INPUT_FAILURE',error_type=type(exc).__name__,error=str(exc))
    dump(out/'gate.json',gate)
    print(json.dumps(gate,indent=2))


if __name__=='__main__':main()
