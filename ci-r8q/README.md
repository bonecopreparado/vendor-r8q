# R8Q port audit

This branch builds tools and review evidence, not a complete or boot-tested ROM.
No device writes are performed by CI.

The shell installer previously used byte offsets in signed 32-bit shell arithmetic
and numeric tests. Real mksh reproduces both reported symptoms: a negative skip
at 2 GiB and a repeated 4096-byte prefix discard at 4 GiB. P0r7 keeps offsets out
of those operations and preserves all hashes and target guards.

CI runs the regression tests, builds a modern secilc and matching policy-capability
checker from SELinuxProject commit `6423998bc7b154da7f9fe726cfda9ace774dfa94`,
then compares exact original and isolated candidate CIL inputs. Every bundle file
is pinned by hash. All policy capabilities, including `functionfs_seclabel`, must
survive compilation and serialization. The candidate is also checked against
neverallow assertions; findings fail the policy audit and remain in the artifact.

The isolated policy changes do not modify any ROM image and are not declared safe
for deployment merely because compilation succeeds. VINTF/context/kernel/runtime
work remains. Files from devices and personal recovery/logcat logs are not included.

The workflow saves a small tools/audit ZIP as a GitHub Actions artifact and attempts
an optional GoFile mirror using the official HTTPS upload API. Anonymous guest
uploads need no secret; an existing `GOFILE_TOKEN` may be used. Mirror availability
does not change validation results. Select `publish_gofile=false` for manual runs
without a mirror.
