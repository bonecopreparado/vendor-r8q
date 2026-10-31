"""Real mksh regression: 2GiB arithmetic, 4GiB zero test, complete 10GB readback.

No block devices, network, ROM payloads or instrumented dd required. The sparse
file has distinct markers per region. MKSH_BINARY must identify a real mksh.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile

CAPACITY = 10292822016
CHUNK = 536870912


def verification_function(text):
    return text[text.index('verify_written() '):text.index('# Resolve target devices')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(os.environ.get('R8Q_PROJECT_ROOT', Path.cwd()))
    parser.add_argument('--old-template', type=Path, default=root / 'delivery/Revisao-P0r6-Windows/p0r6-assets/installer-template.sh')
    parser.add_argument('--new-template', type=Path, default=root / 'delivery/Revisao-P0r7-Windows/p0r7-assets/installer-template.sh')
    parser.add_argument('--report-dir', type=Path, default=Path(os.environ.get('R8Q_TEST_REPORT', Path.cwd() / 'test-results')))
    args = parser.parse_args()
    shell = os.environ.get('MKSH_BINARY') or shutil.which('mksh')
    if not shell:
        raise RuntimeError('Install mksh or set MKSH_BINARY to a real mksh executable')
    args.report_dir.mkdir(parents=True, exist_ok=True)
    old = args.old_template.read_text()
    new = args.new_template.read_text()
    assert '[ "$offset" -eq' not in new
    assert 'cursor+rawbytes' not in new
    assert '[ "$offset" = 0 ]' in new
    assert 'offset_blocks' in new and 'cursor_blocks' in new
    probe = subprocess.run([shell, '-c', r'''
printf 'version=%s\n' "$KSH_VERSION"
value=2147483648
printf 'p0r5_skip=%s\n' "$((value/4096))"
value=4294967296
if [ "$value" -eq 0 ]; then printf 'numeric_zero=1\n'; else printf 'numeric_zero=0\n'; fi
if [ "$value" = 0 ]; then printf 'string_zero=1\n'; else printf 'string_zero=0\n'; fi
length=536870912
if [ "$value" -eq 0 ]; then length=$((length-4096)); fi
printf 'p0r6_length=%s\np0r6_blocks=%s\n' "$length" "$((length/4096))"
'''], capture_output=True, text=True, check=True)
    assert 'MIRBSD KSH' in probe.stdout and 'p0r5_skip=-524288' in probe.stdout, probe
    assert 'numeric_zero=1' in probe.stdout and 'string_zero=0' in probe.stdout, probe
    assert 'p0r6_length=536866816' in probe.stdout and 'p0r6_blocks=131071' in probe.stdout, probe
    results = [dict(case='mksh_32bit_arithmetic_reproduces_both_logs', exit=0, stdout=probe.stdout, stderr=probe.stderr)]
    print(probe.stdout, flush=True)
    with tempfile.TemporaryDirectory(prefix='r8q-mksh-large-') as td:
        work = Path(td)
        image = work / 'super.sparse'
        rows = []
        zeros = b'\0' * (4 * 1024**2)
        with image.open('wb') as stream:
            stream.truncate(CAPACITY)
            stream.seek(0); stream.write(b'P' * 4096)
            for index, offset in enumerate(range(0, CAPACITY, CHUNK)):
                raw_length = min(CHUNK, CAPACITY-offset)
                length = raw_length-(4096 if index == 0 else 0)
                start = offset+(4096 if index == 0 else 0)
                first = f'BEGIN-{index:03}'.encode().ljust(4096, b'A')
                last = f'END-{index:03}'.encode().ljust(4096, b'Z')
                stream.seek(start); stream.write(first)
                stream.seek(offset+raw_length-4096); stream.write(last)
                digest = hashlib.sha256(first)
                left = length-8192
                while left:
                    data = zeros[:min(left, len(zeros))]
                    digest.update(data); left -= len(data)
                digest.update(last)
                h = digest.hexdigest()
                rows.append(f'super super-{index:03}.gz {raw_length} {h} 1 {h} {offset} {h}')
        h = '0'*64
        rows += [f'boot boot-000.gz 67108864 {h} 1 {h} 0 {h}',
                 f'dtbo dtbo-000.gz 10485760 {h} 1 {h} 0 {h}']
        (work / 'payload.rows').write_text('\n'.join(rows) + '\n')

        def run(name, template, fd9=False):
            script = work / (name + '.sh')
            body = '''set -eu
set -o pipefail
WORK="$1"
OUTFD=1
ui_print() { printf '%s\\n' "$*" >"/proc/self/fd/$OUTFD"; }
abort() { ui_print "ERRO: $*"; exit 1; }
hash_stream() { sha256sum; }
'''
            if fd9: body += 'exec 9>&1; OUTFD=9\n'
            if 'super_limit="$(blockdev' in template:
                body += '''SUPER="$2"
BOOT=BOOT
DTBO=DTBO
blockdev() {
    case "$2" in
        "$SUPER") printf '%s\\n' 10292822016 ;;
        BOOT) printf '%s\\n' 67108864 ;;
        DTBO) printf '%s\\n' 10485760 ;;
        *) return 1 ;;
    esac
}
'''
                begin = template.index('super_limit="$(blockdev')
                end = template.index('hash_stream() {', begin)
                body += template[begin:end]
            body += verification_function(template) + '\nverify_written super "$2"\n'
            script.write_text(body)
            result = subprocess.run([shell, str(script), str(work), str(image)], text=True,
                                    capture_output=True, timeout=180)
            record = dict(case=name, exit=result.returncode, stdout=result.stdout, stderr=result.stderr)
            results.append(record)
            print(name, 'exit='+str(result.returncode), flush=True)
            return record

        prefix_before = image.open('rb').read(4096)
        previous = run('p0r6_real_mksh_reproduces_4GiB_hash_failure', old)
        assert previous['exit'] != 0 and 'Hash gravado incorreto em super-008.gz' in previous['stdout'], previous
        good = run('p0r7_real_mksh_full_10GB_fd9', new, fd9=True)
        assert good['exit'] == 0 and 'super-019.gz' in good['stdout'] and 'Tabela de offsets/tamanhos aprovada' in good['stdout'], good
        with image.open('r+b') as stream:
            stream.seek(16 * CHUNK + 4096); stream.write(b'CORRUPT')
        bad = run('corruption_at_8GiB_still_detected', new)
        assert bad['exit'] != 0 and 'Hash gravado incorreto em super-016.gz' in bad['stdout'], bad
        with image.open('r+b') as stream:
            stream.seek(16 * CHUNK + 4096); stream.write(b'\0' * 7)
            stream.truncate(CAPACITY-4096)
        short = run('truncated_last_region_after_9GiB_still_detected', new)
        assert short['exit'] != 0 and 'Hash gravado incorreto em super-019.gz' in short['stdout'], short
        assert prefix_before == image.open('rb').read(4096)
    (args.report_dir / 'shell32-results.json').write_text(json.dumps(results, indent=2) + '\n')
    print('5 real-mksh regression scenarios PASS', flush=True)


if __name__ == '__main__':
    main()
