import json
import unittest
from unittest.mock import Mock
from onram import Onram


class OnramMemoryTests(unittest.TestCase):
    def app(self):
        app = Onram.__new__(Onram)
        app.episodic = Mock()
        app.episodic.augment.side_effect = lambda query: 'MEMORY\n' + query
        app.auto_learn = False
        app._stable_model_alias = 'test:latest'
        return app

    def test_agent_protocols_preserve_tool_blocks(self):
        cases = [
            ('/v1/messages', {'messages': [{'role': 'user', 'content': [
                {'type': 'tool_result', 'tool_use_id': '123', 'content': 'output'},
                {'type': 'text', 'text': 'Pregunta'}]}]}),
            ('/v1/chat/completions', {'messages': [{'role': 'system', 'content': 'System'},
                {'role': 'user', 'content': 'Pregunta'}]}),
            ('/v1/responses', {'input': 'Pregunta'}),
            ('/v1/responses', {'input': [{'role': 'user', 'content': [
                {'type': 'input_text', 'text': 'Pregunta'}]}]}),
            ('/api/chat', {'messages': [{'role': 'user', 'content': 'Pregunta'}]}),
            ('/api/generate', {'prompt': 'Pregunta'}),
        ]
        for route, data in cases:
            with self.subTest(route=route):
                raw = json.dumps(data).encode()
                result = json.loads(self.app().augment_request(route, raw))
                self.assertIn('MEMORY', json.dumps(result))
                self.assertIn('Pregunta', json.dumps(result))
                if route == '/v1/messages':
                    self.assertEqual(result['messages'][0]['content'][0],
                                     data['messages'][0]['content'][0])

    def test_capture_without_auto_training(self):
        app = self.app()
        request = json.dumps({'messages': [{'role': 'user', 'content': 'Pregunta original'}]}).encode()
        response = json.dumps({'choices': [{'finish_reason': 'stop',
            'message': {'content': 'Respuesta completa'}}]}).encode()
        app.record_interaction('/v1/chat/completions', request, response)
        app.episodic.remember.assert_called_once_with('Pregunta original', 'Respuesta completa', model='test:latest')
        app.episodic.remember.reset_mock()
        app.record_interaction('/v1/chat/completions', request, response, 500)
        app.episodic.remember.assert_not_called()

    def test_nexus_worker_traffic_does_not_recall_or_capture_shared_memory(self):
        app = self.app()
        app.auto_learn = True
        app.learning = Mock()
        raw = json.dumps({'nexus_worker': True, 'messages': [
            {'role': 'user', 'content': 'Private account prompt'}]}).encode()
        forwarded = json.loads(app.augment_request('/v1/chat/completions', raw))
        self.assertNotIn('nexus_worker', forwarded)
        self.assertEqual(forwarded['messages'][0]['content'], 'Private account prompt')
        app.episodic.augment.assert_not_called()
        app.record_interaction('/v1/chat/completions', raw,
                               b'{"choices":[{"message":{"content":"private answer"}}]}')
        app.episodic.remember.assert_not_called()
        app.learning.capture_facts.assert_not_called()
        app.learning.add.assert_not_called()

    def test_failure_preserves_request_and_reports_error(self):
        app = self.app()
        app.episodic.augment.side_effect = RuntimeError('unavailable')
        raw = json.dumps({'input': 'Pregunta'}).encode()
        self.assertEqual(app.augment_request('/v1/responses', raw), raw)
        self.assertEqual(app.memory_error, 'unavailable')
