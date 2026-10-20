"""Protocol and lifecycle checks without loading model weights."""
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from onram import Onram


class StrataBackendTests(unittest.TestCase):
    def app(self):
        app = Onram.__new__(Onram)
        app.backend_kind = 'strata'
        app._stable_model_alias = 'qwen3.8-flash-next:latest'
        app.backend_port = 11436
        app.inference_debug = False
        app.lock = threading.RLock()
        return app

    def test_generate_translates_request_and_usage(self):
        app = self.app()
        response = MagicMock()
        response.status = 200
        response.read.return_value = json.dumps({'choices': [{'message': {'content': 'hola'}}],
                                                 'usage': {'completion_tokens': 2}}).encode()
        response.__enter__.return_value = response
        with patch('onram.urllib.request.urlopen', return_value=response) as send:
            result = app.generate('saluda', {'num_predict': 12})
        request = send.call_args.args[0]
        body = json.loads(request.data)
        self.assertTrue(request.full_url.endswith('/v1/chat/completions'))
        self.assertEqual(body['messages'], [{'role': 'user', 'content': 'saluda'}])
        self.assertEqual(body['max_tokens'], 12)
        self.assertEqual(result['content'], 'hola')
        self.assertEqual(result['tokens_predicted'], 2)

    def test_stream_translates_deltas_and_finishes(self):
        app = self.app()
        payload = b'data: {"choices":[{"delta":{"content":"hola"},"finish_reason":null}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n'
        with patch('onram.urllib.request.urlopen', return_value=io.BytesIO(payload)):
            chunks = list(app.stream_generate('saluda', {}))
        self.assertEqual(''.join(c['content'] for c in chunks), 'hola')
        self.assertEqual([c['stop'] for c in chunks], [False, True])

    def test_chat_roles_are_preserved(self):
        app = self.app()
        messages = [{'role': 'system', 'content': 'Habla español'}, {'role': 'user', 'content': 'Hola'}]
        _, body = app._completion_request(app._completion_options('unused', {'_messages': messages}))
        self.assertEqual(body['messages'], messages)

    def test_evolution_is_rejected_before_loading_weights(self):
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            self.app().begin_evolution({})

    def test_strata_disables_incompatible_features_and_starts_local_server(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'serve').mkdir()
            (root / 'serve/server.py').touch()
            python = root / 'python'
            python.touch()
            config = root / 'config.json'
            config.write_text('{}')
            with patch('onram.ROOT', root):
                app = Onram(root / 'missing.gguf', root / 'missing-llama', '127.0.0.1',
                            11434, 11436, root / 'test.nram', auto_learn=True,
                            inference_debug=True, backend_kind='strata', strata_dir=root,
                            strata_config=config, strata_python=python)
            process = MagicMock()
            process.poll.return_value = None
            try:
                with patch('onram.subprocess.Popen', return_value=process) as start, \
                     patch.object(app, '_backend_request', return_value={'status': 'ok', 'loaded': True}):
                    app.start_backend()
                self.assertFalse(app.auto_learn)
                self.assertFalse(app.inference_debug)
                command = start.call_args.args[0]
                self.assertIn('serve.server', command)
                self.assertEqual(command[command.index('--host') + 1], '127.0.0.1')
                self.assertIn(str(config.resolve()), command)
            finally:
                app.close()
            process.terminate.assert_called_once()


if __name__ == '__main__':
    unittest.main()
