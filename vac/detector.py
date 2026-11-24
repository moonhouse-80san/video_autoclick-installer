"""정지(움직임 없음) 감지와 이미지 찾기."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


class MotionDetector:
    """기준 프레임과 비교해 '바뀐 픽셀 비율'로 움직임을 판단.

    기준 프레임은 움직임이 감지될 때만 갱신하므로, 아주 느리게 변하는 장면도
    변화가 누적되면 움직임으로 잡힙니다.
    """

    def __init__(self, ratio_threshold: float = 0.003, pixel_threshold: int = 12, work_width: int = 320):
        self.ratio_threshold = ratio_threshold
        self.pixel_threshold = pixel_threshold
        self.work_width = work_width
        self._ref: np.ndarray | None = None

    def reset(self) -> None:
        self._ref = None

    def _prepare(self, frame: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
        h, w = gray.shape[:2]
        if w > self.work_width:
            scale = self.work_width / w
            gray = cv2.resize(gray, (self.work_width, max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
        return cv2.GaussianBlur(gray, (3, 3), 0)

    def check(self, frame: np.ndarray) -> tuple[bool, float]:
        """(움직임 여부, 바뀐 픽셀 비율 0~1)"""
        cur = self._prepare(frame)
        if self._ref is None or self._ref.shape != cur.shape:
            self._ref = cur
            return False, 0.0
        diff = cv2.absdiff(self._ref, cur)
        ratio = float(np.count_nonzero(diff > self.pixel_threshold)) / diff.size
        if ratio > self.ratio_threshold:
            self._ref = cur
            return True, ratio
        return False, ratio


@dataclass(frozen=True)
class Match:
    cx: int
    cy: int
    score: float


class TemplateMatcher:
    def __init__(self, threshold: float = 0.85):
        self.threshold = threshold

    @staticmethod
    def _gray(img: np.ndarray) -> np.ndarray:
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img

    def find(self, screen: np.ndarray, template: np.ndarray) -> Match | None:
        """screen 안에서 template 중심 좌표(screen 기준)를 찾습니다."""
        sh, sw = screen.shape[:2]
        th, tw = template.shape[:2]
        if th < 1 or tw < 1 or th > sh or tw > sw:
            return None
        g_t = self._gray(template)
        if float(g_t.std()) < 1.0:  # 단색 이미지는 매칭 의미 없음
            return None
        res = cv2.matchTemplate(self._gray(screen), g_t, cv2.TM_CCOEFF_NORMED)
        res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val < self.threshold:
            return None
        return Match(max_loc[0] + tw // 2, max_loc[1] + th // 2, float(max_val))
