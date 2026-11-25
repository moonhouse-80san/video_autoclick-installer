"""화면/Windows 없이 돌아가는 로직 테스트.  실행:  python -m unittest discover -s tests -v"""
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vac.capture import imread_unicode, imwrite_unicode  # noqa: E402
from vac.config import Config, Settings, Step  # noqa: E402
from vac.detector import MotionDetector, TemplateMatcher  # noqa: E402
from vac.engine import Engine, StepPlan  # noqa: E402

H, W = 90, 160
STATIC = np.full((H, W, 3), 80, np.uint8)


def noise(t):
    return np.random.default_rng(int(t * 1000)).integers(0, 255, (H, W, 3), dtype=np.uint8)


class Clock:
    t = 0.0

    def __call__(self):
        return self.t


class FakeGrabber:
    def __init__(self, clock, frame_fn, screen=None, origin=(0, 0)):
        self.clock, self.frame_fn, self.screen, self.origin = clock, frame_fn, screen, origin

    def grab_region(self, rect):
        return self.frame_fn(self.clock.t)

    def grab_virtual(self):
        return self.screen, self.origin


def moving_windows(*windows):
    """windows: (시작, 끝) 구간에서는 움직이는 영상, 그 외에는 정지 화면"""
    return lambda t: noise(t) if any(a <= t < b for a, b in windows) else STATIC


def drive(plans, frame_fn, settings=None, screen=None, origin=(0, 0), idle_fn=lambda: 99.0, limit=100.0):
    settings = settings or Settings(freeze_seconds=5, interval=0.5, idle_wait=0, retry_seconds=0)
    clock, clicks, logs = Clock(), [], []
    eng = Engine((0, 0, W, H), plans, settings, FakeGrabber(clock, frame_fn, screen, origin),
                 lambda x, y: clicks.append((round(clock.t, 1), x, y)), idle_fn,
                 logs.append, lambda s: None, clock)
    result = None
    while result is None and clock.t <= limit:
        result = eng.tick()
        clock.t += settings.interval
    return result, clicks, logs


class MotionTests(unittest.TestCase):
    def test_static_is_not_motion(self):
        d = MotionDetector()
        d.check(STATIC)
        self.assertFalse(d.check(STATIC.copy())[0])

    def test_moving_is_motion(self):
        d = MotionDetector()
        d.check(noise(0))
        self.assertTrue(d.check(noise(1))[0])

    def test_small_blink_is_ignored_but_local_movement_is_caught(self):
        d = MotionDetector()
        d.check(STATIC)
        tiny = STATIC.copy()
        tiny[0:2, 0:2] = 255                      # 시계/커서 정도의 아주 작은 변화
        self.assertFalse(d.check(tiny)[0])
        d.reset()
        d.check(STATIC)
        local = STATIC.copy()
        local[20:50, 40:100] = 255                # 화면 일부가 움직임
        self.assertTrue(d.check(local)[0])


class TemplateTests(unittest.TestCase):
    def test_find_and_miss(self):
        rng = np.random.default_rng(1)
        screen = rng.integers(0, 255, (200, 300, 3), dtype=np.uint8)
        tpl = rng.integers(0, 255, (20, 30, 3), dtype=np.uint8)
        screen[50:70, 100:130] = tpl
        m = TemplateMatcher(0.85).find(screen, tpl)
        self.assertEqual((m.cx, m.cy), (115, 60))
        other = rng.integers(0, 255, (20, 30, 3), dtype=np.uint8)
        self.assertIsNone(TemplateMatcher(0.85).find(screen, other))
        self.assertIsNone(TemplateMatcher(0.85).find(screen, np.full((20, 30, 3), 7, np.uint8)))


class EngineTests(unittest.TestCase):
    def test_sequence_clicks_in_order_and_waits_for_motion(self):
        plans = [StepPlan(0, (100, 100), None), StepPlan(1, (200, 200), None)]
        result, clicks, _ = drive(plans, moving_windows((0, 2), (10, 14)))
        self.assertEqual(result[0], "completed")
        self.assertEqual([(x, y) for _, x, y in clicks], [(100, 100), (200, 200)])
        self.assertGreaterEqual(clicks[1][0], 14 + 5)   # 2번은 화면이 다시 움직인 뒤 다시 멈춰야 클릭

    def test_no_second_click_without_motion(self):
        plans = [StepPlan(0, (1, 1), None), StepPlan(1, (2, 2), None)]
        result, clicks, _ = drive(plans, lambda t: STATIC, limit=60)
        self.assertIsNone(result)
        self.assertEqual(len(clicks), 1)

    def test_image_click_ignores_video_motion_and_origin_offset(self):
        """감시 영역(음수 좌표 모니터 포함) 안에서 이미지를 찾으면 영상 움직임과 무관하게 클릭하고 감시를 계속한다."""
        rng = np.random.default_rng(3)
        tpl = rng.integers(0, 255, (20, 30, 3), dtype=np.uint8)

        plans = [StepPlan(0, None, tpl)]
        settings = Settings(freeze_seconds=5, interval=0.5, idle_wait=0, retry_seconds=0)
        clock, clicks = Clock(), []

        class G(FakeGrabber):
            def grab_region(s, rect):
                # 매 tick마다 배경이 변해도(움직이는 영상) t>=12부터 영역 내부 (50..80, 80..100)에 이미지 등장
                frame = rng.integers(0, 255, (200, 300, 3), dtype=np.uint8)
                if clock.t >= 12:
                    frame[80:100, 50:80] = tpl          # 영역 내 중심 (65, 90)
                return frame

        eng = Engine((-1920, 10, 300, 200), plans, settings, G(clock, lambda t: noise(t)),
                     lambda x, y: clicks.append((clock.t, x, y)), lambda: 99.0,
                     lambda m: None, lambda s: None, clock)
        res = None
        while res is None and clock.t < 40:
            res = eng.tick()
            clock.t += 0.5
        # 이미지 모드는 클릭 후에도 감시를 계속하므로 completed가 되지 않음
        self.assertIsNone(res)
        self.assertGreaterEqual(len(clicks), 1)
        self.assertGreaterEqual(clicks[0][0], 12)
        self.assertLess(clicks[0][0], 13)   # 영상이 계속 움직여도 이미지가 나타나자마자 클릭
        self.assertEqual(clicks[0][1:], (65 - 1920, 90 + 10))   # 영역 시작 좌표(-1920, 10)가 더해진 절대 좌표

    def test_image_step_always_scans_priority_and_stays_watching(self):
        """이미지 단계가 있으면 이미지 우선순위 스캔 모드로 동작하며 클릭 후에도 감시를 유지한다."""
        rng = np.random.default_rng(5)
        base = rng.integers(0, 255, (200, 300, 3), dtype=np.uint8)
        tpl = rng.integers(0, 255, (20, 30, 3), dtype=np.uint8)
        with_tpl = base.copy()
        with_tpl[10:30, 10:40] = tpl  # 중심 (25, 20)
        plans = [StepPlan(0, None, tpl), StepPlan(1, (7, 7), None)]
        settings = Settings(freeze_seconds=5, interval=0.5, idle_wait=0, retry_seconds=0)
        clock, clicks = Clock(), []

        class G(FakeGrabber):
            def grab_region(s, rect):
                return with_tpl if 3 <= clock.t < 4 else base

        eng = Engine((0, 0, 300, 200), plans, settings, G(clock, moving_windows((0, 8))),
                     lambda x, y: clicks.append((clock.t, x, y)), lambda: 99.0,
                     lambda m: None, lambda s: None, clock)
        res = None
        while res is None and clock.t < 20:
            res = eng.tick()
            clock.t += 0.5
        self.assertIsNone(res)
        self.assertEqual([(x, y) for _, x, y in clicks], [(25, 20)])

    def test_waits_while_user_is_active(self):
        plans = [StepPlan(0, (5, 5), None)]
        settings = Settings(freeze_seconds=5, interval=0.5, idle_wait=1.0, retry_seconds=0)
        clock, clicks = Clock(), []
        eng = Engine((0, 0, W, H), plans, settings, FakeGrabber(clock, lambda t: STATIC),
                     lambda x, y: clicks.append(clock.t), lambda: 0.0 if clock.t < 9 else 5.0,
                     lambda m: None, lambda s: None, clock)
        res = None
        while res is None and clock.t < 30:
            res = eng.tick()
            clock.t += 0.5
        self.assertEqual(len(clicks), 1)
        self.assertGreaterEqual(clicks[0], 9)

    def test_stops_after_max_retries(self):
        plans = [StepPlan(0, (1, 1), None), StepPlan(1, (2, 2), None)]
        settings = Settings(freeze_seconds=5, interval=0.5, idle_wait=0, retry_seconds=3)
        result, clicks, _ = drive(plans, lambda t: STATIC, settings, limit=200)
        self.assertEqual(result[0], "error")
        self.assertEqual(len(clicks), Engine.MAX_RETRIES + 1)

    def test_loop_wraps_to_first_step(self):
        plans = [StepPlan(0, (1, 1), None)]
        settings = Settings(freeze_seconds=5, interval=0.5, idle_wait=0, retry_seconds=0, loop=True)
        result, clicks, _ = drive(plans, moving_windows((0, 2), (10, 14)), settings, limit=25)
        self.assertIsNone(result)
        self.assertEqual(len(clicks), 2)

    def test_run_honours_stop_event(self):
        plans = [StepPlan(0, (1, 1), None)]
        settings = Settings(freeze_seconds=5, interval=0.01, idle_wait=0, retry_seconds=0)
        ev = threading.Event()
        eng = Engine((0, 0, W, H), plans, settings, FakeGrabber(Clock(), lambda t: STATIC),
                     lambda x, y: None, lambda: 9.0, lambda m: None, lambda s: None)
        ev.set()
        self.assertEqual(eng.run(ev)[0], "stopped")

    def test_image_skips_missing_and_clicks_next(self):
        """1번 이미지가 없으면 2번을 클릭하고, 클릭 후에도 감시가 계속된다."""
        rng = np.random.default_rng(7)
        base = rng.integers(0, 255, (200, 300, 3), dtype=np.uint8)
        tpl1 = rng.integers(0, 255, (20, 30, 3), dtype=np.uint8)  # never appears
        tpl2 = rng.integers(0, 255, (20, 30, 3), dtype=np.uint8)
        with_tpl2 = base.copy()
        with_tpl2[40:60, 70:100] = tpl2  # center (85, 50)

        plans = [StepPlan(0, None, tpl1), StepPlan(1, None, tpl2)]
        settings = Settings(freeze_seconds=5, interval=0.5, idle_wait=0, retry_seconds=0, loop=True)
        clock, clicks = Clock(), []

        class G(FakeGrabber):
            def grab_region(s, rect):
                return with_tpl2 if clock.t < 1.0 else base

        eng = Engine((0, 0, 300, 200), plans, settings, G(clock, lambda t: STATIC),
                     lambda x, y: clicks.append((round(clock.t, 1), x, y)), lambda: 99.0,
                     lambda m: None, lambda s: None, clock)
        res = None
        while res is None and clock.t < 15:
            res = eng.tick()
            clock.t += 0.5
        self.assertIsNone(res)  # 감시 계속
        self.assertEqual(len(clicks), 1)
        self.assertEqual(clicks[0][1:], (85, 50))  # 2번만 클릭
        self.assertLess(clicks[0][0], 2)  # 1번을 기다리지 않고 바로 2번 클릭


class ConfigTests(unittest.TestCase):
    def test_roundtrip_and_korean_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "한글 폴더"
            folder.mkdir()
            cfg = Config(region=[-1920, 10, 640, 360])
            cfg.steps[1] = Step("step2.png", 300, -20)
            cfg.settings.freeze_seconds = 7
            cfg.save(folder / "config.json")
            back = Config.load(folder / "config.json")
            self.assertEqual(back.region, [-1920, 10, 640, 360])
            self.assertEqual((back.steps[1].image, back.steps[1].click_x, back.steps[1].click_y), ("step2.png", 300, -20))
            self.assertEqual(back.settings.freeze_seconds, 7.0)

            img = np.random.default_rng(0).integers(0, 255, (30, 40, 3), dtype=np.uint8)
            imwrite_unicode(folder / "그림.png", img)
            self.assertTrue(np.array_equal(imread_unicode(folder / "그림.png"), img))

    def test_corrupt_config_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.json"
            p.write_text("{ not json", encoding="utf-8")
            self.assertIsNone(Config.load(p).region)
            p.write_text('{"region":[1,2],"steps":"x","settings":{"freeze_seconds":"abc","loop":true}}', encoding="utf-8")
            cfg = Config.load(p)
            self.assertIsNone(cfg.region)
            self.assertEqual(cfg.settings.freeze_seconds, 5.0)
            self.assertTrue(cfg.settings.loop)


class WindowTargetTests(unittest.TestCase):
    def test_pick_candidate_prefers_exact_title_then_similar(self):
        from vac.target import pick_candidate
        cands = [
            {"hwnd": 1, "title": "메모장", "cls": "Notepad", "exe": "notepad.exe"},
            {"hwnd": 2, "title": "강의 1강 - Google Chrome", "cls": "Chrome_WidgetWin_1", "exe": "chrome.exe"},
            {"hwnd": 3, "title": "뉴스 - Google Chrome", "cls": "Chrome_WidgetWin_1", "exe": "chrome.exe"},
        ]
        self.assertEqual(pick_candidate(cands, "뉴스 - Google Chrome", "Chrome_WidgetWin_1", "chrome.exe"), 3)
        self.assertEqual(pick_candidate(cands, "강의 2강 - Google Chrome", "Chrome_WidgetWin_1", "chrome.exe"), 2)
        self.assertIsNone(pick_candidate(cands, "x", "Other", "chrome.exe"))
        self.assertIsNone(pick_candidate([], "x", "Chrome_WidgetWin_1", "chrome.exe"))

    def test_is_pickable_rejects_desktop_taskbar_and_self(self):
        from vac.target import is_pickable
        self.assertFalse(is_pickable(None, 1))
        self.assertFalse(is_pickable({"cls": "Progman", "pid": 5}, 1))
        self.assertFalse(is_pickable({"cls": "Shell_TrayWnd", "pid": 5}, 1))
        self.assertFalse(is_pickable({"cls": "TkTopLevel", "pid": 1}, 1))
        self.assertTrue(is_pickable({"cls": "Chrome_WidgetWin_1", "pid": 5}, 1))

    def test_coordinate_conversion(self):
        from vac.target import point_to_client, rect_to_client
        client = (100, 50, 800, 600)
        self.assertEqual(rect_to_client((150, 100, 200, 100), client), (50, 50, 200, 100))
        self.assertEqual(rect_to_client((50, 20, 200, 100), client), (0, 0, 150, 70))  # 창 밖은 잘라냄
        self.assertIsNone(rect_to_client((0, 0, 50, 50), client))                       # 완전히 밖
        self.assertEqual(point_to_client((110, 60), client), (10, 10))
        self.assertIsNone(point_to_client((99, 60), client))
        self.assertIsNone(point_to_client((900, 60), client))

    def test_config_roundtrip_with_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.json"
            cfg = Config()
            cfg.target = {"title": "강의", "cls": "Chrome_WidgetWin_1", "exe": "chrome.exe"}
            cfg.region = [10, 20, 300, 200]
            cfg.settings.restore_window = False
            cfg.save(p)
            back = Config.load(p)
            self.assertEqual(back.target, cfg.target)
            self.assertEqual(back.region, [10, 20, 300, 200])
            self.assertFalse(back.settings.restore_window)
            p.write_text('{"target": {"title": 1}}', encoding="utf-8")
            self.assertIsNone(Config.load(p).target)  # cls 없으면 무시


class WindowGrabberTests(unittest.TestCase):
    class T:
        def __init__(self, hwnd=7):
            self.hwnd = hwnd

        def resolve(self):
            return self.hwnd

    def _patch(self, shot, minimized=False):
        from vac import winapi
        self._orig = (winapi.print_window, winapi.is_minimized)
        winapi.print_window = lambda hwnd: shot
        winapi.is_minimized = lambda hwnd: minimized
        self.addCleanup(lambda: (setattr(winapi, "print_window", self._orig[0]),
                                 setattr(winapi, "is_minimized", self._orig[1])))

    @staticmethod
    def _shot(fill=None, w=120, h=100, client=(10, 20, 100, 70)):
        arr = np.zeros((h, w, 4), np.uint8)
        if fill is not None:
            arr[20:90, 10:110, :3] = fill
        return w, h, arr.tobytes(), client

    def test_crops_client_and_region(self):
        from vac.capture import WindowGrabber
        self._patch(self._shot(fill=50))
        g = WindowGrabber(self.T())
        self.assertEqual(g.grab_client().shape, (70, 100, 3))
        self.assertEqual(g.grab_region((5, 5, 40, 30)).shape, (30, 40, 3))
        with self.assertRaises(RuntimeError):
            g.grab_region((500, 500, 40, 30))  # 창 밖

    def test_black_capture_minimized_and_missing_window_raise(self):
        from vac.capture import WindowGrabber
        self._patch(self._shot(fill=None))
        with self.assertRaises(RuntimeError):
            WindowGrabber(self.T()).grab_client()  # 완전 검은 화면 → 정지로 오인 금지
        self._patch(self._shot(fill=50), minimized=True)
        with self.assertRaises(RuntimeError):
            WindowGrabber(self.T()).grab_client()
        self._patch(self._shot(fill=50))
        with self.assertRaises(RuntimeError):
            WindowGrabber(self.T(hwnd=None)).grab_client()
        self._patch(None)
        with self.assertRaises(RuntimeError):
            WindowGrabber(self.T()).grab_client()

    def test_engine_works_with_window_relative_coordinates(self):
        """창 기준 좌표로 감시/클릭해도 엔진은 같은 좌표계를 그대로 클릭 함수에 전달."""
        plans = [StepPlan(0, (30, 40), None)]
        _, clicks, _ = drive(plans, moving_windows((0, 3)))
        self.assertEqual([(x, y) for _, x, y in clicks], [(30, 40)])


if __name__ == "__main__":
    unittest.main()
