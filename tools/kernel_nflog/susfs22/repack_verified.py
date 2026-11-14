"""Replace only the kernel in the exact shipped boot after independent checks.

The current source deliberately uses text_offset=0 instead of the old 0x80000.
No raw Image header is edited. Bootloader/old-DTB compatibility still requires
a hardware test; this tool never writes a phone or claims a successful boot.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(HERE.parents[1]))
import verify_linked
from build_boot_candidate import sections,boot_id,align

BOOT_BYTES=67108864
BOOT_SHA='4283ccbecbf3087bbd520dce1e50e5e449b1f70c4d959e8ee7f24b3ebfde9301'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def repack(original,kernel,summary):
    if len(original)!=BOOT_BYTES or sha(original)!=BOOT_SHA:
        raise ValueError('Source is not the exact shipped boot image')
    evidence=verify_linked.verify(kernel,summary)
    parts=sections(original)
    if original[576:608]!=boot_id(parts):
        raise ValueError('Original Android boot ID differs')
    if not parts['tail'].startswith(b'SEANDROIDENFORCE\0') or any(parts['tail'][16:]):
        raise ValueError('Unknown Samsung boot trailer')
    old=parts['kernel']
    if len(old)<64 or old[56:60]!=b'ARM\x64' or struct.unpack_from('<Q',old,8)[0]!=0x80000:
        raise ValueError('Unexpected original ARM64 Image profile')
    if struct.unpack_from('<Q',kernel,8)[0]!=0 or struct.unpack_from('<Q',kernel,24)[0]!=10 or kernel[24:32]!=old[24:32]:
        raise ValueError('Unexpected current ARM64 Image profile')
    preserved={name:parts[name] for name in ('ramdisk','second','recovery_dtbo','dtb')}
    parts['kernel']=kernel
    header=bytearray(original[:parts['page']])
    struct.pack_into('<I',header,8,len(kernel))
    header[576:608]=boot_id(parts)
    candidate=bytearray(header)
    for name in ('kernel','ramdisk','second','recovery_dtbo','dtb'):
        candidate.extend(parts[name])
        candidate.extend(bytes(align(len(candidate),parts['page'])-len(candidate)))
    candidate.extend(b'SEANDROIDENFORCE\0')
    if len(candidate)>BOOT_BYTES:
        raise ValueError('New kernel and preserved sections exceed the boot partition')
    candidate.extend(bytes(BOOT_BYTES-len(candidate)))
    candidate=bytes(candidate)
    check=sections(candidate)
    if check['kernel']!=kernel or candidate[576:608]!=boot_id(check):
        raise ValueError('Kernel/Android ID readback differs')
    if any(check[name]!=data for name,data in preserved.items()):
        raise ValueError('A preserved boot section changed')
    changed=[i for i,(a,b)in enumerate(zip(original[:parts['page']],candidate[:parts['page']]))if a!=b]
    if any(i not in range(8,12) and i not in range(576,608) for i in changed):
        raise ValueError('Unexpected boot header change')
    report=dict(status='VERIFIED_SUSFS22_KERNEL_REPACK_NOT_HARDWARE_TESTED',
        source_boot_sha256=BOOT_SHA,candidate_boot_sha256=sha(candidate),bytes=BOOT_BYTES,
        kernel_sha256=sha(kernel),kernel_bytes=len(kernel),build_verification=evidence,
        preserved_sections={name:dict(bytes=len(data),sha256=sha(data))for name,data in preserved.items()},
        changed_header_offsets=changed,raw_image_header_rewritten=False,
        text_offset_before=0x80000,text_offset_after=0,load_addresses_and_cmdline_preserved=True,
        userdata_or_vbmeta_modified=False,hardware_boot_confirmed=False,
        bootloader_loading_path_confirmed=False,old_dtb_compatibility_confirmed=False)
    return candidate,report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','kernel','summary','output','report'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    inputs=(args.source,args.kernel,args.summary)
    if any(p.is_symlink()or not p.is_file()for p in inputs):
        parser.error('Expected regular input files')
    if args.kernel.stat().st_size>BOOT_BYTES or args.summary.stat().st_size>1024*1024:
        parser.error('Input exceeds its size bound')
    if args.output.resolve()==args.report.resolve() or any(p.exists()or p.is_symlink()for p in (args.output,args.report)):
        parser.error('Use two new, distinct output files')
    candidate,report=repack(args.source.read_bytes(),args.kernel.read_bytes(),json.loads(args.summary.read_text()))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('xb')as stream:stream.write(candidate)
    if sha(args.output.read_bytes())!=report['candidate_boot_sha256']:
        raise ValueError('Written boot readback differs')
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open('x')as stream:stream.write(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
