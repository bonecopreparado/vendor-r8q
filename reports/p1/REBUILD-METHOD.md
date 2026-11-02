# Metadata-preserving offline EROFS reconstruction

`tools/rebuild_erofs_candidate.py` rebuilds the complete filesystem from a PAX
TAR stream. It does not mount a filesystem, change host ownership, mutate an
original image, or write inode bytes directly. The stream contains every source
path, original UID/GID, mode, mtime/nanoseconds, symlink targets, hardlink
relationships and complete logical xattrs. Patched content is accepted only
when its old and new SHA256 identities match the explicit plan. Added files
require an existing metadata template and parent directory.

The locally unpacked official Debian erofs-utils 1.8.6 tools supply file reads,
image creation and integrity checks. Builds use the original block size and
filesystem UUID, LZ4HC compression, and strict per-file mtime preservation.
New kernel-incompatible feature bits are rejected. The build reads its original
image hash before and after execution.

After `fsck.erofs --extract` validates all encoded files without materializing
them, a second complete inventory compares every path, file content hash,
symlink content, UID, GID, mode, timestamp, link count and xattr with the expected
composition. Original hardlink aliases must still resolve to one output inode.
This is logical equality rather than a claim that filesystem block layout or
the image's bytes remain identical.

Six bounded real-tool fixture tests pass. They include a compressed source,
symlink, hardlink aliases, UID 65536, SELinux labels, a binary capability xattr,
an add/delete plan, altered input rejection, preservation of an existing
output, and rejection of a report path that would overwrite the source image.
Fixture command:

```
python3 ci-r8q/regression/rebuild_erofs_fixture.py
```

An earlier experiment with erofs-utils' incremental/rebuild modes was rejected:
it reserved zero-filled data and xattr areas and changed root metadata. None of
that experimental method is used in these candidate images.

The TAR is streamed directly into mkfs, so no complete extracted host tree or
uncompressed on-disk TAR is needed. During compression mkfs may temporarily use
a large sparse logical file; only its final filesystem size is reported.

These are offline candidate images. Successful integrity and logical readback
checks do not prove that the Samsung kernel mounts them or that Android boots.
