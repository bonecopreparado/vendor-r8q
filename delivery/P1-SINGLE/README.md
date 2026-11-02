# P1 single ZIP installer

This packages the actual P1 composition in one recovery ZIP. It does not require
Windows, Python, external gzip files, a manual installer-building step or a second
ROM-sized extraction directory on the tester's phone. Boot remains unconfirmed.
Known host kernel/FCM/HAL compatibility findings remain explicit in the manifest
and tester instructions. The native helper is a file reader, not a flash writer.

## Build interface

Compile the helper twice: a static AArch64 executable using the pinned Android
NDK for recovery, and a native host executable for independent final ZIP reads:

```sh
aarch64-linux-android29-clang -D_FILE_OFFSET_BITS=64 -static -Os -s \
  -Wall -Wextra -Werror tools/single_zip_helper.c -o build/r8q-zipread
cc -D_FILE_OFFSET_BITS=64 -Os -Wall -Wextra -Werror \
  tools/single_zip_helper.c -o build/r8q-zipread-host
python3 tools/package_p1_single.py --helper build/r8q-zipread \
  --host-helper build/r8q-zipread-host \
  --images-manifest reports/p1/ci-build/package-images.json \
  --output output/HyperOS4-R8Q-P1-SINGLE-EXPERIMENTAL.zip
```

The image manifest must contain exactly super, boot and dtbo with their actual
file paths, byte lengths and SHA256 values. Fixed R8Q capacities and unchanged
reviewed boot/dtbo identities are required. The packager reads every source
twice with identical gzip settings, checks both passes against the identities,
then rereads every completed ZIP member for ZIP CRC, gzip CRC and raw SHA256.
The optional native host helper independently streams and checks all members.

Outputs are the full ZIP, its `.sha256`, `P1-SINGLE-build-report.json` and
`P1-TESTER-ENGLISH.txt`. ZIPs exceed 4 GiB and need internal/exFAT storage;
FAT32 cannot store them. Only the full ROM ZIP is installed in OrangeFox.

## Recovery behavior

The helper is the first ZIP_STORED entry, with data starting at offset4096 and
padded to whole 4 KiB blocks. The early updater uses a small bounded `dd` read
to extract it to `/tmp`, verifies its embedded SHA256, and executes it. The
helper is static AArch64, so recovery's `/system/bin/linker64` is not needed.

The helper parses ZIP64 central/local headers using 64-bit pread, rejects
unsupported/encrypted/duplicate/out-of-bounds members and verifies CRC32 while
streaming named ZIP_STORED gzip members. Recovery's own unzip never processes
multi-gigabyte image entries. Mksh never computes ZIP byte offsets.

The shell derives from the pinned P0r8 template. Battery checks at preflight and
before writing, AVB-header checks, device/capacity/LP-geometry checks, protection
against a source ZIP on a target filesystem, mount/alias checks, all compressed
and raw SHA256 checks, preserved target super prefix and sequential partition
readback remain mandatory. Only super/dtbo/boot are written; userdata is never
automatically formatted.

The tests use bounded mock files and a real mksh. A sparse ZIP with member and
central-directory offsets beyond 5 GiB exercises ZIP64 without allocating 5 GiB
of test data. Tests do not prove OrangeFox runtime, Android boot or hardware.
