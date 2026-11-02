"""Download a named public source; retain .part and verify SHA-256 before rename."""
import hashlib
import json
from pathlib import Path
import sys
import time
import urllib.request

SOURCES = {
    'hyperos': {
        'url': 'https://pixeldrain.com/api/file/Ygwm7Nx3',
        'name': 'HyperOS4-Umiii-@Jopvan1.zip',
        'size': 5376154497,
        'sha256': 'c5eff65d1f963c44c4c44e627cfb789ec7168706685be64030135a44e63fe11d',
    },
    'r8q': {
        'url': 'https://github.com/bonecopreparado/vendor-r8q/releases/download/0.0.1/Color.os.build.zip',
        'name': 'Color.os.build.zip',
        'size': 931453816,
        'sha256': 'd8db5aa65498718a00d55f01e8f7965a4a7918864452be69b483cc48d68674db',
    },
}

def main():
    key = sys.argv[1]
    source = SOURCES[key]
    root = Path(__file__).resolve().parents[1]
    destination = root / 'originals' / source['name']
    if destination.exists():
        raise SystemExit('Destination exists; inspect it before another download.')
    partial = destination.with_name(destination.name + '.part')
    if partial.exists():
        raise SystemExit('Partial exists; preserve it and inspect before retry.')
    digest = hashlib.sha256()
    count = 0
    started = last = time.monotonic()
    request = urllib.request.Request(source['url'], headers={'User-Agent': 'HyperOS-R8Q-static-audit/0.1'})
    with urllib.request.urlopen(request, timeout=90) as response, partial.open('xb') as out:
        while True:
            chunk = response.read(4 * 1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            count += len(chunk)
            if time.monotonic() - last >= 20:
                print(f'{key}: {count:,}/{source["size"]:,} bytes', flush=True)
                last = time.monotonic()
    actual_hash = digest.hexdigest()
    if count != source['size'] or actual_hash != source['sha256']:
        raise SystemExit(f'VERIFICATION FAILED: size={count}, sha256={actual_hash}')
    partial.rename(destination)
    destination.chmod(0o444)
    result = dict(source, actual_size=count, actual_sha256=actual_hash, verified=True,
                  duration_seconds=round(time.monotonic()-started, 2))
    (root / 'reports' / f'{key}-source.json').write_text(json.dumps(result, indent=2)+'\n')
    print(f'{key}: SHA-256 verified; {destination}', flush=True)

if __name__ == '__main__':
    main()
