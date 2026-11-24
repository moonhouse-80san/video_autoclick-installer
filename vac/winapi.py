"""Windows 전용 기능: DPI 설정, 마우스 클릭, 입력 유휴 시간, 전역 단축키.

다른 OS에서는 아무 일도 하지 않는 대체 동작을 하므로 개발/테스트 때 import 오류가 나지 않습니다.
"""
from __future__ import annotations

import ctypes
import sys
import threading
import time
from typing import Callable

IS_WINDOWS = sys.platform == "win32"

VK_F6, VK_F7, VK_F8, VK_F9 = 0x75, 0x76, 0x77, 0x78

_WM_HOTKEY = 0x0312
_WM_QUIT = 0x0012
_WM_USER = 0x0400
_MOD_NOREPEAT = 0x4000
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


if IS_WINDOWS:
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32")
    _kernel32 = ctypes.WinDLL("kernel32")

    _kernel32.GetTickCount.restype = wintypes.DWORD
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    _user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                    wintypes.DWORD, ctypes.c_size_t]
    _user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                    wintypes.UINT, wintypes.UINT]
    _user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                     wintypes.UINT, wintypes.UINT, wintypes.UINT]
    _user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT,
                                           wintypes.WPARAM, wintypes.LPARAM]


def enable_dpi_awareness() -> None:
    """tkinter 창 생성 전에 호출. 화면 캡처/클릭 좌표/오버레이 좌표를 모두 실제 픽셀로 통일."""
    if not IS_WINDOWS:
        return
    try:
        ctypes.WinDLL("user32").SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2
        return
    except Exception:
        pass
    try:
        ctypes.WinDLL("shcore").SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.WinDLL("user32").SetProcessDPIAware()
    except Exception:
        pass


def get_cursor_pos() -> tuple[int, int]:
    if not IS_WINDOWS:
        return (0, 0)
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def click(x: int, y: int, restore_cursor: bool = True) -> None:
    """(x, y)에서 왼쪽 클릭. restore_cursor면 클릭 후 마우스를 원래 위치로 되돌림."""
    if not IS_WINDOWS:
        return
    old = get_cursor_pos()
    _user32.SetCursorPos(int(x), int(y))
    time.sleep(0.05)
    _user32.mouse_event(_MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    _user32.mouse_event(_MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    if restore_cursor:
        time.sleep(0.05)
        _user32.SetCursorPos(old[0], old[1])


def idle_seconds() -> float:
    """사용자가 마지막으로 마우스/키보드를 만진 뒤 경과한 초."""
    if not IS_WINDOWS:
        return 1e9
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        return 1e9
    return ((_kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0


def beep() -> None:
    if not IS_WINDOWS:
        return
    try:
        import winsound
        winsound.MessageBeep()
    except Exception:
        pass


class HotkeyListener(threading.Thread):
    """RegisterHotKey 기반 전역 단축키. 다른 창을 쓰는 중에도 동작합니다."""

    def __init__(self, bindings: dict[int, Callable[[], None]]):
        super().__init__(daemon=True)
        self._bindings = bindings
        self._order = list(bindings)
        self._tid: int | None = None
        self.failed: list[int] = []
        self.ready = threading.Event()

    def run(self) -> None:
        if not IS_WINDOWS:
            self.ready.set()
            return
        self._tid = _kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        _user32.PeekMessageW(ctypes.byref(msg), None, _WM_USER, _WM_USER, 0)  # 메시지 큐 생성
        registered = []
        for idx, vk in enumerate(self._order, start=1):
            if _user32.RegisterHotKey(None, idx, _MOD_NOREPEAT, vk):
                registered.append(idx)
            else:
                self.failed.append(vk)
        self.ready.set()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == _WM_HOTKEY:
                try:
                    self._bindings[self._order[msg.wParam - 1]]()
                except Exception:
                    pass
        for idx in registered:
            _user32.UnregisterHotKey(None, idx)

    def stop(self) -> None:
        if IS_WINDOWS and self._tid:
            _user32.PostThreadMessageW(self._tid, _WM_QUIT, 0, 0)
