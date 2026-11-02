# Clean CI reconstruction of the P1 images

`tools/rebuild_p1_ci.py` starts from the two public pinned ROM archives. It
does not need a tester PC, the old payload folder, an expiring artifact, or any
access to a phone. It refuses previously generated image/build directories.

Use a Linux x86_64 runner with Python 3.11+, zstandard and Brotli modules,
e2fsprogs, the reviewed erofs-utils 1.8.6 tools and **at least 32 GiB free**.
Allow additional disk space for the final ZIP, its temporary gzip pieces and
NDK/tool downloads. A fresh 72 GiB hosted runner is preferable to reusing a
nearly full workspace. Typical duration depends heavily on source-download
speed; this is a multi-gigabyte image rebuild, not a tiny installer patch.

Before reconstruction:

1. Build the pinned SELinuxProject revision with
   `bash ci-r8q/tools/build_secilc.sh`.
2. Build `build/check-contexts` from `ci-r8q/tools/check_contexts.c` linked
   against that same static libsepol. No modern compiler binary from an older
   workflow artifact is required.
3. Prepare `tools/image-tools/root/usr/bin/{mkfs.erofs,dump.erofs,fsck.erofs}`
   from the pinned Debian erofs-utils package. `tools/image-tools/bin` needs
   dump/fsck wrappers; debugfs/e2fsck may use the runner's system tools.
4. Optionally fetch the pinned official Android17 otatools through the existing
   VINTF runner. Pass its extracted `otatools` directory to `--host-tools` so the
   actual new filesystem metadata is checked again.

Run:

```sh
python3 tools/rebuild_p1_ci.py --discard-downloads --discard-intermediate-images --host-tools ci-vintf/otatools
```

`--discard-downloads` is intended for the fresh CI runner only: after all five
source filesystem identities have been checked, it removes the two downloaded
archives to save space. The verified source identities remain recorded.
`--discard-intermediate-images` removes only the four newly derived partition
files after an independent parser proves their exact bytes are present in the
completed super image. It retains the super, boot and DTBO needed by packaging,
and records how to recover every removed partition from super. This saves
about 3.4 GiB before creating both gzip staging files and the final large ZIP.

The flow rebuilds and checks all four changed partitions, verifies every ext4
file through a second implementation, compiles the CIL actually read from those
images, and requires zero invalid context references. It repacks the known
Samsung boot with only the previously reviewed fstab changes, and pads the
original DTBO. Both must reproduce their existing exact hashes. It then builds
the R8Q super using the measured geometry and independently reads back all five
logical partitions with the unchanged LineageOS LP implementation.

The fresh outputs are:

- `candidates/p1/super-r8q-hyperos-p1.img`
- `candidates/p0/boot-r8q-hyperos-p0.img`
- `candidates/p0/dtbo-r8q-p0.img`
- `reports/p1/ci-build/package-images.json`
- `reports/p1/ci-build/` — current-build evidence, never stale snapshot reports

The single-ZIP packager should consume `package-images.json`. Do not require
the new ext4/super hash to equal the earlier local build's raw hash: debugfs and
filesystem bookkeeping timestamps can vary. The source hashes, logical-file
differences, capabilities, context checks, sizes and readback checks remain
mandatory, and the resulting ZIP embeds this build's actual image identities.

## Additional tracked source inputs required by the workflow

Alongside the existing P1 source branch, include:

- `tools/download_verified.py`
- `tools/reconstruct_r8q.py`
- `tools/unpack_hyperos.py`
- `tools/build_boot_candidate.py`
- `patches/0001-first-stage-mounts/fstab.qcom.proposed`
- `patches/0001-first-stage-mounts/status.json`
- `reports/device/validated.json`
- `reports/device/super-first-1MiB.bin` — SHA256
  `a2715d01320391a9dbd2bee3d24a30c1ab45ba5770409f895f4997421eb0d439`
- `reports/composition-proposed.json`
- `tools/lineage-reference/{lp.py,utils.py,lp-source.json}`

The measured prefix contains partition-layout metadata, not a userdata image.
The source archive URLs, byte sizes and SHA256 identities are defined in
`tools/download_verified.py`; all source images are checked against the pinned
original composition before patching.

The current P1 remains an experimental boot-test candidate. A successful
rebuild, valid ZIP and successful readback do not establish kernel loading,
Android startup or working hardware. Current VINTF kernel/FCM4/HAL findings
must remain visible in its release notes.
