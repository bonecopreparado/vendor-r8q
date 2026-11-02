#!/system/bin/sh
# Candidate: read normalized framework brightness, not an OEM-specific 8191 scale.
# Requires a working `cmd display get-brightness 0` implementation on the donor.
BRIGHTNESS=/sys/class/backlight/panel0-backlight/brightness
MAXIMUM=/sys/class/backlight/panel0-backlight/max_brightness

scale_brightness() {
    case "$1" in ''|*[!0-9.eE+-]*) return 1;; esac
    case "$2" in ''|*[!0-9]*) return 1;; esac
    awk -v value="$1" -v maximum="$2" 'BEGIN {
        if (length(value)>32 || length(maximum)>5 ||
            value !~ /^[+-]?([0-9]+([.][0-9]*)?|[.][0-9]+)([eE][+-]?[0-9]+)?$/ ||
            maximum !~ /^[1-9][0-9]*$/ || maximum<1 || maximum>65535 || value<0 || value>1) exit 1;
        printf "%d\n", int(value*maximum+0.5);
    }'
}

# Main loop. No environment variable can redirect the production sysfs paths.
while [ ! -w "$BRIGHTNESS" ] || [ ! -r "$MAXIMUM" ]; do sleep 1; done
while true; do
    maximum="$(cat "$MAXIMUM" 2>/dev/null)"
    scale_brightness 0 "$maximum" >/dev/null && break
    sleep 1
done
previous=-1
while true; do
    value="$(cmd display get-brightness 0 2>/dev/null)" || { sleep 1; continue; }
    scaled="$(scale_brightness "$value" "$maximum")" || { sleep 1; continue; }
    if [ "$scaled" != "$previous" ]; then
        if echo "$scaled" > "$BRIGHTNESS"; then previous="$scaled"; fi
    fi
    sleep 0.25
done
