import json
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import setup_gemma
import onram_cli
from onram import Onram


class GemmaSetupTests(unittest.TestCase):
    def test_range_download_resumes_prefix_without_corrupting_bytes(self):
        data = b'Gemma weights for testing'
        class Response(io.BytesIO):
            status = 206
            def __init__(self, first, last):
                super().__init__(data[first:last + 1])
                self.headers = {'Content-Range': f'bytes {first}-{last}/{len(data)}'}
        def request(req, **kwargs):
            bounds = req.get_header('Range').split('=')[1]
            first, last = map(int, bounds.split('-'))
            return Response(first, last)
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / 'model.gguf.part'
            target.write_bytes(data[:6])
            with patch.object(setup_gemma.urllib.request, 'urlopen', side_effect=request):
                setup_gemma.download_model(target)
            self.assertEqual(target.read_bytes(), data)

    def test_profile_preserves_native_context_and_allows_disk_backed_weights(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'models').mkdir()
            with patch.object(setup_gemma, 'ROOT', root):
                script = setup_gemma.configure(root / 'model.gguf')
            profile = json.loads((root / 'models/onram-launch.json').read_text())
            self.assertEqual(profile['context_size'], 262144)
            args = profile['args']
            self.assertEqual(args[args.index('--ctx-size') + 1], '262144')
            self.assertIn('--backend-arg=mmap', args)
            self.assertIn('--backend-arg=--fit-ctx', args)
            self.assertNotIn('--backend-arg=all', args)
            self.assertIn('--no-auto-learn', args)
            self.assertTrue(script.stat().st_mode & 0o100)

    def test_pi_receives_full_context(self):
        with tempfile.TemporaryDirectory() as temp:
            config = onram_cli.configure_pi_provider(Path(temp), 'http://localhost:11434',
                'gemma4-26b-a4b:latest', None, context_window=262144)
            model = json.loads(config.read_text())['providers']['onram']['models'][0]
            self.assertEqual(model['contextWindow'], 262144)

    def test_launch_profile_takes_precedence_over_strata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'models').mkdir()
            (root / 'models/onram-launch.json').write_text(json.dumps({
                'args': ['--model', '/gemma.gguf', '--ctx-size', '262144'],
                'name': 'gemma4-26b-a4b:latest'}))
            process = MagicMock()
            with patch.object(onram_cli, 'ROOT', root), \
                 patch.object(onram_cli, 'check_onram', side_effect=[RuntimeError('down'), 'gemma']), \
                 patch.object(onram_cli.subprocess, 'Popen', return_value=process) as start:
                onram_cli.ensure_local_server(onram_cli.DEFAULT_BASE_URL)
            self.assertIn('/gemma.gguf', start.call_args.args[0])
            self.assertIn('262144', start.call_args.args[0])

    def test_llama_backend_passes_quantized_cache_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model, server = root / 'model.gguf', root / 'llama-server'
            model.touch(); server.touch()
            with patch('onram.ROOT', root):
                app = Onram(model, server, '127.0.0.1', 11434, 11436, root / 'test.nram',
                            ctx_size=262144, llama_args=['--cache-type-k', 'q4_0', '--load-mode', 'mmap'])
            process = MagicMock()
            process.poll.return_value = None
            try:
                with patch('onram.subprocess.Popen', return_value=process) as start, \
                     patch.object(app, '_backend_request', return_value={}):
                    app.start_backend()
                command = start.call_args.args[0]
                self.assertEqual(command[command.index('--ctx-size') + 1], '262144')
                self.assertIn('mmap', command)
                self.assertIn('q4_0', command)
            finally:
                app.close()
