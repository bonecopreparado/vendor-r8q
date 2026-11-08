"""Replace only the kernel in the exact shipped r8q boot image, offline."""
from pathlib import Path
import argparse,hashlib,json,struct,sys
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from build_boot_candidate import sections,boot_id,align
SHIPPED_BOOT_SHA='4283ccbecbf3087bbd520dce1e50e5e449b1f70c4d959e8ee7f24b3ebfde9301'
SHA=lambda b:hashlib.sha256(b).hexdigest()
def check_image(data):
    if len(data)<64 or data[56:60]!=b'ARM\x64':raise ValueError('Expected an uncompressed ARM64 Image, without appended DTBs')
    image_size=struct.unpack_from('<Q',data,16)[0]
    if image_size<len(data) or image_size>256*1024*1024:raise ValueError('Invalid ARM64 image memory size')
def repack_bytes(original,new_kernel):
    parts=sections(original)
    if original[576:608]!=boot_id(parts):raise ValueError('Original Android boot ID differs')
    if not parts['tail'].startswith(b'SEANDROIDENFORCE\0') or any(parts['tail'][16:]):raise ValueError('Unknown Samsung signature/trailer')
    check_image(parts['kernel']);check_image(new_kernel)
    if new_kernel[8:16]!=parts['kernel'][8:16] or new_kernel[24:32]!=parts['kernel'][24:32]:raise ValueError('Kernel load offset or ARM64 flags changed')
    old=dict(parts);parts['kernel']=bytes(new_kernel)
    header=bytearray(original[:parts['page']]);struct.pack_into('<I',header,8,len(new_kernel));header[576:608]=boot_id(parts)
    candidate=bytearray(header)
    for name in ['kernel','ramdisk','second','recovery_dtbo','dtb']:
        candidate.extend(parts[name]);candidate.extend(bytes(align(len(candidate),parts['page'])-len(candidate)))
    candidate.extend(b'SEANDROIDENFORCE\0')
    if len(candidate)>len(original):raise ValueError('New kernel boot exceeds existing partition capacity')
    candidate.extend(bytes(len(original)-len(candidate)));candidate=bytes(candidate)
    after=sections(candidate)
    for name in ['ramdisk','second','recovery_dtbo','dtb']:
        if after[name]!=old[name]:raise ValueError('Preserved boot section differs: '+name)
    if after['kernel']!=new_kernel or candidate[576:608]!=boot_id(after):raise ValueError('Kernel/boot-ID readback differs')
    changed=[i for i,(a,b) in enumerate(zip(original[:parts['page']],candidate[:parts['page']])) if a!=b]
    if any(i not in range(8,12) and i not in range(576,608) for i in changed):raise ValueError('Unexpected Android boot header mutation')
    report={'status':'KERNEL_ONLY_OFFLINE_REPACK_NOT_BOOT_TESTED','source_boot_sha256':SHA(original),'candidate_boot_sha256':SHA(candidate),'bytes':len(candidate),'kernel_sha256':SHA(new_kernel),'kernel_bytes':len(new_kernel),'changed_header_offsets':changed,'preserved_sections':{n:{'bytes':len(old[n]),'sha256':SHA(old[n])} for n in ['ramdisk','second','recovery_dtbo','dtb']},'cmdline_and_load_addresses_unchanged':True,'userdata_or_vbmeta_modified':False,'hardware_boot_confirmed':False}
    return candidate,report
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--kernel',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--report',type=Path,required=True);a=p.parse_args()
    for path in [a.source,a.kernel]:
        if path.is_symlink() or not path.is_file():raise ValueError('Expected regular input: '+str(path))
    original=a.source.read_bytes()
    if len(original)!=67108864 or SHA(original)!=SHIPPED_BOOT_SHA:raise ValueError('Source is not the exact shipped 64 MiB r8q boot')
    if a.kernel.stat().st_size>64*1024*1024:raise ValueError('Kernel input exceeds bound')
    candidate,report=repack_bytes(original,a.kernel.read_bytes())
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('xb') as f:f.write(candidate)
    if SHA(a.output.read_bytes())!=report['candidate_boot_sha256']:raise ValueError('Written file readback differs')
    a.report.parent.mkdir(parents=True,exist_ok=True);a.report.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
