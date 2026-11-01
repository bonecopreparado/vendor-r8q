"""Build the battery-protected P0r8 template without changing P0r7 or ROM data.

The pinned READY7 parent can be reconstructed in a clean checkout from the
reviewed original P0r7 template. Only its UI label, payload-location support and
battery guards are changed. This tool never opens a real block device.
"""
from pathlib import Path
import hashlib
import os
import subprocess

ROOT = Path(os.environ.get('R8Q_PROJECT_ROOT', Path(__file__).resolve().parents[1])).resolve()
SOURCE = ROOT / 'delivery/Revisao-P0r7-Windows/p0r7-assets/installer-template.sh'
P0R7_SHA256 = '690280161dfa294add407fcb6fa1e853c531b24dc52a38081ba6bcb022aa0ea6'
READY7_SHA256 = '90b1480d16cc4b6a576bcdfeaeec8ab517db1f314430888f795349c7b20677f3'

BATTERY_GUARD = '''# Battery policy: at least 50%, or 20..49% while actively charging/full.
# Merely having USB online does not prove that the battery is charging.
# Read the device's standard Samsung battery supply; there is no environment
# override or recovery property that can silently bypass this measurement.
BATTERY_SYSFS=/sys/class/power_supply/battery
check_battery() {
    battery_phase="$1"
    battery_capacity="$(cat "$BATTERY_SYSFS/capacity" 2>/dev/null)" || abort "Battery capacity unavailable ($battery_phase). Nothing was written."
    # Match only canonical bounded decimal strings BEFORE shell comparisons.
    # This rejects negatives, whitespace, leading zeros and 32-bit wrap values.
    case "$battery_capacity" in
        0|[1-9]|[1-9][0-9]|100) ;;
        *) abort "Battery capacity invalid ($battery_phase); expected 0..100 percent. Nothing was written." ;;
    esac
    battery_status="$(cat "$BATTERY_SYSFS/status" 2>/dev/null)" || battery_status=Unknown
    case "$battery_status" in
        Charging|Full|Discharging|'Not charging'|Unknown) ;;
        *) battery_status=Unknown ;;
    esac
    ui_print "Battery ($battery_phase): $battery_capacity percent, $battery_status"
    [ "$battery_capacity" -ge 20 ] || abort "Battery below 20 percent; charge before installing. Nothing was written."
    if [ "$battery_capacity" -lt 50 ]; then
        case "$battery_status" in
            Charging|Full) ;;
            *) abort "Battery below 50 percent and active charging is not confirmed. Charge to at least 50 percent. Nothing was written." ;;
        esac
    fi
}
'''


def replace_once(text: str, old: str, new: str) -> str:
    if text.count(old) != 1:
        raise ValueError('Pinned installer section changed: ' + old[:70])
    return text.replace(old, new)


def ready7_parent() -> str:
    source = SOURCE.read_bytes()
    if hashlib.sha256(source).hexdigest() != P0R7_SHA256:
        raise ValueError('Reviewed P0r7 source changed')
    text = source.decode()
    text = replace_once(text, '''PAYLOAD_DIR="${zip_real%/*}/payloads"
[ -d "$PAYLOAD_DIR" ] && [ ! -L "$PAYLOAD_DIR" ] || abort "Pasta payloads ausente ou link; copie a pasta P0r7 inteira. Nada foi gravado."
''', '''zip_dir="${zip_real%/*}"
if [ -d "$zip_dir/payloads" ] && [ ! -L "$zip_dir/payloads" ]; then
    PAYLOAD_DIR="$zip_dir/payloads"
elif [ -f "$zip_dir/super-000.gz" ]; then
    PAYLOAD_DIR="$zip_dir"
else
    abort "Payloads not found. Put this ZIP next to the payloads folder or inside it. Nothing was written."
fi
ui_print "READY installer: using payload files in $PAYLOAD_DIR"
''')
    text = replace_once(text, 'HyperOS4 -> R8Q P0r7 EXPERIMENTAL / sem teste de boot',
                        'HyperOS4 -> R8Q P0r7-ready1 EXPERIMENTAL / boot not confirmed')
    if hashlib.sha256(text.encode()).hexdigest() != READY7_SHA256:
        raise ValueError('Reconstructed READY7 parent differs')
    return text


def main() -> None:
    template = ready7_parent()
    template = replace_once(template,
                            'abort() { ui_print "ERRO: $*"; exit 1; }\n',
                            'abort() { ui_print "ERRO: $*"; exit 1; }\n' + BATTERY_GUARD)
    template = replace_once(template,
                            'ui_print "HyperOS4 -> R8Q P0r7-ready1 EXPERIMENTAL / boot not confirmed"\n',
                            'ui_print "HyperOS4 -> R8Q P0r8 EXPERIMENTAL / boot not confirmed"\ncheck_battery preflight\n')
    template = replace_once(template,
                            'ui_print "Gravando super por partes; preservando os primeiros 4 KiB. Nao interrompa."\n',
                            '# Hashing and storage checks can take minutes; measure the battery again.\n'
                            'check_battery before-write\n'
                            'ui_print "Gravando super por partes; preservando os primeiros 4 KiB. Nao interrompa."\n')
    destination = ROOT / 'delivery/Ready-P0r8/installer-template-ready.sh'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(template)
    subprocess.run(['bash', '-n', str(destination)], check=True)
    print('P0r8 template:', destination)
    print('SHA256:', hashlib.sha256(destination.read_bytes()).hexdigest())


if __name__ == '__main__':
    main()
