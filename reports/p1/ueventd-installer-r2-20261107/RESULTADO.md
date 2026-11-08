# Fix recovery System alias selection before bridge activation

The private recovery.log records two sideload attempts of the 5247-byte
original ENABLE ZIP. Both abort with `System configuration escapes its
mounted filesystem`. In the released script this check precedes temporary
payload extraction, Vendor remount and bridge activation. Neither attempt
reaches a write to the installed vendor configuration. The recorded System
filesystem is EROFS on logical dm-0; Vendor is ext4 on logical dm-1.

The original installer selected candidate paths below both /system_root and
/system and required each resolved candidate to retain its mountpoint text
prefix. An absolute system-as-root compatibility link can resolve to an
unrelated recovery alias even after the correct System configuration has
already been found. Rejecting that unused fallback aborts the whole operation.
Legitimate bind aliases can also resolve outside that textual prefix.
The original log did not print the offending resolved path, so the precise
alias layout of the tester remains unconfirmed.

The exact previously published ENABLE ZIP, SHA256
a25c00c7cdbdb24516865e9ca38afccf4349ea44e9920c30f6201d55777d97b5,
reproduces the same error before writes in a local SAR fixture whose fallback
etc link points to a recovery configuration. The R2 installer accepts the
same fixture by selecting only the configuration on verified System.

R2 replaces the textual prefix check with filesystem identity. The logical
mount must still be System/EROFS. Every selected configuration must have the
same stat device ID as that verified mount. A candidate on the recovery
filesystem is logged and skipped, never selected. Aliases identifying the
same filesystem and inode are deduplicated; different eligible config files
remain ambiguous and abort. Failed or malformed stat results abort before
Vendor remount. The actual selected file must still import the canonical
Vendor path exactly once.

All device/vendor/payload pins, foreign-file protection, labels, staging,
activation and removal guards remain. The bridge payload is byte-identical;
only recovery validation and diagnostics change. This fixes an installer
rejection, not the unconfirmed Android Keymaster boot failure itself.

Fifteen focused tests cover the previous guards plus unused SAR recovery
aliases, recovery-alias-only rejection, same-filesystem aliases and duplicate
inodes, same-filesystem symlink targets, nested foreign filesystems, failed
and malformed stat output. One alias/inode case also uses native host stat
and real hardlinks. Filesystem mount identities in the other fixtures are
simulated; these tests do not execute OrangeFox or mount a phone partition.
Local Bash tests pass with the tracked-binary baseline test skipped in this
partial workspace. Release CI requires the complete tracked archive and
runs all fifteen tests using real mksh before attesting the new R2 ZIPs.

No raw recovery logs are published. R2 can be installed directly after the
reported failure because the old installer stopped before bridge creation.
The addon remains experimental and BOOTDIAG V3 should remain enabled for the
subsequent Android test. No additional data formatting is warranted.
