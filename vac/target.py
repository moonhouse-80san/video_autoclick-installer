"""감시 대상 창 식별/재탐색, 화면 좌표 ↔ 창 기준 좌표 변환.

창 핸들(hwnd)은 프로그램을 다시 켜면 바뀌므로 (제목, 클래스, 실행 파일)로 저장해 두고
다시 찾습니다. 순수 로직 위주라 Windows 없이도 테스트할 수 있습니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from . import winapi

Rect = tuple[int, int, int, int]

_IGNORED_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}


def is_pickable(info: dict | None, own_pid: int) -> bool:
    """대상 창으로 쓸 수 있는 창인가 (바탕화면/작업표시줄/이 프로그램 자신 제외)."""
    return bool(info and info.get("cls") and info["cls"] not in _IGNORED_CLASSES
                and info.get("pid") != own_pid)


def pick_candidate(cands: list[dict], title: str, cls: str, exe: str) -> int | None:
    """저장된 정보와 가장 잘 맞는 창의 hwnd. 클래스/실행파일이 같은 창만 후보."""
    pool = [c for c in cands
            if (not cls or c.get("cls") == cls) and (not exe or c.get("exe") == exe)]
    if not pool:
        return None
    for c in pool:
        if c.get("title") == title:
            return c["hwnd"]
    best = max(pool, key=lambda c: SequenceMatcher(None, c.get("title", ""), title).ratio())
    return best["hwnd"]


@dataclass
class WindowTarget:
    title: str = ""
    cls: str = ""
    exe: str = ""
    hwnd: int | None = field(default=None, compare=False)

    def to_dict(self) -> dict:
        return {"title": self.title, "cls": self.cls, "exe": self.exe}

    @classmethod
    def from_dict(cls, d: dict) -> "WindowTarget":
        return cls(title=d.get("title", ""), cls=d.get("cls", ""), exe=d.get("exe", ""))

    @classmethod
    def from_info(cls, info: dict) -> "WindowTarget":
        return cls(info["title"], info["cls"], info["exe"], info["hwnd"])

    def label(self) -> str:
        title = self.title if len(self.title) <= 36 else self.title[:36] + "…"
        return f"{title} [{self.exe or self.cls}]"

    def resolve(self) -> int | None:
        """현재 유효한 hwnd. 기억해 둔 창이 있으면 그대로, 없으면 다시 검색."""
        if self.hwnd and winapi.is_window(self.hwnd) and winapi.window_class(self.hwnd) == self.cls:
            return self.hwnd
        self.hwnd = pick_candidate(winapi.list_top_windows(), self.title, self.cls, self.exe)
        return self.hwnd


def rect_to_client(rect: Rect, client: Rect) -> Rect | None:
    """화면 좌표 사각형 → 클라이언트 기준 사각형(클라이언트 영역과의 교집합). 너무 작으면 None."""
    l, t, w, h = rect
    cl, ct, cw, ch = client
    x0, y0 = max(l - cl, 0), max(t - ct, 0)
    x1, y1 = min(l - cl + w, cw), min(t - ct + h, ch)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    return (x0, y0, x1 - x0, y1 - y0)


def point_to_client(pt: tuple[int, int], client: Rect) -> tuple[int, int] | None:
    """화면 좌표 점 → 클라이언트 기준 점. 영역 밖이면 None."""
    x, y = pt[0] - client[0], pt[1] - client[1]
    if 0 <= x < client[2] and 0 <= y < client[3]:
        return (x, y)
    return None
