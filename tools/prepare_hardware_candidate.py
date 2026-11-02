"""Prepare an isolated, hash-pinned NFC init fix; never open a device/image."""
from pathlib import Path
import argparse
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT/'patches/0006-hardware-adaptation'
MULTI = 'vendor/etc/init/multi.android.hardware.nfc@1.2-service.rc'
DUPLICATE = 'vendor/etc/init/nxp.android.hardware.nfc@1.2-service.rc'
PINS = {
    MULTI: 'df893bbe3b600fcc01a939443d6dfeebb8692ccc5db4b251a8fcf2eb3e4a101c',
    DUPLICATE: 'c7d546b6ee6d3e6662e88f774efa41629dcc857952d8e0ebd9281418438b75f8',
}
INTERFACES = (
    '    interface android.hardware.nfc@1.0::INfc default',
    '    interface android.hardware.nfc@1.1::INfc default',
    '    interface android.hardware.nfc@1.2::INfc default',
    '    interface vendor.samsung.hardware.nfc@2.0::ISehNfc default',
)
SHA = lambda b: hashlib.sha256(b).hexdigest()


def prepare(source_root):
    files = {}
    for name, sha in PINS.items():
        path = Path(source_root)/name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or linked original NFC source: '+name)
        data = path.read_bytes()
        if SHA(data) != sha:
            raise ValueError('Original NFC source identity differs: '+name)
        files[name] = data
    multi = files[MULTI].decode()
    duplicate = files[DUPLICATE].decode()
    declaration = 'service vendor.nfc_hal_service /vendor/bin/hw/nxp.android.hardware.nfc@1.2-service\n'
    if not multi.startswith(declaration) or not duplicate.startswith(declaration):
        raise ValueError('Samsung service command differs')
    if tuple(line for line in duplicate.splitlines() if line.lstrip().startswith('interface ')) != INTERFACES:
        raise ValueError('Duplicate service interface bindings differ')
    if sum(line.startswith('service ') for line in duplicate.splitlines()) != 1:
        raise ValueError('Cannot remove a file with unrelated services')
    replacement = (declaration+'\n'.join(INTERFACES)+'\n'+multi[len(declaration):]).encode()
    manifest = {
        'name': 'Samsung NFC init service consolidation',
        'status': 'ISOLATED_CONFIG_FIX_NOT_APPLIED_NOT_NFC_RUNTIME_VALIDATED',
        'scope': 'Fix duplicate init service and retain its four interface bindings; do not hide Oplus missing-library issue.',
        'files': [dict(path=MULTI, action='replace', old_sha256=PINS[MULTI], new_sha256=SHA(replacement),
                       bytes=len(replacement),uid=0,gid=0,mode='0644',selinux='u:object_r:vendor_configs_file:s0'),
                  dict(path=DUPLICATE, action='delete', old_sha256=PINS[DUPLICATE])],
        'preserved': ['Both Samsung executable paths, disabled flags, class/user/group and all four original hardware-selector triggers.',
                      'All ODM Oplus/NXP binaries, service declarations and VINTF manifests remain untouched.'],
        'limits': ['AOSP init semantics checked statically; host_init_verifier and phone runtime still required.',
                   'This does not repair the absent Oplus libpnscr2_aidl.so or establish which NFC chip is present.'],
    }
    return {MULTI: replacement}, manifest


def write_candidate(source_root, output_root):
    files, manifest = prepare(source_root)
    output_root = Path(output_root)
    for name, data in files.items():
        path = output_root/name
        if path.exists() and (path.is_symlink() or path.read_bytes() != data):
            raise ValueError('Refusing to overwrite another candidate: '+name)
    for name,data in files.items():
        path = output_root/name
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(data)
    output_root.mkdir(parents=True,exist_ok=True)
    (output_root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,default=PATCH/'inputs')
    parser.add_argument('--output-root',type=Path,default=PATCH/'candidate')
    args = parser.parse_args()
    print(json.dumps(write_candidate(args.source_root,args.output_root),indent=2))


if __name__=='__main__':main()
