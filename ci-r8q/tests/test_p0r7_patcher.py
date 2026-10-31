"""Small conversion fixtures; original ZIP/payloads must remain unchanged."""
from pathlib import Path
import gzip
import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('patcher7', ROOT / 'delivery/Revisao-P0r7-Windows/corrigir_p0r7.py')
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)
SHA = lambda data: hashlib.sha256(data).hexdigest()


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'Pasta ç com espaços'; self.root.mkdir()
        self.source = self.root / 'INSTALAR-P0r5.zip'
        self.payloads = self.root / 'payloads'; self.payloads.mkdir()
        self.data = {'super': b'S' * 16384, 'boot': b'B' * 8192, 'dtbo': b'D' * 4096}
        self.layout = dict(chunk_bytes=8192, images=[], chunks=[])
        self.rows = []
        self.assets, _ = p.load_assets()
        for part, data in self.data.items():
            self.layout['images'].append(dict(partition=part, file=f'images/{part}.img', bytes=len(data), sha256=SHA(data)))
            for index, offset in enumerate(range(0, len(data), 8192)):
                raw = data[offset:offset+8192]
                packed = gzip.compress(raw, mtime=0)
                row = dict(part=part, name=f'{part}-{index:03}.gz', bytes=len(raw), sha256=SHA(raw),
                           offset=offset, readback_sha256=SHA(raw[4096:] if part=='super' and offset==0 else raw))
                self.layout['chunks'].append(row.copy())
                row.update(compressed_bytes=len(packed), compressed_sha256=SHA(packed))
                self.rows.append(row)
                (self.payloads / row['name']).write_bytes(packed)
        self.manifest = dict(name='HyperOS4-R8Q-P0r5', images=self.layout['images'], chunks=self.rows,
                             installer_sha256=SHA(p.render(self.assets['installer-p0r5.sh'], self.rows)))
        self.save_source()

    def save_source(self, *, installer=None, duplicate=False):
        with zipfile.ZipFile(self.source, 'w', zipfile.ZIP_DEFLATED) as archive:
            members = {p.INSTALLER: installer if installer is not None else p.render(self.assets['installer-p0r5.sh'], self.rows),
                       p.MANIFEST: json.dumps(self.manifest).encode(), p.README: b'Old', p.UPDATER: b'#'}
            for name, data in members.items(): archive.writestr(name, data)
            if duplicate: archive.writestr(p.README, b'duplicate')

    def build(self):
        return p.build(self.source, self.assets, self.layout)

    def test_success_reuses_all_payloads_without_changes(self):
        before = {f.name: p.file_sha(f) for f in self.payloads.iterdir()}
        old = p.file_sha(self.source)
        result = self.build()
        self.assertEqual(result.name, 'INSTALAR-P0r7.zip')
        self.assertLess(result.stat().st_size, 100000)
        self.assertEqual(p.file_sha(self.source), old)
        self.assertEqual({f.name: p.file_sha(f) for f in self.payloads.iterdir()}, before)
        self.assertFalse(list(self.root.glob('*.partial-*.zip')))
        with zipfile.ZipFile(result) as archive:
            self.assertEqual(len(archive.namelist()), 4)
            self.assertEqual(archive.read(p.INSTALLER), p.render(self.assets['installer-template.sh'], self.rows))
            self.assertEqual(archive.getinfo(p.INSTALLER).external_attr >> 16, 0o100755)
            self.assertTrue(all(i.extract_version < 45 for i in archive.infolist()))
            self.assertEqual(json.loads(archive.read(p.MANIFEST))['images'], self.layout['images'])

    def test_source_installer_modified_rejected(self):
        self.save_source(installer=b'foreign script')
        with self.assertRaises(ValueError): self.build()

    def test_manifest_unknown_image_rejected(self):
        self.manifest['images'] = [dict(i, sha256='0'*64) for i in self.layout['images']]
        self.save_source()
        with self.assertRaises(ValueError): self.build()

    def test_chunk_order_and_path_escape_rejected(self):
        self.rows[0]['name'] = '../escape.gz'; self.save_source()
        with self.assertRaises(ValueError): self.build()

    def test_missing_part_rejected_before_publication(self):
        (self.payloads / self.rows[-1]['name']).unlink()
        with self.assertRaises(ValueError): self.build()
        self.assertFalse((self.root / 'INSTALAR-P0r7.zip').exists())

    def test_corrupt_compressed_file_rejected(self):
        (self.payloads / self.rows[0]['name']).write_bytes(b'bad')
        with self.assertRaises(ValueError): self.build()

    def test_gzip_crc_rejected_even_when_compressed_hash_matches(self):
        path = self.payloads / self.rows[0]['name']
        data = bytearray(path.read_bytes()); data[-8] ^= 1; path.write_bytes(data)
        self.rows[0]['compressed_sha256'] = SHA(data)
        self.manifest['installer_sha256'] = SHA(p.render(self.assets['installer-p0r5.sh'], self.rows)); self.save_source()
        with self.assertRaises(gzip.BadGzipFile): self.build()

    def test_raw_identity_still_pinned_with_valid_gzip(self):
        data = gzip.compress(b'X'*8192, mtime=0)
        (self.payloads / self.rows[0]['name']).write_bytes(data)
        self.rows[0].update(compressed_bytes=len(data), compressed_sha256=SHA(data))
        self.manifest['installer_sha256'] = SHA(p.render(self.assets['installer-p0r5.sh'], self.rows)); self.save_source()
        with self.assertRaises(ValueError): self.build()

    def test_existing_output_preserved(self):
        destination = self.root / 'INSTALAR-P0r7.zip'; destination.write_bytes(b'keep')
        with self.assertRaises(FileExistsError): self.build()
        self.assertEqual(destination.read_bytes(), b'keep')

    def test_duplicate_metadata_rejected(self):
        self.save_source(duplicate=True)
        with self.assertRaises(ValueError): self.build()

    def test_interrupted_write_only_partial(self):
        with patch.object(p.zipfile.ZipFile, 'writestr', side_effect=OSError('full')):
            with self.assertRaises(OSError): self.build()
        self.assertFalse((self.root / 'INSTALAR-P0r7.zip').exists())
        self.assertEqual(len(list(self.root.glob('*.partial-*.zip'))), 1)

    def test_mixed_assets_rejected(self):
        assets = self.root / 'assets'; assets.mkdir()
        pins = {name: SHA(data) for name, data in self.assets.items()}
        for name, data in self.assets.items(): (assets / name).write_bytes(data)
        (assets / 'pins.json').write_text(json.dumps(pins))
        (assets / 'installer-template.sh').write_bytes(b'changed')
        with patch.object(p, 'ASSETS', assets):
            with self.assertRaises(ValueError): p.load_assets()

    def test_source_directory_argument(self):
        self.assertEqual(p.select_source(str(self.root)), self.source)

    def test_p0r6_source_reuses_known_installer(self):
        self.manifest['name'] = 'HyperOS4-R8Q-P0r6'
        installer = p.render(self.assets['installer-p0r6.sh'], self.rows)
        self.manifest['installer_sha256'] = SHA(installer)
        self.save_source(installer=installer)
        self.assertTrue(self.build().is_file())


if __name__ == '__main__': unittest.main()
