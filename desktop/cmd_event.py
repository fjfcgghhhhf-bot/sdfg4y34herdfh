"""Ten-second classic CMD window, with an isolated process cleanup guard."""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
import multiprocessing as mp
from pathlib import Path
import subprocess
import time
import uuid

from screen_rotation import MonitorInfo


class BasicLimits(C.Structure):
    _fields_ = [('process_time', C.c_longlong), ('job_time', C.c_longlong),
                ('flags', W.DWORD), ('min_working', C.c_size_t), ('max_working', C.c_size_t),
                ('active_limit', W.DWORD), ('affinity', C.c_size_t),
                ('priority', W.DWORD), ('scheduling', W.DWORD)]


class ExtendedLimits(C.Structure):
    _fields_ = [('basic', BasicLimits), ('io', C.c_ulonglong * 6),
                ('process_memory', C.c_size_t), ('job_memory', C.c_size_t),
                ('peak_process_memory', C.c_size_t), ('peak_job_memory', C.c_size_t)]


class StartupInfo(C.Structure):
    _fields_ = [('cb', W.DWORD), ('reserved', W.LPWSTR), ('desktop', W.LPWSTR),
                ('title', W.LPWSTR)] + [(name, W.DWORD) for name in
                ('x', 'y', 'width', 'height', 'columns', 'rows', 'fill', 'flags')] + [
                ('show', W.WORD), ('reserved_size', W.WORD), ('reserved_data', C.c_void_p),
                ('stdin', W.HANDLE), ('stdout', W.HANDLE), ('stderr', W.HANDLE)]


class ProcessInfo(C.Structure):
    _fields_ = [('process', W.HANDLE), ('thread', W.HANDLE),
                ('pid', W.DWORD), ('tid', W.DWORD)]


class ConsoleAPI:
    def __init__(self):
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.user = C.WinDLL('user32', use_last_error=True)
        self.EnumProc = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)
        signatures = {
            'CreateJobObjectW': ([C.c_void_p, W.LPCWSTR], W.HANDLE),
            'SetInformationJobObject': ([W.HANDLE, C.c_int, C.c_void_p, W.DWORD], W.BOOL),
            'AssignProcessToJobObject': ([W.HANDLE, W.HANDLE], W.BOOL),
            'IsProcessInJob': ([W.HANDLE, W.HANDLE, C.POINTER(W.BOOL)], W.BOOL),
            'CreateProcessW': ([W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL,
                               W.DWORD, C.c_void_p, W.LPCWSTR, C.POINTER(StartupInfo),
                               C.POINTER(ProcessInfo)], W.BOOL),
            'ResumeThread': ([W.HANDLE], W.DWORD),
            'TerminateProcess': ([W.HANDLE, W.UINT], W.BOOL),
            'WaitForSingleObject': ([W.HANDLE, W.DWORD], W.DWORD),
            'OpenProcess': ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            'CloseHandle': ([W.HANDLE], W.BOOL),
            'GetSystemDirectoryW': ([W.LPWSTR, W.UINT], W.UINT),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = args, result
        signatures = {
            'EnumWindows': ([self.EnumProc, W.LPARAM], W.BOOL),
            'IsWindow': ([W.HWND], W.BOOL),
            'IsWindowVisible': ([W.HWND], W.BOOL),
            'GetWindowTextW': ([W.HWND, W.LPWSTR, C.c_int], C.c_int),
            'GetWindowThreadProcessId': ([W.HWND, C.POINTER(W.DWORD)], W.DWORD),
            'GetWindowRect': ([W.HWND, C.POINTER(W.RECT)], W.BOOL),
            'SetWindowPos': ([W.HWND, W.HWND, C.c_int, C.c_int, C.c_int, C.c_int, W.UINT], W.BOOL),
            'GetCursorPos': ([C.POINTER(W.POINT)], W.BOOL),
            'MonitorFromPoint': ([W.POINT, W.DWORD], W.HANDLE),
            'GetMonitorInfoW': ([W.HANDLE, C.POINTER(MonitorInfo)], W.BOOL),
            'GetWindowLongW': ([W.HWND, C.c_int], W.LONG),
            'SetWindowLongW': ([W.HWND, C.c_int, W.LONG], W.LONG),
            'GetSystemMenu': ([W.HWND, W.BOOL], W.HMENU),
            'DeleteMenu': ([W.HMENU, W.UINT, W.UINT], W.BOOL),
            'DrawMenuBar': ([W.HWND], W.BOOL),
            'IsIconic': ([W.HWND], W.BOOL),
            'ShowWindowAsync': ([W.HWND, C.c_int], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = args, result
        self.job = None
        self.process = None
        self.title = 'Консоль рулетки - F12 выход - ' + uuid.uuid4().hex[:8]

    def launch(self, directory):
        self.job = self.kernel.CreateJobObjectW(None, None)
        if not self.job:
            raise C.WinError(C.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE; includes this CMD's children.
        if not self.kernel.SetInformationJobObject(self.job, 9, C.byref(limits), C.sizeof(limits)):
            raise C.WinError(C.get_last_error())
        buffer = C.create_unicode_buffer(32768)
        if not self.kernel.GetSystemDirectoryW(buffer, len(buffer)):
            raise C.WinError(C.get_last_error())
        system = Path(buffer.value)
        # Classic conhost avoids opening a shared Windows Terminal tab. The
        # script is constant apart from a generated alphanumeric title.
        script = f'title {self.title} & color 2 & dir /s'
        command = C.create_unicode_buffer(subprocess.list2cmdline([
            str(system / 'conhost.exe'), str(system / 'cmd.exe'), '/d', '/k', script]))
        startup = StartupInfo()
        startup.cb, startup.flags, startup.show = C.sizeof(startup), 1, 1
        process = ProcessInfo()
        if not self.kernel.CreateProcessW(str(system / 'conhost.exe'), command, None, None,
                                          False, 0x00000004 | 0x00000010, None, str(directory),
                                          C.byref(startup), C.byref(process)):
            raise C.WinError(C.get_last_error())
        self.process = process.process
        try:
            # Assign before the first instruction, so no child can escape the
            # cleanup job in the interval between launch and assignment.
            if not self.kernel.AssignProcessToJobObject(self.job, process.process):
                self.kernel.TerminateProcess(process.process, 1)
                raise C.WinError(C.get_last_error())
            if self.kernel.ResumeThread(process.thread) == 0xFFFFFFFF:
                raise C.WinError(C.get_last_error())
        finally:
            self.kernel.CloseHandle(process.thread)

    def find_window(self):
        matches = []
        @self.EnumProc
        def visit(hwnd, _):
            if not self.user.IsWindowVisible(hwnd):
                return True
            title = C.create_unicode_buffer(512)
            self.user.GetWindowTextW(hwnd, title, len(title))
            if self.title not in title.value:
                return True
            pid = W.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, C.byref(pid))
            process = self.kernel.OpenProcess(0x1000, False, pid.value)
            if process:
                try:
                    owned = W.BOOL()
                    if self.kernel.IsProcessInJob(process, self.job, C.byref(owned)) and owned.value:
                        matches.append(int(hwnd))
                finally:
                    self.kernel.CloseHandle(process)
            return True
        self.user.EnumWindows(visit, 0)
        return matches[0] if matches else None

    def centered_rect(self):
        point = W.POINT()
        self.user.GetCursorPos(C.byref(point))
        info = MonitorInfo()
        info.cbSize = C.sizeof(info)
        if not self.user.GetMonitorInfoW(self.user.MonitorFromPoint(point, 2), C.byref(info)):
            raise C.WinError(C.get_last_error())
        area = info.rcWork
        width = min(900, area.right-area.left)
        height = min(520, area.bottom-area.top)
        return (area.left + (area.right-area.left-width)//2,
                area.top + (area.bottom-area.top-height)//2, width, height)

    def pin(self, hwnd, desired, first=False):
        if first:
            style=self.user.GetWindowLongW(hwnd,-16)
            self.user.SetWindowLongW(hwnd,-16,style & ~0x00030000)
            menu=self.user.GetSystemMenu(hwnd,False)
            for item in (0xF060,0xF020,0xF030):  # Close, minimize, maximize.
                self.user.DeleteMenu(menu,item,0)
            self.user.DrawMenuBar(hwnd)
        if self.user.IsIconic(hwnd): self.user.ShowWindowAsync(hwnd,9)
        rect = W.RECT()
        if not self.user.GetWindowRect(hwnd, C.byref(rect)):
            return
        actual = (rect.left, rect.top, rect.right-rect.left, rect.bottom-rect.top)
        if not first:
            # Console hosts round sizes to character cells. Keep their actual
            # size and only correct position, so rounding never causes a loop.
            center_x, center_y = desired[0]+desired[2]//2, desired[1]+desired[3]//2
            desired = (center_x-actual[2]//2, center_y-actual[3]//2, actual[2], actual[3])
        if first or actual != desired:
            # No repeated window updates while already centered. Async avoids
            # waiting on the console's interactive move/resize message loop.
            flags = 0x0010 | 0x4000 | (0x0040 | 0x0020 if first else 0x0004 | 0x0001)
            self.user.SetWindowPos(hwnd, W.HWND(-1) if first else None, *desired, flags)

    def close(self):
        if self.job:
            self.kernel.CloseHandle(self.job)
            self.job = None
        if self.process:
            self.kernel.WaitForSingleObject(self.process, 1000)
            self.kernel.CloseHandle(self.process)
            self.process = None


def _console_worker(connection, directory, duration):
    api = ConsoleAPI()
    def notify(value):
        try:
            connection.send(value)
        except (OSError, EOFError):
            pass
    def cancelled(wait):
        if not connection.poll(wait):
            return False
        try:
            connection.recv()
        except EOFError:
            pass
        return True
    try:
        if cancelled(0):
            return
        desired = api.centered_rect()
        api.launch(directory)
        until = time.monotonic()+5
        hwnd = None
        while time.monotonic() < until:
            if cancelled(.05):
                return
            hwnd = api.find_window()
            if hwnd:
                break
        if not hwnd:
            raise RuntimeError('Окно консоли не появилось за 5 секунд.')
        api.pin(hwnd, desired, first=True)
        notify(('window', hwnd))
        deadline = time.monotonic()+duration
        notify(('started', deadline))
        while time.monotonic() < deadline:
            if cancelled(min(.1, max(0, deadline-time.monotonic()))):
                break
            if not api.user.IsWindow(hwnd):
                # Reopen only our console, without extending the original event.
                api.close()
                if cancelled(0) or time.monotonic() >= deadline:
                    break
                api.launch(directory)
                hwnd = None
                while time.monotonic() < deadline:
                    if cancelled(.05):
                        return
                    hwnd = api.find_window()
                    if hwnd:
                        break
                if not hwnd:
                    break
                api.pin(hwnd, desired, first=True)
                notify(('window', hwnd))
            api.pin(hwnd, desired)
    except Exception as exc:
        notify(('error', str(exc)))
    finally:
        api.close()
        notify(('finished', None))
        connection.close()


class CmdEvent:
    def __init__(self):
        self.process = None
        self.connection = None
        self.deadline = None
        self.pending = False
        self.hwnd = None

    def start(self, directory, duration=10.0):
        self.stop()
        context = mp.get_context('spawn')
        parent, child = context.Pipe()
        process = context.Process(target=_console_worker, args=(child, str(directory), duration),
                                  name='CmdEventGuard', daemon=False)
        try:
            process.start()
        except Exception:
            parent.close()
            child.close()
            raise
        child.close()
        self.process, self.connection = process, parent
        self.pending = True

    def poll(self):
        messages = []
        if self.connection:
            try:
                while self.connection.poll():
                    kind, value = self.connection.recv()
                    messages.append((kind, value))
                    if kind == 'started': self.deadline = value
                    if kind == 'window': self.hwnd = value
                    if kind == 'finished': self.pending = False; self.deadline = None
            except (EOFError, OSError):
                self.connection.close()
                self.connection = None
        if self.process and not self.process.is_alive():
            self.process.join(0)
            if self.pending:
                messages.append(('error', 'Процесс события консоли завершился неожиданно.'))
            self.pending = False
        return messages

    def remaining(self):
        return max(0, self.deadline-time.monotonic()) if self.deadline else (10.0 if self.pending else 0)

    def stop(self):
        if self.connection:
            try: self.connection.send('stop')
            except (OSError, EOFError): pass
            self.connection.close()
            self.connection = None
        if self.process:
            self.process.join(.5)
            if self.process.is_alive():
                # Closing this helper's job handle in the kernel also closes
                # only its own console tree, even when graceful stop failed.
                self.process.terminate()
                self.process.join(.5)
            self.process = None
        self.deadline, self.pending = None, False
        self.hwnd = None
