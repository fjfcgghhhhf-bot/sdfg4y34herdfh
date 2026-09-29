"""Temporary Windows colour transform; separate process restores on GUI exit."""
import ctypes as C
from ctypes import wintypes as W
import time
from screen_rotation import ScreenRotation

Matrix=(C.c_float*5)*5

class ColourAPI:
    def __init__(self):
        self.api=C.WinDLL('Magnification',use_last_error=True)
        for name in ('MagInitialize','MagUninitialize'):
            getattr(self.api,name).argtypes=[]; getattr(self.api,name).restype=W.BOOL
        for name in ('MagGetFullscreenColorEffect','MagSetFullscreenColorEffect'):
            getattr(self.api,name).argtypes=[C.POINTER(Matrix)]
            getattr(self.api,name).restype=W.BOOL
        if not self.api.MagInitialize(): raise RuntimeError('Windows не включила цветовой фильтр.')
    def capture(self):
        value=Matrix()
        if not self.api.MagGetFullscreenColorEffect(C.byref(value)):
            raise RuntimeError('Не удалось сохранить исходные цвета экрана.')
        return value
    def change(self,value):
        if not self.api.MagSetFullscreenColorEffect(C.byref(value)):
            raise RuntimeError('Windows отклонила цветовой фильтр. Проверьте права приложения.')
    def close(self): self.api.MagUninitialize()

def _grayscale_worker(connection,duration):
    api=None; original=None; attempted=False
    def notify(message):
        try: connection.send(message)
        except (OSError,EOFError): pass
    try:
        api=ColourAPI(); original=api.capture()
        if connection.poll(): return
        matrix=Matrix((.3,.3,.3,0,0),(.6,.6,.6,0,0),(.1,.1,.1,0,0),(0,0,0,1,0),(0,0,0,0,1))
        attempted=True; api.change(matrix)
        deadline=time.monotonic()+duration; notify(('started',deadline))
        while time.monotonic()<deadline:
            if connection.poll(min(.05,max(0,deadline-time.monotonic()))): break
    except Exception as error: notify(('error',str(error)))
    finally:
        if api:
            if attempted and original is not None:
                for attempt in range(3):
                    try: api.change(original); break
                    except Exception:
                        if attempt==2: notify(('error','Не удалось вернуть исходные цвета. Завершите сеанс Windows.'))
                        else: time.sleep(.1)
            api.close()
        notify(('finished',None)); connection.close()

class Grayscale(ScreenRotation):
    worker=staticmethod(_grayscale_worker)
