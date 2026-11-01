# Already-generated P0r7 recovery installer

The latest tester log selected `Auditoria-R8Q-20261031 (1).zip` from the
`payloads` directory. OrangeFox rejected its file format before launching an
updater. The 4,501,288-byte audit/tools archive was not a recovery installer.

`tools/package_ready_p0r7.py` builds a conventional recovery ZIP with a top-level
`META-INF/com/google/android/update-binary`, executable mode 0755, the updater
script, manifest, and English instructions. This is the file the tester selects
in OrangeFox Files. No PC-side installer generation is needed.

The reviewed P0r7 installer template is pinned by SHA256. The only execution
change permits the ZIP either next to `payloads` or inside the directory holding
the original 22 `.gz` files. Canonical path checks, target partition protection,
compressed SHA256, gzip CRC, raw SHA256, size/geometry/AVB checks and write
readback checks are retained. The recovery status label identifies ready1.

The 22 raw chunk identities and all three original image identities are pinned
by the original P0r5 layout. Their gzip identities were reproduced offline from
the actual original images, using the official CPython v3.12.10 `Lib/gzip.py`,
zlib 1.3.1, level 1, filename empty, mtime zero, and 4 MiB writes: the same code,
library and settings as the shipped Windows kit. Each generated gzip stream
was simultaneously decoded to check CRC, size and raw hash. The full image
hashes and special first-super readback hash were also verified. The phone
still verifies the actual compressed and raw files before any write. A
different gzip representation will stop at those checks.

The metadata reproduction sources are retained in
`tools/prepare_ready_p0r7_metadata.py` and `tools/python31210_gzip.py`.
`delivery/Ready-P0r7/payload-identities.json` records the source module hash.

The ROM images have not changed. This corrects distribution and installer
folder discovery; it does not prove boot or fix SELinux, VINTF, radio, camera
or biometric compatibility. No real phone or physical partition was written
by the offline validation.
