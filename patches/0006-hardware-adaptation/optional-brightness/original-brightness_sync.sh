#!/system/bin/sh

# Wait for brightness sysfs
while [ ! -e /sys/class/backlight/panel0-backlight/brightness ]; do
    sleep 0.5
done

OLD=-1

# Wait until settings database is ready
until settings get system screen_brightness >/dev/null 2>&1; do
    sleep 1
done

while true; do
    SLIDER=$(settings get system screen_brightness)
    if [ "$SLIDER" != "$OLD" ]; then
        REAL_VAL=$(((SLIDER * 255) / 8191))
        echo $REAL_VAL > /sys/class/backlight/panel0-backlight/brightness
        OLD=$SLIDER
    fi
    sleep 0.1
done

