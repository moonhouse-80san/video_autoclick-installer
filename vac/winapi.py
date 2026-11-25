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


# ======================================================================
# 창 단위 기능: 창 찾기 / 가려진 창 캡처 / 클릭 순간에만 앞으로 가져와 클릭
# ======================================================================
_GA_ROOT = 2
_SW_MINIMIZE = 6
_SW_RESTORE = 9
_PW_RENDERFULLCONTENT = 0x00000002
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_VK_MENU = 0x12
_KEYEVENTF_KEYUP = 0x0002

if IS_WINDOWS:
    _gdi32 = ctypes.WinDLL("gdi32")
    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    class _BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                    ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                    ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                    ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

    _user32.WindowFromPoint.argtypes = [wintypes.POINT]
    _user32.WindowFromPoint.restype = wintypes.HWND
    _user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetAncestor.restype = wintypes.HWND
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.BringWindowToTop.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    _user32.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, wintypes.DWORD, ctypes.c_size_t]
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.GetDC.restype = wintypes.HDC
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    _user32.PrintWindow.restype = wintypes.BOOL
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    _gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                 ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    _gdi32.GetDIBits.restype = ctypes.c_int
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                     ctypes.POINTER(wintypes.DWORD)]


def top_window_at(x: int, y: int) -> int | None:
    """화면 좌표 (x, y) 위치의 최상위 창 핸들."""
    if not IS_WINDOWS:
        return None
    h = _user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    if not h:
        return None
    return int(_user32.GetAncestor(h, _GA_ROOT) or h)


def is_window(hwnd: int | None) -> bool:
    return bool(IS_WINDOWS and hwnd and _user32.IsWindow(hwnd))


def is_minimized(hwnd: int) -> bool:
    return bool(IS_WINDOWS and _user32.IsIconic(hwnd))


def foreground_window() -> int | None:
    if not IS_WINDOWS:
        return None
    h = _user32.GetForegroundWindow()
    return int(h) if h else None


def window_title(hwnd: int) -> str:
    if not IS_WINDOWS:
        return ""
    n = _user32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    _user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def window_class(hwnd: int) -> str:
    if not IS_WINDOWS:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _process_exe(pid: int) -> str:
    h = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value.replace("/", "\\").split("\\")[-1].lower()
    finally:
        _kernel32.CloseHandle(h)
    return ""


def window_info(hwnd: int) -> dict:
    """{'hwnd', 'title', 'cls', 'exe', 'pid'}"""
    pid = wintypes.DWORD(0)
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return {"hwnd": int(hwnd), "title": window_title(hwnd), "cls": window_class(hwnd),
            "exe": _process_exe(pid.value), "pid": int(pid.value)}


def list_top_windows() -> list[dict]:
    """제목이 있는 보이는 최상위 창 목록 (Z순서: 위 → 아래)."""
    if not IS_WINDOWS:
        return []
    found: list[dict] = []

    def cb(hwnd, _lparam):
        try:
            if _user32.IsWindowVisible(hwnd) and window_title(hwnd):
                found.append(window_info(hwnd))
        except Exception:
            pass
        return True

    _user32.EnumWindows(_WNDENUMPROC(cb), 0)
    return found


def client_rect_screen(hwnd: int) -> tuple[int, int, int, int] | None:
    """창 클라이언트 영역의 (left, top, width, height) - 화면 좌표. 최소화 상태면 None."""
    if not IS_WINDOWS or _user32.IsIconic(hwnd):
        return None
    rc = wintypes.RECT()
    if not _user32.GetClientRect(hwnd, ctypes.byref(rc)):
        return None
    pt = wintypes.POINT(0, 0)
    if not _user32.ClientToScreen(hwnd, ctypes.byref(pt)):
        return None
    w, h = rc.right - rc.left, rc.bottom - rc.top
    return (pt.x, pt.y, w, h) if w > 0 and h > 0 else None


def print_window(hwnd: int):
    """가려져 있어도 창 내용을 그려 옵니다(PrintWindow + PW_RENDERFULLCONTENT).

    반환: (창 너비, 창 높이, BGRA 바이트, (클라이언트 x, y, 너비, 높이: 창 이미지 기준)) 또는 None
    """
    if not IS_WINDOWS:
        return None
    wr = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(wr)):
        return None
    w, h = wr.right - wr.left, wr.bottom - wr.top
    client = client_rect_screen(hwnd)
    if w <= 0 or h <= 0 or client is None:
        return None
    hdc = _user32.GetDC(None)
    mdc = _gdi32.CreateCompatibleDC(hdc)
    bmp = _gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = _gdi32.SelectObject(mdc, bmp)
    try:
        if not _user32.PrintWindow(hwnd, mdc, _PW_RENDERFULLCONTENT):
            return None
        bmi = _BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bmi.biWidth, bmi.biHeight = w, -h  # 위에서 아래로
        bmi.biPlanes, bmi.biBitCount, bmi.biCompression = 1, 32, 0
        buf = (ctypes.c_ubyte * (w * h * 4))()
        if _gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bmi), 0) == 0:
            return None
        return w, h, bytes(buf), (client[0] - wr.left, client[1] - wr.top, client[2], client[3])
    finally:
        _gdi32.SelectObject(mdc, old)
        _gdi32.DeleteObject(bmp)
        _gdi32.DeleteDC(mdc)
        _user32.ReleaseDC(None, hdc)


def activate_window(hwnd: int, timeout: float = 1.0) -> bool:
    """창을 맨 앞(포그라운드)으로. 최소화되어 있으면 복원. 성공 여부 반환."""
    if not IS_WINDOWS or not _user32.IsWindow(hwnd):
        return False
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, _SW_RESTORE)
        time.sleep(0.3)
    if foreground_window() == hwnd:
        return True

    def attempt(use_alt: bool) -> bool:
        cur = _kernel32.GetCurrentThreadId()
        fg = foreground_window()
        tids = set()
        for h in (fg, hwnd):
            if h:
                tids.add(_user32.GetWindowThreadProcessId(h, None))
        attached = [t for t in tids if t and t != cur and _user32.AttachThreadInput(cur, t, True)]
        try:
            if use_alt:  # 포그라운드 잠금 우회용 (일부 앱에서는 메뉴 포커스가 갈 수 있어 2차 시도로만 사용)
                _user32.keybd_event(_VK_MENU, 0, 0, 0)
                _user32.keybd_event(_VK_MENU, 0, _KEYEVENTF_KEYUP, 0)
            _user32.BringWindowToTop(hwnd)
            _user32.SetForegroundWindow(hwnd)
        finally:
            for t in attached:
                _user32.AttachThreadInput(cur, t, False)
        end = time.monotonic() + timeout / 2
        while time.monotonic() < end:
            if foreground_window() == hwnd:
                return True
            time.sleep(0.05)
        return False

    return attempt(False) or attempt(True)


def click_in_window(hwnd: int, rel_x: int, rel_y: int,
                    restore_cursor: bool = True, restore_window: bool = True) -> bool:
    """창 클라이언트 기준 (rel_x, rel_y)를 클릭. 클릭하는 동안만 창을 앞으로 가져오고,
    끝나면 원래 앞에 있던 창으로 되돌립니다. 클릭 위치가 다른 창에 가려져 있으면 클릭하지 않고 False."""
    if not IS_WINDOWS or not _user32.IsWindow(hwnd):
        return False
    prev = foreground_window()
    was_minimized = bool(_user32.IsIconic(hwnd))
    if not activate_window(hwnd):
        return False
    time.sleep(0.15)
    rect = client_rect_screen(hwnd)
    if rect is None:
        return False
    ax, ay = rect[0] + int(rel_x), rect[1] + int(rel_y)
    if top_window_at(ax, ay) != hwnd:
        return False  # 항상 위 창 등이 가리고 있음 → 엉뚱한 곳 클릭 방지
    click(ax, ay, restore_cursor)
    if restore_window:
        time.sleep(0.15)
        if was_minimized:
            _user32.ShowWindow(hwnd, _SW_MINIMIZE)
        elif prev and prev != hwnd and _user32.IsWindow(prev):
            activate_window(prev)
    return True
