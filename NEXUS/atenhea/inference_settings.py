"""Public explanation preferences, independent of weights and private model fields."""
import argparse
import copy
import json
import os
from pathlib import Path
import tempfile

SETTINGS=Path(__file__).resolve().parent/'models/athenea-inference.json'
SUMMARY_INSTRUCTION=('Para preguntas que requieren explicación, empieza con "Enfoque:" y una sola frase '
    'breve que describa el método o los criterios relevantes, sin deliberaciones internas ni pasos privados. '
    'Después escribe "Respuesta:" y contesta la pregunta. El enfoque es una explicación pública y resumida. '
    'Para saludos, respuestas literales, formatos estrictos como JSON y llamadas de herramientas, '
    'respeta el formato solicitado y omite ese preámbulo.')

def enabled(body=None):
    body=body or {}
    if 'show_reasoning_summary' in body:
        if not isinstance(body['show_reasoning_summary'],bool):raise ValueError('show_reasoning_summary must be boolean')
        return body['show_reasoning_summary']
    reasoning=body.get('reasoning') or {}
    if isinstance(reasoning,dict) and 'summary' in reasoning:
        value=reasoning['summary']
        if value in ('auto','concise','brief','detailed'):return True
        if value in (None,'none'):return False
        raise ValueError('Unsupported reasoning summary preference')
    if not SETTINGS.exists():return False
    data=json.loads(SETTINGS.read_text())
    if not isinstance(data.get('show_reasoning_summary',False),bool):
        raise ValueError('Invalid inference settings: summary must be boolean')
    return data.get('show_reasoning_summary',False)

def public_messages(messages,show):
    result=copy.deepcopy(messages)
    if not show:return result
    if result and result[0].get('role')=='system':
        content=result[0].get('content') or ''
        result[0]['content']=content+'\n\n'+SUMMARY_INSTRUCTION
    else:result.insert(0,{'role':'system','content':SUMMARY_INSTRUCTION})
    return result

def main():
    parser=argparse.ArgumentParser(description='Toggle brief public explanations without reloading weights')
    parser.add_argument('mode',choices=['on','off','status'],nargs='?',default='status')
    args=parser.parse_args()
    if args.mode!='status':
        data=json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
        data['show_reasoning_summary']=args.mode=='on'
        SETTINGS.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w',dir=SETTINGS.parent,delete=False) as f:
            json.dump(data,f,indent=2);f.write('\n');temporary=f.name
        os.replace(temporary,SETTINGS)
    print(json.dumps({'show_reasoning_summary':enabled(),'mode':'brief_public_explanation',
                      'reload_weights':False}))

if __name__=='__main__':main()
