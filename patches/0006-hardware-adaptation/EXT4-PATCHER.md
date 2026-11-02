# Offline ext4 candidate builder

`tools/patch_ext4_candidate.py` edits an independent regular image file. It never
accepts a physical block device or patches an input image in place. No actual
vendor image was written during the ten bounded fixture tests.

Example plan, stored beside its candidate content file:

```json
{
  "schema_version": 1,
  "source_image_sha256": "EXACT_SHA256_OF_THE_ORIGINAL_VENDOR_IMAGE",
  "operations": [
    {
      "op": "replace",
      "path": "/etc/init/example.rc",
      "old_sha256": "EXACT_ORIGINAL_FILE_SHA256",
      "source": "candidate/etc/init/example.rc",
      "sha256": "EXACT_NEW_FILE_SHA256"
    }
  ]
}
```

Run against the agreed patch manifest, with a fresh output path:

```sh
python3 tools/patch_ext4_candidate.py \
  --source extracted/r8q/vendor.img \
  --plan patches/0006-hardware-adaptation/vendor-patch-plan.json \
  --output candidates/p1/vendor.img \
  --report reports/p1/vendor-build.json
```

`delete` operations need `path` and `old_sha256`. `add` operations need `path`,
`source`, `sha256`, and `metadata_from`, naming an existing regular source file
whose owners, mode, timestamps and extended attributes are intentionally reused.
New files are not allowed to silently default to an unlabeled/root-only mode.
The report path must also be fresh and distinct from image/plan files.

The input image and every changed file are SHA256 pinned. Files with multiple
hardlinks or special inode flags are refused. Every path component must be an
actual directory; image symlinks and debugfs command metacharacters are refused.
Patch content stays beneath the plan directory and is copied into a controlled
temporary path before debugfs receives it.

Replacements preserve uid, gid, mode, project ID, generation/version, supported
flags, all four timestamps including extra fields, and every extended attribute
as binary bytes. This includes the exact `security.selinux` label. The same
metadata is preserved for parent directories. Inode allocation, file extent
locations and directory byte sizes may change and are not claimed identical.

The source must pass read-only `e2fsck -fn`. After edits, another read-only check
runs first. If already clean, no preen or optimization is requested. If repair
is actually required, `e2fsck -fp -E fixes_only` runs only on the private staging
copy and accepts only normal clean/corrected exit statuses. This conditional
repair is necessary because debugfs file removal can leak an external
EA block even after removing the attributes; the binary-xattr fixture exposed
and reproduces that behavior. Preen refuses repairs needing interactive/forced
approval, and the complete output is retained. A fresh read-only `-fn` must then
return zero, every changed file is read back, all preserved metadata is compared,
and the original image SHA256 must still match. Only then is the new image
published exclusively to the previously nonexistent output path.

Preen can also optimize large untouched linear directories into indexed htrees,
changing flags and storage layout unnecessarily, even with `fixes_only` on the
bundled e2fsprogs 1.47.2. The verifier exposed this documented-option limitation.
The full-tree independent reader caught that in the first vendor candidate at
`/lib` and `/lib64`. The revised builder avoids preen for already-clean candidates;
the large-directory fixture checks both flags and size. If actual repair was
needed, full independent tree comparison remains necessary to detect unrelated
layout changes. A private-stage repair is never treated as proof that unrelated
directory flags stayed unchanged.

The builder records the resulting image hash and checks; filesystem housekeeping
timestamps can vary between runs. It does not claim byte-identical reproducible
images, Android compatibility, boot, or NFC functionality merely because ext4
validation succeeds.
