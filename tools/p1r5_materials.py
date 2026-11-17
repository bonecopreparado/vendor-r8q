"""Bind baked R2 contents/labels to the actual Super included in a P1r5 ZIP."""
import json

from p1r3_materials import input_file
from vendor_security import full_rom


def bind(manifest,root,images):
    if manifest.get('build_label')!='P1r5':raise ValueError('Expected full P1r5 profile')
    programs=full_rom.payloads()
    firmware=manifest.get('vendor_firmware',{})
    labels=manifest.get('vendor_label_repair',{})
    staged=manifest.get('firmware_stage',{})
    expected_files=[dict(name=name,bytes=len(data),sha256=full_rom.sha(data))for name,data in sorted(programs.items())]
    if (firmware.get('status')!='R2_FIRMWARE_VERIFIED_IN_BUILT_VENDOR_NOT_BOOT_TESTED'
        or firmware.get('hardware_boot_confirmed')is not False or firmware.get('files')!=expected_files
        or firmware.get('bundle_sha256')!=full_rom.sha(full_rom.PROGRAMS.read_bytes())):
        raise ValueError('The actual Vendor firmware evidence differs from reviewed R2 programs')
    if staged!=dict(bundle_sha256=firmware['bundle_sha256'],firmware={r['name']:r['sha256']for r in expected_files},
                    operations_added=8,hardware_boot_confirmed=False):
        raise ValueError('Firmware staging evidence differs')
    wanted={('/'if r['path']=='.'else '/'+r['path']):r['label']for r in full_rom.image_labels.package.profile()['labels']}
    changes=labels.get('changes')
    if (labels.get('status')!='VENDOR_LABELS_REPAIRED_OFFLINE_NOT_BOOT_TESTED'
        or labels.get('file_contents_preserved')is not True or labels.get('hardware_boot_confirmed')is not False
        or labels.get('candidate_e2fsck',{}).get('exit')!=0 or not isinstance(changes,list)
        or len(changes)!=len(wanted) or {r.get('path'):r.get('expected')for r in changes}!=wanted):
        raise ValueError('Checked Vendor root/context label repair evidence is missing')
    if firmware.get('image_sha256')!=labels.get('candidate_sha256'):
        raise ValueError('Firmware and labels do not describe the same Vendor image')
    report=json.loads(input_file(root,'reports/p1/ci-build/super-independent-readback.json',1024**2).read_text())
    supers=[r for r in images if r['partition']=='super']
    vendors=[r for r in report.get('partitions',[])if r.get('name')=='vendor']
    if (report.get('status')!='INDEPENDENT_SUPER_HASHES_MATCH_NOT_BOOT_TESTED'
        or len(supers)!=1 or report.get('super_image_sha256')!=supers[0]['sha256']
        or len(vendors)!=1 or vendors[0].get('sha256')!=firmware['image_sha256']):
        raise ValueError('Independent LP readback does not bind the repaired Vendor to the actual Super')
    return dict(vendor_security=dict(firmware=firmware,labels=labels,staging=staged,
                independent_super_sha256=report['super_image_sha256']),
                stock_firmware_preflight_required=True,direct_storage_readback_required=True)
