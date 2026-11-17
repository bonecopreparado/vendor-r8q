"""Bake the exact R2 firmware into copied Vendor plans and verify real images."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import tempfile

from . import image_labels

HERE=Path(__file__).resolve().parent
PROGRAMS=HERE/'stock-programs.json'


def sha(data):return hashlib.sha256(data).hexdigest()


def split_program(name,data):
    if data[:7]!=b'\x7fELF\x01\x01\x01' or len(data)>128*1024:
        raise ValueError('Expected bounded little-endian ELF32 firmware')
    phoff=struct.unpack_from('<I',data,28)[0]
    ehsize,phsize,count=struct.unpack_from('<HHH',data,40)
    if phoff!=52 or ehsize!=52 or phsize!=32 or count!={'ipa_fws':5,'ipa_uc':3}.get(name):
        raise ValueError('Unexpected firmware ELF program table')
    result={name+'.elf':data}
    spans=[]
    for i in range(count):
        _,offset,_,_,size,_,_,_=struct.unpack_from('<8I',data,phoff+i*phsize)
        if size<=0 or offset>len(data) or size>len(data)-offset:
            raise ValueError('Firmware segment outside ELF')
        if any(offset<a+n and a<offset+size for a,n in spans):
            raise ValueError('Overlapping firmware segments')
        spans.append((offset,size));result[name+'.b%02d'%i]=data[offset:offset+size]
    if spans[0]!=(0,52+32*count) or spans[1][0]!=4096:
        raise ValueError('Unknown firmware header/auth layout')
    result[name+'.mdt']=result[name+'.b00']+result[name+'.b01']
    return result


def payloads(programs=PROGRAMS):
    programs=Path(programs)
    if programs.is_symlink() or not programs.is_file() or programs.stat().st_size>256*1024:
        raise ValueError('Expected bounded stock program bundle')
    source=json.loads(programs.read_text())
    if source.get('schema_version')!=1 or not isinstance(source.get('files'),list) or len(source['files'])!=2:
        raise ValueError('Invalid stock program bundle')
    profile=image_labels.package.profile()
    target={r['name']:r['new_sha256']for r in profile['data']}
    immutable={r['name']:r['sha256']for r in profile['immutable']}
    result={};seen=set()
    for row in source['files']:
        name=row.get('name')
        if name not in ('ipa_fws.elf','ipa_uc.elf') or name in seen:
            raise ValueError('Unexpected or duplicate stock ELF')
        seen.add(name)
        data=base64.b64decode(row['base64'],validate=True)
        if row.get('bytes')!=len(data) or sha(data)!=row.get('sha256') or sha(data)!=target[name]:
            raise ValueError('Stock ELF differs from reviewed R2 hash')
        result.update(split_program(name[:-4],data))
    expected=target|immutable
    if set(result)!=set(expected) or any(sha(result[n])!=digest for n,digest in expected.items()):
        raise ValueError('Stock split program/ELF coherence differs from R2')
    return result


def augment(plan):
    result=copy.deepcopy(plan)
    if result.get('schema_version')!=1 or not isinstance(result.get('operations'),list):
        raise ValueError('Expected reviewed Vendor plan')
    existing={r.get('path')for r in result['operations']}
    files=payloads()
    for row in image_labels.package.profile()['data']:
        path='/firmware/'+row['name']
        if path in existing:raise ValueError('Firmware already has a planned operation')
        result['operations'].append(dict(op='replace',path=path,old_sha256=row['old_sha256'],
            source='candidate/vendor'+path,sha256=sha(files[row['name']])))
    return result,{r['name']:files[r['name']]for r in image_labels.package.profile()['data']}


def stage(plans,output):
    plans,output=Path(plans),Path(output)
    if output.exists() or output.is_symlink():raise ValueError('Use a fresh security-plan directory')
    plan,files=augment(json.loads((plans/'vendor-plan.json').read_text()))
    shutil.copytree(plans,output)
    folder=output/'candidate/vendor/firmware';folder.mkdir(parents=True,exist_ok=False)
    for name,data in files.items():(folder/name).write_bytes(data)
    (output/'vendor-plan.json').write_text(json.dumps(plan,indent=2)+'\n')
    return dict(bundle_sha256=sha(PROGRAMS.read_bytes()),
        firmware={name:sha(data)for name,data in payloads().items()},
        operations_added=8,hardware_boot_confirmed=False)


def inspect(image):
    expected=payloads();ext4=image_labels.ext4
    with tempfile.TemporaryDirectory(prefix='r8q-firmware-inspect-')as folder:
        fs=ext4.Ext4(Path(image),Path(folder));rows=[]
        for name,data in sorted(expected.items()):
            path='/firmware/'+name;record=fs.regular(path);actual=fs.content(path)
            if actual!=data or (record['uid'],record['gid'],record['mode'])!=(0,0,0o644):
                raise ValueError('Built Vendor firmware differs: '+name)
            rows.append(dict(name=name,bytes=len(data),sha256=sha(actual)))
    return dict(status='R2_FIRMWARE_VERIFIED_IN_BUILT_VENDOR_NOT_BOOT_TESTED',
        image_sha256=ext4.sha_file(Path(image)),bundle_sha256=sha(PROGRAMS.read_bytes()),
        files=rows,hardware_boot_confirmed=False)
