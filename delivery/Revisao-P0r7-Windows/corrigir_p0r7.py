"""Reuse P0r5/P0r6 payloads; publish a shell-width-safe P0r7 installer."""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import time
import traceback
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / 'p0r7-assets'
INSTALLER = 'META-INF/com/google/android/update-binary'
MANIFEST = 'P0-MANIFEST.json'
README = 'LEIA-ME.txt'
UPDATER = 'META-INF/com/google/android/updater-script'
BUFFER = 4 * 1024**2
HEX64 = re.compile(r'^[0-9a-f]{64}$')
ROW_KEYS = ('part', 'name', 'bytes', 'sha256', 'compressed_bytes', 'compressed_sha256', 'offset', 'readback_sha256')


def file_sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_assets():
    pins = json.loads((ASSETS / 'pins.json').read_text(encoding='utf-8'))
    expected = {'chunks.json', 'installer-p0r5.sh', 'installer-p0r6.sh', 'installer-template.sh', README}
    if set(pins) != expected:
        raise ValueError('Lista de assets incorreta')
    assets = {name: (ASSETS / name).read_bytes() for name in expected}
    for name, data in assets.items():
        if hashlib.sha256(data).hexdigest() != pins[name]:
            raise ValueError('Arquivos da revisao misturados ou alterados: ' + name)
    if any(assets[name].count(b'@@PAYLOAD_ROWS@@') != 1 for name in ('installer-p0r5.sh', 'installer-p0r6.sh', 'installer-template.sh')):
        raise ValueError('Template incorreto')
    return assets, json.loads(assets['chunks.json'])


def render(template, rows):
    lines = '\n'.join(' '.join(str(row[key]) for key in ROW_KEYS) for row in rows)
    return template.replace(b'@@PAYLOAD_ROWS@@', lines.encode('ascii'))


def read_source(path, assets, layout):
    expected = {INSTALLER, UPDATER, MANIFEST, README}
    with zipfile.ZipFile(path) as source:
        if len(source.infolist()) != 4 or set(source.namelist()) != expected:
            raise ValueError('Escolha o ZIP pequeno INSTALAR-P0r5.zip ou INSTALAR-P0r6.zip')
        if any(i.file_size > 1024**2 or i.flag_bits & 1 for i in source.infolist()):
            raise ValueError('ZIP pequeno invalido ou criptografado')
        data = {name: source.read(name) for name in expected}
    manifest = json.loads(data[MANIFEST])
    templates = {'HyperOS4-R8Q-P0r5': 'installer-p0r5.sh', 'HyperOS4-R8Q-P0r6': 'installer-p0r6.sh'}
    if manifest.get('name') not in templates or manifest.get('images') != layout['images']:
        raise ValueError('Origem nao corresponde a P0r5/P0r6 conhecida')
    rows = manifest['chunks']
    if len(rows) != len(layout['chunks']):
        raise ValueError('Quantidade de partes incorreta')
    for row, trusted in zip(rows, layout['chunks']):
        if any(row.get(key) != value for key, value in trusted.items()):
            raise ValueError('Identidade/ordem de parte diferente da P0: ' + trusted['name'])
        size = row.get('compressed_bytes')
        if type(size) is not int or not 0 < size <= 1024**3:
            raise ValueError('Tamanho comprimido invalido')
        if not isinstance(row.get('compressed_sha256'), str) or not HEX64.fullmatch(row['compressed_sha256']):
            raise ValueError('Hash comprimido invalido')
    known_installer = render(assets[templates[manifest['name']]], rows)
    if data[INSTALLER] != known_installer or manifest.get('installer_sha256') != hashlib.sha256(known_installer).hexdigest():
        raise ValueError('Instalador de origem diferente da revisao conhecida')
    return rows


def verify_payloads(directory, rows, layout):
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Subpasta payloads ausente ou indireta; selecione a pasta completa da P0r5')
    for image in layout['images']:
        whole = hashlib.sha256()
        total = 0
        for row in rows:
            if row['part'] != image['partition']:
                continue
            path = directory / row['name']
            print('Conferindo:', row['name'], flush=True)
            if path.is_symlink() or not path.is_file():
                raise ValueError('Parte ausente ou indireta: ' + row['name'])
            if path.stat().st_size != row['compressed_bytes'] or file_sha(path) != row['compressed_sha256']:
                raise ValueError('Parte comprimida incompleta/corrompida: ' + row['name'])
            digest = hashlib.sha256()
            count = 0
            with gzip.open(path, 'rb') as stream:
                while data := stream.read(BUFFER):
                    count += len(data)
                    if count > row['bytes']:
                        raise ValueError('Parte maior que o previsto: ' + row['name'])
                    digest.update(data)
                    whole.update(data)
            if count != row['bytes'] or digest.hexdigest() != row['sha256']:
                raise ValueError('Conteudo incorreto: ' + row['name'])
            total += count
        if total != image['bytes'] or whole.hexdigest() != image['sha256']:
            raise ValueError('Hash completo da imagem diferente da P0: ' + image['partition'])


def build(source, assets, layout):
    source = source.resolve()
    destination = source.with_name('INSTALAR-P0r7.zip')
    if destination.exists():
        raise FileExistsError('INSTALAR-P0r7.zip ja existe; o resultado anterior foi preservado')
    rows = read_source(source, assets, layout)
    verify_payloads(source.parent / 'payloads', rows, layout)
    installer = render(assets['installer-template.sh'], rows)
    manifest = dict(name='HyperOS4-R8Q-P0r7', status='EXPERIMENTAL_NOT_BOOT_TESTED',
                    images=layout['images'], chunks=rows, chunk_bytes=layout['chunk_bytes'],
                    transport='Reuse unchanged loose P0r5 gzip payloads',
                    readback='Sequential descriptor; string zero test and bounded block counters; 32-bit mksh compatible',
                    installer_sha256=hashlib.sha256(installer).hexdigest())
    members = {INSTALLER: installer, UPDATER: b'# P0r7 shell installer\n',
               MANIFEST: (json.dumps(manifest, indent=2) + '\n').encode(), README: assets[README]}
    staging = destination.with_name('INSTALAR-P0r7.partial-' + uuid.uuid4().hex[:12] + '.zip')
    with zipfile.ZipFile(staging, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=False) as archive:
        for name, data in members.items():
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 31, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (0o100755 if name == INSTALLER else 0o100644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    with zipfile.ZipFile(staging) as archive:
        if len(archive.namelist()) != 4 or set(archive.namelist()) != set(members):
            raise ValueError('ZIP de saida invalido')
        for name, data in members.items():
            if archive.read(name) != data:
                raise ValueError('Falha na releitura do instalador')
        if archive.getinfo(INSTALLER).external_attr >> 16 != 0o100755:
            raise ValueError('Permissao do instalador incorreta')
    if destination.exists():
        raise FileExistsError('Outra preparacao criou INSTALAR-P0r7.zip; nada foi substituido')
    # Windows rename fails if a destination exists (also works on FAT/exFAT).
    # POSIX rename replaces a destination, so use exclusive hard-link creation.
    if os.name == 'nt':
        staging.rename(destination)
    else:
        os.link(staging, destination)
        staging.unlink()
    print('\nPRONTO:', destination, flush=True)
    print('Copie somente INSTALAR-P0r7.zip para a pasta do celular que ja contem payloads.', flush=True)
    print('No OrangeFox instale INSTALAR-P0r7.zip; os 22 gzip continuam iguais.', flush=True)
    return destination


def select_source(argument):
    if argument:
        path = Path(argument).expanduser()
        if path.is_dir():
            for name in ('INSTALAR-P0r6.zip', 'INSTALAR-P0r5.zip'):
                if (path / name).is_file(): return path / name
            raise FileNotFoundError('Pasta sem INSTALAR-P0r5.zip ou INSTALAR-P0r6.zip')
        return path
    for base in (ROOT, ROOT / 'output', ROOT.parent):
        for folder in (base, base / 'HyperOS4-R8Q-P0r6', base / 'HyperOS4-R8Q-P0r5'):
            for name in ('INSTALAR-P0r6.zip', 'INSTALAR-P0r5.zip'):
                path = folder / name
                if path.is_file(): return path
    raise FileNotFoundError('Arraste o ZIP pequeno INSTALAR-P0r5.zip ou INSTALAR-P0r6.zip sobre CORRIGIR-P0r7.cmd')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?')
    args = parser.parse_args()
    assets, layout = load_assets()
    source = select_source(args.source)
    print('Origem:', source, flush=True)
    build(source, assets, layout)


class Tee:
    def __init__(self, console, log):
        self.console, self.log = console, log
    def write(self, value):
        self.log.write(value)
        self.log.flush()
        try:
            self.console.write(value)
        except UnicodeEncodeError:
            enc = getattr(self.console, 'encoding', None) or 'ascii'
            self.console.write(value.encode(enc, 'backslashreplace').decode(enc))
        self.console.flush()
        return len(value)
    def flush(self):
        self.console.flush()
        self.log.flush()


if __name__ == '__main__':
    logpath = ROOT / ('correcao-p0r7-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6] + '.log')
    with logpath.open('x', encoding='utf-8') as log:
        stdout, stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = Tee(stdout, log), Tee(stderr, log)
        try:
            main()
        except Exception:
            traceback.print_exc()
            print('\nFALHOU. Envie este log:', logpath)
            print('Nao use arquivos .partial-*. A origem e os payloads foram preservados.')
            sys.exit(1)
        finally:
            sys.stdout, sys.stderr = stdout, stderr
