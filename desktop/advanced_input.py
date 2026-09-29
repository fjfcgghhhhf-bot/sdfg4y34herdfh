"""Bounded global desktop effects. Hook callbacks never call SendInput.

Game actions explicitly activate Dota; global challenges survive focus changes.
No registry changes or driver installation. F12 always remains available.
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass, field
import os
import queue
import random
import threading
import time
from typing import Any, Callable

import psutil


DURATIONS = {"swap": 20.0, "invert": 20.0, "tp": 6.0, "window": 5.0, "keyboard": 3.0, "mouse": 3.0, "both": 3.0}
GAME_NAME = "dota2.exe"
INPUT_TAG = 0x44524254
WM_COMMAND = 0x8000 + 41
WM_QUIT = 0x0012
BUTTON_DOWN = {0x0201: (1, 0x0008, 0x0010), 0x0204: (2, 0x0002, 0x0004)}
BUTTON_UP = {0x0202: 1, 0x0205: 2}


class MouseInput(C.Structure):
    _fields_ = [("dx", W.LONG), ("dy", W.LONG), ("mouseData", W.DWORD),
                ("dwFlags", W.DWORD), ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class KeyboardInput(C.Structure):
    _fields_ = [("wVk", W.WORD), ("wScan", W.WORD), ("dwFlags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class HardwareInput(C.Structure):
    _fields_ = [("uMsg", W.DWORD), ("wParamL", W.WORD), ("wParamH", W.WORD)]


class InputUnion(C.Union):
    _fields_ = [("mi", MouseInput), ("ki", KeyboardInput), ("hi", HardwareInput)]


class Input(C.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", W.DWORD), ("data", InputUnion)]


class MouseHookData(C.Structure):
    _fields_ = [("pt", W.POINT), ("mouseData", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


class KeyHookData(C.Structure):
    _fields_ = [("vkCode", W.DWORD), ("scanCode", W.DWORD), ("flags", W.DWORD),
                ("time", W.DWORD), ("dwExtraInfo", C.c_size_t)]


@dataclass(frozen=True)
class Target:
    hwnd: int
    pid: int
    created: float
    name: str


@dataclass(frozen=True)
class Lease:
    kind: str
    target: Target
    expires: float
    cancel: threading.Event


@dataclass
class Command:
    action: Callable[..., Any]
    args: tuple[Any, ...]
    done: threading.Event = field(default_factory=threading.Event)
    abandoned: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: BaseException | None = None


class WindowsController:
    """Owns the low-level hooks, their message loop, and a separate watchdog.

    Hook-owned state is changed through a command queue. Every callback checks
    a monotonic deadline, so a delayed GUI timer cannot extend a restriction.
    Mapped mouse downs have a matching injected up on every cleanup path.
    """

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Эта программа требует Windows 10/11.")
        self.user = C.WinDLL("user32", use_last_error=True)
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.dwm = C.WinDLL("dwmapi", use_last_error=True)
        self.dwm.DwmGetWindowAttribute.argtypes = [C.c_void_p, W.DWORD, C.c_void_p, W.DWORD]
        self.dwm.DwmGetWindowAttribute.restype = C.c_long
        self.HookProc = C.WINFUNCTYPE(C.c_ssize_t, C.c_int, C.c_size_t, C.c_ssize_t)
        self.EnumProc = C.WINFUNCTYPE(W.BOOL, C.c_void_p, W.LPARAM)
        self._set_signatures()
        self.panic = threading.Event()
        self._closing = threading.Event()
        self._finished = threading.Event()
        self._ready = threading.Event()
        self._commands: queue.Queue[Command] = queue.Queue()
        self._lease: Lease | None = None
        self.pong_keys = frozenset()
        self._held: dict[int, int] = {}  # Physical button -> injected UP flag.
        self._held_keys: set[int] = set()  # Only our incomplete SendInput pairs.
        self._swallow_up: set[int] = set()
        self._cursor: tuple[int, int] | None = None
        self._thread_id = 0
        self._thread: threading.Thread | None = None
        self._callbacks: list[Any] = []
        self._error: BaseException | None = None
        self._last_identity_check = 0.0
        self._tick_pending = threading.Event()
        self._in_cleanup = False
        self._outbound = queue.Queue()
        self._sender = None
        self._sender_stop = threading.Event()
        self._displayed = None
        self._inversion_pending = None
        self._bounds = (0, 0, 1920, 1080)
        self.last_error = ""
        self.notifications = queue.SimpleQueue()
        self.shop_key = "F4"
        self.shop_position: tuple[int, int] | None = None
        self._sending_since = 0.0

    def _set_signatures(self) -> None:
        signatures = {
            "SetWindowsHookExW": ([C.c_int, self.HookProc, C.c_void_p, W.DWORD], C.c_void_p),
            "CallNextHookEx": ([C.c_void_p, C.c_int, C.c_size_t, C.c_ssize_t], C.c_ssize_t),
            "UnhookWindowsHookEx": ([C.c_void_p], W.BOOL),
            "GetForegroundWindow": ([], C.c_void_p),
            "GetWindowThreadProcessId": ([C.c_void_p, C.POINTER(W.DWORD)], W.DWORD),
            "GetMessageW": ([C.POINTER(W.MSG), C.c_void_p, W.UINT, W.UINT], C.c_int),
            "PeekMessageW": ([C.POINTER(W.MSG), C.c_void_p, W.UINT, W.UINT, W.UINT], W.BOOL),
            "PostThreadMessageW": ([W.DWORD, W.UINT, W.WPARAM, W.LPARAM], W.BOOL),
            "GetAsyncKeyState": ([C.c_int], W.SHORT),
            "GetCursorPos": ([C.POINTER(W.POINT)], W.BOOL),
            "GetSystemMetrics": ([C.c_int], C.c_int),
            "SendInput": ([W.UINT, C.POINTER(Input), C.c_int], W.UINT),
            "EnumWindows": ([self.EnumProc, W.LPARAM], W.BOOL),
            "IsWindowVisible": ([C.c_void_p], W.BOOL),
            "IsWindowEnabled": ([C.c_void_p], W.BOOL),
            "IsIconic": ([C.c_void_p], W.BOOL),
            "GetWindow": ([C.c_void_p, W.UINT], C.c_void_p),
            "GetWindowTextLengthW": ([C.c_void_p], C.c_int),
            "GetWindowTextW": ([C.c_void_p, W.LPWSTR, C.c_int], C.c_int),
            "GetClassNameW": ([C.c_void_p, W.LPWSTR, C.c_int], C.c_int),
            "GetWindowLongW": ([C.c_void_p, C.c_int], W.LONG),
            "SetForegroundWindow": ([C.c_void_p], W.BOOL),
            "ShowWindowAsync": ([C.c_void_p, C.c_int], W.BOOL),
            "GetShellWindow": ([], C.c_void_p),
            "GetDesktopWindow": ([], C.c_void_p),
        }
        for name, (arguments, result) in signatures.items():
            getattr(self.user, name).argtypes = arguments
            getattr(self.user, name).restype = result
        self.kernel.GetModuleHandleW.argtypes = [W.LPCWSTR]
        self.kernel.GetModuleHandleW.restype = C.c_void_p
        self.kernel.GetCurrentThreadId.argtypes = []
        self.kernel.GetCurrentThreadId.restype = W.DWORD

    def _foreground(self) -> tuple[int, int]:
        hwnd = int(self.user.GetForegroundWindow() or 0)
        pid = W.DWORD()
        if hwnd:
            self.user.GetWindowThreadProcessId(hwnd, C.byref(pid))
        return hwnd, int(pid.value)

    def _target(self, hwnd: int | None = None) -> Target | None:
        if hwnd is None:
            hwnd, pid = self._foreground()
        else:
            pid_buffer = W.DWORD()
            self.user.GetWindowThreadProcessId(hwnd, C.byref(pid_buffer))
            pid = int(pid_buffer.value)
        try:
            process = psutil.Process(pid)
            return Target(hwnd, pid, process.create_time(), process.name().casefold())
        except (psutil.Error, ValueError):
            return None

    def _matches(self, target: Target) -> bool:
        return self._foreground() == (target.hwnd, target.pid)

    def game_is_foreground(self) -> bool:
        target = self._target()
        return target is not None and target.name == GAME_NAME

    @property
    def active_kind(self) -> str:
        lease = self._lease
        if lease and not lease.cancel.is_set() and time.monotonic() < lease.expires:
            return lease.kind
        return ""

    def remaining(self) -> float:
        lease = self._lease
        return max(0.0, lease.expires - time.monotonic()) if lease else 0.0

    def start(self) -> None:
        if self._thread:
            return
        self._sender = threading.Thread(target=self._send_loop, daemon=True, name="MouseOutput")
        self._sender.start()
        self._thread = threading.Thread(target=self._hook_loop, daemon=True,
                                        name="DebuffInputHooks")
        self._thread.start()
        if not self._ready.wait(4.0):
            self.close()
            raise RuntimeError("Не удалось запустить обработчик ввода.")
        if self._error:
            self.close()
            raise RuntimeError(f"Обработчик ввода: {self._error}")
        threading.Thread(target=self._watchdog, daemon=True,
                         name="DebuffInputWatchdog").start()

    def _post(self, command: Command) -> None:
        self._commands.put(command)
        if not self.user.PostThreadMessageW(self._thread_id, WM_COMMAND, 0, 0):
            command.abandoned.set()
            raise RuntimeError("Поток ввода недоступен.")

    def _call(self, action: Callable[..., Any], *args: Any) -> Any:
        if self._closing.is_set() or self._finished.is_set() or not self._thread_id:
            raise RuntimeError("Обработчик ввода остановлен.")
        command = Command(action, args)
        self._post(command)
        if not command.done.wait(2.0):
            command.abandoned.set()
            raise RuntimeError("Обработчик ввода не отвечает; эффект отменён.")
        if command.error:
            raise command.error
        return command.result

    def stop_effect(self) -> None:
        if self._finished.is_set() or not self._thread_id:
            return
        try:
            self._call(self._release)
        except RuntimeError:
            # Callbacks also check this cancellation flag, even if a command
            # cannot be delivered to their queue.
            lease = self._lease
            if lease:
                lease.cancel.set()

    def close(self) -> None:
        if self._finished.is_set():
            return
        self.stop_effect()
        self._closing.set()
        if self._thread_id:
            self.user.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(0.7)
        if not self._thread or not self._thread.is_alive():
            self._finished.set()
        self._sender_stop.set()
        if self._sender and self._sender is not threading.current_thread():
            self._sender.join(1.0)

    def _send_mouse(self, flags: int, x: int = 0, y: int = 0) -> bool:
        event = Input()
        event.type = 0
        event.mi = MouseInput(x, y, 0, flags, 0, INPUT_TAG)
        return self._send_inputs(1, C.byref(event)) == 1

    def _send_inputs(self, count: int, events) -> int:
        self._sending_since = time.monotonic()
        try:
            return self.user.SendInput(count, events, C.sizeof(Input))
        finally:
            self._sending_since = 0.0

    def _emit_mouse(self, flags: int, x: int = 0, y: int = 0) -> bool:
        # Never synchronously inject from a low-level hook: Windows may wait
        # for that same hook while SendInput waits for delivery.
        owner = self._lease if flags & (0x0002 | 0x0008) else None
        self._outbound.put((flags, x, y, owner))
        return True

    def _send_loop(self) -> None:
        while not self._sender_stop.is_set() or not self._outbound.empty():
            try:
                flags, x, y, owner = self._outbound.get(timeout=0.002)
                if owner is None or (self._lease is owner and not owner.cancel.is_set()
                                     and time.monotonic() < owner.expires):
                    if not self._send_mouse(flags, x, y):
                        self.last_error = "Windows отклонила ввод мыши; эффект снят."
                        if self._lease:
                            self._lease.cancel.set()
            except queue.Empty:
                pass
            pending, self._inversion_pending = self._inversion_pending, None
            if pending:
                owner, x, y = pending
                if self._lease is owner and not owner.cancel.is_set() and time.monotonic() < owner.expires:
                    if not self._send_mouse(0xC001, x, y):
                        self.last_error = "Windows отклонила перемещение курсора."
                        owner.cancel.set()

    def _release(self) -> None:
        """Idempotent cleanup; retain failed UPs for the next watchdog tick."""
        self._lease = None
        self.pong_keys = frozenset()
        self._cursor = None
        self._inversion_pending = None
        if self._in_cleanup:
            return
        self._in_cleanup = True
        try:
            for physical, up_flag in tuple(self._held.items()):
                self._swallow_up.add(physical)
                if self._emit_mouse(up_flag):
                    self._held.pop(physical, None)
            # Partial key injections are cleaned by the action worker.
        finally:
            self._in_cleanup = False

    def _current(self) -> Lease | None:
        lease = self._lease
        if lease and (time.monotonic() >= lease.expires or lease.cancel.is_set()
                      or self.panic.is_set() or self._closing.is_set()):
            self._release()
            return None
        return lease

    def _release_owned(self, owner: threading.Event) -> None:
        if self._lease and self._lease.cancel is owner:
            self._release()

    def _acquire(self, kind: str, target: Target, cancel: threading.Event,
                 duration: float | None = None) -> None:
        self._release()
        if cancel.is_set() or self.panic.is_set() or self._closing.is_set():
            raise RuntimeError("Эффект отменён.")
        if self._held or self._held_keys:
            raise RuntimeError("Не удалось отпустить ввод; эффект отменён.")
        if kind == "invert":
            self._cursor = self._displayed
        self._lease = Lease(kind, target, time.monotonic() +
                            (DURATIONS[kind] if duration is None else duration), cancel)

    def _release_key(self, keycode: int) -> None:
        event = Input()
        event.type = 1
        event.ki = KeyboardInput(keycode, 0, 0x0002, 0, INPUT_TAG)
        if self._send_inputs(1, C.byref(event)) == 1:
            self._held_keys.discard(keycode)

    def start_pong(self, cancel: threading.Event, duration: float = 30.0) -> None:
        self._call(self._acquire, "pong", Target(0, 0, 0, "desktop"), cancel, duration)

    def lock_for_monitor(self, cancel: threading.Event, duration=10.0) -> None:
        # A bounded lease prevents physical movement from immediately waking
        # the screen. F12 is still handled before every blocking decision.
        self._call(self._acquire, "both", Target(0, 0, 0, "desktop"), cancel, duration+2)

    def _press_tp(self, keycode: int, target: Target, cancel: threading.Event) -> None:
        if cancel.is_set() or self.panic.is_set() or not self._matches(target):
            raise RuntimeError("TP отменён: изменилось активное окно.")
        events = (Input * 2)()
        for event in events:
            event.type = 1
            event.ki = KeyboardInput(keycode, 0, 0, 0, INPUT_TAG)
        events[1].ki.dwFlags = 0x0002
        count = self._send_inputs(2, events)
        if count != 2:
            if count == 1:
                self._held_keys.add(keycode)
                self._release_key(keycode)
            raise RuntimeError("Windows отклонила нажатие TP.")

    def activate(self, kind: str, tp_key: str = "T",
                 cancel: threading.Event | None = None, duration=None) -> str:
        """Worker-thread API. No GUI calls and no blocking duration sleeps."""
        if kind not in DURATIONS and kind not in ("kill", "buy"):
            raise ValueError(f"Неизвестный эффект: {kind}")
        seconds=DURATIONS.get(kind,0) if duration is None else float(duration)
        if kind in DURATIONS and not 0<seconds<=3600:
            raise ValueError('Недопустимая длительность.')
        cancel = cancel or threading.Event()
        if cancel.is_set() or self.panic.is_set():
            raise RuntimeError("Эффект отменён.")
        target = self._target() or Target(0, 0, 0, "desktop")
        if kind == "kill":
            count = 0
            for process in psutil.process_iter(["name"]):
                try:
                    if cancel.is_set() or self.panic.is_set():
                        break
                    if (process.info["name"] or "").casefold() == GAME_NAME:
                        process.kill()
                        count += 1
                except psutil.NoSuchProcess:
                    pass
            return f"Закрыто процессов Dota 2: {count}."
        if kind in ("tp", "buy"):
            target = self._game_window()
            self._focus_window(target, cancel)
        if kind == "buy":
            return self._buy_scrolls(target, cancel)
        if kind == "invert":
            point = W.POINT()
            if not self.user.GetCursorPos(C.byref(point)):
                raise C.WinError(C.get_last_error())
            self._displayed = (int(point.x), int(point.y))
            self._bounds = tuple(self.user.GetSystemMetrics(i) for i in (76, 77, 78, 79))
        if cancel.is_set() or self.panic.is_set():
            raise RuntimeError("Эффект отменён.")
        if kind == "window":
            selected, title = self._choose_window(target)
            self._focus_window(selected, cancel)
            self._call(self._acquire, kind, selected, cancel, seconds)
            return f"Окно: {title[:80]} · блок ввода на {seconds:g} с."
        if kind == "tp":
            key = tp_key.strip().upper()
            if len(key) != 1 or key not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
                raise ValueError("Клавиша TP: одна латинская буква или цифра.")
            if any(self.user.GetAsyncKeyState(vk) & 0x8000 for vk in (0x10, 0x11, 0x12, ord(key))):
                raise RuntimeError("Отпустите Shift/Ctrl/Alt и клавишу TP; эффект пропущен.")
            try:
                self._call(self._release)
                self._press_tp(ord(key), target, cancel)
                if cancel.wait(0.12):
                    raise RuntimeError("TP отменён.")
                self._press_tp(ord(key), target, cancel)
                # The full six-second lease starts after the final TP key up.
                self._call(self._acquire, kind, target, cancel, seconds)
            except Exception:
                self.stop_effect()
                raise
            return f"Т нажата дважды · блок ввода на {seconds:g} с."
        self._call(self._acquire, kind, target, cancel, seconds)
        return {"swap": "Кнопки мыши поменяны", "invert": "Обе оси курсора инвертированы",
                "keyboard": "Клавиатура заблокирована", "mouse": "Мышь заблокирована",
                "both": "Клавиатура и мышь заблокированы"}[kind]+f' на {seconds:g} с.'

    def _tap_key(self, keycode: int) -> None:
        events = (Input * 2)()
        for event in events:
            event.type = 1
            event.ki = KeyboardInput(keycode, 0, 0, 0, INPUT_TAG)
        events[1].ki.dwFlags = 2
        if self._send_inputs(2, events) != 2:
            self._release_key(keycode)
            raise RuntimeError("Windows отклонила нажатие клавиши.")

    def press_windows_once(self, cancel: threading.Event) -> bool:
        """One complete Win down/up pair, called outside the GUI/hook threads."""
        if cancel.is_set() or self.panic.is_set() or self._closing.is_set():
            return False
        self._tap_key(0x5B)
        return True

    def _focus_window(self, target: Target, cancel: threading.Event) -> None:
        """Try normal activation, then a bounded Alt-assisted retry.

        Never attach input queues: an unresponsive foreign window could hang
        our own input thread. Elevation does not remove foreground policies.
        """
        if self.user.IsIconic(target.hwnd):
            self.user.ShowWindowAsync(target.hwnd, 9)
        for attempt in range(3):
            if cancel.is_set() or self.panic.is_set():
                raise RuntimeError("Переключение отменено.")
            if self._matches(target):
                return
            if attempt and not self.user.GetAsyncKeyState(0x12) & 0x8000:
                self._tap_key(0x12)
            self.user.SetForegroundWindow(target.hwnd)
            for _ in range(15):
                if self._matches(target):
                    return
                if cancel.wait(0.01) or self.panic.is_set():
                    raise RuntimeError("Переключение отменено.")
        raise RuntimeError("Windows отклонила смену окна; блокировка не включена.")

    def _game_window(self) -> Target:
        candidates = []
        @self.EnumProc
        def collect(hwnd, _):
            if self.user.IsWindowVisible(hwnd):
                target = self._target(hwnd)
                if target and target.name == GAME_NAME:
                    candidates.append(target)
            return True
        self.user.EnumWindows(collect, 0)
        if not candidates:
            raise RuntimeError("Окно Dota 2 не найдено. Остальные эффекты работают без игры.")
        return candidates[0]

    def _buy_scrolls(self, target: Target, cancel: threading.Event) -> str:
        if self.shop_position is None:
            raise RuntimeError("Сначала укажите координаты TP в открытом магазине.")
        key = self.shop_key.strip().upper()
        if key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 11:
            vk = 0x70 + int(key[1:]) - 1
        elif len(key) == 1 and key in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
            vk = ord(key)
        else:
            raise RuntimeError("Клавиша магазина: F1–F11, латинская буква или цифра.")
        count = random.randint(1, 10)
        x, y = self.shop_position
        left, top, width, height = (self.user.GetSystemMetrics(i) for i in (76, 77, 78, 79))
        if not (left <= x < left + width and top <= y < top + height):
            raise RuntimeError("Координаты магазина находятся за пределами экрана.")
        self.notifications.put((cancel, f"Выпало {count} TP. Мышь заблокирована на время покупки."))
        self._call(self._acquire, "buy", target, cancel, 5.0)
        try:
            self._tap_key(vk)
            if cancel.wait(0.4) or self.panic.is_set() or not self._matches(target):
                raise RuntimeError("Покупка отменена.")
            if not self._send_mouse(0xC001, round((x-left)*65535/(width-1)),
                                    round((y-top)*65535/(height-1))):
                raise RuntimeError("Не удалось навести курсор на TP.")
            for _ in range(count):
                if cancel.is_set() or self.panic.is_set() or not self._matches(target):
                    raise RuntimeError("Покупка прервана: сменилось окно или нажат F12.")
                if self.active_kind != "buy":
                    raise RuntimeError("Покупка остановлена: истёк срок блокировки мыши.")
                if not self._send_mouse(0x0008):
                    raise RuntimeError("Нажатие покупки не выполнено.")
                try:
                    cancel.wait(0.03)
                finally:
                    self._send_mouse(0x0010)
                if cancel.wait(0.15):
                    raise RuntimeError("Покупка отменена.")
        finally:
            self._call(self._release_owned, cancel)
        return f"Отправлено {count} покупок TP. Результат зависит от золота и наличия свитков."

    def _choose_window(self, game: Target) -> tuple[Target, str]:
        windows: list[tuple[Target, str]] = []
        excluded = {game.hwnd, int(self.user.GetShellWindow() or 0),
                    int(self.user.GetDesktopWindow() or 0)}
        shell_classes = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}
        shell_processes = {"shellexperiencehost.exe", "startmenuexperiencehost.exe",
                           "searchhost.exe", "textinputhost.exe"}

        @self.EnumProc
        def collect(hwnd: int, _parameter: int) -> bool:
            try:
                handle = int(hwnd or 0)
                if (handle in excluded or not self.user.IsWindowVisible(handle)
                        or not self.user.IsWindowEnabled(handle)
                        or self.user.GetWindow(handle, 4)  # GW_OWNER
                        or self.user.GetWindowLongW(handle, -20) & 0x00000080):
                    return True
                size = self.user.GetWindowTextLengthW(handle)
                if size < 1:
                    return True
                title = C.create_unicode_buffer(min(size + 1, 512))
                self.user.GetWindowTextW(handle, title, len(title))
                cls = C.create_unicode_buffer(128)
                self.user.GetClassNameW(handle, cls, len(cls))
                if cls.value in shell_classes:
                    return True
                cloaked = W.DWORD()
                if (self.dwm.DwmGetWindowAttribute(handle, 14, C.byref(cloaked),
                                                   C.sizeof(cloaked)) == 0 and cloaked.value):
                    return True
                target = self._target(handle)
                if (target and target.pid != os.getpid() and target.name != GAME_NAME
                        and target.name not in shell_processes):
                    windows.append((target, title.value))
            except (OSError, ValueError):
                pass
            return True

        self.user.EnumWindows(collect, 0)
        if not windows:
            raise RuntimeError("Нет другого открытого окна для переключения.")
        return random.choice(windows)

    def _keyboard_callback(self, code: int, message: int, address: int) -> int:
        try:
            if code >= 0:
                data = C.cast(address, C.POINTER(KeyHookData)).contents
                if data.vkCode == 0x7B and message in (0x0100, 0x0104):
                    self.panic.set()
                    self._release()
                    return 1
                if data.dwExtraInfo == INPUT_TAG:
                    return self.user.CallNextHookEx(None, code, message, address)
                lease = self._current()
                if lease and lease.kind == "pong" and data.vkCode in (0x26, 0x28):
                    if message in (0x0100, 0x0104):
                        self.pong_keys = self.pong_keys | {int(data.vkCode)}
                        return 1
                    if message in (0x0101, 0x0105):
                        self.pong_keys = self.pong_keys - {int(data.vkCode)}
                        # Pass UP to release arrows held before this event.
                if lease and lease.kind in ("tp", "window", "keyboard", "both") and message in (0x0100, 0x0104):
                    return 1
                # Physical UP events always pass to release pre-existing keys.
        except Exception:
            self._release()
        return self.user.CallNextHookEx(None, code, message, address)

    def _mouse_callback(self, code: int, message: int, address: int) -> int:
        try:
            if code >= 0:
                data = C.cast(address, C.POINTER(MouseHookData)).contents
                if data.dwExtraInfo == INPUT_TAG:
                    if message == 0x0200:
                        self._displayed = (int(data.pt.x), int(data.pt.y))
                    return self.user.CallNextHookEx(None, code, message, address)
                lease = self._current()
                physical_up = BUTTON_UP.get(message)
                if physical_up in self._swallow_up:
                    self._swallow_up.discard(physical_up)
                    return 1
                # A new physical DOWN proves any old matching physical UP is
                # no longer pending (for example after a desktop transition).
                if message in BUTTON_DOWN:
                    self._swallow_up.discard(BUTTON_DOWN[message][0])
                if lease and lease.kind in ("tp", "window", "mouse", "both", "buy"):
                    # Releases pass; moves, new clicks and wheels cannot cancel TP.
                    if message not in (0x0202, 0x0205, 0x0208, 0x020C):
                        return 1
                if lease and lease.kind == "swap":
                    down = BUTTON_DOWN.get(message)
                    if down:
                        physical, down_flag, up_flag = down
                        self._held[physical] = up_flag
                        if self._emit_mouse(down_flag):
                            return 1
                        self._held.pop(physical, None)
                        self._release()
                    elif physical_up in self._held:
                        up_flag = self._held[physical_up]
                        if self._emit_mouse(up_flag):
                            self._held.pop(physical_up, None)
                        else:
                            self._release()
                        return 1
                if lease and lease.kind == "invert" and message == 0x0200:
                    self._invert_move(int(data.pt.x), int(data.pt.y))
                    return 1
        except Exception:
            self._release()
        return self.user.CallNextHookEx(None, code, message, address)

    def _invert_move(self, x: int, y: int) -> None:
        if self._cursor is None:
            return
        previous_x, previous_y = self._cursor
        shown_x, shown_y = self._displayed or self._cursor
        left, top, width, height = self._bounds
        if width < 2 or height < 2:
            return
        next_x = min(left + width - 1, max(left, previous_x - (x - shown_x)))
        next_y = min(top + height - 1, max(top, previous_y - (y - shown_y)))
        self._cursor = (next_x, next_y)
        absolute_x = round((next_x - left) * 65535 / (width - 1))
        absolute_y = round((next_y - top) * 65535 / (height - 1))
        self._inversion_pending = (self._lease, absolute_x, absolute_y)

    def _tick(self) -> None:
        self._tick_pending.clear()
        lease = self._current()
        if lease is None and (self._held or self._held_keys):
            self._release()

    def _drain_commands(self) -> None:
        for _ in range(32):
            try:
                command = self._commands.get_nowait()
            except queue.Empty:
                break
            try:
                if not command.abandoned.is_set():
                    command.result = command.action(*command.args)
            except BaseException as exc:
                command.error = exc
            finally:
                command.done.set()

    def _hook_loop(self) -> None:
        handles: list[int] = []
        try:
            self._thread_id = int(self.kernel.GetCurrentThreadId())
            msg = W.MSG()
            self.user.PeekMessageW(C.byref(msg), None, 0, 0, 0)
            module = self.kernel.GetModuleHandleW(None)
            for number, function in ((13, self._keyboard_callback), (14, self._mouse_callback)):
                callback = self.HookProc(function)
                self._callbacks.append(callback)
                handle = self.user.SetWindowsHookExW(number, callback, module, 0)
                if not handle:
                    raise C.WinError(C.get_last_error())
                handles.append(handle)
            self._ready.set()
            while not self._closing.is_set():
                status = self.user.GetMessageW(C.byref(msg), None, 0, 0)
                if status <= 0:
                    break
                if msg.message == WM_COMMAND:
                    self._drain_commands()
        except BaseException as exc:
            self._error = exc
            self.panic.set()
        finally:
            self._release()
            for handle in reversed(handles):
                self.user.UnhookWindowsHookEx(handle)
            self._ready.set()
            self._finished.set()

    def _watchdog(self) -> None:
        panic_since: float | None = None
        while not self._finished.wait(0.01):
            if self._sending_since and time.monotonic() - self._sending_since > 0.8:
                # A stalled OS injection must not leave our hooks restricting
                # physical input. The GUI closes on panic; no more injections.
                self.panic.set()
            # Backup F12 detection also works if Windows has removed a hook.
            if self.user.GetAsyncKeyState(0x7B) & 0x8000:
                self.panic.set()
            if self.panic.is_set():
                panic_since = panic_since or time.monotonic()
                lease = self._lease
                if lease:
                    lease.cancel.set()
                if time.monotonic() - panic_since > 1.0:
                    # Qt's normal timer closes the UI first. If Qt is frozen,
                    # exiting also destroys every video/overlay owned by us.
                    if not self._sending_since:
                        for flag in tuple(self._held.values()):
                            self._send_mouse(flag)
                        for keycode in tuple(self._held_keys):
                            self._release_key(keycode)
                    os._exit(0)
            if not self._tick_pending.is_set() and not self._closing.is_set():
                self._tick_pending.set()
                try:
                    self._post(Command(self._tick, ()))
                except RuntimeError:
                    self._tick_pending.clear()

