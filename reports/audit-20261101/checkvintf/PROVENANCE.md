# Exact metadata export and official checkvintf execution

The host input is `ci-r8q/inputs/checkvintf-inputs.tar.gz`, 110,589 bytes,
SHA256 `f17ddd9728493043147ab5506a4123e1c613e0570943962904e789ce08030432`.
The runner refuses a different input hash.

`tools/prepare_checkvintf_inputs.py` read the five P0 source images without
mounting or modifying them. Every complete source image SHA256 and size matched
`reports/composition-proposed.json`; these are the same immutable files embedded
in P0 super. It exported all VINTF XML trees, relevant legacy XML and build.prop
files. All 84 XML files from the preceding independent filesystem config export
are present and byte-identical, including 24 filenames containing `@`.

All 46 preinstalled APEX/CAPEX modules in the five source partitions were read.
Compressed modules were opened through their original_apex ZIP member, each
payload was read through the appropriate host ext4/EROFS tool, and /etc/vintf
was recursively collected. Only com.android.virt supplies an additional VINTF
fragment. Container and payload hashes, actual module names/versions and source
partitions are recorded in the input manifest.

The generated `apex-info-list.xml` is an **explicit host model of all factory
modules active**, not a capture of apexd state. It supplies the actual source
partition tags required by Android 17 Apex.cpp to collect framework/vendor/ODM
fragments. It does not validate APEX activation, payload trust, rollback, data
updates or an Android runtime namespace. Actual phone activation can differ.

The kernel is the real P0 boot kernel, SHA256
`d64c9c8856b7a30acb0fcc262d931f48a062a2077fcd9357a1974667aa37880e`.
Its embedded release is `4.19.325-st11-rc-not:A.06@a1182f39`; its IKCONFIG was
decompressed directly and matched the independent previous export, SHA256
`ce4b98d368058f4d5fd2c5c3380d53813a10f57c72544838548c61759bceab4a`.
The CI host kernel is never used as the phone kernel.

Properties: first_api_level=29 comes from the actual vendor build.prop;
hardware SKU was returned empty by the original read-only r8q inventory.
Vendor SKU was not collected; empty is explicitly a host assumption. No SKU
manifest alternatives were found in the current vendor/ODM trees. Runtime
property overrides still require phone logs.

`ci-r8q/tools/run_checkvintf.py --output vintf-results` downloads official AOSP
otatools via ci.android.com, records the exact build/target/release/API/archive
SHA256 and checkvintf binary SHA256 in tool-lock.json. Discovery first tries
Android 17 and verifies release 17/API37 from that build's official build.prop.
A different API is diagnostic only and yields BLOCKED_TOOL_VERSION_MISMATCH.
The first run discovers and locks evidence; it is not a pre-reviewed tool pin.
After review, checking in ci-r8q/pins/official-otatools.json makes subsequent
runs use that exact build and verify the reviewed archive SHA before execution.

Checks include framework/device consistency, full metadata without kernel,
full metadata with the actual candidate kernel/config, and literal two-file
manifest/matrix checks as targeted diagnostics. Full `--check-compat` combines
checkCompatibility, checkDeprecation and additional HAL checks; there is no
standalone deprecation flag. Targeted pair checks do not compose fragments and
are not substitutes for the full command. Raw commands, outputs and exit codes
are retained separately.

Eight offline runner tests passed, including tool version selection, mismatched
SDK handling, foreign redirects, altered locked tools, exact input/kernel
identities, @ filenames, and Android 17 APEX partition selection. The real host
check must be read from the CI-produced gate.json/results.json. A successful
audit process or green CI job is not ROM compatibility approval or proof of boot.
