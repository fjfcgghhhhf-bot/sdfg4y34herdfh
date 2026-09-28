"""Ключи провайдеров доступны только серверу. Ответы никогда не исполняются."""
import json
import os
import re
import requests
from ai_rules import SYSTEM_PROMPT

SCHEMA={'type':'object','properties':{'reply_ru':{'type':'string'},
        'close_confidence':{'type':'integer','minimum':0,'maximum':100}},
        'required':['reply_ru','close_confidence'],'additionalProperties':False}

def respond(data):
    provider=data.get('provider','gemini')
    if provider not in ('gemini','groq'): raise ValueError('Провайдер ИИ не разрешён.')
    history=data.get('history')
    if not isinstance(history,list) or not 1<=len(history)<=64: raise ValueError('Неверная история чата.')
    for item in history:
        if not isinstance(item,dict) or set(item)!={'role','content'} or item['role'] not in ('user','assistant'):
            raise ValueError('Неверное сообщение.')
        if not isinstance(item['content'],str) or len(item['content'])>4000: raise ValueError('Сообщение слишком длинное.')
    score=data.get('score')
    if score is not None and (type(score) is not int or not 0<=score<=100): raise ValueError('Неверный градус.')
    context=SYSTEM_PROMPT+(f'\nТекущий градус: {score}%. Оцени последний довод относительно этого значения.' if score is not None else '')
    key=os.environ.get('GEMINI_API_KEY' if provider=='gemini' else 'GROQ_API_KEY','')
    if not key: raise ValueError('Ключ выбранного ИИ не настроен на сервере.')
    if provider=='groq':
        model=os.environ.get('GROQ_MODEL','openai/gpt-oss-20b')
        payload={'model':model,'messages':[{'role':'system','content':context},*history],
                 'response_format':{'type':'json_object'},'max_completion_tokens':1024,'stream':False}
        if model in ('openai/gpt-oss-20b','openai/gpt-oss-120b'): payload['reasoning_effort']='low'
        url='https://api.groq.com/openai/v1/chat/completions'
        headers={'Authorization':'Bearer '+key}
    else:
        model=os.environ.get('GEMINI_MODEL','gemini-2.5-flash')
        if not re.fullmatch('[A-Za-z0-9._-]{2,100}',model): raise ValueError('Неверная модель Gemini на сервере.')
        url=f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent'
        headers={'x-goog-api-key':key}
        payload={'systemInstruction':{'parts':[{'text':context}]},
            'contents':[{'role':'model' if x['role']=='assistant' else 'user','parts':[{'text':x['content']}]} for x in history],
            'generationConfig':{'responseMimeType':'application/json','responseJsonSchema':SCHEMA,'maxOutputTokens':2048}}
    with requests.post(url,headers=headers,json=payload,timeout=(3,15),allow_redirects=False,stream=True) as response:
        if response.status_code!=200: raise ValueError(f'Провайдер ИИ вернул ошибку {response.status_code}. Событие отменено.')
        chunks=[]; total=0
        for chunk in response.iter_content(8192):
            total+=len(chunk)
            if total>131072: raise ValueError('Слишком большой ответ ИИ.')
            chunks.append(chunk)
        result=json.loads(b''.join(chunks))
    if provider=='groq':
        choice=result['choices'][0]
        if choice.get('finish_reason')!='stop': raise ValueError('Незавершённый ответ ИИ.')
        text=choice['message']['content']
    else:
        choice=result['candidates'][0]
        if choice.get('finishReason')!='STOP': raise ValueError('Незавершённый ответ ИИ.')
        text=''.join(p.get('text','') for p in choice['content']['parts'] if not p.get('thought'))
    answer=json.loads(text); score=answer.get('close_confidence'); reply=answer.get('reply_ru')
    if type(score) is not int or not 0<=score<=100 or not isinstance(reply,str) or not 1<=len(reply)<=2000 or not re.search('[А-Яа-яЁё]',reply):
        raise ValueError('Некорректная оценка ИИ. Событие отменено.')
    # Existing client validates this OpenAI-compatible wrapper for either provider.
    return {'choices':[{'finish_reason':'stop','message':{'content':json.dumps(answer,ensure_ascii=False)}}]}
