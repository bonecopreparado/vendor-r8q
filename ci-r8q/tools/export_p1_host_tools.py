"""Export pinned host-only tools with source/relink material; never ROM inputs."""
from pathlib import Path
import gzip
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tarfile
import urllib.parse
import zipfile

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'host-tools-output';OUT.mkdir(exist_ok=False)
STAGE=OUT/'p1-host';STAGE.mkdir()
pin=json.loads((ROOT/'ci-r8q/pins/official-otatools.json').read_text())
if pin['release']!='17' or pin['sdk']!='37' or pin['build_id']!='16644040':
    raise ValueError('Unexpected reviewed AOSP tool identity')
module_spec=importlib.util.spec_from_file_location('official_vintf',ROOT/'ci-r8q/tools/run_checkvintf.py')
official=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(official)
archive=OUT/'otatools.zip';sha=hashlib.sha256();size=0
with official.OPENER.open(pin['url'],timeout=45) as response,archive.open('xb') as target:
    while blob:=response.read(1024*1024):
        size+=len(blob)
        if size>pin['bytes']:raise ValueError('Official archive exceeds reviewed size')
        sha.update(blob);target.write(blob)
if size!=pin['bytes'] or sha.hexdigest()!=pin['sha256']:
    raise ValueError('Official archive differs from reviewed size/hash')
wanted={'bin/checkvintf','bin/host_init_verifier','bin/idmap2','bin/aapt2'}
found=[];notices=[];expanded=0
with zipfile.ZipFile(archive) as source:
    seen=set()
    for entry in source.infolist():
        name=entry.filename
        if name in seen:raise ValueError('Duplicate official ZIP path')
        seen.add(name)
        selected=name in wanted or name.startswith('lib64/')
        notice=Path(name).name.upper() in {'NOTICE','NOTICE.TXT','LICENSE','LICENSE.TXT'}
        if not selected and not notice:continue
        p=Path(name)
        if p.is_absolute() or '..' in p.parts or '\\' in name or (entry.external_attr>>16)&0o170000==0o120000:
            raise ValueError('Unsafe official ZIP member')
        if entry.is_dir():continue
        expanded+=entry.file_size
        if expanded>2*1024**3 or (notice and entry.file_size>16*1024**2):
            raise ValueError('Unexpected official tool size')
        dest=STAGE/('aosp/'+name if selected else 'aosp-notices/'+name)
        dest.parent.mkdir(parents=True,exist_ok=True)
        with source.open(entry) as src,dest.open('xb') as dst:shutil.copyfileobj(src,dst,1024*1024)
        dest.chmod(0o755 if name in wanted else 0o644)
        if name in wanted:found.append(name)
        if notice:notices.append(name)
if 'bin/checkvintf' not in found:raise ValueError('Official checkvintf missing')
if hashlib.sha256((STAGE/'aosp/bin/checkvintf').read_bytes()).hexdigest()!=pin['checkvintf_sha256']:
    raise ValueError('Official checkvintf binary differs')
archive.unlink()

sources=STAGE/'relink';sources.mkdir()
for src,dest in [('ci-r8q/tools/check_contexts.c','check_contexts.c'),
                 ('ci-r8q/tools/check_context_traits.c','check_context_traits.c'),
                 ('.deps/policy-bundle/check_policy_caps.c','check_policy_caps.c')]:
    shutil.copyfile(ROOT/src,sources/dest)
upstream='6423998bc7b154da7f9fe726cfda9ace774dfa94'
actual=subprocess.check_output(['git','-C',str(ROOT/'.deps/selinux'),'rev-parse','HEAD'],text=True).strip()
if actual!=upstream:raise ValueError('SELinux source revision differs')
with (sources/'selinux-source.tar').open('wb') as output:
    subprocess.run(['git','-C',str(ROOT/'.deps/selinux'),'archive',upstream],stdout=output,check=True)
shutil.copyfile(ROOT/'.deps/selinux/libsepol/src/libsepol.a',sources/'libsepol.a')
for name in ('check-contexts','check-context-traits','check-policy-caps','secilc-host'):
    shutil.copyfile(ROOT/'build'/name,STAGE/name);(STAGE/name).chmod(0o755)
    shutil.copyfile(ROOT/'build'/(name+'.o'),sources/(name+'.o'))
for path in (ROOT/'licenses').glob('SELinux-*.txt'):
    shutil.copyfile(path,sources/path.name)
(sources/'BUILD-AND-RELINK.txt').write_text('''SELinux source pin: 6423998bc7b154da7f9fe726cfda9ace774dfa94
Extract selinux-source.tar in a new directory. This includes the full exact
corresponding upstream source and license notices. libsepol.a is the static
library used for these binaries; the four .o files permit relinking against a
modified compatible libsepol. No ROM policy/config input is included.

make -C libsepol/src -j2 libsepol.a
cc -D_GNU_SOURCE -Ilibsepol/include -Ilibsepol/cil/include -c secilc/secilc.c -o secilc-host.o
cc secilc-host.o libsepol/src/libsepol.a -o secilc-host
cc -Wall -Wextra -Werror -Ilibsepol/include -c ../check_contexts.c -o check-contexts.o
cc check-contexts.o libsepol/src/libsepol.a -o check-contexts
cc -Wall -Wextra -Werror -Ilibsepol/include -c ../check_context_traits.c -o check-context-traits.o
cc check-context-traits.o libsepol/src/libsepol.a -o check-context-traits
cc -Ilibsepol/include -c ../check_policy_caps.c -o check-policy-caps.o
cc check-policy-caps.o libsepol/src/libsepol.a -o check-policy-caps

For a supplied existing object file: cc NAME.o MODIFIED_LIBSEPOL.a -o NAME
The supplied objects were built on Ubuntu24.04 x86_64 using the commands above.
The system C runtime is not redistributed. Use a compatible Linux x86_64 host.
''')
provenance=dict(status='HOST_DIAGNOSTIC_TOOLS_NOT_FLASHABLE',official_aosp=pin,
                available_tools=sorted(found),missing_optional_tools=sorted(wanted-set(found)),
                copied_upstream_notice_paths=notices,selinux_source_commit=upstream,
                repository_commit=os.environ.get('GITHUB_SHA'),
                run=os.environ.get('GITHUB_RUN_ID'),contains_rom_inputs=False)
(STAGE/'PROVENANCE.json').write_text(json.dumps(provenance,indent=2)+'\n')
(STAGE/'README.txt').write_text('Host Linux x86_64 diagnostic tools. Not a recovery archive or ROM.\nAOSP tools use aosp/lib64 through LD_LIBRARY_PATH. SELinux source and relink material are in relink/.\n')
checks={str(p.relative_to(STAGE)):dict(bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),mode=p.stat().st_mode&0o777)
        for p in sorted(STAGE.rglob('*')) if p.is_file()}
(STAGE/'MANIFEST.json').write_text(json.dumps(checks,indent=2)+'\n')
dest=OUT/'R8Q-P1-HOST-TOOLS-NOT-FLASHABLE.tar.gz'
with dest.open('wb') as stream,gzip.GzipFile(filename='',mode='wb',mtime=0,fileobj=stream,compresslevel=6) as compressed:
    with tarfile.open(fileobj=compressed,mode='w') as tar:
        for path in sorted(STAGE.rglob('*')):
            if not path.is_file():continue
            info=tarfile.TarInfo('p1-host/'+str(path.relative_to(STAGE)))
            info.size=path.stat().st_size;info.mode=path.stat().st_mode&0o777;info.mtime=0
            with path.open('rb') as src:tar.addfile(info,src)
digest=hashlib.sha256(dest.read_bytes()).hexdigest()
(OUT/(dest.name+'.sha256')).write_text(digest+'  '+dest.name+'\n')
print(json.dumps(dict(file=dest.name,bytes=dest.stat().st_size,sha256=digest,tools=found,expanded_bytes=expanded),indent=2))
