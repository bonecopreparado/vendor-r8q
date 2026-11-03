"""Read every final payload with the actual Android helper under QEMU.

Runs entirely on regular files in CI. This verifies the distributed helper's
CRC implementation and byte stream; it does not emulate recovery or phone I/O.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import selectors
import struct
import subprocess
import tempfile
import time
import zipfile


def stream_digest(command, expected_bytes, timeout=180):
    with tempfile.TemporaryFile() as errors:
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=errors)
        digest=hashlib.sha256();size=0;deadline=time.monotonic()+timeout
        try:
            with selectors.DefaultSelector() as selector:
                os.set_blocking(process.stdout.fileno(),False)
                selector.register(process.stdout,selectors.EVENT_READ)
                while True:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError('Runtime helper timed out')
                    if not selector.select(remaining):raise TimeoutError('Runtime helper timed out')
                    data=os.read(process.stdout.fileno(),1024**2)
                    if not data:break
                    size+=len(data)
                    if size>expected_bytes:raise ValueError('Runtime helper emitted excess bytes')
                    digest.update(data)
            code=process.wait(timeout=max(0.01,deadline-time.monotonic()))
            errors.seek(0);diagnostic=errors.read(4096).decode(errors='replace')
            if code:raise ValueError('Runtime helper rejected member: '+diagnostic)
            if size!=expected_bytes:raise ValueError('Runtime helper emitted truncated bytes')
        finally:
            if process.poll() is None:process.kill()
            process.wait();process.stdout.close()
        return digest.hexdigest()


def verify(archive, helper, emulator=None, require_arm64=True):
    archive=Path(archive).resolve(strict=True);helper=Path(helper).resolve(strict=True)
    if not archive.is_file() or not helper.is_file():raise ValueError('Regular files required')
    binary=helper.read_bytes()
    if len(binary)<64 or binary[:6]!=b'\x7fELF\x02\x01':raise ValueError('ELF64 helper required')
    machine=struct.unpack_from('<H',binary,18)[0]
    if require_arm64 and (machine!=183 or not emulator):raise ValueError('Android ARM64 helper and emulator required')
    padded=binary.ljust((len(binary)+4095)//4096*4096,b'\0')
    with zipfile.ZipFile(archive) as source:
        item=source.getinfo('P1-MANIFEST.json')
        if item.file_size>1024**2:raise ValueError('Manifest exceeds bound')
        manifest=json.loads(source.read(item))
        if manifest['helper']['sha256']!=hashlib.sha256(padded).hexdigest():
            raise ValueError('Runtime helper differs from packaged helper')
        item=source.getinfo(manifest['helper']['member'])
        if item.file_size!=len(padded) or source.read(item)!=padded:
            raise ValueError('Actual packaged helper bytes differ')
    command=([str(emulator)] if emulator else [])+[str(helper)]
    rows=[]
    for row in manifest['chunks']:
        name=row['name']
        if name!=Path(name).name or not name.endswith('.gz'):raise ValueError('Invalid member name')
        actual=stream_digest(command+[str(archive),'payloads/'+name],row['compressed_bytes'])
        if actual!=row['compressed_sha256']:raise ValueError('Runtime payload SHA256 differs: '+name)
        rows.append(dict(name=name,bytes=row['compressed_bytes'],sha256=actual))
        print('Runtime CRC and SHA256 passed:',name,flush=True)
    if not rows:raise ValueError('No payloads verified')
    with archive.open('rb') as stream:whole=hashlib.file_digest(stream,'sha256').hexdigest()
    return dict(status='ALL_FINAL_PAYLOADS_RUNTIME_READ_BACK_NOT_BOOT_TESTED',
                file=archive.name,bytes=archive.stat().st_size,sha256=whole,
                helper_sha256=manifest['helper']['sha256'],elf_machine=machine,
                emulator=bool(emulator),chunks=rows,physical_writes=False,boot_confirmed=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip',required=True,type=Path)
    parser.add_argument('--helper',required=True,type=Path)
    parser.add_argument('--emulator',required=True,type=Path)
    parser.add_argument('--report',required=True,type=Path)
    args=parser.parse_args()
    result=verify(args.zip,args.helper,args.emulator)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    with args.report.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')


if __name__=='__main__':main()
