"""Text and tool protocol adapters for Onram's direct NRAM runtime."""
import copy
import json
import time
import uuid


def ident(prefix):return prefix + '_' + uuid.uuid4().hex


def messages_for(path, body, history=None):
    if path == '/v1/responses':
        value = body.get('input', [])
        messages = copy.deepcopy(history or [])
        if body.get('instructions'):
            messages.insert(0, {'role':'system','content':body['instructions']})
        if isinstance(value,str):messages.append({'role':'user','content':value})
        else:
            for item in value:
                kind=item.get('type')
                if kind=='function_call':
                    messages.append({'role':'assistant','content':'','tool_calls':[{'id':item.get('call_id'),
                        'type':'function','function':{'name':item['name'],'arguments':item.get('arguments','{}')}}]})
                elif kind=='custom_tool_call':
                    messages.append({'role':'assistant','content':'','tool_calls':[{'id':item.get('call_id'),
                        'type':'function','function':{'name':item['name'],'arguments':{'input':item.get('input','')}}}]})
                elif kind in {'function_call_output','custom_tool_call_output'}:
                    messages.append({'role':'tool','tool_call_id':item['call_id'],'content':item.get('output','')})
                elif item.get('role'):messages.append(copy.deepcopy(item))
        tools=[]
        def add_tool(tool):
            kind=tool.get('type')
            if kind=='namespace':
                for child in tool.get('tools',[]):add_tool(child)
            elif kind=='custom':
                tools.append({'type':'function','function':{'name':tool['name'],
                    'description':tool.get('description',''),
                    'parameters':{'type':'object','properties':{'input':{'type':'string'}},'required':['input']}},
                    'onram_custom':True})
            elif kind=='function':
                tools.append(tool if 'function' in tool else
                    {'type':'function','function':{k:v for k,v in tool.items() if k!='type'}})
            else:raise ValueError(f'Unsupported native tool type: {kind}')
        for tool in body.get('tools',[]):add_tool(tool)
    else:
        messages=copy.deepcopy(body.get('messages',[]))
        tools=copy.deepcopy(body.get('tools',[]))
        if path.startswith('/v1/messages'):
            system=body.get('system')
            if isinstance(system,list):system='\n'.join(block.get('text','') for block in system)
            if system:messages.insert(0,{'role':'system','content':system})
            tools=[{'type':'function','function':{'name':tool['name'],'description':tool.get('description',''),
                    'parameters':tool.get('input_schema',{})}} for tool in tools]
    normalized=[];names={}
    for message in messages:
        content=message.get('content','')
        if isinstance(content,list):
            text=[];calls=[];results=[]
            for block in content:
                kind=block.get('type')
                if kind in {'text','input_text','output_text'}:text.append(block.get('text',''))
                elif kind=='tool_use':
                    calls.append({'id':block['id'],'type':'function','function':{'name':block['name'],'arguments':block.get('input',{})}})
                elif kind=='tool_result':
                    result=block.get('content','')
                    if isinstance(result,list):result='\n'.join(b.get('text','') for b in result if b.get('type')=='text')
                    results.append({'role':'tool','tool_call_id':block['tool_use_id'],'content':result})
                else:raise ValueError('Direct NRAM runtime currently accepts text and tool blocks only')
            if text or calls:
                normalized.append({'role':message['role'],'content':'\n'.join(text),**({'tool_calls':calls} if calls else {})})
            normalized.extend(results)
        else:normalized.append(message)
    for message in normalized:
        for call in message.get('tool_calls',[]):
            function=call['function'];names[call.get('id')]=function['name']
            if isinstance(function.get('arguments'),str):function['arguments']=json.loads(function['arguments'])
        if message.get('role')=='tool':message['name']=message.get('name') or names.get(message.get('tool_call_id'),'tool')
    return normalized,tools


def response_for(path, message, model, usage, version):
    calls=message.get('tool_calls',[])
    content=message.get('content') or ''
    for call in calls:
        call.setdefault('id',ident('call'))
        if not isinstance(call['function'].get('arguments'),str):
            call['function']['arguments']=json.dumps(call['function'].get('arguments',{}),ensure_ascii=False)
    if path=='/v1/responses':
        output=[]
        if content:output.append({'type':'message','id':ident('msg'),'status':'completed','role':'assistant',
            'content':[{'type':'output_text','text':content,'annotations':[]}]})
        for call in calls:
            if call.get('onram_custom'):
                args=json.loads(call['function']['arguments'])
                output.append({'type':'custom_tool_call','id':ident('ctc'),'status':'completed',
                    'call_id':call['id'],'name':call['function']['name'],'input':args['input']})
            else:output.append({'type':'function_call','id':ident('fc'),'status':'completed',
                'call_id':call['id'],'name':call['function']['name'],'arguments':call['function']['arguments']})
        return {'id':ident('resp'),'object':'response','created_at':int(time.time()),'status':'completed',
            'model':model,'output':output,'output_text':content,'error':None,
            'usage':{'input_tokens':usage['prompt_tokens'],'output_tokens':usage['completion_tokens'],
                     'total_tokens':sum(usage.values())},'onram_micro_version':version}
    if path=='/v1/messages':
        blocks=([{'type':'text','text':content}] if content else [])
        blocks.extend({'type':'tool_use','id':call['id'],'name':call['function']['name'],
                       'input':json.loads(call['function']['arguments'])} for call in calls)
        return {'id':ident('msg'),'type':'message','role':'assistant','content':blocks,'model':model,
            'stop_reason':'tool_use' if calls else 'end_turn','stop_sequence':None,
            'usage':{'input_tokens':usage['prompt_tokens'],'output_tokens':usage['completion_tokens']},
            'onram_micro_version':version}
    return {'id':ident('chatcmpl'),'object':'chat.completion','created':int(time.time()),'model':model,
        'choices':[{'index':0,'message':{'role':'assistant','content':content,**({'tool_calls':calls} if calls else {})},
                    'finish_reason':'tool_calls' if calls else 'stop'}],
        'usage':{**usage,'total_tokens':sum(usage.values())},'onram_micro_version':version}


def stream_events(path,response):
    """Emit complete, valid protocol events after generation and tool parsing."""
    if path=='/v1/messages':
        yield 'message_start',{'type':'message_start','message':{**response,'content':[],
            'stop_reason':None,'usage':{'input_tokens':response['usage']['input_tokens'],'output_tokens':0}}}
        for index,block in enumerate(response['content']):
            empty={**block,**({'text':''} if block['type']=='text' else {'input':{}})}
            yield 'content_block_start',{'type':'content_block_start','index':index,'content_block':empty}
            delta=({'type':'text_delta','text':block['text']} if block['type']=='text' else
                   {'type':'input_json_delta','partial_json':json.dumps(block['input'])})
            yield 'content_block_delta',{'type':'content_block_delta','index':index,'delta':delta}
            yield 'content_block_stop',{'type':'content_block_stop','index':index}
        yield 'message_delta',{'type':'message_delta','delta':{'stop_reason':response['stop_reason'],'stop_sequence':None},
                              'usage':{'output_tokens':response['usage']['output_tokens']}}
        yield 'message_stop',{'type':'message_stop'}
    elif path=='/v1/responses':
        seq=0
        def event(kind,**values):
            nonlocal seq
            result={'type':kind,'sequence_number':seq,**values};seq+=1;return kind,result
        yield event('response.created',response={**response,'status':'in_progress','output':[]})
        yield event('response.in_progress',response={**response,'status':'in_progress','output':[]})
        for index,item in enumerate(response['output']):
            initial={**item,'status':'in_progress'}
            if item['type']=='message':initial['content']=[]
            else:initial['input' if item['type']=='custom_tool_call' else 'arguments']=''
            yield event('response.output_item.added',output_index=index,item=initial)
            if item['type']=='message':
                part=item['content'][0]
                yield event('response.content_part.added',item_id=item['id'],output_index=index,content_index=0,
                            part={**part,'text':''})
                yield event('response.output_text.delta',item_id=item['id'],output_index=index,content_index=0,delta=part['text'])
                yield event('response.output_text.done',item_id=item['id'],output_index=index,content_index=0,text=part['text'])
                yield event('response.content_part.done',item_id=item['id'],output_index=index,content_index=0,part=part)
            else:
                custom=item['type']=='custom_tool_call'
                field='input' if custom else 'arguments'
                stem='response.custom_tool_call_input' if custom else 'response.function_call_arguments'
                yield event(stem+'.delta',item_id=item['id'],output_index=index,delta=item[field])
                yield event(stem+'.done',item_id=item['id'],output_index=index,**{field:item[field]})
            yield event('response.output_item.done',output_index=index,item=item)
        yield event('response.completed' if response['status']=='completed' else 'response.incomplete',response=response)
    else:
        choice=copy.deepcopy(response['choices'][0])
        for index, call in enumerate(choice['message'].get('tool_calls',[])):call['index']=index
        yield None,{'id':response['id'],'object':'chat.completion.chunk','model':response['model'],
            'created':response['created'],'choices':[{'index':0,'delta':choice['message'],'finish_reason':None}]}
        yield None,{'id':response['id'],'object':'chat.completion.chunk','model':response['model'],
            'created':response['created'],'choices':[{'index':0,'delta':{},'finish_reason':choice['finish_reason']}]}


class LiveStream:
    """Incremental visible text; parsed tool calls are committed at completion."""
    def __init__(self,path,model,version,prompt_tokens):
        self.path=path;self.text='';self.opened=False;self.seq=0
        self.response=response_for(path,{'content':''},model,
            {'prompt_tokens':prompt_tokens,'completion_tokens':0},version)
        self.item_id=ident('msg')

    def event(self,kind,**values):
        value={'type':kind,**values}
        if self.path=='/v1/responses':
            value['sequence_number']=self.seq;self.seq+=1
        return kind,value

    def start(self):
        events=list(stream_events(self.path,self.response))
        if self.path=='/v1/responses':
            for kind,value in events[:2]:
                value.pop('sequence_number',None);value.pop('type',None)
                yield self.event(kind,**value)
        elif self.path=='/v1/messages':yield events[0]
        else:
            value=events[0][1];value['choices'][0]['delta']={'role':'assistant'}
            yield None,value

    def delta(self,text):
        if not text:return
        path=self.path
        if not self.opened:
            self.opened=True
            if path=='/v1/messages':
                yield self.event('content_block_start',index=0,content_block={'type':'text','text':''})
            elif path=='/v1/responses':
                yield self.event('response.output_item.added',output_index=0,item={
                    'id':self.item_id,'type':'message','role':'assistant','status':'in_progress','content':[]})
                yield self.event('response.content_part.added',item_id=self.item_id,output_index=0,
                    content_index=0,part={'type':'output_text','text':'','annotations':[]})
        self.text+=text
        if path=='/v1/messages':yield self.event('content_block_delta',index=0,delta={'type':'text_delta','text':text})
        elif path=='/v1/responses':
            yield self.event('response.output_text.delta',item_id=self.item_id,output_index=0,content_index=0,delta=text)
        else:
            value=dict(self.response);value['object']='chat.completion.chunk'
            value.pop('usage',None)
            value['choices']=[{'index':0,'delta':{'content':text},'finish_reason':None}]
            yield None,value

    def finish(self,response):
        response['id']=self.response['id']
        if self.path=='/v1/responses' and self.opened:
            response['output'][0]['id']=self.item_id
        for kind,value in stream_events(self.path,response):
            if self.path=='/v1/messages':
                if kind=='message_start':continue
                if self.opened and value.get('index')==0:
                    if kind!='content_block_stop':continue
            elif self.path=='/v1/responses':
                if kind in {'response.created','response.in_progress'}:continue
                if self.opened and value.get('output_index')==0 and kind in {
                    'response.output_item.added','response.content_part.added','response.output_text.delta'}:continue
                value.pop('sequence_number',None);value.pop('type',None)
                yield self.event(kind,**value);continue
            else:
                choice=value['choices'][0]
                if choice['finish_reason'] is None:
                    calls=choice['delta'].get('tool_calls')
                    if not calls:continue
                    choice['delta']={'tool_calls':calls}
            yield kind,value
