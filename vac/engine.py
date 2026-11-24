"""감시/클릭 상태머신. GUI·Windows API와 분리되어 있어 가짜 입력으로 테스트할 수 있습니다.

흐름:  WAIT_FREEZE(정지 대기) → 클릭 → WAIT_MOTION(다시 움직일 때까지 대기) → 다음 단계 → ...
"""
from __future__ import annotations

import collections
import time
import traceback
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Callable

import numpy as np

from .capture import imread_unicode
from .config import Config
from .detector import MotionDetector, TemplateMatcher

RunResult = tuple[str, str]  # ("completed" | "stopped" | "error", 메시지)


class State(Enum):
    WAIT_FREEZE = auto()
    WAIT_MOTION = auto()


@dataclass
class StepPlan:
    index: int                          # 0부터 시작하는 원래 단계 번호
    click: tuple[int, int] | None       # 지정 좌표 (없으면 이미지 중앙 클릭)
    template: np.ndarray | None         # 있으면 화면에서 찾은 뒤에만 클릭

    @property
    def label(self) -> str:
        return f"{self.index + 1}번"


def build_plans(config: Config, images_dir: Path, log: Callable[[str], None] = lambda m: None) -> list[StepPlan]:
    plans = []
    for i, step in enumerate(config.steps):
        template = None
        if config.settings.use_images and step.image:
            template = imread_unicode(images_dir / step.image)
            if template is None:
                log(f"{i + 1}번 이미지 파일을 읽을 수 없습니다: {step.image}")
        click = (step.click_x, step.click_y) if step.has_click() else None
        if template is None and click is None:
            continue
        plans.append(StepPlan(i, click, template))
    return plans


class Engine:
    RESUME_WINDOW = 3.0   # 이 시간 안에
    RESUME_HITS = 2       # 움직임이 이 횟수 이상 잡히면 '다시 움직임'
    MAX_RETRIES = 3
    MIN_CLICK_GAP = 2.0   # 이미지 단계에서 같은 이미지를 연속 클릭하지 않도록 하는 최소 간격(초)

    def __init__(self, region, plans, settings, grabber, clicker, idle_fn,
                 log: Callable[[str], None], status: Callable[[str], None],
                 clock: Callable[[], float] = time.monotonic):
        self.region = tuple(region)
        self.plans = plans
        self.settings = settings
        self.grabber = grabber
        self.clicker = clicker
        self.idle_fn = idle_fn
        self.log = log
        self.status = status
        self.clock = clock
        self.detector = MotionDetector(ratio_threshold=settings.motion_percent / 100.0)
        self.matcher = TemplateMatcher(settings.threshold)

        self.pos = 0
        self.state = State.WAIT_FREEZE
        self.still_since: float | None = None
        self.click_time = 0.0
        self.hits: collections.deque[float] = collections.deque()
        self.retries = 0
        self._last_note = 0.0
        self.last_click_time = -1e9

    # ---- 한 번의 감시 주기 -------------------------------------------------
    def tick(self) -> RunResult | None:
        now = self.clock()
        frame = self.grabber.grab_region(self.region)
        moved, ratio = self.detector.check(frame)
        if self.state is State.WAIT_FREEZE:
            # 이미지 단계가 하나라도 있으면 항상 우선순위 스캔 먼저 수행
            if any(p.template is not None for p in self.plans):
                return self._image_step(now)
            return self._wait_freeze(now, moved, ratio)
        return self._wait_motion(now, moved)

    def _image_step(self, now: float) -> RunResult | None:
        """이미지 우선순위 스캔 (1 > 2 > 3).
        - 1번 이미지가 있으면 1번만 클릭하고 2·3번은 건너뜀
        - 1번 없고 2번 있으면 2번만 클릭하고 3번은 건너뜀
        - 클릭 후에도 감시는 절대 종료하지 않음 (F8로만 중지)
        """
        if now - self.last_click_time < self.MIN_CLICK_GAP:
            return None

        # 등록된 이미지 단계만 1번 → 2번 → 3번 순으로 검사
        image_plans = [(i, p) for i, p in enumerate(self.plans) if p.template is not None]
        if not image_plans:
            return None

        for i, p in image_plans:
            found = self._find(p.template)
            if found is None:
                continue  # 이 번호 없음 → 다음 우선순위 시도

            # 가장 높은 우선순위 이미지 발견 → 클릭 후 나머지 전부 Pass
            if self.idle_fn() < self.settings.idle_wait:
                self.status(f"{p.label} · 이미지 발견, 사용자 입력 중이라 클릭 보류")
                return None

            target = p.click or (found[0], found[1])
            self.clicker(int(target[0]), int(target[1]))
            self.last_click_time = now
            self.log(f"{p.label} 이미지 발견(일치 {found[2]:.2f}) → ({target[0]}, {target[1]}) 클릭")

            # 클릭 후에도 감시 계속 (완료로 끝내지 않음)
            self.pos = 0
            self.retries = 0
            self._to_wait_freeze(now)
            return None

        # 어떤 이미지도 화면에 없음 → 계속 감시
        labels = "·".join(p.label for _, p in image_plans)
        self.status(f"{labels} · 화면에 이미지가 나타나길 기다리는 중...")
        return None

    def _wait_freeze(self, now: float, moved: bool, ratio: float) -> RunResult | None:
        plan = self.plans[self.pos]
        s = self.settings
        if moved:
            self.still_since = now
            self.status(f"{plan.label} 대기 · 화면이 움직이는 중 (변화 {ratio * 100:.2f}%)")
            return None
        if self.still_since is None:
            self.still_since = now
        elapsed = now - self.still_since
        if elapsed < s.freeze_seconds:
            self.status(f"{plan.label} 대기 · 정지 {elapsed:.1f}/{s.freeze_seconds:g}초")
            return None

        target = plan.click
        if target is None:  # build_plans가 걸러내므로 정상적으로는 오지 않음
            return ("error", f"{plan.label}: 클릭할 좌표나 이미지가 없습니다.")

        if self.idle_fn() < s.idle_wait:
            self.status(f"{plan.label} · 사용자 입력 중이라 클릭 보류")
            return None

        self.clicker(int(target[0]), int(target[1]))
        self.last_click_time = now
        self.log(f"{plan.label} 정지 {elapsed:.1f}초 감지 → ({target[0]}, {target[1]}) 클릭")

        if self.pos == len(self.plans) - 1 and not s.loop:
            self.log("모든 단계를 완료했습니다.")
            return ("completed", "모든 단계를 완료했습니다.")
        self.state = State.WAIT_MOTION
        self.click_time = now
        self.hits.clear()
        return None

    def _wait_motion(self, now: float, moved: bool) -> RunResult | None:
        plan = self.plans[self.pos]
        s = self.settings
        if moved:
            self.hits.append(now)
        while self.hits and now - self.hits[0] > self.RESUME_WINDOW:
            self.hits.popleft()

        if len(self.hits) >= self.RESUME_HITS:
            self.log(f"{plan.label} 클릭 후 화면이 다시 움직임 → 다음 단계")
            self.pos += 1
            if self.pos >= len(self.plans):
                self.pos = 0
                self.log("마지막 단계까지 끝났습니다. 처음(1단계)부터 반복합니다.")
            self.retries = 0
            self._to_wait_freeze(now)
            return None

        waited = now - self.click_time
        if s.retry_seconds > 0 and waited >= s.retry_seconds:
            self.retries += 1
            if self.retries > self.MAX_RETRIES:
                msg = f"{plan.label} 클릭 후에도 화면이 움직이지 않아 중지했습니다."
                self.log(msg)
                return ("error", msg)
            self.log(f"{plan.label} 클릭 후 {s.retry_seconds:g}초간 움직임 없음 → 다시 시도 "
                     f"({self.retries}/{self.MAX_RETRIES})")
            self._to_wait_freeze(now)
            return None

        self.status(f"{plan.label} 클릭 완료 · 화면이 다시 움직이길 기다리는 중 ({waited:.0f}초)")
        return None

    def _to_wait_freeze(self, now: float) -> None:
        self.state = State.WAIT_FREEZE
        self.still_since = now
        self.hits.clear()

    def _find(self, template: np.ndarray) -> tuple[int, int, float] | None:
        """감시 영역 안에서만 이미지를 찾습니다.
        (프로그램 창에 보이는 미리보기 이미지를 오탐하지 않도록)
        """
        frame = self.grabber.grab_region(self.region)
        if frame is None or frame.size == 0:
            return None
        hit = self.matcher.find(frame, template)
        if hit is None:
            return None
        # 영역 상대 좌표 → 화면 절대 좌표
        rx, ry = int(self.region[0]), int(self.region[1])
        return hit.cx + rx, hit.cy + ry, hit.score

    def _note(self, now: float, message: str, every: float = 10.0) -> None:
        if now - self._last_note >= every:
            self._last_note = now
            self.log(message)

    # ---- 스레드에서 실행 ---------------------------------------------------
    def run(self, stop_event) -> RunResult:
        self.log("감시를 시작했습니다.")
        try:
            while not stop_event.is_set():
                result = self.tick()
                if result is not None:
                    return result
                stop_event.wait(self.settings.interval)
        except Exception as exc:
            self.log("감시 오류:\n" + traceback.format_exc())
            return ("error", f"오류로 중단되었습니다: {exc}")
        self.log("감시를 중지했습니다.")
        return ("stopped", "감시 중지됨")
