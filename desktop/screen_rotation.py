"""Temporary display rotation owned and restored by an independent process."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import multiprocessing as mp
import time


class DevMode(C.Structure):
    _fields_ = [
        ('dmDeviceName', W.WCHAR * 32), ('dmSpecVersion', W.WORD),
        ('dmDriverVersion', W.WORD), ('dmSize', W.WORD), ('dmDriverExtra', W.WORD),
        ('dmFields', W.DWORD), ('dmPosition', W.POINT),
        ('dmDisplayOrientation', W.DWORD), ('dmDisplayFixedOutput', W.DWORD),
        ('dmColor', W.SHORT), ('dmDuplex', W.SHORT), ('dmYResolution', W.SHORT),
        ('dmTTOption', W.SHORT), ('dmCollate', W.SHORT), ('dmFormName', W.WCHAR * 32),
        ('dmLogPixels', W.WORD), ('dmBitsPerPel', W.DWORD), ('dmPelsWidth', W.DWORD),
        ('dmPelsHeight', W.DWORD), ('dmDisplayFlags', W.DWORD),
        ('dmDisplayFrequency', W.DWORD), ('dmICMMethod', W.DWORD),
        ('dmICMIntent', W.DWORD), ('dmMediaType', W.DWORD), ('dmDitherType', W.DWORD),
        ('dmReserved1', W.DWORD), ('dmReserved2', W.DWORD),
        ('dmPanningWidth', W.DWORD), ('dmPanningHeight', W.DWORD),
    ]


class MonitorInfo(C.Structure):
    _fields_ = [('cbSize', W.DWORD), ('rcMonitor', W.RECT), ('rcWork', W.RECT),
                ('dwFlags', W.DWORD), ('szDevice', W.WCHAR * 32)]


class DisplayAPI:
    def __init__(self):
        self.user = C.WinDLL('user32', use_last_error=True)
        self.user.EnumDisplaySettingsW.argtypes = [W.LPCWSTR, W.DWORD, C.POINTER(DevMode)]
        self.user.EnumDisplaySettingsW.restype = W.BOOL
        self.user.ChangeDisplaySettingsExW.argtypes = [W.LPCWSTR, C.POINTER(DevMode),
                                                      C.c_void_p, W.DWORD, C.c_void_p]
        self.user.ChangeDisplaySettingsExW.restype = W.LONG
        self.user.GetCursorPos.argtypes = [C.POINTER(W.POINT)]
        self.user.MonitorFromPoint.argtypes = [W.POINT, W.DWORD]
        self.user.MonitorFromPoint.restype = C.c_void_p
        self.user.GetMonitorInfoW.argtypes = [C.c_void_p, C.POINTER(MonitorInfo)]
        self.user.GetMonitorInfoW.restype = W.BOOL

    def capture(self):
        point = W.POINT()
        if not self.user.GetCursorPos(C.byref(point)):
            raise RuntimeError('Не удалось определить монитор.')
        info = MonitorInfo()
        info.cbSize = C.sizeof(info)
        if not self.user.GetMonitorInfoW(self.user.MonitorFromPoint(point, 2), C.byref(info)):
            raise RuntimeError('Не удалось прочитать имя монитора.')
        mode = DevMode()
        mode.dmSize = C.sizeof(mode)
        if not self.user.EnumDisplaySettingsW(info.szDevice, 0xFFFFFFFF, C.byref(mode)):
            raise RuntimeError('Не удалось сохранить исходную ориентацию экрана.')
        return info.szDevice, mode

    def change(self, device, mode, test=False):
        # flags=0 changes the live mode only, never CDS_UPDATEREGISTRY.
        return self.user.ChangeDisplaySettingsExW(device, C.byref(mode), None,
                                                  2 if test else 0, None)


def _rotation_worker(connection, duration):
    """If the GUI dies, pipe EOF causes restoration here, outside that GUI."""
    api = DisplayAPI()
    device = None
    original = None
    attempted = False
    def notify(message):
        try:
            connection.send(message)
        except (BrokenPipeError, EOFError, OSError):
            pass
    try:
        device, original = api.capture()
        changed = DevMode.from_buffer_copy(bytes(original))
        changed.dmDisplayOrientation = (original.dmDisplayOrientation + 2) % 4
        changed.dmFields |= 0x00000080  # DM_DISPLAYORIENTATION; 180° keeps dimensions.
        result = api.change(device, changed, test=True)
        if result != 0:
            raise RuntimeError(f'Драйвер монитора не поддерживает переворот: код {result}.')
        if connection.poll():
            try:
                connection.recv()
            except EOFError:
                pass
            return
        attempted = True
        result = api.change(device, changed)
        if result != 0:
            raise RuntimeError(f'Windows не перевернула экран: код {result}.')
        deadline = time.monotonic() + duration
        notify(('started', deadline))
        while time.monotonic() < deadline:
            if connection.poll(min(0.05, max(0, deadline-time.monotonic()))):
                try:
                    connection.recv()  # stop or EOF when parent terminates
                except EOFError:
                    pass
                break
    except Exception as exc:
        notify(('error', str(exc)))
    finally:
        if attempted and original is not None:
            result = api.change(device, original)
            for _ in range(2):
                if result == 0:
                    break
                time.sleep(0.15)
                result = api.change(device, original)
            if result != 0:
                notify(('error', f'Не удалось вернуть ориентацию: код {result}. Откройте параметры экрана Windows.'))
        notify(('finished', None))
        connection.close()


class ScreenRotation:
    worker = staticmethod(_rotation_worker)

    def __init__(self):
        self.process = None
        self.connection = None
        self.deadline = None
        self.pending = False
        self.retired = []
        self.duration = 30.0

    def start(self, duration=30.0):
        self.stop()
        self.duration = duration
        if any(process.is_alive() for process in self.retired):
            raise RuntimeError('Предыдущий эффект ещё восстанавливается; повторите позже.')
        context = mp.get_context('spawn')
        parent, child = context.Pipe()
        process = context.Process(target=self.worker, args=(child, duration),
                                  name='DisplayRestoreGuard', daemon=False)
        try:
            process.start()
        except Exception:
            parent.close()
            child.close()
            raise
        child.close()
        self.process, self.connection = process, parent
        self.deadline, self.pending = None, True

    def poll(self):
        messages = []
        if self.connection:
            try:
                while self.connection.poll():
                    kind, value = self.connection.recv()
                    messages.append((kind, value))
                    if kind == 'started':
                        self.deadline = value
                    elif kind == 'finished':
                        self.pending = False
                        self.deadline = None
            except (EOFError, OSError):
                self.connection.close()
                self.connection = None
        if self.process and not self.process.is_alive():
            self.process.join(0)
            if self.pending:
                messages.append(('error', 'Вспомогательный процесс эффекта завершился неожиданно.'))
            self.pending = False
        self.retired = [p for p in self.retired if p.is_alive()]
        return messages

    def remaining(self):
        if self.deadline is not None:
            return max(0, self.deadline-time.monotonic())
        return self.duration if self.pending else 0.0

    def stop(self):
        if self.connection:
            try:
                self.connection.send('stop')
            except (BrokenPipeError, OSError, EOFError):
                pass
            self.connection.close()
            self.connection = None
        if self.process:
            # Never terminate the helper: it must be allowed to restore mode.
            self.process.join(0.8)
            if self.process.is_alive():
                self.retired.append(self.process)
            self.process = None
        self.deadline, self.pending = None, False
