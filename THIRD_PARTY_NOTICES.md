# Third-party notices and licensing scope

The [MIT license](LICENSE) applies to this project's original tooling,
installer code, tests and documentation. Third-party files keep their original
terms. The license does not relicense ROMs, vendor blobs, extracted device
configs, SELinux policies, firmware, kernels or recovery images. A download
link, input hash or baseline archive does not grant redistribution rights.

## CPython gzip module

`tools/python31210_gzip.py` is a copy of
[`Lib/gzip.py` from CPython v3.12.10](https://github.com/python/cpython/blob/v3.12.10/Lib/gzip.py).
Its SHA256 is:

```text
2a1d4faf848c63223d489af17599580a1b35c65a704d9750a8d3a17286b65b1e
```

The file was renamed locally to allow the metadata reproduction tool to load
the upstream gzip implementation. The local copy has one additional empty line
at end of file; no Python statements, constants or compression behavior were
changed. The upstream file's SHA256 is
`ea6e194b9df26398bf0d5215e63320c7b9d801b2d8b723fb9c80619df48076e9`.
The pinned local source hash above is retained to preserve provenance.
The file remains governed by the upstream Python licenses. The complete upstream
v3.12.10 license, including the PSF copyright notice, is retained in
[licenses/CPython-3.12.10-LICENSE.txt](licenses/CPython-3.12.10-LICENSE.txt).
The notice and license must accompany redistribution of this source file.

The module is used to reproduce the gzip identities of existing P0 payloads.
It is not included in the small recovery installer. Its source SHA is also
recorded in `delivery/Ready-P0r7/payload-identities.json`; changing that source
requires a new provenance review rather than silently updating the pin.

## Downloaded Python runtime and optional packages

When the historical Windows preparation kit includes a Python runtime, retain
that distribution's complete `runtime/LICENSE.txt`. The Windows distribution
also contains conditions for its bundled binaries and components; the source
module license above does not replace those notices. Optional Python packages
such as Brotli, zstandard and lz4 retain the licenses shipped in their package
metadata. This repository's MIT license does not supersede them.

## Android, SELinux and device inputs

Android source excerpts, SELinux/compiler dependencies, firmware configuration
and device policy inputs retain their upstream or manufacturer copyright and
license notices. Pinned sources and audit inputs are evidence of the exact
composition examined, not a declaration that the project owns those materials.
Build tools fetched by CI must retain their upstream notices in redistributions.

The SELinux compiler build uses SELinuxProject commit
`6423998bc7b154da7f9fe726cfda9ace774dfa94`.
[`libsepol/LICENSE`](https://github.com/SELinuxProject/selinux/blob/6423998bc7b154da7f9fe726cfda9ace774dfa94/libsepol/LICENSE)
is retained in [licenses/SELinux-libsepol-LGPL-2.1.txt](licenses/SELinux-libsepol-LGPL-2.1.txt).
[`secilc/LICENSE`](https://github.com/SELinuxProject/selinux/blob/6423998bc7b154da7f9fe726cfda9ace774dfa94/secilc/LICENSE)
is retained in [licenses/SELinux-secilc-FreeBSD.txt](licenses/SELinux-secilc-FreeBSD.txt).
The LGPL terms for libsepol still apply when linked into a host executable.
Publishing compiler binaries requires the corresponding source and relinking
materials required by their licenses; publishing only hashes does not supply
those materials. The source pin and build recipe are recorded in
`ci-r8q/tools/build_secilc.sh`.

The baseline vendor archive and external ROM/vendor releases are not licensed
under the project's MIT license. Obtain external images from their maintainers
and observe their applicable distribution terms. A source/tooling release is
separate from a complete ROM distribution.

## LineageOS LP reader and AOSP compatibility reference

`tools/lineage-reference/lp.py` and `utils.py` retain the LineageOS Project
copyright and Apache-2.0 SPDX headers. The pinned LP reader provenance is in
`tools/lineage-reference/lp-source.json`. They are used unchanged for an
independent readback of the candidate super, outside the image builder.
The complete Apache-2.0 text is retained at
`patches/0005-vintf-adaptation/reference/NOTICE`, alongside the pinned AOSP
FCM4 diagnostic-only reference and its source provenance.
