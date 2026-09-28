"""Разрешённые команды и проверка данных — общие для сайта и клиента."""
import re
import unicodedata

EVENTS = [
    ('swap','Смена кнопок мыши',20,'Мышь'), ('invert','Инверсия мыши',20,'Мышь'),
    ('tp','ТП на базу + блок ввода',6,'Игра'), ('window','Смена окна + блок ввода',5,'Окна'),
    ('video','Видео со звуком',30,'Оверлеи'), ('keyboard','Блок клавиатуры',3,'Ввод'),
    ('mouse','Блок мыши',3,'Ввод'), ('both','Блок клавиатуры и мыши',3,'Ввод'),
    ('kill','Закрыть Dota 2',0,'Игра'), ('buy','Купить 1–10 ТП',0,'Игра'),
    ('reverse','Переворот экрана',30,'Экран'), ('cmd','Консоль по центру',10,'Окна'),
    ('monitor','Выключение монитора',10,'Экран'), ('pong','Пинг-понг',30,'Мини-игры'),
    ('desktop','Второй рабочий стол',0,'Окна'), ('cubes','Прыгающие красные кубы',40,'Оверлеи'),
    ('chess','Шахматы — 25 ходов',60,'Мини-игры'), ('ai','Убеди ИИ — растущий накал',60,'Мини-игры'),
]
EVENT_IDS = {e[0] for e in EVENTS}
ACTIONS = {'event','start','stop','spin','settings','capture_shop','choose_video','preview_video'}
DEFAULT_SETTINGS = {'enabled':[e[0] for e in EVENTS if e[0] not in ('kill','buy')],
                    'volume':65, 'tp_key':'T', 'shop_key':'F4', 'shop_xy':'',
                    'demo':False, 'ai_provider':'gemini'}

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
    if not isinstance(out['enabled'],list) or not out['enabled'] or len(out['enabled'])>18 or any(x not in EVENT_IDS for x in out['enabled']):
        raise ValueError('Выберите от 1 до 18 событий.')
    out['enabled']=list(dict.fromkeys(out['enabled']))
    if type(out['volume']) is not int or not 0<=out['volume']<=100: raise ValueError('Громкость: 0–100.')
    if type(out['demo']) is not bool: raise ValueError('Неверный режим демо.')
    if out['ai_provider'] not in ('gemini','groq'): raise ValueError('Неизвестный провайдер ИИ.')
    if not isinstance(out['tp_key'],str) or not re.fullmatch('[A-Za-z0-9]',out['tp_key']): raise ValueError('Клавиша ТП: одна латинская буква или цифра.')
    if not isinstance(out['shop_key'],str) or not re.fullmatch(r'(?:F(?:[1-9]|1[0-2])|[A-Za-z0-9])',out['shop_key']): raise ValueError('Клавиша магазина: F1–F12, буква или цифра.')
    xy=out['shop_xy']
    if not isinstance(xy,str) or (xy and not re.fullmatch(r'-?\d{1,5}\s*,\s*-?\d{1,5}',xy)): raise ValueError('Координаты ТП: x, y.')
    return out

def command(value):
    if not isinstance(value,dict) or set(value)-{'action','event','settings'}: raise ValueError('Неизвестная команда.')
    action=value.get('action')
    if action not in ACTIONS: raise ValueError('Команда не разрешена.')
    out={'action':action}
    if action=='event':
        if value.get('event') not in EVENT_IDS: raise ValueError('Событие не разрешено.')
        out['event']=value['event']
    if action=='settings': out['settings']=settings(value.get('settings'))
    return out
