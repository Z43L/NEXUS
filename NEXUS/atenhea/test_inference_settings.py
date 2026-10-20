import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import inference_settings as settings

class PublicExplanationTests(unittest.TestCase):
    def test_toggle_is_read_without_model_reload_and_request_can_override(self):
        with tempfile.TemporaryDirectory() as directory,patch.object(settings,'SETTINGS',Path(directory)/'settings.json'):
            self.assertFalse(settings.enabled())
            settings.SETTINGS.write_text(json.dumps({'show_reasoning_summary':True}))
            self.assertTrue(settings.enabled())
            self.assertFalse(settings.enabled({'show_reasoning_summary':False}))
            self.assertFalse(settings.enabled({'reasoning':{'summary':None}}))
            settings.SETTINGS.write_text(json.dumps({'show_reasoning_summary':False}))
            self.assertFalse(settings.enabled())
            self.assertTrue(settings.enabled({'reasoning':{'summary':'concise'}}))
    def test_public_instruction_does_not_mutate_history_or_tool_messages(self):
        messages=[{'role':'system','content':'system'},{'role':'user','content':'question'},
                  {'role':'tool','tool_call_id':'abc','content':'result'}]
        output=settings.public_messages(messages,True)
        self.assertEqual(messages[0]['content'],'system')
        self.assertEqual(output[1:],messages[1:])
        self.assertIn('una sola frase',output[0]['content'])
        self.assertIn('formatos estrictos',output[0]['content'])
        self.assertEqual(settings.public_messages(messages,False),messages)
    def test_invalid_public_display_preference_is_rejected(self):
        with self.assertRaises(ValueError):settings.enabled({'show_reasoning_summary':'yes'})
