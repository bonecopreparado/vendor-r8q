"""Stage the official r8q Samsung Keymaster & Gatekeeper backends with legacy crypto.

Preserves the donor VNDK-30 Keymaster service binary (reordering only its
DT_NEEDED entries so libskeymaster4device.so loads before libkeymaster4.so)
to avoid introducing C++14 sized-delete (_ZdlPvm) symbols absent from the
VNDK-30 libc++.so namespace, and stages the shimmed gatekeeper.mdfpp.so
alongside libskeymaster4device.so, libkeymaster_helper.so and libcrypto-v33.so.
"""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import zipfile

from reconstruct_r8q import reconstruct

OTA_SHA = '8fcf4ffdf47d549aa8fd0e30e31872aa45074cb6081a09b8b4f8cbe81e1711f4'
OTA_BYTES = 1363590201
VENDOR_SHA = '74aac540f69c96ff3a87d5092a545402b2c40c1f51bbf33e77800e3b6386c9f0'
BIN = '/bin/hw/android.hardware.keymaster@4.0-service'
BIN_ORIGINAL_SHA = '64f724c3b12f0e69fdd63f5c4559335fcdb446891122cfca56144a421ce41aea'
HELPER = '/lib64/libkeymaster_helper.so'
DEVICE = '/lib64/libskeymaster4device.so'
GATEKEEPER = '/lib64/hw/gatekeeper.mdfpp.so'
GATEKEEPER_ORIGINAL_SHA = 'b1ce07db8ddb55ffc9014b46e8c36c8bc6154d14b813eba94a7e34e02e989997'
CRYPTO = '/lib64/libcrypto-v33.so'
# path, original vendor SHA (None for a new file), official payload SHA (None = verified via OTA+ABI)
FILES = (
    (DEVICE, '88a56de610b1d663293329b1adff087fd22f272fa67a152f8e7fd5b50b2e32f9',
     '17c0e86f03028dc32c73986674d5c4dfd5b0365c8604e0b849af7b1efb1a44ff'),
    (HELPER, '79cf5c1d0fc80d94e9bf52e3583ef56e8b13218d5643657a0a100094c59f9fd6',
     'a37e1d1ba4094e4c2d16948a328750f37b85d3480bf0a88ca209a638e2826ffc'),
    (GATEKEEPER, GATEKEEPER_ORIGINAL_SHA, None),
    (CRYPTO, None, '1e61f1c75fdd40b3054eb18d45500eb204f46ec684598c97df659d06f9c0d4d6'),
)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def reorder_needed_vndk30(data, first_lib='libskeymaster4device.so', second_lib='libkeymaster4.so'):
    """Swap two DT_NEEDED entries in an ELF64 LE binary so first_lib precedes second_lib."""
    if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01' or data[18:20] != b'\xb7\x00':
        raise ValueError('Expected AArch64 ELF64 binary')
    shoff = struct.unpack_from('<Q', data, 40)[0]
    shentsize, shnum = struct.unpack_from('<HH', data, 58)
    if shentsize < 64 or shoff + shentsize * shnum > len(data):
        raise ValueError('Invalid ELF section header table')
    dyn_hdr = None
    for i in range(shnum):
        hdr = struct.unpack_from('<IIQQQQIIQQ', data, shoff + i * shentsize)
        if hdr[1] == 6:  # SHT_DYNAMIC
            dyn_hdr = hdr
            break
    if dyn_hdr is None:
        raise ValueError('Missing SHT_DYNAMIC section')
    _, _, _, _, dyn_off, dyn_size, str_idx, _, _, _ = dyn_hdr
    _, _, _, _, str_off, str_size, _, _, _, _ = struct.unpack_from('<IIQQQQIIQQ', data, shoff + str_idx * shentsize)
    strtab = data[str_off:str_off + str_size]
    pos_first = pos_second = None
    val_first = val_second = None
    for off in range(0, dyn_size, 16):
        d_tag, d_val = struct.unpack_from('<QQ', data, dyn_off + off)
        if d_tag != 1:  # DT_NEEDED
            continue
        end = strtab.index(b'\x00', d_val)
        name = strtab[d_val:end].decode('ascii')
        if name == first_lib:
            pos_first, val_first = dyn_off + off, d_val
        elif name == second_lib:
            pos_second, val_second = dyn_off + off, d_val
    if pos_first is None or pos_second is None:
        raise ValueError(f'Missing DT_NEEDED pair ({first_lib}, {second_lib})')
    if pos_first < pos_second:
        return data
    patched = bytearray(data)
    struct.pack_into('<Q', patched, pos_second + 8, val_first)
    struct.pack_into('<Q', patched, pos_first + 8, val_second)
    return bytes(patched)


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
    recorded_files = []
    with tempfile.TemporaryDirectory(prefix='r8q-keymaster-') as temp:
        work = Path(temp)
        with zipfile.ZipFile(archive) as source:
            vendor = reconstruct(source, 'vendor', work, prefix='')
        if vendor['sha256'] != VENDOR_SHA:
            raise ValueError('Reconstructed Lineage Vendor SHA-256 mismatch')

        if any(row['path'] == BIN for row in plan['operations']):
            raise ValueError('Vendor path already staged: ' + BIN)
        old_bin = reader('vendor', BIN)
        if sha(old_bin) != BIN_ORIGINAL_SHA:
            raise ValueError('Unexpected port baseline: ' + BIN)
        (work / ('old-' + Path(BIN).name)).write_bytes(old_bin)
        new_bin = reorder_needed_vndk30(old_bin)
        local[BIN] = new_bin
        (work / Path(BIN).name).write_bytes(new_bin)
        recorded_files.append((BIN, BIN_ORIGINAL_SHA, sha(new_bin)))

        for path, original, digest in FILES:
            if any(row['path'] == path for row in plan['operations']):
                raise ValueError('Vendor path already staged: ' + path)
            if original:
                old = reader('vendor', path)
                if sha(old) != original:
                    raise ValueError('Unexpected port baseline: ' + path)
                (work / ('old-' + Path(path).name)).write_bytes(old)
            data = subprocess.check_output([str(erofs), '--cat', '--path=' + path, str(work / 'vendor.img')],
                                           timeout=30)
            actual_sha = sha(data)
            if (digest is not None and actual_sha != digest) or data[:6] != b'\x7fELF\x02\x01' or data[18:20] != b'\xb7\x00':
                raise ValueError('Official AArch64 payload identity differs: ' + path)
            local[path] = data
            (work / Path(path).name).write_bytes(data)
            recorded_files.append((path, original, actual_sha))

        def inspect(path, prefix=''):
            return elf(work / (prefix + Path(path).name))

        new_deps, new_imports, _ = inspect(BIN)
        old_deps, old_imports, _ = inspect(BIN, 'old-')
        if set(new_deps) != set(old_deps) or new_deps.index(Path(DEVICE).name) >= new_deps.index('libkeymaster4.so'):
            raise ValueError('The reviewed Samsung service dependency order changed')
        if new_imports != old_imports or '_ZdlPvm' in new_imports:
            raise ValueError('VNDK-30 Keymaster service must not introduce new platform symbols')
        for path in (HELPER, DEVICE, GATEKEEPER):
            old_deps_lib, old_imports_lib, _ = inspect(path, 'old-')
            new_deps_lib, new_imports_lib, _ = inspect(path)
            if (new_deps_lib != [Path(CRYPTO).name if lib == 'libcrypto.so' else lib for lib in old_deps_lib]
                or not new_imports_lib <= old_imports_lib):
                raise ValueError('Unexpected Keymaster/Gatekeeper backend ABI change: ' + path)
        (work / 'libcrypto.so').write_bytes(reader('system', '/system/lib64/libcrypto.so'))
        if ('sk_delete' not in inspect(HELPER, 'old-')[1] or
            'sk_delete' in elf(work / 'libcrypto.so')[2] or
            'sk_delete' not in inspect(CRYPTO)[2]):
            raise ValueError('Expected legacy crypto mismatch was not reproduced')

    for path, original, digest in recorded_files:
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
                vndk30_native_service_preserved=True, gatekeeper_shimmed=True,
                files=[dict(path=path, old_sha256=old, sha256=new) for path, old, new in recorded_files])

