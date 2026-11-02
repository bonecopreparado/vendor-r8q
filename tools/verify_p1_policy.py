"""Validate CIL and context references read afresh from actual P1 filesystems.

All images are opened read-only. No cached fs-config export is accepted as an
input. Policy compilation uses Android-init-compatible host flags and keeps
every capability; this does not load a policy into the phone kernel.
"""
from pathlib import Path
from collections import defaultdict
import argparse,hashlib,json,re,struct,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ci-r8q/vendor_audit'))
from ext4_readonly import Ext4
LABEL=re.compile(r'^u:[A-Za-z0-9_]+:[A-Za-z0-9_]+:s[0-9]+(?:[-:][A-Za-z0-9_:.,-]+)?$')
CAPS=('network_peer_controls','open_perms','extended_socket_class','nnp_nosuid_transition','netlink_xperm','functionfs_seclabel')
SPEC=(
 ('system','/system/etc/selinux/plat_sepolicy.cil','system_plat_sepolicy.cil'),
 ('system','/system/etc/selinux/mapping/30.0.cil','system_mapping_30.0.cil'),
 ('system','/system/etc/selinux/mapping/30.0.compat.cil','system_mapping_30.0.compat.cil'),
 ('system_ext','/etc/selinux/system_ext_sepolicy.cil','system_ext_system_ext_sepolicy.cil'),
 ('system_ext','/etc/selinux/mapping/30.0.cil','system_ext_mapping_30.0.cil'),
 ('system_ext','/etc/selinux/mapping/30.0.compat.cil','system_ext_mapping_30.0.compat.cil'),
 ('product','/etc/selinux/product_sepolicy.cil','product_product_sepolicy.cil'),
 ('product','/etc/selinux/mapping/30.0.cil','product_mapping_30.0.cil'),
 ('vendor','/etc/selinux/plat_pub_versioned.cil','vendor_plat_pub_versioned.cil'),
 ('vendor','/etc/selinux/vendor_sepolicy.cil','vendor_vendor_sepolicy.cil'))
SHA=lambda b:hashlib.sha256(b).hexdigest()

def file_sha(path):
    with path.open('rb')as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def command(argv,timeout=90):
    result=subprocess.run(list(map(str,argv)),capture_output=True,timeout=timeout)
    return result

class Filesystem:
    def __init__(self,image):
        self.image=Path(image);self.ext=None;self.cache={}
        with self.image.open('rb')as f:f.seek(1024);magic=f.read(4)
        self.erofs=magic==bytes.fromhex('e2e1f5e0')
        if not self.erofs:self.ext=Ext4(self.image)
    def close(self):
        if self.ext:self.ext.close()
    def ls(self,path):
        if path in self.cache:return self.cache[path]
        if self.ext:
            try:rows=list(self.ext.list_dir(path))
            except (FileNotFoundError,ValueError):rows=[]
        else:
            r=command([ROOT/'tools/image-tools/bin/dump.erofs','--ls','--path='+path,self.image])
            rows=[]
            for line in r.stdout.decode(errors='replace').splitlines():
                m=re.match(r'^\s*\d+\s+(\d+)\s+(.+)$',line)
                if m and m[2]not in('.','..'):rows.append((m[2],m[1]=='2'))
        for name,_ in rows:
            if '/'in name or name in('.','..'):raise ValueError('Unsafe filesystem directory entry')
        self.cache[path]=rows;return rows
    def exists(self,path):
        parent,name=path.rsplit('/',1)
        return any(n==name for n,_ in self.ls(parent or '/'))
    def read(self,path):
        if not self.exists(path):raise FileNotFoundError(str(self.image)+':'+path)
        if self.ext:return self.ext.read_file(path,max_bytes=16*1024**2)
        r=command([ROOT/'tools/image-tools/bin/dump.erofs','--cat','--path='+path,self.image])
        if r.returncode or len(r.stdout)>16*1024**2:raise ValueError('Unable to read bounded file '+path)
        return r.stdout
    def walk(self,base):
        todo=[base];seen=set()
        while todo:
            path=todo.pop()
            if path in seen:continue
            seen.add(path)
            if len(seen)>5000:raise ValueError('Unexpected configuration directory tree')
            for name,directory in self.ls(path):
                child=path.rstrip('/')+'/'+name
                if directory:todo.append(child)
                else:yield child

def labels_from_text(part,path,data):
    if b'\0'in data:return []
    found=[]
    for n,line in enumerate(data.decode().splitlines(),1):
        text=line.split('#',1)[0]
        for token in text.split():
            if LABEL.fullmatch(token):found.append((token,dict(partition=part,path=path,line=n,kind='literal_context')))
        if path.endswith('seapp_contexts'):
            for key,value in re.findall(r'\b(domain|type)=([A-Za-z0-9_]+)',text):
                label='u:'+('r'if key=='domain'else'object_r')+':'+value+':s0'
                found.append((label,dict(partition=part,path=path,line=n,kind='seapp_'+key)))
    return found

def labels_from_rc(part,path,data):
    found=[]
    for n,line in enumerate(data.decode().splitlines(),1):
        fields=line.split('#',1)[0].split()
        labels=fields[1:2]if fields[:1]in(['seclabel'],['exec'],['exec_background'],['exec_start'])else[]
        for label in labels:
            if LABEL.fullmatch(label):found.append((label,dict(partition=part,path=path,line=n,kind='init_explicit_context')))
    return found

def check_rows(stdout,expected):
    rows=[];seen=set()
    for line in stdout.splitlines():
        values=line.split('\t')
        if len(values)!=3 or values[0]in seen:raise ValueError('Malformed or duplicate binary checker output')
        label,parse,check=values
        if label not in expected:raise ValueError('Unknown binary checker context')
        seen.add(label);rows.append(dict(context=label,parse_status=int(parse),check_status=int(check)))
    if seen!=set(expected):raise ValueError('Binary checker coverage differs from extracted references')
    return rows

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--images-dir',type=Path,default=ROOT/'candidates/p1')
    ap.add_argument('--product',type=Path,default=ROOT/'extracted/hyperos/product.img')
    ap.add_argument('--output',type=Path,default=ROOT/'reports/p1/policy-validation')
    ap.add_argument('--checker',type=Path)
    ap.add_argument('--require-checker',action='store_true')
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    images={p:(args.product if p=='product'else args.images_dir/(p+'.img')).resolve()for p in('system','system_ext','product','vendor','odm')}
    readers={};report=dict(status='P1_POLICY_VALIDATION_STARTED_NOT_BOOT_TESTED',boot_confirmed=False,images={},cil=[],context_files=[],init_files=[],limits=['Host init-compatible compilation is not a phone kernel load test.','Policy version 30 follows the observed original ODM binary; maximum kernel policy version remains unmeasured.','Dynamic MLS, /data applications, inode xattrs and runtime permission decisions are not validated by label checks.'])
    try:
        for part,path in images.items():
            report['images'][part]=dict(path=str(path),bytes=path.stat().st_size,sha256=file_sha(path))
            readers[part]=Filesystem(path)
        subprocess.run([sys.executable,str(ROOT/'tools/materialize_policy_bundle.py')],check=True)
        manifest_path=ROOT/'reports/audit-20261031/overnight/selinux/policy-bundle/manifest.json'
        manifest=json.loads(manifest_path.read_text());report['reviewed_cil_manifest_sha256']=file_sha(manifest_path)
        provenance=json.loads((ROOT/'tools/selinux-modern/PROVENANCE.json').read_text())
        compiler=ROOT/'tools/selinux-modern/secilc-host';cap_checker=ROOT/'tools/selinux-modern/check-policy-caps'
        if provenance['source_commit']!='6423998bc7b154da7f9fe726cfda9ace774dfa94' or file_sha(compiler)!=provenance['secilc_host_sha256'] or file_sha(cap_checker)!=provenance['cap_checker_sha256']:
            raise ValueError('Pinned compiler/capability tool identity differs')
        report['compiler_tools']={k:provenance[k]for k in('source_repository','source_commit','build_workflow_run','secilc_host_sha256','cap_checker_sha256')}
        # Match the exact already reviewed CIL candidate while proving it is
        # now embedded in the actual new filesystems.
        cil_dir=out/'cils';cil_dir.mkdir(exist_ok=True);inputs=[]
        for part,path,name in SPEC:
            data=readers[part].read(path);candidate='candidate/'+name;original='original/'+name
            expected=manifest['files'][candidate if candidate in manifest['files']else original]
            if SHA(data)!=expected:raise ValueError('Actual embedded CIL identity differs: '+part+':'+path)
            dest=cil_dir/name;dest.write_bytes(data);inputs.append(dest)
            report['cil'].append(dict(partition=part,path=path,bytes=len(data),sha256=SHA(data),matches_reviewed_input=True))
        if readers['vendor'].read('/etc/selinux/plat_sepolicy_vers.txt').strip()!=b'30.0':raise ValueError('Actual vendor sepolicy interface differs from selected mapping')
        if readers['vendor'].exists('/etc/selinux/genfs_labels_version.txt'):raise ValueError('Explicit vendor genfs selection requires separate review')
        report['genfs_selection']='Absent vendor marker; default 202404, without optional dated genfs files. OEM init selection remains unexecuted.'
        removed=['/etc/selinux/precompiled_sepolicy']+['/etc/selinux/precompiled_sepolicy.'+x+'_sepolicy_and_mapping.sha256'for x in('plat','system_ext','product')]
        for path in removed:
            if readers['odm'].exists(path):raise ValueError('Obsolete ODM policy cache remains: '+path)
        report['removed_odm_precompiled_files_verified_absent']=removed
        if readers['vendor'].exists('/etc/selinux/precompiled_sepolicy'):raise ValueError('Unexpected vendor policy cache needs review')
        policy=out/'compiled.policy'
        argv=[compiler,'-m','-M','true','-G','-c','30','-N','-o',policy,'-f',out/'compiled.file_contexts']+inputs
        compiled=command(argv,180);(out/'compiler.log').write_bytes(compiled.stdout+compiled.stderr)
        report['compile']=dict(argv=list(map(str,argv)),exit=compiled.returncode,neverallow_assertions_disabled_like_init=True)
        if compiled.returncode:raise ValueError('Actual P1 CIL compilation failed')
        data=policy.read_bytes();ident_len=struct.unpack_from('<I',data,4)[0]
        if struct.unpack_from('<I',data,0)[0]!=0xf97cff8c or ident_len>64:raise ValueError('Serialized policy header invalid')
        version=struct.unpack_from('<I',data,8+ident_len)[0]
        if version!=30:raise ValueError('Serialized policy version differs')
        caps=command([cap_checker,policy]+list(CAPS))
        (out/'capabilities.log').write_bytes(caps.stdout+caps.stderr)
        if caps.returncode:raise ValueError('Actual P1 policy capabilities differ')
        report['compiled_policy']=dict(bytes=len(data),sha256=SHA(data),version=version,preserved_capabilities=list(CAPS),cap_check_exit=caps.returncode)
        refs=defaultdict(list)
        for part,fs in readers.items():
            prefix='/system'if part=='system'else'';base=prefix+'/etc/selinux'
            for path in fs.walk(base):
                if 'contexts'not in Path(path).name:continue
                blob=fs.read(path);record=dict(partition=part,path=path,bytes=len(blob),sha256=SHA(blob),binary=b'\0'in blob)
                dest=out/'contexts-inputs'/part/path.lstrip('/');dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(blob)
                report['context_files'].append(record)
                for label,ref in labels_from_text(part,path,blob):refs[label].append(ref)
            paths=list(fs.walk(prefix+'/etc/init'))
            if fs.exists('/init.rc'):paths.append('/init.rc')
            for path in sorted(set(p for p in paths if p.endswith('.rc'))):
                blob=fs.read(path);report['init_files'].append(dict(partition=part,path=path,sha256=SHA(blob),bytes=len(blob)))
                for label,ref in labels_from_rc(part,path,blob):refs[label].append(ref)
        labels=sorted(refs);(out/'contexts.txt').write_text('\n'.join(labels)+'\n')
        (out/'references.json').write_text(json.dumps(dict(references=dict(refs)),indent=2)+'\n')
        report['contexts']=dict(unique=len(labels),source_files=len(report['context_files']),actual_init_files=len(report['init_files']))
        if args.checker:
            result=command([args.checker.resolve(),policy,out/'contexts.txt'],120)
            (out/'context-checker.log').write_bytes(result.stdout+result.stderr)
            if result.returncode:raise ValueError('Binary checker input/control failure')
            rows=check_rows(result.stdout.decode(),labels);invalid=[r for r in rows if r['parse_status']or r['check_status']]
            (out/'context-results.json').write_text(json.dumps(rows,indent=2)+'\n')
            report['contexts'].update(binary_checked=True,checker_sha256=file_sha(args.checker.resolve()),valid=len(rows)-len(invalid),invalid=invalid)
            if invalid:raise ValueError('Actual P1 filesystem still references invalid contexts')
            report['status']='ACTUAL_P1_CIL_CAPABILITIES_AND_CONTEXTS_PASSED_HOST_ONLY'
        else:
            report['contexts']['binary_checked']=False;report['status']='ACTUAL_P1_CIL_AND_CAPS_PASSED_CONTEXT_BINARY_CHECK_PENDING'
            if args.require_checker:raise ValueError('Binary context checker is required but unavailable')
    except Exception as exc:
        report['status']='P1_POLICY_VALIDATION_FAILED';report['error']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        for reader in readers.values():reader.close()
        (out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(dict(status=report['status'],error=report.get('error'),contexts=report.get('contexts'),policy=report.get('compiled_policy')),indent=2))

if __name__=='__main__':main()
