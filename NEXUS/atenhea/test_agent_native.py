"""Agent launch must resolve to the configured native checkpoint runtime."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from onram_cli import check_native_runtime,build_agent_invocation,launch_agent

class NativeAgentTests(unittest.TestCase):
    profile={'name':'athenea-e2b:latest','backend':'nram','args':['--bundle','/tmp/athenea.nram']}
    def status(self,**changes):
        return {'loaded':True,'backend':'nram','model':'athenea-e2b:latest',
                'bundle':'/tmp/athenea.nram',**changes}
    def test_accepts_native_bundle_and_sends_auth(self):
        with patch('onram_cli.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(self.status()).encode())) as open_url:
            self.assertTrue(check_native_runtime('http://127.0.0.1:11434',self.profile,'secret')['loaded'])
            self.assertEqual(open_url.call_args.args[0].get_header('Authorization'),'Bearer secret')
    def test_rejects_gguf_wrong_bundle_model_and_unloaded_runtime(self):
        for changes in ({'backend':'llama.cpp'},{'bundle':'/tmp/other.nram'},
                        {'model':'other'},{'loaded':False}):
            with self.subTest(changes=changes),patch('onram_cli.urllib.request.urlopen',
                return_value=io.BytesIO(json.dumps(self.status(**changes)).encode())):
                with self.assertRaisesRegex(RuntimeError,'no GGUF fallback'):
                    check_native_runtime('http://127.0.0.1:11434',self.profile)
    def test_all_agents_use_same_local_model_and_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            for agent in ('pi','claude','codex'):
                command,env=build_agent_invocation(agent,'/bin/'+agent,[],
                    base_url='http://127.0.0.1:11434',model=self.profile['name'],env={},
                    agent_dir=Path(directory),context_window=131072)
                if agent=='pi':
                    model=json.loads((Path(directory)/'models.json').read_text())['providers']['onram']['models'][0]
                    self.assertEqual(model['id'],self.profile['name']);self.assertEqual(model['maxTokens'],131072)
                elif agent=='claude':
                    self.assertEqual(env['ANTHROPIC_MODEL'],self.profile['name'])
                    self.assertEqual(env['ANTHROPIC_BASE_URL'],'http://127.0.0.1:11434')
                else:
                    self.assertIn('model="athenea-e2b:latest"',command)
                    self.assertIn('model_providers.onram.wire_api="responses"',command)
                    self.assertIn('web_search="disabled"',command)
                    self.assertEqual(Path(env['CODEX_HOME']).name,'codex')
                    self.assertIn('model_context_window=131072',command)
    def test_launch_validates_native_backend_before_executing_each_agent(self):
        for agent in ('pi','claude','codex'):
            with tempfile.TemporaryDirectory() as directory,patch('onram_cli.check_onram',return_value=self.profile['name']),\
                 patch('onram_cli.check_native_runtime',side_effect=RuntimeError('wrong backend')) as check,\
                 patch('onram_cli.os.execvpe') as execute:
                self.assertEqual(launch_agent([agent],environ={}),1)
                check.assert_called_once();execute.assert_not_called()

    def test_codex_custom_tools_round_trip_without_exposing_grammar_as_a_function(self):
        from native_protocol import messages_for,response_for,stream_events
        tools=[{'type':'custom','name':'apply_patch','description':'Apply patch','format':{'type':'grammar'}}]
        messages,normalized=messages_for('/v1/responses',{'input':'edit','tools':tools})
        self.assertTrue(normalized[0]['onram_custom'])
        self.assertEqual(normalized[0]['function']['parameters']['properties']['input']['type'],'string')
        response=response_for('/v1/responses',{'tool_calls':[{'id':'call_a','onram_custom':True,
            'function':{'name':'apply_patch','arguments':{'input':'*** Begin Patch\n*** End Patch'}}}]},
            'athenea-e2b:latest',{'prompt_tokens':10,'completion_tokens':5},1)
        item=response['output'][0]
        self.assertEqual(item['type'],'custom_tool_call')
        self.assertEqual(item['input'],'*** Begin Patch\n*** End Patch')
        events=list(stream_events('/v1/responses',response))
        self.assertTrue(any(kind=='response.custom_tool_call_input.delta' for kind,_ in events))
        history,_=messages_for('/v1/responses',{'input':[item,{'type':'custom_tool_call_output',
            'call_id':'call_a','output':'done'}],'tools':tools})
        self.assertEqual(history[0]['tool_calls'][0]['function']['arguments']['input'],item['input'])
        self.assertEqual(history[1]['name'],'apply_patch')

    def test_existing_server_is_reused_without_spawning_or_loading_weights(self):
        from onram_cli import ensure_local_server
        with patch('onram_cli.check_onram',return_value=self.profile['name']),patch('onram_cli.subprocess.Popen') as spawn:
            ensure_local_server('http://127.0.0.1:11434')
            ensure_local_server('http://127.0.0.1:11434')
            spawn.assert_not_called()
