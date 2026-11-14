"""Offline, exact-file correction of a truncated DisplayMode group comparison.

This does not install a library or write any device/partition. A rebuilt EROFS
image and separate device testing are still required. No OEM binary is bundled.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

SIZE = 13826216
BUILD_ID = '37802932c7e56f8bdcec511be7bb1e90'
ORIGINAL_SHA256 = '5c472e0e217b054a95b207ccfa4cca8737b2a6e5ce5d0e07aa303a1965f6f5be'
PATCHED_SHA256 = 'f11986fff4ce9d9f1b59d282722d529b8f847f78bac4e4f0a308fe80d911abd6'
VA = 0x49B954
OFFSET = 0x49B954
ORIGINAL = bytes.fromhex('08c14039')  # ldrb w8, [x8, #0x30]
PATCHED = bytes.fromhex('083140b9')   # ldr  w8, [x8, #0x30]
CONTEXT = bytes.fromhex('4a114039aa0000376a3240b908c140395f01086b21030054e8031f2a6ac24139')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def verify(data, patched=False):
    expected = PATCHED_SHA256 if patched else ORIGINAL_SHA256
    if len(data) != SIZE or sha(data) != expected:
        raise ValueError('Exact SurfaceFlinger size/SHA256 differs; no patch is permitted')
    if data[:7] != b'\x7fELF\x02\x01\x01':
        raise ValueError('Expected ELF64 little-endian file')
    kind, machine = struct.unpack_from('<HH', data, 16)
    if (kind, machine) != (3, 183):
        raise ValueError('Expected AArch64 ET_DYN library')
    phoff = struct.unpack_from('<Q', data, 32)[0]
    phsize, count = struct.unpack_from('<HH', data, 54)
    if phsize != 56 or phoff + phsize * count > len(data):
        raise ValueError('Invalid program headers')
    code_offsets = []
    build_ids = []
    for i in range(count):
        typ, flags, off, va, _, size, _, _ = struct.unpack_from('<IIQQQQQQ', data, phoff + i * phsize)
        if off + size > len(data):
            raise ValueError('Segment outside file')
        if typ == 1 and flags & 1 and va <= VA and VA + 4 <= va + size:
            code_offsets.append(off + VA - va)
        if typ == 4:
            pos, end = off, off + size
            while pos + 12 <= end:
                namesz, descsz, nt = struct.unpack_from('<III', data, pos)
                start = pos + 12
                desc = start + ((namesz + 3) & ~3)
                nxt = desc + ((descsz + 3) & ~3)
                if nxt > end:
                    raise ValueError('Truncated ELF note')
                if nt == 3 and data[start:start + namesz] == b'GNU\0':
                    build_ids.append(data[desc:desc + descsz].hex())
                pos = nxt
    if code_offsets != [OFFSET] or build_ids != [BUILD_ID]:
        raise ValueError('Executable mapping/Build ID differs')
    context = CONTEXT[:12] + (PATCHED if patched else ORIGINAL) + CONTEXT[16:]
    if data[OFFSET - 12:OFFSET + 20] != context:
        raise ValueError('Instruction context differs')
    return expected


def transform(data, reverse=False):
    verify(data, patched=reverse)
    after = data[:OFFSET] + (ORIGINAL if reverse else PATCHED) + data[OFFSET + 4:]
    verify(after, patched=not reverse)
    return after


def write_new(path, data):
    # Validate the complete result before opening any destination. Exclusive
    # creation rejects existing files, dangling symlinks and the input itself.
    with Path(path).open('xb') as stream:
        stream.write(data)
        stream.flush()
    if Path(path).read_bytes() != data:
        raise OSError('Output readback differs; do not use the incomplete output')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--reverse', action='store_true', help='Restore the exact original into a NEW offline file')
    args = parser.parse_args()
    if args.input.is_symlink() or not args.input.is_file():
        parser.error('Input must be a regular file, not a symlink')
    result = transform(args.input.read_bytes(), reverse=args.reverse)
    write_new(args.output, result)
    print(json.dumps(dict(status='OFFLINE_LIBRARY_VERIFIED_NOT_INSTALLED_NOT_BOOT_TESTED',
        reverse=args.reverse, sha256=sha(result), bytes=len(result),
        original_build_id_retained=BUILD_ID, instruction_va=hex(VA),
        changed_byte_offsets=['0x49b955', '0x49b957']), indent=2))


if __name__ == '__main__':
    main()
