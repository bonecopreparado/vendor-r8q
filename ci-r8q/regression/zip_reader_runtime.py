"""Exercise the real reader command across sparse ZIP64 and CRC boundaries.

Use --emulator qemu-aarch64 with the statically linked Android helper. Fixtures
are regular temporary files, not ROMs or block devices. Sparse logical size is
over 5 GiB but allocated disk use stays below 64 MiB. This does not emulate a
phone's storage driver, recovery mounts, or Android boot.
"""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import random
import struct
import subprocess
import tempfile
import warnings
import zipfile

MEMBER = 'payloads/super-012.gz'


def check(condition, message):
    if not condition:
        raise RuntimeError(message)


def run_suite(helper, emulator=None, legacy_two_gib_rejection=False, expected_padded_sha=None):
    helper = helper.resolve(strict=True)
    binary = helper.read_bytes()
    padded_sha = hashlib.sha256(binary.ljust((len(binary)+4095)//4096*4096, b'\0')).hexdigest()
    if expected_padded_sha:
        check(padded_sha == expected_padded_sha, 'Helper differs from published padded binary')
    command = ([str(emulator)] if emulator else []) + [str(helper)]
    version = subprocess.run(command + ['--version'], check=True, capture_output=True,
                             text=True, timeout=30).stdout.strip()
    raw = random.Random(12345).randbytes(2 * 1024**2 + 37)
    payload = gzip.compress(raw, compresslevel=1, mtime=0)
    expected = hashlib.sha256(payload).hexdigest()
    results = []

    def invoke(path, size=False, member=MEMBER):
        return subprocess.run(command + (['--size'] if size else []) + [str(path), member],
                              capture_output=True, timeout=60)

    def fixture(path, prefix=0, method=zipfile.ZIP_STORED, data=payload):
        if prefix:
            with path.open('wb') as stream:
                stream.truncate(prefix)
        with zipfile.ZipFile(path, 'a' if prefix else 'w', allowZip64=True) as archive:
            info = zipfile.ZipInfo(MEMBER)
            info.compress_type = method
            with archive.open(info, 'w', force_zip64=True) as stream:
                stream.write(data)
        with zipfile.ZipFile(path) as archive:
            check(archive.read(MEMBER) == data, 'Independent Python ZIP readback failed')
            offset = archive.getinfo(MEMBER).header_offset
        with path.open('rb') as stream:
            stream.seek(offset)
            header = stream.read(30)
        start = offset + 30 + struct.unpack_from('<H', header, 26)[0] + struct.unpack_from('<H', header, 28)[0]
        check(path.stat().st_blocks * 512 < 64 * 1024**2, 'Fixture is not sparse/bounded')
        return start

    with tempfile.TemporaryDirectory(prefix='r8q-reader-runtime-') as directory:
        root = Path(directory)
        offsets = [('ordinary', 0), ('local_offset_2g_minus_1', 2**31-1),
                   ('stream_crosses_4g', 2**32-256*1024),
                   ('local_offset_uint32_max', 2**32-1),
                   ('central_and_member_above_5g', 5*1024**3+4096)]
        for name, offset in offsets:
            path = root / (name + '.zip')
            start = fixture(path, prefix=offset)
            if name == 'stream_crosses_4g':
                check(start < 2**32 < start + len(payload), 'Fixture does not cross 4 GiB')
            result = invoke(path)
            if name == 'local_offset_2g_minus_1' and legacy_two_gib_rejection:
                check(result.returncode != 0 and not result.stdout and
                      b'central directory bounds invalid' in result.stderr,
                      'Published helper did not reproduce its known 2 GiB compatibility bug')
                results.append(dict(name=name, passed=True, known_legacy_rejection=True,
                                    diagnostic=result.stderr.decode().strip()))
                path.unlink()
                continue
            check(result.returncode == 0 and result.stdout == payload,
                  name + ': valid member rejected/corrupted: ' + result.stderr.decode(errors='replace'))
            sized = invoke(path, size=True)
            check(sized.returncode == 0 and sized.stdout.strip() == str(len(payload)).encode(),
                  name + ': wrong reported member size')
            results.append(dict(name=name, passed=True, local_offset=offset,
                                data_offset=start, data_bytes=len(payload),
                                logical_zip_bytes=path.stat().st_size, sha256=expected))
            path.unlink()

        # More than 256 consecutive 64 KiB reads, including a partial last block.
        path = root / 'long.zip'
        long_data = payload * 9 + b'partial-final-block'
        fixture(path, data=long_data)
        result = invoke(path)
        check(result.returncode == 0 and result.stdout == long_data,
              'Long CRC stream differs: ' + result.stderr.decode(errors='replace'))
        results.append(dict(name='long_crc_stream_partial_last_block', passed=True,
                            data_bytes=len(long_data), sha256=hashlib.sha256(long_data).hexdigest()))
        path.unlink()

        for name, prefix, relative in [('corrupt_before_4g', 2**32-256*1024, 3),
                                       ('corrupt_after_4g', 2**32-256*1024, len(payload)-3)]:
            path = root / (name + '.zip')
            start = fixture(path, prefix)
            with path.open('r+b') as stream:
                stream.seek(start+relative)
                byte = stream.read(1)
                stream.seek(start+relative)
                stream.write(bytes([byte[0] ^ 1]))
            result = invoke(path)
            check(result.returncode != 0 and b'CRC32 mismatch' in result.stderr,
                  name + ': corruption did not fail CRC')
            results.append(dict(name=name, passed=True, corruption_offset=start+relative,
                                exit=result.returncode, diagnostic=result.stderr.decode().strip()))
            path.unlink()

        for name in ('truncated_at_4g', 'local_crc_mismatch', 'unsupported_outer_deflate',
                     'duplicate_member', 'missing_member'):
            path = root / (name + '.zip')
            if name == 'truncated_at_4g':
                fixture(path, 5*1024**3+4096)
                with path.open('r+b') as stream:
                    stream.truncate(2**32-1)
            elif name == 'unsupported_outer_deflate':
                fixture(path, method=zipfile.ZIP_DEFLATED)
            else:
                fixture(path)
                if name == 'local_crc_mismatch':
                    with path.open('r+b') as stream:
                        stream.seek(14)
                        byte = stream.read(1)
                        stream.seek(14)
                        stream.write(bytes([byte[0] ^ 1]))
                elif name == 'duplicate_member':
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore')
                        with zipfile.ZipFile(path, 'a') as archive:
                            archive.writestr(MEMBER, payload)
            result = invoke(path, member='payloads/missing.gz' if name == 'missing_member' else MEMBER)
            check(result.returncode != 0 and not result.stdout,
                  name + ': invalid header/archive emitted member bytes')
            results.append(dict(name=name, passed=True, exit=result.returncode,
                                diagnostic=result.stderr.decode().strip()))
            path.unlink()
    return dict(status='READER_FIXTURES_PASS_NOT_A_PHONE_BOOT_TEST',
                command=command, version=version, helper_sha256=hashlib.sha256(binary).hexdigest(),
                padded_helper_sha256=padded_sha, published_helper_match=bool(expected_padded_sha),
                known_legacy_two_gib_rejection=legacy_two_gib_rejection,
                elf_machine=struct.unpack_from('<H', binary, 18)[0],
                emulator=bool(emulator), passed=len(results), physical_writes=False,
                boot_test=False, cases=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helper', required=True, type=Path)
    parser.add_argument('--emulator', type=Path)
    parser.add_argument('--report', required=True, type=Path)
    parser.add_argument('--legacy-two-gib-rejection', action='store_true',
                        help='Reproduce the documented parser bug only in the pinned published helper')
    parser.add_argument('--expected-padded-sha', help='Require exact identity with a published helper')
    args = parser.parse_args()
    report = run_suite(args.helper, args.emulator, args.legacy_two_gib_rejection, args.expected_padded_sha)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
