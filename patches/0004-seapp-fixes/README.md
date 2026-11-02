# Isolated P1 application-context corrections

These are concrete configuration edits for the exact current factory
composition. They do not add SELinux allows, aliases, roles or privileges.
`tools/prepare_seapp_candidate.py` checks the original source SHA256 and APK
inventory SHA256 before writing the two candidate files and their diffs.

## Measured application coverage

The read-only inventory recursively enumerated all five P0 source partitions:
374 `.apk` paths comprise 372 real APKs and two zero-byte placeholders under
`/mi_ext`. Both empty files have the SHA256 of an empty string, so neither can
provide a package. The separate APEX inventory verified every container and
payload identity from the VINTF exporter, then scanned all 46 factory modules.
It found 29 additional signed APKs. Thus the absence checks cover **401 actual
factory APK package/shared-UID identities and signing-certificate metadata**.

No inspected package matches any named selector for the seven invalid Samsung
app domains. No APK claims an `oneseg` shared UID. None of the factory APK
certificates matches the 20 vendor signer certificates assigning
`trustonicpartner`; no `good_trustonicpartner` certificate assignment exists.
The seven domain families therefore select no factory application in this
composition. Removing their 18 stale rules avoids invalid process contexts
without assigning a replacement privileged domain.

The certificate scan reads APK v2/v3 signing blocks or v1 PKCS7 metadata; it
does not independently verify signatures. Images/container identities are
pinned. `/data` apps and future sideloaded Samsung/Trustonic apps are outside
the available evidence. This factory port does not promise those app suites.

## Qualcomm duplicate selectors

Four exact selector-input groups are duplicated across the existing files:

* `com.qualcomm.telephony`: remove the system_ext rule requesting the invalid
  process domain `radio_service`. Retain the existing vendor rule requesting
  `vendor_qtelephony`, the already valid telephony app domain. No new rule is
  added. `radio_service` remains a service-object label elsewhere.
* `org.codeaurora.ims`: remove the vendor copy; system_ext already supplies the
  same selector, domain, data type and MLS output.
* `com.qualcomm.qti.devicestatisticsservice`: remove the vendor copy; product
  already supplies the identical output.
* `com.qualcomm.qti.services.systemhelper:systemhelper_service`: retain the
  system_ext mapping to `system_app_data_file` and remove the contradictory
  vendor output `app_data_file levelFrom=user`. Its actual APK declares
  `sharedUserId=android.uid.system`. Both framework and vendor CIL already
  permit this domain to access `system_app_data_file`; the change adds no allow.

All 22 modifications remove lines. No new process or data label is introduced.
The builder refuses changed domain mappings, different SystemHelper UID or
missing coherent retained rules. Duplicate-input groups are empty afterward
in the three contributing files; the unchanged plat/odm sources had no other
duplicate groups in the full five-file inspection.

## Validation and integration limits

Ten bounded regression tests cover package/prefix/signing-certificate/shared
UID collision rejection, unknown APK inspection failure, missing APEX coverage,
unexpected domain replacements, and exact retention of existing vendor
telephony policy. Run:

```
python3 tools/prepare_seapp_candidate.py
python3 -m unittest discover -s ci-r8q/tests -p test_seapp_candidate.py -v
```

`context-projection.json` projects changed references against the prior exact
binary-policy measurement: eight invalid seapp process contexts disappear;
the separate disabled `logdumpd` init finding remains. This is a subset proof
using the unchanged policy, not a fresh policy/runtime load test. The parent
image build must read back the installed files, regenerate complete references
and run the binary checker against the newly composed image inputs.

The original CIL duplicate-declaration repair is a separate candidate. No ROM
image, phone partition, runtime setting or release readiness flag is changed
by this directory. App startup, IMS and hardware behavior remain unconfirmed.
