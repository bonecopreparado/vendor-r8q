"""Reconstruct full-OTA new/zero/erase data offline, rejecting incremental commands."""
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/python-deps'))
import brotli

BLOCK = 4096

def ranges(value):
    fields = [int(s) for s in value.split(',')]
    if fields[0] != len(fields)-1 or fields[0] % 2:
        raise ValueError('Invalid range count')
    pairs = list(zip(fields[1::2], fields[2::2]))
    if any(a < 0 or b <= a for a,b in pairs):
        raise ValueError('Invalid block range')
    return pairs

class BrotliReader:
    def __init__(self, stream):
        self.stream = stream
        self.decoder = brotli.Decompressor()
        self.buffer = bytearray()
        self.eof = False

    def read_exact(self, count):
        while len(self.buffer) < count and not self.eof:
            compressed = self.stream.read(256*1024)
            if not compressed:
                self.eof = True
                if not self.decoder.is_finished():
                    raise ValueError('Truncated Brotli input')
                break
            self.buffer.extend(self.decoder.process(compressed))
        if len(self.buffer) < count:
            raise ValueError('Transfer list needs more new data than present')
        result = bytes(self.buffer[:count])
        del self.buffer[:count]
        return result

    def finish(self):
        if self.buffer:
            raise ValueError('Unconsumed Brotli output')
        while True:
            compressed = self.stream.read(256*1024)
            if not compressed:
                break
            if self.decoder.process(compressed):
                raise ValueError('Unconsumed Brotli output')
        if not self.decoder.is_finished():
            raise ValueError('Truncated Brotli stream')

def reconstruct(archive, part, output):
    base = 'Color os build/' + part
    transfer = archive.read(base+'.transfer.list').decode('ascii').splitlines()
    if transfer[0] != '4':
        raise ValueError('Expected v4 full OTA transfer list')
    commands = []
    for line in transfer[4:]:
        if not line.strip():
            continue
        command, value = line.split()
        if command not in ('new', 'zero', 'erase'):
            raise ValueError('Incremental or unsupported command: '+command)
        commands.append((command, ranges(value)))
    spans = sorted((a,b) for _,rs in commands for a,b in rs)
    if any(spans[i][0] < spans[i-1][1] for i in range(1,len(spans))):
        raise ValueError('Overlapping ranges')
    length = max(b for a,b in spans)*BLOCK
    if length > 4*1024**3:
        raise ValueError('Unexpected image size')
    destination = output / (part+'.img')
    written = 0
    with archive.open(base+'.new.dat.br') as source, destination.open('xb') as image:
        reader = BrotliReader(source)
        image.truncate(length)
        for command,rs in commands:
            if command != 'new':
                continue  # fresh sparse output already contains zero bytes
            for start,end in rs:
                image.seek(start*BLOCK)
                remaining = (end-start)*BLOCK
                while remaining:
                    n = min(remaining, 1024*1024)
                    image.write(reader.read_exact(n))
                    remaining -= n
                    written += n
        reader.finish()
    digest = hashlib.file_digest(destination.open('rb'), 'sha256').hexdigest()
    print(part, length, digest, flush=True)
    return dict(name=part, bytes=length, new_bytes=written, sha256=digest,
                transfer_list_header_blocks=int(transfer[1]),
                method='Fresh image; new ranges reconstructed, zero/erase ranges represented as zero. No source ROM code executed.')

def main():
    output = ROOT / 'extracted/r8q'
    output.mkdir(exist_ok=False)
    results = []
    with zipfile.ZipFile(ROOT/'originals/Color.os.build.zip') as archive:
        for part in ('odm','vendor'):
            results.append(reconstruct(archive, part, output))
        for name in ('boot.img','dtbo.img','unsparse_super_empty.img'):
            content = archive.read('Color os build/'+name)
            with (output/name).open('xb') as target:
                target.write(content)
            results.append(dict(name=name, bytes=len(content), sha256=hashlib.sha256(content).hexdigest()))
    (ROOT/'reports/r8q/reconstruction.json').write_text(json.dumps(results,indent=2)+'\n')

if __name__ == '__main__':
    main()
