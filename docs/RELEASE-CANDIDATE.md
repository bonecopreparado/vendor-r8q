# P0r8 installer candidate — HOLD

This draft contains a complete recovery installer candidate and its checksum,
build attestation, English instructions, readiness status and a separate audit
report TAR. The small ZIP reuses the original 22 external gzip payloads; it does
not contain the multi-gigabyte ROM. No PC-side installer creation is needed.

**Boot is unconfirmed. The P0 ROM composition still has unresolved SELinux,
VINTF/kernel and runtime work. This draft does not recommend another device
flash.** Battery checks, valid payload hashes, successful readback and green
regression CI are distinct from a bootable, compatible system.

The candidate adds battery guards before preflight and again before the first
partition write. It retains the existing device, image, geometry, AVB, path,
mount, compressed/raw hash and readback checks. It does not format userdata or
write vbmeta, recovery, modem, bootloader or EFS. The original P0 images have
not changed as a result of these installer corrections.

The installer, checksum and attestation must refer to the exact same ZIP.
The English instructions explain SHA256 verification on Android. For a computer
with GitHub CLI, the attestation can also be verified with:

```sh
gh attestation verify HyperOS4-R8Q-P0r8-CANDIDATE.zip --repo bonecopreparado/vendor-r8q
```

`R8Q-AUDIT-REPORTS-NOT-FLASHABLE.tar.gz` contains reports, status and licenses.
It has no recovery updater and must never be selected in OrangeFox Install.
Missing CI report roots are recorded in its package manifest and do not mean
that a compatibility check passed. Compiler binaries, proprietary inputs and
phone capture logs are excluded from this report package.

This workflow creates a **draft prerelease only** from `main`, for owner review.
It does not publish the release, upload the candidate to GoFile, or distribute
the installer through public Actions artifacts. Publishing requires review of
the exact image composition and its compatibility/runtime evidence, a new
explicit readiness decision, and matching release notes. Until then retain the
HOLD status and do not treat this draft as a testing invitation.
