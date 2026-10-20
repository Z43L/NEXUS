import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import download_trainable as downloader


class RangeResponse(io.BytesIO):
    status = 206
    def __init__(self, value, first, last, total):
        super().__init__(value)
        self.headers = {'Content-Range': f'bytes {first}-{last}/{total}'}


class TrainableDownloadTests(unittest.TestCase):
    def test_ranges_resume_and_verify_exact_file(self):
        content = b'0123456789ABCDEF'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'model.safetensors.part').write_bytes(content[:4] + b'\0' * 12)
            (root / 'model.safetensors.ranges.json').write_text(json.dumps({'revision': 'pinned', 'done': [0]}))
            fetched = []
            def open_range(request, timeout):
                first, last = map(int, request.get_header('Range').removeprefix('bytes=').split('-'))
                fetched.append(first)
                return RangeResponse(content[first:last+1], first, last, len(content))
            entry = {'rfilename': 'model.safetensors', 'size': len(content),
                     'lfs': {'sha256': hashlib.sha256(content).hexdigest()}}
            with patch.object(downloader, 'DEST', root), patch.object(downloader, 'CHUNK', 4), \
                 patch.object(downloader.urllib.request, 'urlopen', side_effect=open_range), \
                 patch('builtins.print'):
                downloader.fetch_file('repo/model', 'pinned', entry)
            self.assertEqual((root / 'model.safetensors').read_bytes(), content)
            self.assertEqual(set(fetched), {4, 8, 12})
            self.assertFalse((root / 'model.safetensors.ranges.json').exists())

    def test_checksum_mismatch_does_not_publish_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with patch.object(downloader, 'DEST', root), \
                 patch.object(downloader.urllib.request, 'urlopen', return_value=io.BytesIO(b'bad')):
                with self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
                    downloader.fetch_file('repo/model', 'pin', {'rfilename': 'model.safetensors',
                        'size': 3, 'lfs': {'sha256': 'wrong'}})
            self.assertFalse((root / 'model.safetensors').exists())
