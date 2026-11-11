# Exact current-source fixtures

These are unmodified files from
`notkernel-oss/not_samsung.sm8250-4.19` commit
`a265508933bbecb682e45e3b956d95bf4426d60b`:

- `block/mq-deadline.c`, Git blob `2cdd09c7b4c7ab4c5c1bb17a38f4cb02977843d2`;
- `drivers/block/zram/zram_drv.c`, SHA256
  `e4789899ff9cbe812517ca2cf47cbd3398011b5f5a0d488a081093adab83134c`.

Copyright and license notices remain intact. The kernel's GNU GPL version 2
license text is included as `COPYING`; zram's original header also describes
its dual BSD/GPL license.

They support offline tests of the exact reviewed source overlays. Tests check
original and resulting hashes, apply both patches to a temporary Git checkout,
reject unrelated changes, and compile extracted real scheduler/zram functions
against focused host stubs. Runtime fixtures cover merge-list ownership,
unlock-before-free, backing-device BIO initialization, parent chaining, sector
conversion and allocation-error propagation. They do not execute a real kernel,
block device, interrupt handler or ARM64 boot.
