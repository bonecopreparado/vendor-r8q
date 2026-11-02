# P1r1: system_ext/product mapping experiment

The P1 full ZIP flashed successfully on two testers, but they report a reboot
about two seconds after the Samsung logo. The submitted logs captured recovery,
not the failed Android boot. The donor developer's instruction, as relayed by
the user, specifically names the mapping directories in system_ext and product.

P1r1 removes the 15 regular mapping files in system_ext and the eight in product.
It retains system/platform mappings, the system_ext/product policy CIL files,
vendor interface 30.0, all six policy capabilities, kernel, boot and DTBO. The
empty mapping directories retain their metadata. All other P1 adaptations stay.
This is an experiment to test that advice, not a confirmed bootloop correction.
Known kernel/FCM/HAL VINTF findings remain explicit.

The compiler probe without the three active optional mapping CIL inputs produced
policy SHA256 `a09214b72ab473870e055aa7f2678e53fc1c5e657477c0b24974ef201f025eed`
and validated all 2,879 referenced contexts. Actual rebuilt filesystems must be
checked again; this host probe alone does not validate runtime boot/access.

## Clean CI build

`.github/workflows/r8q-p1r1-singlezip.yml` reconstructs the same pinned complete
archives, passes `--omit-optional-mappings` to the planner and policy verifier,
rebuilds product as well as system/system_ext, and verifies the full unchanged
file contents and metadata. Both policy and VINTF tools read the rebuilt product.
All five logical partitions are independently read back from super before any
derived filesystem is discarded. Original source images remain untouched.

The packager propagates `build_label: P1r1` and all 23 hash-pinned mapping removals
from the fresh image manifest into the final ZIP manifest and build report.
Its native ZIP64 reader, battery/AVB/device/geometry/mount checks, compressed and
raw hashes, write/readback checks and target-super-prefix preservation remain.

The workflow produces `HyperOS4-R8Q-P1r1-SINGLE-EXPERIMENTAL.zip`, its SHA256,
English phone-only instructions and provenance. It uploads the full ZIP to
GoFile and publishes that link plus small evidence files in a GitHub prerelease.
The Actions report artifact and GitHub source archives are not ROM installers.
