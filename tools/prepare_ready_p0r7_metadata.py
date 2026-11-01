"""Reproduce the shipped Windows gzip identities without storing another ROM.

Uses the exact CPython 3.12.10 gzip module and zlib 1.3.1 from the Windows kit.
Each produced gzip is streamed through a hash and a CRC-checking decompressor.
No device paths are accepted. Original images are opened read-only.
"""
from pathlib import Path
import gzip
import hashlib
import importlib.util
import json
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
if zlib.ZLIB_RUNTIME_VERSION != '1.3.1':
    raise RuntimeError('Run /usr/bin/python3 with zlib 1.3.1, matching the shipped Windows runtime')
spec = importlib.util.spec_from_file_location('windows312gzip', ROOT/'tools/python31210_gzip.py')
g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
layout = json.loads((ROOT/'delivery/Revisao-P0r5-Windows/p0r5-assets/chunks.json').read_text())
paths = {'super':'super-r8q-hyperos-p0.img','boot':'boot-r8q-hyperos-p0.img','dtbo':'dtbo-r8q-p0.img'}


class CheckSink:
    def __init__(self):
        self.sha = hashlib.sha256(); self.bytes = 0
        self.decoder = zlib.decompressobj(31)
        self.rawsha = hashlib.sha256(); self.rawbytes = 0
    def write(self, data):
        self.sha.update(data); self.bytes += len(data)
        raw = self.decoder.decompress(data)
        self.rawsha.update(raw); self.rawbytes += len(raw)
        return len(data)


records = []
for image in layout['images']:
    part = image['partition']; whole = hashlib.sha256(); total = 0
    with (ROOT/'candidates/p0'/paths[part]).open('rb') as stream:
        for row in (r for r in layout['chunks'] if r['part']==part):
            print('Reproducing and verifying:',row['name'],flush=True)
            sink = CheckSink(); remaining = row['bytes']; rawsha = hashlib.sha256()
            readback = hashlib.sha256(); position = 0
            skip = 4096 if part=='super' and row['offset']==0 else 0
            with g.GzipFile(filename='',mode='wb',compresslevel=1,fileobj=sink,mtime=0) as writer:
                while remaining:
                    data = stream.read(min(4*1024**2,remaining))
                    if not data: raise ValueError('Raw source ended early')
                    rawsha.update(data); whole.update(data)
                    if position+len(data)>skip: readback.update(data[max(0,skip-position):])
                    writer.write(data)
                    remaining -= len(data); position += len(data); total += len(data)
            if rawsha.hexdigest()!=row['sha256'] or readback.hexdigest()!=row['readback_sha256']:
                raise ValueError('Raw chunk identity differs: '+row['name'])
            if not sink.decoder.eof or sink.decoder.unused_data or sink.rawbytes!=row['bytes'] or sink.rawsha.hexdigest()!=row['sha256']:
                raise ValueError('Produced gzip CRC/length/content verification failed')
            records.append(dict(row,compressed_bytes=sink.bytes,compressed_sha256=sink.sha.hexdigest()))
        if stream.read(1): raise ValueError('Raw image has extra bytes')
    if total!=image['bytes'] or whole.hexdigest()!=image['sha256']:
        raise ValueError('Full image identity differs: '+part)
result=dict(name='HyperOS4-R8Q-P0r7-ready1',images=layout['images'],chunks=records,
            gzip_module='CPython v3.12.10 Lib/gzip.py',gzip_module_sha256=hashlib.sha256((ROOT/'tools/python31210_gzip.py').read_bytes()).hexdigest(),
            zlib_version=zlib.ZLIB_RUNTIME_VERSION,compressed_identity_source='Reproduced using the same gzip code/settings/zlib as shipped Windows kit; phone rechecks all actual files',
            status='ALL_RAW_IMAGES_AND_GZIP_STREAMS_VERIFIED_OFFLINE_NOT_BOOT_TESTED')
out=ROOT/'delivery/Ready-P0r7';out.mkdir(exist_ok=True)
(out/'payload-identities.json').write_text(json.dumps(result,indent=2)+'\n')
print('READY metadata:',out/'payload-identities.json',flush=True)
