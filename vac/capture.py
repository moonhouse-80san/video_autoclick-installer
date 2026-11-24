"""화면 캡처(mss)와 한글 경로 안전 이미지 입출력."""
from __future__ import annotations

from pathlib import Path

import cv2
import mss
import numpy as np

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
