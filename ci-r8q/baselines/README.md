# SELinux diagnostic regression baseline

`neverallows-v1.json` preserves the exact multiset of normalized verbose
diagnostics from the pinned isolated candidate. It contains **338 records**:
335 regular `neverallow` records and three extended ioctl `neverallowx` records.
There are 337 distinct full diagnostics. The earlier summary counted only the
335 regular records (334 distinct regular assertions); its parser omitted the
extended form. This baseline corrects that omission.

The baseline includes all matching allow rules from `secilc -v`, not the
truncated first-four-rule output. File names and canonical rule text identify
findings. Absolute checkout prefixes, source line numbers and output ordering
do not; duplicate occurrence counts are preserved. An added matching allow is
a new diagnostic even when its neverallow assertion was already present.

Run the audit using `tools/run_policy_audit.py --baseline
ci-r8q/baselines/neverallows-v1.json` along with its normal compiler/input/output
arguments. The unchanged raw audit still fails with these findings and is
retained in `result.json`. A separate gate reruns strict compilation with `-v`,
checks that candidate init compilation and all policy capabilities are intact,
and fails on new findings, unknown diagnostics, truncated diagnostics, or other
compiler errors. Resolved records are reported as improvements.
Removing matching allow rules from an existing assertion is also reported as
an improvement; matching preserves each occurrence's capacity and cannot
accept an allow absent from that assertion's baseline.

A green regression check means no added finding; it **does not mean that the
policy passes neverallow assertions or that the ROM is boot ready**. Reports
always retain `boot_ready: false` and a `NOT_BOOT_READY` status. No policy rule,
capability, filesystem image or runtime enforcement setting is changed here.
