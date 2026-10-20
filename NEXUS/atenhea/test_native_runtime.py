import json
from pathlib import Path
import unittest
from native_protocol import messages_for,response_for,stream_events
from interaction_learning import extract_completion


class NativeProtocolTests(unittest.TestCase):
    def test_anthropic_tools_and_results_preserve_identifiers(self):
        messages,tools=messages_for('/v1/messages',{'system':'system','tools':[{'name':'read','input_schema':{'type':'object'}}],
            'messages':[{'role':'assistant','content':[{'type':'tool_use','id':'a','name':'read','input':{'path':'x'}}]},
                        {'role':'user','content':[{'type':'tool_result','tool_use_id':'a','content':'result'}]}]})
        self.assertEqual(messages[0]['role'],'system')
        self.assertEqual(messages[-1]['name'],'read')
        self.assertEqual(messages[-1]['tool_call_id'],'a')
        self.assertEqual(tools[0]['function']['name'],'read')

    def test_responses_function_history(self):
        messages,_=messages_for('/v1/responses',{'input':[{'type':'function_call','call_id':'abc','name':'read','arguments':'{"path":"x"}'},
            {'type':'function_call_output','call_id':'abc','output':'result'}]})
        self.assertEqual(messages[0]['tool_calls'][0]['function']['arguments'],{'path':'x'})
        self.assertEqual(messages[-1]['name'],'read')

    def test_all_protocol_streams_are_captured_as_completed_text(self):
        for route in ('/v1/messages','/v1/chat/completions','/v1/responses'):
            with self.subTest(route=route):
                response=response_for(route,{'content':'Respuesta completa'},'athenea',{'prompt_tokens':3,'completion_tokens':2},1)
                raw=''.join(('event: '+event+'\n' if event else '')+'data: '+json.dumps(value)+'\n\n'
                            for event,value in stream_events(route,response)).encode()
                self.assertEqual(extract_completion(route,raw),'Respuesta completa')

    def test_tool_calls_are_never_captured_as_training_answers(self):
        for route in ('/v1/messages','/v1/chat/completions','/v1/responses'):
            message={'content':'','tool_calls':[{'type':'function','function':{'name':'read','arguments':{'path':'x'}}}]}
            response=response_for(route,message,'athenea',{'prompt_tokens':3,'completion_tokens':2},1)
            self.assertEqual(extract_completion(route,json.dumps(response).encode()),'')

    def test_gemma_parser_uses_downloaded_tool_template(self):
        if not Path('models/gemma4-e2b-trainable/tokenizer.json').exists():self.skipTest('E2B tokenizer unavailable')
        from transformers import AutoTokenizer
        tokenizer=AutoTokenizer.from_pretrained('models/gemma4-e2b-trainable',local_files_only=True)
        tools=[{'type':'function','function':{'name':'read','parameters':{'type':'object','properties':{'path':{'type':'string'}}}}}]
        prefix=tokenizer.apply_chat_template([{'role':'user','content':'Read x'}],tools=tools,tokenize=False,add_generation_prompt=True,enable_thinking=False)
        result=tokenizer.parse_response('<|tool_call>call:read{path:<|"|>x<|"|>}<tool_call|>',prefix=prefix,tools=tools)
        self.assertEqual(result['tool_calls'][0]['function']['name'],'read')
        self.assertEqual(result['tool_calls'][0]['function']['arguments'],{'path':'x'})


class OnlineTrainingTests(unittest.TestCase):
    def test_live_update_keeps_base_frozen_and_matches_persisted_version(self):
        import tempfile,threading
        from unittest.mock import patch
        import torch
        from native_runtime import NativeEngine
        from test_micro_extensions import MicroExtensionTests,Tokenizer
        from micro_extensions import bank_tensors
        from nram_container import save_bundle,load_bundle
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);model,bank=MicroExtensionTests().fixture()
            engine=NativeEngine.__new__(NativeEngine)
            engine.model=model;engine.tokenizer=Tokenizer();engine.lock=threading.RLock()
            engine.bundle=root/'base.nram';engine.bundle.write_bytes(b'upstream identity')
            engine.extension_path=root/'active.nram';engine.version=0
            from prefix_cache import PrefixCache
            engine.prefix_cache=PrefixCache();engine.prefix_cache.snapshot=object()
            engine.prefix_cache.ids=(1,2);engine.prefix_cache.version=0
            engine.manifest={'base_model':{'weights_sha256':'tiny'}}
            engine.micro_manifest={'model_family':'onram-external-micro-mlp-v1','version':0,
                'base_weights_sha256':'tiny','parent_bundle':str(engine.bundle),
                'micro_extensions':{'hidden_size':8,'rank':2,'experts':3,'module':'model.layers.1.mlp'},'journal':[]}
            save_bundle(engine.extension_path,engine.micro_manifest,bank_tensors(bank))
            frozen={name:value.detach().clone() for name,value in model.named_parameters()
                    if not name.startswith('onram_micro_extensions.')}
            row=lambda prompt:{'prompt':prompt,'completion':'b','verified':True}
            body={'train':[row('training question')],'validation':[row('validation question')],
                  'guardrail':[row('regression question')],'epochs':10,'learning_rate':.01}
            with patch('native_runtime.ROOT',root):report=engine.train(body)
            self.assertEqual(engine.version,1 if report['accepted'] else 0)
            if report['accepted']:self.assertIsNone(engine.prefix_cache.snapshot)
            saved,_=load_bundle(engine.extension_path)
            self.assertEqual(saved['version'],engine.version)
            for name,value in model.named_parameters():
                if name in frozen:torch.testing.assert_close(value,frozen[name],rtol=0,atol=0)
            self.assertEqual(list((root/'models/athenea-online').glob('*/tail.safetensors')),[])

    def test_unverified_examples_are_rejected_before_model_use(self):
        from native_runtime import NativeEngine
        engine=NativeEngine.__new__(NativeEngine);engine.extension_path=Path('exists')
        body={name:[{'prompt':'question','completion':'unreviewed'}]
              for name in ('train','validation','guardrail')}
        with self.assertRaisesRegex(ValueError,'verified'):engine.train(body)

class LiveStreamingTests(unittest.TestCase):
    def test_incremental_protocol_text_matches_completed_capture(self):
        from native_protocol import LiveStream
        for path in ('/v1/messages','/v1/responses','/v1/chat/completions'):
            live=LiveStream(path,'test',1,3)
            events=list(live.start())
            events+=list(live.delta('Hola '));events+=list(live.delta('mundo 🌍'))
            response=response_for(path,{'content':'Hola mundo 🌍'},'test',
                {'prompt_tokens':3,'completion_tokens':4},1)
            events+=list(live.finish(response))
            wire=''.join(('event: '+kind+'\n' if kind else '')+'data: '+json.dumps(value)+'\n\n'
                         for kind,value in events)
            self.assertEqual(extract_completion(path,wire.encode()),'Hola mundo 🌍')
            if path=='/v1/responses':
                self.assertEqual([v['sequence_number'] for _,v in events],list(range(len(events))))
                ids=[v['item_id'] for _,v in events if 'item_id' in v]
                self.assertEqual(len(set(ids)),1)

    def test_native_generation_emits_before_model_finishes(self):
        import threading
        from types import SimpleNamespace
        import torch
        from native_runtime import NativeEngine
        entered=threading.Event();release=threading.Event()
        class Batch(dict):
            def to(self,device):return self
        class Tokenizer:
            response_template=None;pad_token_id=0;eos_token_id=9
            def __call__(self,*args,**kwargs):return Batch(input_ids=torch.tensor([[1]]))
            def decode(self,ids,**kwargs):
                return ''.join({2:'Hola ',3:'mundo ',9:''}.get(int(i),'') for i in ids)
        self_outer=self;thread_ids=[]
        class Model:
            generation_config=SimpleNamespace(eos_token_id=9)
            def generate(self,input_ids,streamer,**kwargs):
                thread_ids.append(threading.get_ident())
                self_outer.assertEqual(kwargs['max_new_tokens'],4095)
                streamer.put(input_ids);streamer.put(torch.tensor([2]));entered.set()
                if not release.wait(5):raise RuntimeError('test generation timed out')
                streamer.put(torch.tensor([3]));streamer.put(torch.tensor([9]));streamer.end()
                return torch.tensor([[1,2,3,9]])
        engine=NativeEngine.__new__(NativeEngine)
        engine.lock=threading.RLock();engine.name='test';engine.version=1;engine.history={}
        engine.device='cpu';engine.ctx_size=4096;engine.tokenizer=Tokenizer();engine.model=Model()
        engine.render=lambda messages,tools:'prompt'
        stream=engine.stream('/v1/chat/completions',{'messages':[{'role':'user','content':'hi'}]})
        try:
            next(stream)
            event=next(stream)
            self.assertTrue(entered.wait(1))
            self.assertEqual(event[1]['choices'][0]['delta']['content'],'Hola ')
            self.assertFalse(release.is_set())
            release.set();rest=list(stream)
            self.assertEqual(rest[-1][1]['choices'][0]['finish_reason'],'stop')
            self.assertEqual(engine.last_inference['output_limit_source'],'default')
            self.assertEqual(engine.last_inference['max_output_tokens'],4095)
            list(engine.stream('/v1/chat/completions',{'messages':[{'role':'user','content':'hi'}]}))
            self.assertEqual(len(thread_ids),2)
            self.assertEqual(len(set(thread_ids)),1)
            self.assertEqual(engine.activity['state'],'idle')
        finally:release.set();stream.close()

    def test_fragmented_tool_delimiters_are_not_visible_text(self):
        if not Path('models/gemma4-e2b-trainable/tokenizer.json').exists():self.skipTest('E2B tokenizer unavailable')
        from transformers import AutoTokenizer
        tokenizer=AutoTokenizer.from_pretrained('models/gemma4-e2b-trainable',local_files_only=True)
        tools=[{'type':'function','function':{'name':'read','parameters':{'type':'object','properties':{'path':{'type':'string'}}}}}]
        prefix=tokenizer.apply_chat_template([{'role':'user','content':'Read x'}],tools=tools,
            tokenize=False,add_generation_prompt=True,enable_thinking=False)
        parser=tokenizer.get_response_parser(prefix=prefix,tools=tools)
        visible=[]
        for char in '<|tool_call>call:read{path:<|"|>x<|"|>}<tool_call|>':
            visible.extend(event['text'] for event in parser.feed(char)
                if event['type']=='region_chunk' and event['field']=='content')
        message,events=parser.finalize()
        visible.extend(event['text'] for event in events if event['type']=='region_chunk' and event['field']=='content')
        self.assertEqual(''.join(visible),'')
        self.assertEqual(message['tool_calls'][0]['function']['arguments'],{'path':'x'})
