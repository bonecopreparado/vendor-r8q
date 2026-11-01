# P0r8 battery guard

Before preflight and immediately before the first target partition write, the
installer reads `/sys/class/power_supply/battery/capacity` and `status`.

* At least 50%: accepted regardless of charger state.
* 20–49%: accepted only when battery status is `Charging` or `Full`.
* Below 20%: rejected even with a cable connected.
* Missing, unreadable or invalid capacity: rejected.
* Unknown or unreadable status does not establish charging.

Only canonical decimal values from 0 through 100 reach shell arithmetic.
Large numbers, negative values, fractions, whitespace and leading zeros fail
closed. USB `online` alone is intentionally insufficient: a connected cable
does not establish that the battery is charging.

The second measurement catches a charge drop or disconnected charger while
the 22 payloads are being hashed. A failed measurement stops before opening
the first image destination for writing. Temporary `/tmp` dd probes can run
during preflight, but no target image is written before the second guard.

This reduces an avoidable power-loss risk; it does not guarantee uninterrupted
power. It changes no ROM image and does not establish Android boot, SELinux or
VINTF compatibility. P0r7 remains pinned and unchanged.
