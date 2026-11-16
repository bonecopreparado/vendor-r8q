# Kernel configuration audit: Lineage r8q references versus P1r4

This is a read-only comparison and a proposed compile/config experiment.
No kernel was compiled or flashed, and no boot fix is claimed.

## Pinned inputs

- LineageOS kernel lineage-23.2: `50cffe6c51d966229ba80656e70210ce8c396655`.
- LineageOS common device lineage-23.2: `7a4f1a3feaada10fef3d5afcc4f212817fcd4f84`.
- Additional lineage-24.0 look-only kernel: `b13460286d2792b13c0090fe1ad688a7136410e3`.
- Additional lineage-24.0 common device: `576897d7c84c391b326ebd8b109062e0219b3096`.
- Current Notkernel source: `a265508933bbecb682e45e3b956d95bf4426d60b`.
- Current actual configuration was extracted from the real P1r4 raw Image,
  not inferred from its source defconfig. `provenance.json` records local
  input SHA256s. The shipped old config was independently checked too.

The upstream common BoardConfig selects `vendor/kona-perf_defconfig` and
`vendor/samsung/kona-sec-common.config`; r8q adds `vendor/samsung/r8q.config`.
The JSON comparison merges explicit requests from these three fragments.
It is not a full upstream `olddefconfig` output; invisible defaults are
discussed separately where their source was inspected.

## Strongest concrete gaps

| Selector | Actual P1r4 | Upstream explicit request |
| --- | --- | --- |
| `CONFIG_PSI` | n, actual config line 97 | y, kona-perf line 11 |
| `CONFIG_MEMCG` | n, line 148 | y, line 20 |
| `CONFIG_MEMCG_SWAP` | absent because MEMCG is off | y, line 21 |
| `CONFIG_CGROUP_FREEZER` | n, line 157 | y, line 24 |
| `CONFIG_MEMFD_ASHMEM_SHIM` | n, line 965 | y, line 116 |

These first three disabled parent options also occur in the shipped old
baseline config; they are inherited configuration, not an R2 regression.
The existing Android boot cmdline already includes `androidboot.memcg=1`,
but that userspace property cannot enable a disabled kernel memory controller.
No cgroup memory-disable parameter was observed in the retained boot cmdlines.

The installed Vendor directly requires the **v1 freezer ABI**:
`etc/init/hw/init.r8q.rc:129-136` mounts `freezer` at `/dev/freezer` and
writes `freezer.state`; camera-provider rc lines 26/32 write its cgroup.procs.
Current source also contains the v2 cgroup.freeze interface, but it does not
provide the missing v1 controller. This is a concrete kernel/init mismatch.

Missing PSI/MEMCG is a meaningful candidate for the memory-daemon integration
failures. It does not prove the cause of the observed camopt SIGSEGV: the
supplied log lacks the LMKD fault PC and complete tombstone.

## Minimal isolated memory experiment

`memory-profile-proposal.json` gives these requested additions:

```text
CONFIG_PSI=y
# CONFIG_PSI_DEFAULT_DISABLED is not set
CONFIG_MEMCG=y
CONFIG_MEMCG_SWAP=y
CONFIG_MEMCG_SWAP_ENABLED=y
CONFIG_CGROUP_FREEZER=y
# CONFIG_MEMCG_HEIMDALL is not set
```

Current `init/Kconfig:937-940` makes MEMCG select PAGE_COUNTER and EVENTFD.
CGROUPS is already y. SWAP and EVENTFD are already y in the real Image;
MEMCG_SWAP depends on MEMCG and SWAP. MEMCG_SWAP_ENABLED defaults y.
FREEZER is already y; enabling the v1 controller does not require changing
the existing suspend/freezer infrastructure.

CGROUP_WRITEBACK is hidden default y when MEMCG and BLK_CGROUP are y
(current init/Kconfig:1004-1007). BLK_CGROUP is already y in the shipped
and actual configurations, so enabling MEMCG also enables cgroup-aware
writeback; the isolated proposal pins/checks this closure explicitly.

Record the `olddefconfig` changes to MEMCG_KMEM (hidden default y with !SLOB),
MEMCG_FORCE_USE_VM_SWAPPINESS (default y), and SLUB_MEMCG_SYSFS_ON. Do not
hide newly selected symbols from the semantic config delta.

### Heimdall is an explicit semantic choice

Neither upstream selected fragment explicitly sets MEMCG_HEIMDALL, but both
current mm/Kconfig:986-992 and upstream mm/Kconfig:959-965 default it y
when MEMCG becomes available. It is not just a dormant daemon flag:

- mm/memcontrol.c:210-214 changes reclaim-loop limit 100 to 10.
- Current lines 2871-2874 skip non-kswapd soft-limit reclaim.
- Lines 3122-3131 change non-root memory usage accounting from page_counter
  (which includes cache) to RSS, optionally plus swap.
- It adds the memory.force_shrink userspace endpoint at 4406-4410.

No Heimdall/force_shrink use was found in the supplied Vendor init corpus;
the complete HyperOS userspace has not been inspected for it. Requesting n
in the proposed profile deliberately avoids silently enabling these Samsung
accounting/reclaim changes while adding standard memcg capabilities. It is
a conservative experimental choice, not an assertion that upstream's y is
wrong or that a daemon dependency has been disproved.

### Guards and validation

Keep the existing NFLOG, hardware, kernel-image header and all enabled
KernelSU/SUSFS protections. Add the desired options to REQUESTED so current
`build_current.config_guards()` and `verify_linked()` check them both after
olddefconfig and against the actual linked Image's IKCONFIG.

Adding MEMCG/PSI/freezer to the baseline-value-preserving EXTRA_PROTECTED
list without explicit reviewed exceptions would reject the intended n-to-y
transitions. The parent isolated implementation now adds exact n-to-y
exceptions for only those three keys, plus an independent memory contract
that cannot be weakened by changing REQUESTED. SUSFS/NFLOG/hardware guard
failures are never exempted.
Check the selected/preserved prerequisites PAGE_COUNTER, EVENTFD, CGROUPS,
SWAP and FREEZER are y, and PSI_DEFAULT_DISABLED/HEIMDALL remain n.
A successful source/config compile still needs an actual boot test with
`/proc/pressure`, `/proc/cgroups`, `/dev/memcg` and `/dev/freezer` checks.

## Independent followups, not bundled blindly

- MEMFD_ASHMEM_SHIM is supported in current mm/Kconfig:1014-1023 and depends
  only on MEMFD_CREATE, which is already y. ASHMEM is also y. This is a
  plausible older-HAL memfd ioctl compatibility improvement, but no provided
  crash establishes it as a boot blocker; test it separately.
- Notkernel's hidden TRACING_SUPPORT default is **n** at
  kernel/trace/Kconfig:166-170; upstream default is **y** at 156-160.
  Both dependencies (TRACE_IRQFLAGS_SUPPORT and STACKTRACE_SUPPORT) are y in
  the current Image. Merely requesting FTRACE=y cannot bypass the hidden
  parent default. A tracing experiment needs a reviewed source change first.
  Upstream fragments do not explicitly enable FTRACE either, so do not
  misreport a generated upstream tracing state from fragment absence.
- Current MODULES is n and protected, whereas upstream kona-perf lines
  99/101 enable MODULES/MODVERSIONS. Do not replace the entire defconfig and
  unintentionally change the built-in-driver/module integration model.

## Bounded 23.2 to 24.0 comparison

The Samsung common and r8q fragments are byte-identical between the pinned
23.2 and 24.0 kernels. The kona-perf fragment adds only CMA_SYSFS=y at line
112 and FUSE_BPF=y at line 685. The current real Image already has FUSE_BPF=y;
CMA_SYSFS is absent. This does not establish a CMA sysfs boot requirement.
The 24.0 selected memory-controller/PSI requests are unchanged from 23.2.

No suggestion here disables SUSFS, firmware authentication, SELinux or
encryption, or requires formatting user data.
