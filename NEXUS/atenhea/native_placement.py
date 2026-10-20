"""Keep Gemma's large sparse per-layer lookup on CPU, dense compute on Metal."""
import torch


def place_native(model,device):
    target=torch.device(device)
    lookups=[(name,module) for name,module in model.named_modules()
             if name.endswith('embed_tokens_per_layer') and isinstance(module,torch.nn.Embedding)]
    if target.type!='mps' or not lookups:
        model.to(target)
        return {'mode':'single_device','cpu_lookup_bytes':0}
    saved=[]
    for name,module in lookups:
        parent_name,_,leaf=name.rpartition('.')
        parent=model.get_submodule(parent_name) if parent_name else model
        module.to('cpu')
        saved.append((parent,leaf,module))
        setattr(parent,leaf,None)
    try:model.to(target)
    finally:
        for parent,leaf,module in saved:setattr(parent,leaf,module)
    for _,_,module in saved:
        def cpu_ids(layer,args):return (args[0].to('cpu'),*args[1:])
        def gpu_rows(layer,args,output):return output.to(target)
        module.register_forward_pre_hook(cpu_ids)
        module.register_forward_hook(gpu_rows)
    return {'mode':'cpu_sparse_lookup_mps_compute',
            'cpu_lookup_bytes':sum(p.numel()*p.element_size() for _,_,module in saved for p in module.parameters()),
            'quantized':False}
