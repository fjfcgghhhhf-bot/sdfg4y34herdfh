"""Разрешённые команды и проверка данных — общие для сайта и клиента."""
import re
import unicodedata
import ipaddress
from urllib.parse import urlsplit, urlunsplit

EVENTS = [
    ('swap','Смена кнопок мыши',20,'Мышь'), ('invert','Инверсия мыши',20,'Мышь'),
    ('tp','ТП на базу + блок ввода',6,'Игра'), ('window','Смена окна + блок ввода',5,'Окна'),
    ('video','Видео со звуком',30,'Оверлеи'), ('keyboard','Блок клавиатуры',3,'Ввод'),
    ('mouse','Блок мыши',3,'Ввод'), ('both','Блок клавиатуры и мыши',3,'Ввод'),
    ('kill','Закрыть Dota 2',0,'Игра'), ('buy','Купить 1–10 ТП',0,'Игра'),
    ('reverse','Переворот экрана',30,'Экран'), ('cmd','Консоль по центру',10,'Окна'),
    ('monitor','Выключение монитора',10,'Экран'), ('pong','Пинг-понг · 1 на 1',0,'Мини-игры'),
    ('desktop','Второй рабочий стол',0,'Окна'), ('cubes','Прыгающие красные кубы',40,'Оверлеи'),
    ('chess','Шахматы · 1 на 1',0,'Мини-игры'), ('ai','Убеди ИИ — растущий накал',60,'Мини-игры'),
    ('upgrader','Апгрейдер · шанс на иммунитет',7,'Мини-игры'),
    ('music','Музыка',60,'Медиа'), ('bw','Чёрно-белый экран',60,'Экран'),
]
EVENT_IDS = {e[0] for e in EVENTS}
PROTOCOL_VERSION=4
MIN_PROTOCOL_VERSION=3  # Existing commands still work with V3 clients.
UPGRADER_FILL_SECONDS = 0.6
UPGRADER_HOLD_SECONDS = 2.0
UPGRADER_RESULT_SECONDS = UPGRADER_FILL_SECONDS + UPGRADER_HOLD_SECONDS
PVP_EVENTS={'chess','pong'}
DURATION_LIMITS={e[0]:(1,3600) for e in EVENTS if e[2]}
for _kind in ('keyboard','mouse','both','tp','window','monitor'):
    DURATION_LIMITS[_kind]=(1,60)
DURATION_LIMITS['upgrader']=(3,30)
DURATION_LIMITS['cubes']=(5,3600)
DEFAULT_DURATIONS={e[0]:e[2] for e in EVENTS if e[2]}
ACTIONS = {'event','start','stop','spin','settings','capture_shop','choose_video','preview_video','choose_music','music_volume','open_url'}
DEFAULT_SETTINGS = {'enabled':[e[0] for e in EVENTS if e[0] not in ('kill','buy')],
                    'volume':65, 'tp_key':'T', 'shop_key':'F4', 'shop_xy':'',
                    'demo':False, 'ai_provider':'gemini','durations':DEFAULT_DURATIONS,'music_track':'default',
                    'music_volume':65,'upgrader_chance':50}

def percent(value,label):
    if type(value) is not int or not 0<=value<=100:
        raise ValueError(f'{label}: целое число от 0 до 100%.')
    return value

def website_url(value):
    """Validate on both ends; only web URLs may reach the desktop browser handler."""
    if not isinstance(value,str) or not value or len(value)>2048:
        raise ValueError('Введите ссылку на сайт длиной до 2048 символов.')
    if any(ord(c)<32 or ord(c)==127 for c in value) or '\\' in value:
        raise ValueError('Ссылка содержит недопустимые символы.')
    value=value.strip()
    if re.search(r'%(?:0[0-9a-f]|1[0-9a-f]|7f)',value,re.I):
        raise ValueError('Ссылка содержит управляющие символы.')
    try:
        url=urlsplit(value)
        if url.scheme.lower() not in ('http','https') or not url.hostname:
            raise ValueError()
        if url.username is not None or url.password is not None:
            raise ValueError()
        host=url.hostname.encode('idna').decode('ascii').lower()
        if ':' in host:
            host='['+str(ipaddress.IPv6Address(host))+']'
        elif len(host)>253 or not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',part)
                                      for part in host.rstrip('.').split('.')):
            raise ValueError()
        port=url.port
        if port is not None and not 1<=port<=65535: raise ValueError()
        authority=host+(f':{port}' if port is not None else '')
        result=urlunsplit((url.scheme.lower(),authority,url.path,url.query,url.fragment))
        if len(result)>2048: raise ValueError()
        return result
    except (ValueError,UnicodeError):
        raise ValueError('Нужна ссылка http:// или https:// с корректным адресом сайта, без логина и пароля.') from None

def duration(kind,value):
    if kind not in DURATION_LIMITS: raise ValueError('У этого события нет таймера.')
    low,high=DURATION_LIMITS[kind]
    if type(value) is not int or not low<=value<=high:
        raise ValueError(f'Длительность события: {low}–{high} секунд.')
    return value

def username(value):
    if not isinstance(value,str): raise ValueError('Введите ник.')
    value=unicodedata.normalize('NFKC',value).strip()
    if not re.fullmatch(r'[\w .-]{2,32}',value):
        raise ValueError('Ник: 2–32 буквы, цифры, пробелы, точки, дефисы или подчёркивания.')
    return value

def settings(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULT_SETTINGS):
        raise ValueError('Неизвестные настройки.')
    out={**DEFAULT_SETTINGS,**value}
    if 'music_volume' not in value: out['music_volume']=out['volume']
    if not isinstance(out['enabled'],list) or not out['enabled'] or len(out['enabled'])>len(EVENTS) or any(not isinstance(x,str) or x not in EVENT_IDS for x in out['enabled']):
        raise ValueError(f'Выберите от 1 до {len(EVENTS)} событий.')
    out['enabled']=list(dict.fromkeys(out['enabled']))
    if type(out['volume']) is not int or not 0<=out['volume']<=100: raise ValueError('Громкость: 0–100.')
    out['music_volume']=percent(out['music_volume'],'Громкость музыки')
    out['upgrader_chance']=percent(out['upgrader_chance'],'Шанс апгрейдера')
    if type(out['demo']) is not bool: raise ValueError('Неверный режим демо.')
    if out['ai_provider'] not in ('gemini','groq'): raise ValueError('Неизвестный провайдер ИИ.')
    if not isinstance(out['tp_key'],str) or not re.fullmatch('[A-Za-z0-9]',out['tp_key']): raise ValueError('Клавиша ТП: одна латинская буква или цифра.')
    if not isinstance(out['shop_key'],str) or not re.fullmatch(r'(?:F(?:[1-9]|1[0-2])|[A-Za-z0-9])',out['shop_key']): raise ValueError('Клавиша магазина: F1–F12, буква или цифра.')
    xy=out['shop_xy']
    if not isinstance(xy,str) or (xy and not re.fullmatch(r'-?\d{1,5}\s*,\s*-?\d{1,5}',xy)): raise ValueError('Координаты ТП: x, y.')
    durations=out['durations']
    if not isinstance(durations,dict) or set(durations)-set(DURATION_LIMITS): raise ValueError('Неизвестные длительности.')
    out['durations']={**DEFAULT_DURATIONS,**{k:duration(k,v) for k,v in durations.items()}}
    if not isinstance(out['music_track'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',out['music_track']): raise ValueError('Неверный идентификатор трека.')
    return out

def command(value):
    if not isinstance(value,dict) or set(value)-{'action','event','settings','duration','track','chance','volume','url'}: raise ValueError('Неизвестная команда.')
    action=value.get('action')
    if action not in ACTIONS: raise ValueError('Команда не разрешена.')
    if action=='open_url':
        if set(value)-{'action','url'}: raise ValueError('Команда открытия сайта принимает только ссылку.')
        return {'action':action,'url':website_url(value.get('url'))}
    if 'url' in value: raise ValueError('Ссылка задаётся только для открытия сайта.')
    if action=='music_volume' and set(value)-{'action','volume'}:
        raise ValueError('Команда громкости принимает только процент.')
    if 'chance' in value and not (action=='event' and value.get('event')=='upgrader'):
        raise ValueError('Шанс задаётся только для апгрейдера.')
    if 'volume' in value and not (action=='music_volume' or action=='event' and value.get('event')=='music'):
        raise ValueError('Громкость задаётся только для музыки.')
    out={'action':action}
    if action=='event':
        if not isinstance(value.get('event'),str) or value['event'] not in EVENT_IDS: raise ValueError('Событие не разрешено.')
        out['event']=value['event']
        if 'duration' in value: out['duration']=duration(out['event'],value['duration'])
        if 'chance' in value: out['chance']=percent(value['chance'],'Шанс апгрейдера')
        if 'volume' in value: out['volume']=percent(value['volume'],'Громкость музыки')
        if 'track' in value:
            if out['event']!='music' or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',str(value['track'])): raise ValueError('Неверный трек.')
            out['track']=value['track']
    if action=='settings': out['settings']=settings(value.get('settings'))
    if action=='music_volume': out['volume']=percent(value.get('volume'),'Громкость музыки')
    return out
