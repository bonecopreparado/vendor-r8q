"""32 installer scenarios under a real mksh shell, with bounded temp-file fixtures."""
from pathlib import Path
import tempfile,hashlib,os,subprocess,json,struct,gzip
R=Path(os.environ.get('R8Q_PROJECT_ROOT',Path.cwd()))
SOURCE=Path(os.environ.get('R8Q_TEST_SOURCE',str(R/'delivery/Revisao-P0r7-Windows/p0r7-assets/installer-template.sh')))
REPORT=Path(os.environ.get('R8Q_TEST_REPORT',str(R/'reports/audit-20261031/overnight/reader')))
REPORT.mkdir(parents=True,exist_ok=True)
SHELL=os.environ.get('MKSH_BINARY','mksh')
VB_HEADERS={"device":"41564230000000010000000000000000000002400000000000001f800000000200000000000000000000000000000020000000000000002000000000000002000000000000001b7800000000000004080000000000001f80000000000000000000000000000000000000000000001b7800000000000000000000000300000000617662746f6f6c20312e322e3000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000","tester-g780g":"41564230000000010000000000000000000002400000000000001f800000000200000000000000000000000000000020000000000000002000000000000002000000000000001b7800000000000004080000000000001f80000000000000000000000000000000000000000000001b7800000000000000000000000300000000617662746f6f6c20312e322e3000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000"}
SHA=lambda b:hashlib.sha256(b).hexdigest()
HASHES={'super':'001617abf9c04d36a20f23d68a0e3ecbcea475364df06df82399feb97ea7607b','boot':'4283ccbecbf3087bbd520dce1e50e5e449b1f70c4d959e8ee7f24b3ebfde9301','dtbo':'3d78f213d52a5d4875b634c4ea914d04dea678bfd70dd81625d6c9f056b60468'}
GEOMETRY=bytes.fromhex('67446c61340000004e31cf64275442f40e25c772a18d1fccd8b1291232e593f65e522fc7ac07df03000001000200000000100000').ljust(4096,b'\0')*2

def run_case(name,flags=3,magic=True,geometry=True,mount='',zip_on_target=False,unmount_fail=False,corrupt_payload=False,extract_fail=False,device='r8q',fixture='device',variant_prefix=b'P',fragmented=False,unknown_version=False,geometry_padding=False,reject_fsync=False,sync_failure=False,outfd9=False,short_second_read=False,path_spaces=False,missing=False,bad_crc=False,bad_raw=False,invalid_name=False,symlink_protected=False,bind_payload=False,fail_second_read=False,hash_failure=False,table_mutation=''):
 with tempfile.TemporaryDirectory(prefix='r8q-') as td:
  root=Path(td);bins=root/'bin';bins.mkdir();target=root/'target';target.mkdir();payload=root/'payloads';payload.mkdir();counters=root/'counts';counters.mkdir()
  original={'super':variant_prefix*4096+(GEOMETRY if geometry else b'X'*8192)+b'O'*(32768-12288),'boot':b'O'*8192,'dtbo':b'O'*4096}
  if geometry_padding:
   v=bytearray(original['super']);v[4200]=77;v[8300]=78;original['super']=bytes(v)
  new={'super':b'D'*4096+GEOMETRY+b'N'*(32768-12288),'boot':b'B'*8192,'dtbo':b'T'*4096}
  rows=[]
  for part in HASHES:
   (target/part).write_bytes(original[part])
   for index,offset in enumerate(range(0,len(new[part]),16384)):
    chunk=new[part][offset:offset+16384];packed=gzip.compress(chunk,compresslevel=1,mtime=0);filename=f'{part}-{index:03}.gz'
    (payload/filename).write_bytes(packed);rb=chunk[4096:] if part=='super' and offset==0 else chunk
    rows.append([part,filename,len(chunk),SHA(chunk),len(packed),SHA(packed),offset,SHA(rb)])
  vb=bytearray(bytes.fromhex(VB_HEADERS[fixture]).ljust(65536,b'\0'))
  # Arbitrary harmless padding changes whole-file identity: must no longer block.
  vb[-16:]=b'new tester state';struct.pack_into('>I',vb,120,flags)
  if not magic:vb[:4]=b'NOPE'
  if unknown_version:struct.pack_into('>I',vb,4,2)
  (target/'vbmeta').write_bytes(vb)
  victim=payload/'super-001.gz'
  if corrupt_payload:victim.write_bytes(b'BAD')
  if missing:victim.unlink()
  if bad_crc:
   b=bytearray(victim.read_bytes());b[-8]^=1;victim.write_bytes(b)
   for row in rows:
    if row[1]==victim.name:row[4:6]=[len(b),SHA(b)]
  if bad_raw:
   b=gzip.compress(b'Z'*16384,compresslevel=1,mtime=0);victim.write_bytes(b)
   for row in rows:
    if row[1]==victim.name:row[4:6]=[len(b),SHA(b)]
  if invalid_name:rows[0][1]='../escape.gz'
  if table_mutation=='offset_4GiB':rows[0][6]=4294967296
  if table_mutation=='gap':rows[1][6]+=4096
  if table_mutation=='misaligned':rows[0][2]+=1
  if table_mutation=='bad_hash':rows[0][3]='z'*64
  if table_mutation=='gzip_size_4GiB':rows[0][4]=4294967296
  if symlink_protected:
   protected=root/'protected';protected.mkdir();actual=protected/victim.name;victim.rename(actual);victim.symlink_to(actual)
  mf=root/'mounts';mf.write_text(f'/dev/block/dm-1 {mount} ext4 ro 0 0\n' if mount else '')
  mi=root/'mountinfo';lines='1 0 0:2 / / rw - tmpfs tmpfs rw\n'
  if mount:lines+=f'2 1 253:1 / {mount} ro - ext4 /dev/block/dm-1 ro\n'
  if zip_on_target:lines+=f'3 1 253:1 / {root} ro - ext4 /dev/block/dm-1 ro\n'
  if symlink_protected:lines+=f'4 1 253:1 / {root}/protected ro - ext4 /dev/block/dm-1 ro\n'
  if bind_payload:lines+=f'5 1 253:1 / {payload} ro - ext4 /dev/block/dm-1 ro\n'
  mi.write_text(lines);zip_path=root/('fake ZIP ç.zip' if path_spaces else 'fake.zip');zip_path.write_bytes(b'zipfixture')
  sd=root/'sys';sd.mkdir()
  for n,num in [('super','8:29'),('boot','8:23'),('dtbo','8:22'),('dm-1','253:1')]:
   d=sd/n;d.mkdir();(d/'dev').write_text(num+'\n')
  (sd/'dm-1/slaves').mkdir();(sd/'dm-1/slaves/super').symlink_to(sd/'super')
  def exe(n,text):
   p=bins/n;p.write_text('#!/bin/bash\n'+text);p.chmod(0o700)
  exe('getprop','echo '+device+'\n');exe('blockdev','stat -c %s "$2"\n')
  exe('dd','for arg in "$@"; do\n case "$arg" in iflag=*|oflag=*|*skip_bytes*|*seek_bytes*) echo "Unsupported option $arg" >&2; exit 90;; esac\n if [ "${REJECT_FSYNC:-0}" = 1 ] && [ "$arg" = conv=fsync ]; then exit 91; fi\ndone\nexec /usr/bin/dd "$@"\n')
  exe('sync','[ "${SYNC_FAILURE:-0}" != 1 ] || exit 92\nexit 0\n')
  wrapper=root/'gzip_wrapper.py'
  wrapper.write_text('''import os,sys,subprocess
from pathlib import Path
args=sys.argv[1:]
p=subprocess.run(['/usr/bin/gzip']+args,capture_output=True)
data=p.stdout
name=Path(args[-1]).name if args else 'stdin'
counter=Path(os.environ['COUNTERS'])/name
n=int(counter.read_text())+1 if counter.exists() else 1
counter.write_text(str(n))
if os.environ.get('EXTRACT_FAIL')=='1' and name=='super-001.gz':sys.exit(17)
if os.environ.get('FAIL_SECOND')=='1' and name=='super-001.gz' and n>=2:sys.exit(17)
if os.environ.get('HASH_FAILURE')=='1' and name=='super-000.gz':(Path(os.environ['COUNTERS'])/'hash-failure').touch()
if os.environ.get('SHORT_SECOND')=='1' and name=='super-001.gz' and n>=2:data=data[:-4096]
if os.environ.get('FRAGMENTED')=='1':
 for i in range(0,len(data),101):sys.stdout.buffer.write(data[i:i+101]);sys.stdout.buffer.flush()
else:sys.stdout.buffer.write(data);sys.stdout.buffer.flush()
sys.stderr.buffer.write(p.stderr)
sys.exit(p.returncode)
''')
  exe('gzip','exec python3 "'+str(wrapper)+'" "$@"\n')
  exe('sha256sum','/usr/bin/sha256sum "$@"\nrc=$?\n[ ! -f "$COUNTERS/hash-failure" ] || exit 134\nexit "$rc"\n')
  exe('umount','[ "${UNMOUNT_FAIL:-}" != 1 ] || exit 9\n: > "$MOUNTS"\nprintf "1 0 0:2 / / rw - tmpfs tmpfs rw\\n" > "$MOUNTINFO"\n')
  script=SOURCE.read_text().replace('/dev/block/bootdevice/by-name/',str(target)+'/').replace('[ -b "$1" ]','[ -f "$1" ]')
  script=script.replace('@@PAYLOAD_ROWS@@','\n'.join(' '.join(map(str,row)) for row in rows))
  script=script.replace('[ "$row_count" -eq 22 ]','[ "$row_count" -eq 4 ]')
  script=script.replace('/proc/mounts',str(mf)).replace('/proc/self/mountinfo',str(mi)).replace('/sys/class/block',str(sd))
  for part,size in [('SUPER','10292822016'),('BOOT','67108864'),('DTBO','10485760')]:script=script.replace('check_size "$'+part+'" '+size,'check_size "$'+part+'" '+str(len(original[part.lower()])))
  for part,h in HASHES.items():script=script.replace(h,SHA(new[part]))
  script=script.replace('591fe9ef42e4e04a2834cab1dfc06d70d1b00ae70a599ef13e4ab5df2a223e78',SHA(new['super'][4096:]))
  p=root/'installer';p.write_text(script)
  argv=[SHELL,str(p),'3','1',str(zip_path)]
  if outfd9:argv=['bash','-c','exec 9>&1; exec "$1" "$2" 3 9 "$3"','_',SHELL,str(p),str(zip_path)]
  result=subprocess.run(argv,text=True,capture_output=True,timeout=30,env=os.environ|dict(PATH=str(bins)+':'+os.environ['PATH'],PAYLOAD=str(payload),COUNTERS=str(counters),FRAGMENTED=str(int(fragmented)),SHORT_SECOND=str(int(short_second_read)),FAIL_SECOND=str(int(fail_second_read)),HASH_FAILURE=str(int(hash_failure)),MOUNTS=str(mf),MOUNTINFO=str(mi),EXTRACT_FAIL=str(int(extract_fail)),UNMOUNT_FAIL=str(int(unmount_fail)),REJECT_FSYNC=str(int(reject_fsync)),SYNC_FAILURE=str(int(sync_failure))))
  changed=[part for part in HASHES if (target/part).read_bytes()!=original[part]]
  prefix_same=(target/'super').read_bytes()[:4096]==original['super'][:4096]
  body_matches=(target/'super').read_bytes()[4096:]==new['super'][4096:]
  return dict(case=name,exit=result.returncode,changed=changed,prefix_preserved=prefix_same,super_body_matches=body_matches,counts={p.name:int(p.read_text()) for p in counters.iterdir() if p.name!='hash-failure'},stdout=result.stdout,stderr=result.stderr)

cases=[('new_vbmeta_hash',{}),('g780g_header',dict(fixture='tester-g780g')),('different_samsung_prefix',dict(variant_prefix=b'Q')),('short_pipe_reads',dict(fragmented=True)),('named_mount',dict(mount='/vendor')),('nonfunctional_geometry_padding',dict(geometry_padding=True)),('dd_without_fsync',dict(reject_fsync=True)),('fragmented_no_fsync',dict(fragmented=True,reject_fsync=True)),('recovery_output_fd9',dict(outfd9=True)),('path_spaces_and_accents',dict(path_spaces=True))]
failures=[('flags0',dict(flags=0)),('flags1',dict(flags=1)),('flags2',dict(flags=2)),('bad_magic',dict(magic=False)),('unknown_version',dict(unknown_version=True)),('geometry_mismatch',dict(geometry=False)),('alternate_mount',dict(mount='/mnt/vendor')),('zip_on_target',dict(zip_on_target=True)),('unmount_failure',dict(mount='/vendor',unmount_fail=True)),('bad_payload',dict(corrupt_payload=True)),('gzip_failure',dict(extract_fail=True)),('exynos_device',dict(device='r8s')),('no_durability_method',dict(reject_fsync=True,sync_failure=True)),('missing_part',dict(missing=True)),('bad_gzip_crc',dict(bad_crc=True)),('bad_raw_hash',dict(bad_raw=True)),('invalid_part_name',dict(invalid_name=True)),('symlink_payload_on_target',dict(symlink_protected=True))]
results=[]
failures += [('bind_payload_on_target',dict(bind_payload=True)),('hash_process_failure',dict(hash_failure=True))]
failures += [('table_'+mutation,dict(table_mutation=mutation)) for mutation in ['offset_4GiB','gap','misaligned','bad_hash','gzip_size_4GiB']]
for name,kw in cases+failures:
 r=run_case(name,**kw);results.append(r)
 if (name,kw) in cases:assert r['exit']==0 and len(r['changed'])==3 and r['prefix_preserved'] and r['super_body_matches'],r
 else:assert r['exit']!=0 and not r['changed'] and r['prefix_preserved'],r
 if kw.get('table_mutation'):assert 'Tabela de partes invalida' in r['stdout'],r
 print(name,'PASS',flush=True)
truncated=run_case('short_after_verified_source',short_second_read=True)
assert truncated['exit']!=0 and truncated['changed']==['super'] and truncated['prefix_preserved'] and not truncated['super_body_matches'],truncated
# Exact message may include part name in the P0r5 per-part readback check.
assert 'retorno' in truncated['stdout'].lower() or 'hash' in truncated['stdout'].lower(),truncated
results.append(truncated);print('short_after_verified_source PASS')
failed_write=run_case('gzip_failure_during_write',fail_second_read=True)
assert failed_write['exit']!=0 and failed_write['changed']==['super'] and failed_write['prefix_preserved'],failed_write
assert 'codigo 17' in failed_write['stderr'] and 'restaure a base' in failed_write['stdout'],failed_write
results.append(failed_write);print('gzip_failure_during_write PASS')
assert 'sha256sum falhou: codigo 134' in next(r for r in results if r['case']=='hash_process_failure')['stderr']
assert 'esta em particao alvo' in next(r for r in results if r['case']=='bind_payload_on_target')['stdout']
(REPORT/'installer-results.json').write_text(json.dumps(results,indent=2)+'\n')
