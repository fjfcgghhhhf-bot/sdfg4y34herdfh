"""Transient display power request with an independent automatic wake guard."""
import ctypes as C
from ctypes import wintypes as W
import time
import uuid

from screen_rotation import ScreenRotation


class PowerAPI:
    def __init__(self):
        self.user = C.WinDLL('user32', use_last_error=True)
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.user.CreateWindowExW.argtypes = [W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,
                C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p]
        self.user.CreateWindowExW.restype = W.HWND
        self.user.DefWindowProcW.argtypes = [W.HWND,W.UINT,W.WPARAM,W.LPARAM]
        self.user.DefWindowProcW.restype = W.LPARAM
        self.user.SetWindowLongPtrW.argtypes = [W.HWND,C.c_int,C.c_void_p]
        self.user.SetWindowLongPtrW.restype = C.c_void_p
        self.user.CallWindowProcW.argtypes = [C.c_void_p,W.HWND,W.UINT,W.WPARAM,W.LPARAM]
        self.user.CallWindowProcW.restype = W.LPARAM
        self.user.RegisterPowerSettingNotification.argtypes = [W.HANDLE,C.c_void_p,W.DWORD]
        self.user.RegisterPowerSettingNotification.restype = W.HANDLE
        self.user.UnregisterPowerSettingNotification.argtypes = [W.HANDLE]
        self.user.DestroyWindow.argtypes = [W.HWND]
        self.user.PeekMessageW.argtypes = [C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT,W.UINT]
        self.user.TranslateMessage.argtypes = [C.POINTER(W.MSG)]
        self.user.DispatchMessageW.argtypes = [C.POINTER(W.MSG)]
        self.user.DispatchMessageW.restype = W.LPARAM
        self.kernel.SetThreadExecutionState.argtypes = [W.DWORD]
        self.kernel.SetThreadExecutionState.restype = W.DWORD
        self.state = None
        self.seen_off = False
        self.hwnd = self.user.CreateWindowExW(0,'STATIC','DebuffDisplayGuard',0,
                                               0,0,0,0,None,None,None,None)
        if not self.hwnd:
            raise C.WinError(C.get_last_error())
        self.guid_bytes = uuid.UUID('6fe69556-704a-47a0-8f24-c28d936fda47').bytes_le
        self.guid = C.create_string_buffer(self.guid_bytes)
        callback_type = C.WINFUNCTYPE(W.LPARAM,W.HWND,W.UINT,W.WPARAM,W.LPARAM)
        self.callback = callback_type(self._window_proc)
        self.previous = self.user.SetWindowLongPtrW(self.hwnd,-4,C.cast(self.callback,C.c_void_p))
        self.notification = self.user.RegisterPowerSettingNotification(self.hwnd,self.guid,0)
        if not self.previous or not self.notification:
            self.close()
            raise RuntimeError('Не удалось включить наблюдение за питанием дисплея.')

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message == 0x0218 and wparam == 0x8013 and lparam:
            if C.string_at(lparam,16) == self.guid_bytes and C.c_uint.from_address(lparam+16).value >= 4:
                self.state = C.c_uint.from_address(lparam+20).value
                self.seen_off = self.seen_off or self.state == 0
            return 1
        return self.user.CallWindowProcW(self.previous,hwnd,message,wparam,lparam)

    def pump(self):
        message = W.MSG()
        while self.user.PeekMessageW(C.byref(message),None,0,0,1):
            self.user.TranslateMessage(C.byref(message))
            self.user.DispatchMessageW(C.byref(message))

    def close(self):
        if getattr(self,'notification',None):
            self.user.UnregisterPowerSettingNotification(self.notification)
        if self.hwnd:
            if getattr(self,'previous',None):
                self.user.SetWindowLongPtrW(self.hwnd,-4,self.previous)
            self.user.DestroyWindow(self.hwnd)
            self.hwnd = None

    def power(self, on):
        if on:
            # Reset display idle time, without persisting a power policy.
            self.kernel.SetThreadExecutionState(2)
        # Call the default system handler on our own hidden window. Sending to
        # the desktop window can return success without handling the request.
        self.user.DefWindowProcW(self.hwnd,0x0112,0xF170,-1 if on else 2)


def _power_worker(connection, duration):
    api = PowerAPI()
    attempted = False
    def notify(message):
        try:
            connection.send(message)
        except (OSError, EOFError):
            pass
    try:
        if connection.poll():
            return
        attempted = True
        api.pump()  # Consume the initial display-state notification.
        api.power(False)
        deadline = time.monotonic() + duration
        notify(('started', deadline))
        reported = False
        while time.monotonic() < deadline:
            api.pump()
            if api.seen_off and not reported:
                notify(('display_off', None))
                reported = True
            if not reported and time.monotonic() > deadline-duration+2:
                raise RuntimeError('Windows не сообщила об отключении дисплея; эффект отменён.')
            # Parent exit closes the pipe, and wakes the display immediately.
            if connection.poll(min(.05, max(0, deadline-time.monotonic()))):
                break
    except Exception as exc:
        notify(('error', str(exc)))
    finally:
        if attempted:
            try:
                api.power(True)
            except Exception as exc:
                notify(('error', str(exc)))
        api.close()
        notify(('finished', None))
        connection.close()


class MonitorPower(ScreenRotation):
    worker = staticmethod(_power_worker)

    def start(self, duration=10.0):
        super().start(duration)
