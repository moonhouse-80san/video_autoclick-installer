"""화면 캡처(mss)와 한글 경로 안전 이미지 입출력."""
from __future__ import annotations

from pathlib import Path

import cv2
import mss
import numpy as np

from . import winapi

Rect = tuple[int, int, int, int]  # left, top, width, height


def imread_unicode(path) -> np.ndarray | None:
    """cv2.imread는 한글 경로에서 실패하므로 fromfile + imdecode 사용."""
    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if data.size == 0:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def imwrite_unicode(path, image: np.ndarray) -> None:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise OSError("이미지 인코딩 실패")
    buf.tofile(str(Path(path)))


def virtual_bounds() -> tuple[int, int, int, int, int, int]:
    """(가상데스크톱 left, top, width, height, 주 모니터 left, top)"""
    with mss.mss() as sct:
        mons = sct.monitors
        v = mons[0]
        p = mons[1] if len(mons) > 1 else mons[0]
        return v["left"], v["top"], v["width"], v["height"], p["left"], p["top"]


class ScreenGrabber:
    """mss 래퍼. 사용하는 스레드 안에서 생성하세요 (Windows에서 스레드별 핸들 사용)."""

    def __init__(self):
        self._sct = mss.mss()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        try:
            self._sct.close()
        except Exception:
            pass

    def grab_region(self, rect: Rect) -> np.ndarray:
        left, top, width, height = rect
        shot = self._sct.grab({"left": int(left), "top": int(top),
                               "width": max(1, int(width)), "height": max(1, int(height))})
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3])  # BGRA -> BGR

    def grab_virtual(self) -> tuple[np.ndarray, tuple[int, int]]:
        """모든 모니터를 합친 화면과 그 좌상단 좌표."""
        mon = self._sct.monitors[0]
        shot = self._sct.grab(mon)
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3]), (mon["left"], mon["top"])


class WindowGrabber:
    """특정 창만 캡처합니다. 다른 창에 가려져 있어도 창 내용 자체를 가져옵니다.

    좌표는 모두 창 클라이언트 영역 기준입니다. 안전을 위해 아래 경우에는 예외를 던져
    감시를 멈춥니다(검은 화면을 '정지'로 오인해 엉뚱한 클릭을 하는 일을 막기 위해).
      - 창이 닫힘 / 최소화됨 / 캡처 실패 / 캡처 결과가 완전히 검은 화면
    """

    def __init__(self, target):
        self.target = target

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self) -> None:
        pass

    def grab_client(self) -> np.ndarray:
        hwnd = self.target.resolve()
        if not hwnd:
            raise RuntimeError("대상 창을 찾을 수 없습니다. (창이 닫혔거나 이름이 바뀌었나요?)")
        if winapi.is_minimized(hwnd):
            raise RuntimeError("대상 창이 최소화되어 있습니다. 최소화하지 말고 다른 창 뒤에 두세요.")
        shot = winapi.print_window(hwnd)
        if shot is None:
            raise RuntimeError("대상 창을 캡처하지 못했습니다.")
        w, h, data, (cx, cy, cw, ch) = shot
        arr = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 4)
        cx, cy = max(cx, 0), max(cy, 0)
        crop = arr[cy:cy + ch, cx:cx + cw, :3]
        if crop.size == 0:
            raise RuntimeError("대상 창의 화면 영역이 비어 있습니다.")
        if not crop.any():
            raise RuntimeError("창 캡처 결과가 검은 화면입니다. 이 창은 가려진 상태 캡처를 지원하지 않을 수 있습니다.")
        return np.ascontiguousarray(crop)

    def grab_region(self, rect: Rect) -> np.ndarray:
        frame = self.grab_client()
        left, top, width, height = (int(v) for v in rect)
        fh, fw = frame.shape[:2]
        x0, y0 = max(left, 0), max(top, 0)
        x1, y1 = min(left + max(width, 1), fw), min(top + max(height, 1), fh)
        if x1 <= x0 or y1 <= y0:
            raise RuntimeError("감시 영역이 창 밖으로 벗어났습니다. 창 크기가 바뀌었다면 영역을 다시 지정하세요.")
        return np.ascontiguousarray(frame[y0:y1, x0:x1])
