import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import setup_strata as installer


class StrataInstallerTests(unittest.TestCase):
    def test_setup_downloads_missing_source_and_keeps_all_paths_in_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            runtime = root / 'third_party/strata'
            data = root / 'models/strata'
            def download(url):
                runtime.mkdir(parents=True)
                (runtime / 'setup.sh').touch()
            def setup(command, **kwargs):
                (runtime / 'strata-q2_0.json').write_text('{}')
                self.assertEqual(kwargs['cwd'], runtime)
                self.assertIn(str(data), command)
                self.assertIn(str(data / 'models'), command)
                self.assertIn('--no-start', command)
                return type('Result', (), {'returncode': 0})()
            with patch.multiple(installer, ROOT=root, RUNTIME=runtime, DATA=data), \
                 patch.object(installer, 'download_source', side_effect=download) as fetch, \
                 patch.object(installer.subprocess, 'run', side_effect=setup), \
                 patch.object(installer.subprocess, 'check_output', return_value=b'17179869184'):
                result = installer.main(['--source', str(root / 'absent'), '--io-backend', 'metal', '--arena-gb', '1', '--no-start'])
            self.assertEqual(result, 0)
            installed = json.loads((runtime / 'strata-q2_0.json').read_text())
            self.assertEqual(installed['env']['STRATA_METAL_IO'], 'metal')
            self.assertEqual(installed['env']['STRATA_METAL_ARENA_GB'], '1.0')
            self.assertEqual(json.loads((data / 'strata-ssd-fast.json').read_text())['env']['STRATA_ROUTE_TAIL_SKIP'], '0')
            self.assertEqual(json.loads((runtime / 'strata-q2_0.json').read_text())['env']['STRATA_METAL_PROMPT_GEMM'], '0')
            fetch.assert_called_once()
            script = (root / 'start-strata.sh').read_text()
            self.assertIn('--backend strata', script)
            self.assertIn(str(runtime), script)

    def test_archive_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / 'runtime'
            def fetch(url, destination):
                with tarfile.open(destination, 'w:gz') as archive:
                    member = tarfile.TarInfo('../../escape')
                    member.size = 1
                    archive.addfile(member, io.BytesIO(b'x'))
            with patch.object(installer, 'RUNTIME', runtime), \
                 patch.object(installer.urllib.request, 'urlretrieve', side_effect=fetch):
                with self.assertRaisesRegex(ValueError, 'Unsafe'):
                    installer.download_source('https://example.test/source.tar.gz')
            self.assertFalse(runtime.exists())

    def test_archive_installs_source_and_records_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / 'runtime'
            def fetch(url, destination):
                with tarfile.open(destination, 'w:gz') as archive:
                    member = tarfile.TarInfo('Strata/setup.sh')
                    member.size = 1
                    archive.addfile(member, io.BytesIO(b'x'))
            with patch.object(installer, 'RUNTIME', runtime), \
                 patch.object(installer.urllib.request, 'urlretrieve', side_effect=fetch):
                installer.download_source('https://example.test/source.tar.gz')
            self.assertTrue((runtime / 'setup.sh').exists())
            provenance = json.loads((runtime / 'onram-source.json').read_text())
            self.assertEqual(len(provenance['sha256']), 64)
