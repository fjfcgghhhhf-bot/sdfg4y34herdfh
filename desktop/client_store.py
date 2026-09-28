"""Настройки только в собственной папке; токен защищён Windows DPAPI."""
import base64
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

def server_url(value):
    value=value.strip().rstrip('/')
    url=urlsplit(value)
    local=url.hostname in ('localhost','127.0.0.1','::1')
    if url.scheme!='https' and not (url.scheme=='http' and local):
        raise ValueError('Используйте HTTPS; HTTP разрешён только на localhost для проверки.')
    if not url.hostname or url.username or url.password or url.query or url.fragment or url.path:
        raise ValueError('Адрес должен иметь вид https://имя.onrender.com без пути.')
    return value

class Blob(C.Structure):
    _fields_=[('size',W.DWORD),('data',C.POINTER(C.c_ubyte))]

def protect(data,decrypt=False):
    buf=C.create_string_buffer(data); source=Blob(len(data),C.cast(buf,C.POINTER(C.c_ubyte))); target=Blob()
    crypt=C.WinDLL('crypt32',use_last_error=True); kernel=C.WinDLL('kernel32',use_last_error=True)
    function=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes=[C.POINTER(Blob),C.c_void_p,C.c_void_p,C.c_void_p,C.c_void_p,W.DWORD,C.POINTER(Blob)]
    function.restype=W.BOOL
    kernel.LocalFree.argtypes=[C.c_void_p]; kernel.LocalFree.restype=C.c_void_p
    if not function(C.byref(source),None,None,None,None,1,C.byref(target)): raise C.WinError(C.get_last_error())
    try: return C.string_at(target.data,target.size)
    finally: kernel.LocalFree(target.data)

class Store:
    def __init__(self,path=None):
        self.path=Path(path) if path else Path(os.environ['LOCALAPPDATA'])/'DotaDebuffRemote'/'client.json'
    def load(self):
        if not self.path.exists(): return {}
        data=json.loads(self.path.read_text(encoding='utf-8'))
        encrypted=data.pop('protected_token',None)
        if encrypted: data['token']=protect(base64.b64decode(encrypted),True).decode()
        data['server']=server_url(data['server'])
        return data
    def save(self,value):
        data=dict(value); token=data.pop('token',''); data.pop('code',None)
        if token: data['protected_token']=base64.b64encode(protect(token.encode())).decode()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix('.tmp'); tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(tmp,self.path)
