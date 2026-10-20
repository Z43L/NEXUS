"""Onram direct Transformers/NRAM runtime with transactional in-memory micro-updates."""
from __future__ import annotations
import argparse
import copy
import os
from concurrent.futures import ThreadPoolExecutor
import json
import queue
from pathlib import Path
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import torch
from safetensors.torch import save_file
from nram_generic import load_nram_model, load_tokenizer
from nram_container import load_bundle, save_bundle
from inference_settings import enabled as summary_enabled,public_messages
from prefix_cache import PrefixCache,stable_prefix_length
from native_placement import place_native
from micro_extensions import load_extension
from native_protocol import messages_for, response_for, LiveStream
from micro_training_control import MicroTrainingController,TRAIN_TOOL

ROOT=Path(__file__).resolve().parent


class NativeEngine:
    def __init__(self,bundle,model_name='athenea-e2b:latest',device='auto',ctx_size=0):
        self.lock=threading.RLock();self.name=model_name;self.bundle=Path(bundle)
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='atenhea-inference')
        self.activity={'state':'idle'};self.loaded_at=time.time()
        self.prefix_cache=PrefixCache()
        self.device=('mps' if torch.backends.mps.is_available() else 'cpu') if device=='auto' else device
        self.manifest,self.model,_=load_nram_model(bundle,local_files_only=True)
        self.placement=place_native(self.model,self.device)
        self.model.eval()
        for p in self.model.parameters():p.requires_grad_(False)
        base=self.manifest['base_model']
        self.tokenizer=load_tokenizer(base.get('tokenizer_source') or base['source'],local_files_only=True)
        config=getattr(self.model.config,'text_config',self.model.config)
        self.model_context_size=int(config.max_position_embeddings)
        self.ctx_size=min(ctx_size or self.model_context_size,self.model_context_size)
        if self.ctx_size<1:raise ValueError('ctx_size must be positive or zero for model maximum')
        self.history={};self.last_training=None;self.last_inference=None
        self.extension_path=Path(self.manifest['micro_extension']['path']) if self.manifest.get('micro_extension') else None
        self.micro_manifest=load_bundle(self.extension_path)[0] if self.extension_path else None
        self.version=self.micro_manifest['version'] if self.micro_manifest else 0
        self.micro_controller=MicroTrainingController(self,
            memory_path=Path(self.manifest.get('episodic_memory',{}).get('path') or ROOT/'models/athenea.memory'))
        print(json.dumps({'event':'native_loaded','device':self.device,'bundle':str(bundle),'micro_version':self.version}),flush=True)

    def health(self):
        return {'loaded':True,'backend':'nram','device':self.device,'model':self.name,
                'bundle':str(self.bundle),'micro_version':self.version,
                'base_weights_frozen':True,
                'show_reasoning_summary':summary_enabled(),
                'reasoning_display':'brief_public_explanation',
                'prefix_cache':self.prefix_cache.status(),'placement':self.placement,
                'micro_training_schedule':self.micro_controller.status() if hasattr(self,'micro_controller') else None,
                'pid':os.getpid(),'loaded_at':getattr(self,'loaded_at',None),
                'activity':getattr(self,'activity',{'state':'idle'}),'weights_load_count':1,
                'context_size':self.ctx_size,'model_context_size':self.model_context_size,
                'parameter_bytes':sum(p.numel()*p.element_size() for p in self.model.parameters()),
                'parameter_devices':sorted({p.device.type for p in self.model.parameters()}),
                'last_inference':self.last_inference,
                'last_training':self.last_training,
                'mps_allocated_bytes':torch.mps.current_allocated_memory() if self.device=='mps' else None}

    def render(self,messages,tools):
        return self.tokenizer.apply_chat_template(messages,tools=tools or None,tokenize=False,
            add_generation_prompt=True,enable_thinking=False)

    def worker(self):
        if not hasattr(self,'executor'):
            self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='atenhea-inference')
        return self.executor

    def generate(self,path,body):
        return self.worker().submit(self._generate,path,body).result()

    def _generate(self,path,body,emit=None,cancel=None):
        with self.lock:
            self.activity={'state':'preparing','started_at':time.time()}
            try:return self._generate_locked(path,body,emit,cancel)
            finally:self.activity={'state':'idle'}

    def _generate_locked(self,path,body,emit=None,cancel=None):
            previous=body.get('previous_response_id')
            if previous and previous not in self.history:
                raise ValueError('Unknown previous_response_id; resend the full message history')
            messages,tools=messages_for(path,body,self.history.get(previous))
            tools=list(tools)
            if not any(tool.get('function',{}).get('name')==TRAIN_TOOL['function']['name'] for tool in tools):
                tools.append(copy.deepcopy(TRAIN_TOOL))
            show_summary=summary_enabled(body)
            prepared_messages=public_messages(messages,show_summary)
            rendered=self.render(prepared_messages,tools)
            encoded=self.tokenizer(rendered,return_tensors='pt',add_special_tokens=False).to(self.device)
            count=encoded['input_ids'].shape[1]
            requested=next((body[key] for key in ('max_output_tokens','max_completion_tokens','max_tokens')
                            if body.get(key) is not None),None)
            available=self.ctx_size-count
            if available<1:raise ValueError(f'Context budget exhausted: {count}>={self.ctx_size}')
            limit=int(requested) if requested is not None else self.ctx_size
            if not 1<=limit<=self.ctx_size:
                raise ValueError(f'max tokens must be in 1..{self.ctx_size}')
            maximum=min(limit,available)
            temperature=float(body.get('temperature',0.2))
            if not 0<=temperature<=2:raise ValueError('temperature must be in 0..2')
            eos=self.model.generation_config.eos_token_id
            eos=[eos] if isinstance(eos,int) else list(eos or [])
            if tools:
                tool_end=self.tokenizer.convert_tokens_to_ids('<tool_call|>')
                if tool_end is not None and tool_end != self.tokenizer.unk_token_id:
                    eos=list(set(eos+[tool_end]))
            live=LiveStream(path,self.name,self.version,count) if emit else None
            streamer=None;extra={}
            if live:
                from transformers import TextStreamer,StoppingCriteria,StoppingCriteriaList
                parser=(self.tokenizer.get_response_parser(prefix=rendered,tools=tools or None)
                        if getattr(self.tokenizer,'response_template',None) else None)
                def consume(events):
                    for event in events:
                        if event['type']=='region_chunk' and event['field']=='content':
                            for item in live.delta(event['text']):emit(item)
                class Streamer(TextStreamer):
                    def put(inner,value):
                        nonlocal first_token
                        if not inner.next_tokens_are_prompt and first_token is None:
                            first_token=time.perf_counter()
                            self.activity['phase']='decoding'
                        super().put(value)
                    def on_finalized_text(inner,text,stream_end=False):
                        if text:
                            self.activity['output_fragments']=self.activity.get('output_fragments',0)+1
                            self.activity['phase']='decoding'
                        if parser:consume(parser.feed(text))
                        else:
                            for item in live.delta(text):emit(item)
                class Cancelled(StoppingCriteria):
                    def __call__(inner,input_ids,scores,**kwargs):return cancel.is_set()
                streamer=Streamer(self.tokenizer,skip_prompt=True,skip_special_tokens=parser is None)
                extra={'streamer':streamer,'stopping_criteria':StoppingCriteriaList([Cancelled()])}
                for item in live.start():emit(item)
                if parser:consume(parser.initial_events)
            self.activity={'state':'generating','phase':'prefill','show_reasoning_summary':show_summary,
                           'started_at':time.time(),'input_tokens':count,
                           'max_output_tokens':maximum,'output_fragments':0}
            started=time.perf_counter();first_token=None
            cache_info={'hit':False,'tokens':0}
            cache=getattr(self,'prefix_cache',None)
            if cache is not None:
                prefix_length=stable_prefix_length(prepared_messages,tools,self.render,self.tokenizer,
                    encoded['input_ids'][0].detach().cpu().tolist())
                self.activity['phase']='prefix_cache'
                past,cache_info=cache.prepare(self.model,encoded,prefix_length,self.version)
                if past is not None:extra['past_key_values']=past
                self.activity['phase']='prefill';self.activity['cached_prefix_tokens']=cache_info['tokens']
            with torch.inference_mode():
                output=self.model.generate(**encoded,**extra,max_new_tokens=maximum,do_sample=temperature>0,
                    **({'temperature':temperature,'top_p':float(body.get('top_p',.95))} if temperature>0 else {}),
                    pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
                    **({'eos_token_id':eos} if eos else {}))
            generated=output[0,count:]
            raw=self.tokenizer.decode(generated,skip_special_tokens=False)
            if getattr(self.tokenizer,'response_template',None):
                message=self.tokenizer.parse_response(raw,prefix=rendered,tools=tools or None)
            else:message={'role':'assistant','content':self.tokenizer.decode(generated,skip_special_tokens=True)}
            if live and parser:
                message,events=parser.finalize();consume(events)
            message.pop('thinking',None)
            internal_calls=[call for call in message.get('tool_calls',[])
                            if call.get('function',{}).get('name')==TRAIN_TOOL['function']['name']]
            if internal_calls:
                user_text=next((str(item.get('content','')) for item in reversed(messages)
                                if item.get('role')=='user'),'')
                if not any(word in user_text.casefold() for word in ('entren','train','microexperto','micro experto')):
                    message={'role':'assistant','content':'Solo inicio el entrenamiento de un microexperto cuando el usuario lo pide explícitamente.'}
                else:
                    try:
                        request=internal_calls[-1]['function'].get('arguments',{})
                        if isinstance(request,str):request=json.loads(request)
                        if not isinstance(request,dict):raise ValueError('Parámetros de entrenamiento inválidos.')
                        report=self.micro_controller.train_topic(request.get('topic',''),messages,
                            request.get('expert'))
                        if report.get('state')=='insufficient_topic_data':
                            detail=report['message']
                        elif report.get('accepted'):
                            detail=(f"Entrenamiento del microexperto para «{report.get('topic',request.get('topic'))}» "
                                    f"aceptado y activado. Experto {report['expert']}; versión {report['micro_version']}; "
                                    f"NLL validación {report['validation_nll_before']:.4f} → {report['validation_nll_after']:.4f}; "
                                    f"control de regresión {'superado' if report['guardrail_ok'] else 'fallido'}.")
                            if report.get('chat_data_fact_verified') is False:
                                detail+=' Se usaron pares del chat autorizados para esta ronda, pero no se consideran hechos verificados.'
                        else:
                            detail=(f"El candidato para «{report.get('topic',request.get('topic'))}» fue rechazado; "
                                    "la extensión activa se conserva porque no mejoró la validación o falló el control de regresión.")
                    except Exception as exc:
                        detail=f'No pude completar el entrenamiento del microexperto: {exc}'
                    message={'role':'assistant','content':detail}
            custom_names={tool['function']['name'] for tool in tools if tool.get('onram_custom')}
            for call in message.get('tool_calls',[]):
                if call['function']['name'] in custom_names:call['onram_custom']=True
            usage={'prompt_tokens':count,'completion_tokens':len(generated)}
            completed=bool(len(generated) and int(generated[-1]) in eos)
            response=response_for(path,message,self.name,usage,self.version)
            if not completed:
                if path=='/v1/messages':response['stop_reason']='max_tokens'
                elif path=='/v1/responses':
                    response['status']='incomplete';response['incomplete_details']={'reason':'max_output_tokens'}
                else:response['choices'][0]['finish_reason']='length'
            if live:
                if cancel.is_set():return response
                # Assign stable stream IDs before retaining Responses history.
                final_events=list(live.finish(response))
            if path=='/v1/responses':
                self.history[response['id']]=messages+[message]
                while len(self.history)>64:self.history.pop(next(iter(self.history)))
            elapsed=time.perf_counter()-started
            self.last_inference={'seconds':round(elapsed,3),'tokens':len(generated),
                                 'tokens_per_second':round(len(generated)/max(elapsed,1e-9),2),
                                 'max_output_tokens':maximum,'input_tokens':count,
                                 'output_limit_source':'client' if requested is not None else 'default',
                                 'finish_reason':'stop' if completed else 'length',
                                 'first_token_seconds':round(first_token-started,3) if first_token is not None else None,
                                 'prefix_cache_hit':cache_info['hit'],
                                 'cached_prefix_tokens':cache_info['tokens'],
                                 'reused_prefix_tokens':cache_info['tokens'] if cache_info['hit'] else 0}
            if live:
                for item in final_events:emit(item)
            return response

    def stream(self,path,body):
        pending=queue.Queue(maxsize=128);cancel=threading.Event()
        def emit(item):
            while not cancel.is_set():
                try:pending.put(item,timeout=.1);return
                except queue.Full:pass
        def run():
            try:self._generate(path,body,emit,cancel)
            except Exception as exc:emit(exc)
            finally:emit(None)
        future=self.worker().submit(run)
        try:
            while True:
                try:item=pending.get(timeout=5)
                except queue.Empty:
                    yield None,None
                    continue
                if item is None:break
                if isinstance(item,Exception):raise item
                yield item
        finally:
            cancel.set();future.result()

    def train(self,body):
        self.activity={'state':'training','phase':'validating_examples','started_at':time.time(),
                       'topic':body.get('topic')}
        try:
            return self._train(body)
        finally:
            if self.activity.get('state')=='training':
                self.activity={'state':'idle'}

    def _train(self,body):
        from micro_training import CachedTail,cache_examples,train_cached,sha
        from self_improvement import validate_separation
        if not self.extension_path:raise ValueError('Create a micro-extension before online training')
        train=body.get('train');validation=body.get('validation');guardrail=body.get('guardrail')
        if not all(isinstance(rows,list) and rows and len(rows)<=128 for rows in (train,validation,guardrail)):
            raise ValueError('Provide 1..128 train, validation and guardrail examples each')
        for rows in (train,validation,guardrail):
            for row in rows:
                approved_chat=(body.get('initiated_by')=='user_request'
                               and row.get('training_authorized') is True) or (
                               body.get('initiated_by')=='periodic_schedule'
                               and body.get('allow_unverified_chat') is True
                               and row.get('verified') is not True
                               and row.get('source')=='chl_chat')
                if ((row.get('verified') is not True and not approved_chat) or not all(isinstance(row.get(k),str) and
                    0<len(row[k].strip())<=8000 for k in ('prompt','completion'))):
                    raise ValueError('Use verified CHL examples, or complete chat pairs authorized by an explicit topic-training request')
        validate_separation(train,validation+guardrail)
        expert=int(body.get('expert',0));epochs=int(body.get('epochs',2));max_length=int(body.get('max_length',64))
        if not 1<=epochs<=20 or not 16<=max_length<=256:raise ValueError('Use epochs 1..20 and max_length 16..256')
        rate=float(body.get('learning_rate',.001))
        if not 0<rate<=.01:raise ValueError('learning_rate must be >0 and <=.01')
        with self.lock:
            bank=self.model.onram_micro_extensions
            self.last_training={'state':'preparing_cache','expert':expert}
            if not 0<=expert<len(bank.experts):raise ValueError('Unknown expert')
            directory=ROOT/'models/athenea-online'/uuid.uuid4().hex
            directory.mkdir(parents=True)
            tail=CachedTail.from_model(self.model,self.micro_manifest['micro_extensions']['module'])
            for name,rows in (('train',train),('validation',validation),('guardrail',guardrail)):
                data=cache_examples(self.model,rows,self.tokenizer,self.micro_manifest['micro_extensions']['module'],bank,max_length)
                save_file(data,directory/(name+'.safetensors'))
            save_file({k:v.detach().cpu().contiguous() for k,v in tail.state_dict().items()},directory/'tail.safetensors')
            metadata={'schema':'onram-e2b-micro-cache-v1','tail':tail.spec,
                'base_weights_sha256':self.manifest['base_model']['weights_sha256'],
                'bundle_sha256':sha(self.bundle),'module':self.micro_manifest['micro_extensions']['module']}
            (directory/'cache.json').write_text(json.dumps(metadata))
            candidate=directory/'candidate.nram'
            self.last_training={'state':'training_candidate','expert':expert}
            report=train_cached(self.extension_path,directory,candidate,expert=expert,epochs=epochs,
                                learning_rate=rate,tokens_per_batch=8)
            if report['accepted']:
                if hasattr(self,'prefix_cache'):self.prefix_cache.clear()
                updated,new_bank=load_extension(candidate)
                # All generation is serialized by the same lock: no mixed versions mid-answer.
                old_state={k:v.detach().clone() for k,v in bank.state_dict().items()}
                old_version=self.version
                try:
                    bank.load_state_dict(new_bank.state_dict(),strict=True)
                    save_bundle(self.extension_path,updated,{k:v.detach().cpu().contiguous() for k,v in bank.state_dict().items()})
                    self.micro_manifest=updated;self.version=updated['version']
                except BaseException:
                    bank.load_state_dict(old_state,strict=True);self.version=old_version
                    raise
            report['runtime_promoted']=report['accepted'];report['micro_version']=self.version
            report['topic']=body.get('topic')
            report['initiated_by']=body.get('initiated_by','api_request')
            report['data_sources']=body.get('data_sources',[])
            if {'user_requested_chat','chl_chat'} & set(report['data_sources']):
                report['chat_data_fact_verified']=False
            self.last_training=report
            self.activity={'state':'idle'}
            # Cached head is reconstructible; retain metrics/candidate/features, avoid accumulating 0.8 GB per run.
            (directory/'tail.safetensors').unlink(missing_ok=True)
            return report


def handler_for(engine):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,fmt,*args):print('[nram] '+fmt%args,flush=True)
        def json(self,value,status=200):
            data=json.dumps(value,ensure_ascii=False).encode();self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)))
            self.end_headers();self.wfile.write(data)
        def do_GET(self):
            path=urlsplit(self.path).path
            if path in {'/health','/onram/status'}:return self.json(engine.health())
            if path=='/v1/models':return self.json({'object':'list','data':[{'id':engine.name,'object':'model'}]})
            self.json({'error':'not found'},404)
        def do_POST(self):
            streaming=False;events=None
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=4_000_000:return self.json({'error':'request body too large or empty'},400)
                body=json.loads(self.rfile.read(size));path=urlsplit(self.path).path
                if path=='/onram/train':return self.json(engine.train(body))
                if path=='/onram/train-topic':
                    report=engine.micro_controller.train_topic(body.get('topic',''),body.get('messages',[]),body.get('expert'))
                    return self.json(report,200 if report.get('accepted') else 202)
                if path=='/v1/messages/count_tokens':
                    messages,tools=messages_for(path,body)
                    return self.json({'input_tokens':len(engine.tokenizer(engine.render(public_messages(messages,summary_enabled(body)),tools))['input_ids'])})
                if path not in {'/v1/chat/completions','/v1/responses','/v1/messages'}:
                    return self.json({'error':'unsupported endpoint'},404)
                if not body.get('stream'):return self.json(engine.generate(path,body))
                events=engine.stream(path,body)
                first=next(events)
                self.send_response(200);self.send_header('Content-Type','text/event-stream')
                self.send_header('Cache-Control','no-cache');self.send_header('Connection','close');self.end_headers()
                self.close_connection=True;streaming=True
                from itertools import chain
                for event,value in chain([first],events):
                    if value is None:
                        self.wfile.write(b': atenhea keep-alive\n\n');self.wfile.flush();continue
                    if event:self.wfile.write(('event: '+event+'\n').encode())
                    self.wfile.write(('data: '+json.dumps(value,ensure_ascii=False)+'\n\n').encode());self.wfile.flush()
                if path=='/v1/chat/completions':self.wfile.write(b'data: [DONE]\n\n')
            except (BrokenPipeError,ConnectionResetError):return
            except ValueError as exc:
                if not streaming:self.json({'error':str(exc)},400)
                else:self.wfile.write(('event: error\ndata: '+json.dumps({'type':'error','error':str(exc)})+'\n\n').encode())
            except Exception as exc:
                import traceback;traceback.print_exc()
                if not streaming:self.json({'error':str(exc)},500)
                else:self.wfile.write(('event: error\ndata: '+json.dumps({'type':'error','error':str(exc)})+'\n\n').encode())
            finally:
                if events is not None:events.close()
    return Handler


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,required=True)
    parser.add_argument('--port',type=int,default=11436)
    parser.add_argument('--model-name',default='athenea-e2b:latest')
    parser.add_argument('--device',default='auto',choices=['auto','cpu','mps','cuda'])
    parser.add_argument('--ctx-size',type=int,default=0)
    args=parser.parse_args()
    torch.set_num_threads(4)
    engine=NativeEngine(args.bundle,args.model_name,args.device,args.ctx_size)
    ThreadingHTTPServer(('127.0.0.1',args.port),handler_for(engine)).serve_forever()


if __name__=='__main__':main()
