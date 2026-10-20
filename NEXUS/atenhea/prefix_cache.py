"""One bounded, immutable exact-prefix KV snapshot; no sliding-cache rollback."""
import copy
import torch

class PrefixCache:
    def __init__(self,max_tokens=2048,max_bytes=32*1024**2):
        self.max_tokens=max_tokens;self.max_bytes=max_bytes
        self.snapshot=None;self.ids=();self.version=None
        self.hits=0;self.misses=0;self.bytes=0

    def clear(self):
        self.snapshot=None;self.ids=();self.version=None;self.bytes=0

    def status(self):
        return {'tokens':len(self.ids),'bytes':self.bytes,'max_tokens':self.max_tokens,
                'max_bytes':self.max_bytes,'hits':self.hits,'misses':self.misses}

    def prepare(self,model,encoded,prefix_length,version):
        ids=tuple(encoded['input_ids'][0].detach().cpu().tolist())
        count=min(prefix_length,self.max_tokens,len(ids)-1)
        if self.snapshot is not None and self.version==version and tuple(ids[:len(self.ids)])==self.ids:
            self.hits+=1
            return copy.deepcopy(self.snapshot),{'hit':True,'tokens':len(self.ids)}
        self.clear();self.misses+=1
        if count<64:return None,{'hit':False,'tokens':0}
        args={key:value[:,:count] for key,value in encoded.items() if key in ('input_ids','attention_mask')}
        with torch.inference_mode():
            result=model(**args,use_cache=True,logits_to_keep=1,return_dict=True)
        cache=result.past_key_values
        size=sum(value.numel()*value.element_size() for layer in cache.layers
                 for value in (getattr(layer,'keys',None),getattr(layer,'values',None))
                 if isinstance(value,torch.Tensor))
        if size>self.max_bytes:
            return cache,{'hit':False,'tokens':count,'retained':False}
        # generate mutates its working cache. Never expose the stored snapshot.
        self.snapshot=cache;self.ids=ids[:count];self.version=version;self.bytes=size
        return copy.deepcopy(cache),{'hit':False,'tokens':count,'retained':True}


def stable_prefix_length(messages,tools,render,tokenizer,full_ids):
    """Cache only the exact prefix before the newest user text, not its content."""
    if len(full_ids)<65:return 0
    anchor=copy.deepcopy(messages)
    for message in reversed(anchor):
        if message.get('role')=='user':
            message['content']=''
            break
    else:return 0
    reference=tokenizer(render(anchor,tools),return_tensors='pt',add_special_tokens=False)['input_ids'][0].tolist()
    length=0
    for left,right in zip(full_ids,reference):
        if left!=right:break
        length+=1
    return min(length,len(full_ids)-1)
