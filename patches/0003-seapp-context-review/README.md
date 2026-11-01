# Context review proposal — no shipping policy or seapp edits

The first actual context checker run (GitHub Actions 41319419220, exact candidate
policy SHA256 `70278111389ef8affecddf0eee346f4d3cba4b72fe7bc907e512f7c610d769ad`)
checked 2,888 contexts: 2,879 valid and nine invalid. All nine parse successfully;
exact policy context validation returns -1. The eight additional findings were
not predicted by the earlier source-only declaration inventory. They remain
unresolved and visible in the measured regression baseline.

Seven are Samsung vendor seapp process domains: `dsms_app`, `kfa_app`,
`oneseg_apk`, `sec_untrusted_app`, `teed_app`, `teeregistryd_app`, and
`trustonicpartner_app`. Their types exist in the legacy public policy file, but
the requested `u:r:<domain>:s0` context is invalid. The binary trait checker
reports exact role/type authorization and retained domain/appdomain attributes.
The fixed context construction uses Android's process role `r`. The pinned
libsepol `libsepol/src/context.c:context_is_valid` checks role authorization for
the type before checking MLS, so missing role/type authorization cannot be fixed
by changing synthetic MLS categories. This does not prove every matching app is
installed or launched.

`system_ext_seapp_contexts:33` maps `com.qualcomm.telephony` to `radio_service`.
The framework defines that name as a service object type. The invalid process
context is a separate donor mapping issue, rather than a missing type. Do not
make this service object type an app domain merely to satisfy the checker.

The ninth finding, `logdumpd`, is a missing explicit init domain in a disabled
service guarded by `ro.logdumpd.enabled=1`.

Before changing the seven Samsung mappings, inventory the actual APK package
names, signing certificates, seinfo assignments and runtime callers. If an entry
only serves an absent Samsung application, remove that stale seapp selector in
an isolated new image. If the application is retained, restore an intentionally
scoped domain with its role, appdomain attributes, transitions and required
permissions and review those permissions separately. Adding `roletype r` alone
would only fix one validity predicate and would not restore the app's policy.

For `com.qualcomm.telephony`, establish whether the packaged app is needed on
Samsung and which coherent Qualcomm/Samsung telephony domain it should use.
Do not replace it with a broadly privileged domain without this evidence.

No role, type, allow rule or seapp selector is changed by this proposal. The
original P0 CIL compilation failure and the VINTF incompatibilities remain
independent release blockers. The measured baseline is CI regression evidence,
not a policy repair or a claim that the ROM boots.
