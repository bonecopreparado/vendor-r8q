"""Stage the official r8q Samsung Keymaster backend with its legacy crypto."""
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import zipfile

from reconstruct_r8q import reconstruct

OTA_SHA = '8fcf4ffdf47d549aa8fd0e30e31872aa45074cb6081a09b8b4f8cbe81e1711f4'
OTA_BYTES = 1363590201
VENDOR_SHA = '74aac540f69c96ff3a87d5092a545402b2c40c1f51bbf33e77800e3b6386c9f0'
BIN = '/bin/hw/android.hardware.keymaster@4.0-service'
HELPER = '/lib64/libkeymaster_helper.so'
DEVICE = '/lib64/libskeymaster4device.so'
CRYPTO = '/lib64/libcrypto-v33.so'
# path, original vendor SHA (None for a new file), official payload SHA
FILES = (
    (BIN, '64f724c3b12f0e69fdd63f5c4559335fcdb446891122cfca56144a421ce41aea',
     '3a121cc4b3fb4a09ed66b63354d0844e8efb07be2a91375c147acd94694fd560'),
    (DEVICE, '88a56de610b1d663293329b1adff087fd22f272fa67a152f8e7fd5b50b2e32f9',
     '17c0e86f03028dc32c73986674d5c4dfd5b0365c8604e0b849af7b1efb1a44ff'),
    (HELPER, '79cf5c1d0fc80d94e9bf52e3583ef56e8b13218d5643657a0a100094c59f9fd6',
     'a37e1d1ba4094e4c2d16948a328750f37b85d3480bf0a88ca209a638e2826ffc'),
    (CRYPTO, None, '1e61f1c75fdd40b3054eb18d45500eb204f46ec684598c97df659d06f9c0d4d6'),
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def elf(path):
    dynamic = subprocess.check_output(['readelf', '-dW', str(path)], text=True)
    symbols = subprocess.check_output(['readelf', '--dyn-syms', '--wide', str(path)], text=True)
    linked = [line.split('[')[-1].split(']')[0] for line in dynamic.splitlines() if '(NEEDED)' in line]
    imports, exports = set(), set()
    for line in symbols.splitlines():
        words = line.split()
        if len(words) >= 8 and words[0].endswith(':'):
            name = words[7].split('@', 1)[0]
            if words[6] == 'UND' and words[4] == 'GLOBAL':
                imports.add(name)
            elif words[6] != 'UND' and words[4] in ('GLOBAL', 'WEAK'):
                exports.add(name)
    return linked, imports, exports


def stage(plans, archive, reader, erofs):
    archive = Path(archive)
    if archive.is_symlink() or archive.stat().st_size != OTA_BYTES:
        raise ValueError('Unexpected official r8q OTA size')
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != OTA_SHA:
            raise ValueError('Official r8q OTA SHA-256 mismatch')
    plan_path = plans / 'vendor-plan.json'
    plan = json.loads(plan_path.read_text())
    local = {}
    with tempfile.TemporaryDirectory(prefix='r8q-keymaster-') as temp:
        work = Path(temp)
        with zipfile.ZipFile(archive) as source:
            vendor = reconstruct(source, 'vendor', work, prefix='')
        if vendor['sha256'] != VENDOR_SHA:
            raise ValueError('Reconstructed Lineage Vendor SHA-256 mismatch')
        for path, original, digest in FILES:
            if any(row['path'] == path for row in plan['operations']):
                raise ValueError('Vendor path already staged: ' + path)
            if original:
                old = reader('vendor', path)
                if sha(old) != original:
                    raise ValueError('Unexpected port baseline: ' + path)
                (work / ('old-' + Path(path).name)).write_bytes(old)
            source = path + '.samsung' if path == BIN else path
            data = subprocess.check_output([str(erofs), '--cat', '--path=' + source, str(work/'vendor.img')],
                                           timeout=30)
            if sha(data) != digest or data[:6] != b'\x7fELF\x02\x01' or data[18:20] != b'\xb7\x00':
                raise ValueError('Official AArch64 payload identity differs: ' + source)
            local[path] = data
            (work/Path(path).name).write_bytes(data)

        def inspect(path, prefix=''):
            return elf(work/(prefix + Path(path).name))
        new_deps, new_imports, _ = inspect(BIN)
        old_deps, old_imports, _ = inspect(BIN, 'old-')
        if set(new_deps) != set(old_deps) or new_deps.index(Path(DEVICE).name) >= new_deps.index('libkeymaster4.so'):
            raise ValueError('The reviewed Samsung service dependency order changed')
        for path in (HELPER, DEVICE):
            old_deps, old_imports_lib, _ = inspect(path, 'old-')
            new_deps, new_imports_lib, _ = inspect(path)
            if (new_deps != [Path(CRYPTO).name if lib == 'libcrypto.so' else lib for lib in old_deps]
                or not new_imports_lib <= old_imports_lib):
                raise ValueError('Unexpected Keymaster backend ABI change: ' + path)
        for name in ('libcrypto.so', 'libc++.so'):
            (work/name).write_bytes(reader('system', '/system/lib64/' + name))
        additions = new_imports - old_imports
        if additions != {'_ZdlPvm'} or not additions <= elf(work/'libc++.so')[2]:
            raise ValueError('Samsung service added an unresolved platform symbol')
        if ('sk_delete' not in inspect(HELPER, 'old-')[1] or
            'sk_delete' in elf(work/'libcrypto.so')[2] or
            'sk_delete' not in inspect(CRYPTO)[2]):
            raise ValueError('Expected legacy crypto mismatch was not reproduced')

    for path, original, digest in FILES:
        relative = 'candidate/vendor' + path
        destination = plans / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(local[path])
        change = dict(path=path, source=relative, sha256=digest)
        if original:
            change.update(op='replace', old_sha256=original)
        else:
            change.update(op='add', metadata_from=HELPER)
        plan['operations'].append(change)
    plan_path.write_text(json.dumps(plan, indent=2) + '\n')
    return dict(ota_sha256=OTA_SHA, vendor_sha256=VENDOR_SHA, resolved_legacy_symbol='sk_delete',
                files=[dict(path=path, old_sha256=old, sha256=new) for path, old, new in FILES])
