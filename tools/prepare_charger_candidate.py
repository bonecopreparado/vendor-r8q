"""Prepare deletion of a strictly superseded charger init file, not a HAL fix."""
from pathlib import Path
import argparse
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]
PATCH=ROOT/'patches/0006-hardware-adaptation'
LEGACY='odm/etc/init/vendor.oplus.hardware.charger@1.0-service.rc'
CURRENT='odm/etc/init/vendor.oplus.hardware.charger-V3-service.rc'
PINS={LEGACY:'57cee4d7c34b53cd8b131603642c9c8dec8df3e85a315a2438b9919f799755e2',
      CURRENT:'986d49f4a531125790fdf9d8d9949993ea5ce3c56b9e08e78a5ec1f1ef0ed78a'}
EXTRA=(b'    chown system system /sys/class/oplus_chg/common/deep_dischg_count_cali\n'
       b'    chown system system /sys/class/oplus_chg/battery/gauge_info\n')


def prepare(source_root):
    data={}
    for name,sha in PINS.items():
        path=Path(source_root)/name
        if path.is_symlink() or not path.is_file():raise ValueError('Missing or linked source: '+name)
        data[name]=path.read_bytes()
        if hashlib.sha256(data[name]).hexdigest()!=sha:raise ValueError('Source identity differs: '+name)
    # Establish exact semantic superset rather than deleting by filename alone.
    normalized=data[CURRENT].replace(b'/odm/bin/hw/vendor.oplus.hardware.charger-V3-service',
                                    b'/odm/bin/hw/vendor.oplus.hardware.charger@1.0-service',1)
    if normalized.count(EXTRA)!=1 or normalized.replace(EXTRA,b'',1)!=data[LEGACY]:
        raise ValueError('Current init is not the reviewed strict superset')
    return dict(name='Consolidate duplicate Oplus charger init declarations',
                status='OPTIONAL_ISOLATED_CONFIG_FIX_NOT_APPLIED_NOT_CHARGING_VALIDATED',
                files=[dict(path=LEGACY,action='delete',old_sha256=PINS[LEGACY])],
                required_retained_files=[dict(path=CURRENT,sha256=PINS[CURRENT]),
                    dict(path='odm/bin/hw/vendor.oplus.hardware.charger-V3-service',bytes=309872,
                         sha256='1c5ad4715da8faa46de26249a58a13fb824c55b80d191144da2fd3a7cb80f672')],
                required_interface='vendor.oplus.hardware.charger.ICharger/default AIDL version 3',
                reason='The V3 RC sorts before the legacy RC and already defines all three same-named services. The later RC has no override, repeats the same actions and contributes no distinct action.',
                limits=['Verify whole-tree init imports and host_init_verifier before applying.',
                        'This preserves the selected V3 implementation; its compatibility with Samsung charging hardware remains unproven.',
                        'No charger binary, VINTF declaration, sysfs path, permission or runtime state is modified by this generator.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=PATCH/'inputs')
    parser.add_argument('--output-root',type=Path,default=PATCH/'candidate-charger')
    args=parser.parse_args()
    manifest=prepare(args.source_root)
    args.output_root.mkdir(parents=True,exist_ok=True)
    (args.output_root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))


if __name__=='__main__':main()
