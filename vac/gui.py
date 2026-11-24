"""메인 화면(tkinter). 감시 스레드와는 queue로만 통신합니다."""
from __future__ import annotations

import base64
import logging
import queue
import threading
import time
import tkinter as tk
import traceback
from functools import partial
from logging.handlers import RotatingFileHandler
from tkinter import filedialog, messagebox, ttk

import cv2

from . import winapi
from .capture import ScreenGrabber, imread_unicode, imwrite_unicode
from .config import STEP_COUNT, Config, data_dir
from .engine import Engine, build_plans
from .overlay import pick_point, select_region

APP_TITLE = "동영상 정지 감지 오토클릭"
FONT = "맑은 고딕"


def make_photo(img, max_w: int, max_h: int) -> tk.PhotoImage:
    h, w = img.shape[:2]
    scale = min(max_w / w, max_h / h, 1.0)
    if scale < 1.0:
        img = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise ValueError("미리보기 인코딩 실패")
    return tk.PhotoImage(data=base64.b64encode(buf.tobytes()).decode("ascii"))


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.dir = data_dir()
        self.images_dir = self.dir / "images"
        self.config_path = self.dir / "config.json"
        self.cfg = Config.load(self.config_path)

        handler = RotatingFileHandler(self.dir / "autoclick.log", maxBytes=500_000, backupCount=1,
                                      encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        self.logger = logging.getLogger("vac")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            self.logger.addHandler(handler)

        self.ui_queue: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self._photos: dict[str, tk.PhotoImage] = {}

        self.status_var = tk.StringVar(value="대기 중")
        self.region_text = tk.StringVar()
        self.run_var_names = ("freeze", "interval", "motion", "idle", "retry", "threshold")
        self.v = {name: tk.StringVar() for name in self.run_var_names}
        self.b_use_images = tk.BooleanVar()
        self.b_loop = tk.BooleanVar()
        self.b_restore = tk.BooleanVar()
        self.b_minimize = tk.BooleanVar()
        self.step_widgets: list[dict] = []

        root.title(APP_TITLE)
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.report_callback_exception = self._on_tk_error
        try:
            style = ttk.Style()
            if "vista" in style.theme_names():
                style.theme_use("vista")
        except tk.TclError:
            pass

        self._build_ui()
        self._load_vars()
        self._refresh_region()
        for i in range(STEP_COUNT):
            self._refresh_step(i)

        self.hotkeys = winapi.HotkeyListener({winapi.VK_F8: lambda: self.ui_queue.put(("toggle",))})
        self.hotkeys.start()
        self.hotkeys.ready.wait(1.0)
        if self.hotkeys.failed:
            self._log("F8 단축키를 등록하지 못했습니다(다른 프로그램이 사용 중). 버튼으로 시작/중지하세요.")
        self.root.after(100, self._poll)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(0, weight=1)
        left = ttk.Frame(outer)
        left.grid(row=0, column=0, sticky="n")
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        self._build_region(left)
        self._build_steps(left)
        self._build_settings(right)
        self._build_controls(right)
        self._build_log(right)

    def _build_region(self, parent):
        box = ttk.LabelFrame(parent, text="① 감시 영역 (동영상 화면)", padding=10)
        box.pack(fill="x")
        self.region_img = ttk.Label(box, text="미리보기 없음", width=18, anchor="center", relief="groove")
        self.region_img.grid(row=0, column=0, rowspan=3, padx=(0, 10))
        ttk.Label(box, textvariable=self.region_text).grid(row=0, column=1, sticky="w")
        ttk.Button(box, text="영역 드래그로 지정", command=self.pick_region).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Button(box, text="미리보기 새로고침", command=self.refresh_region_preview).grid(row=2, column=1, sticky="w")

    def _build_steps(self, parent):
        box = ttk.LabelFrame(parent, text="② 단계별 이미지 · 클릭 좌표 (1 → 2 → 3 순서)", padding=10)
        box.pack(fill="x", pady=(10, 0))
        for i in range(STEP_COUNT):
            row = ttk.Frame(box)
            row.pack(fill="x", pady=5)
            ttk.Label(row, text=f"{i + 1}번", font=(FONT, 11, "bold")).grid(row=0, column=0, rowspan=2, padx=(0, 8))
            img = ttk.Label(row, text="이미지 없음", width=14, anchor="center", relief="groove")
            img.grid(row=0, column=1, rowspan=2, padx=(0, 8))
            bf = ttk.Frame(row)
            bf.grid(row=0, column=2, sticky="w")
            ttk.Button(bf, text="이미지 캡처", command=partial(self.capture_image, i)).pack(side="left")
            ttk.Button(bf, text="파일 선택", command=partial(self.load_image, i)).pack(side="left", padx=4)
            ttk.Button(bf, text="삭제", width=5, command=partial(self.clear_image, i)).pack(side="left")
            cf = ttk.Frame(row)
            cf.grid(row=1, column=2, sticky="w", pady=(4, 0))
            coord_var = tk.StringVar()
            ttk.Label(cf, textvariable=coord_var, width=24).pack(side="left")
            ttk.Button(cf, text="좌표 지정", command=partial(self.pick_click, i)).pack(side="left")
            ttk.Button(cf, text="삭제", width=5, command=partial(self.clear_click, i)).pack(side="left", padx=4)
            self.step_widgets.append({"img": img, "coord": coord_var})

    def _build_settings(self, parent):
        box = ttk.LabelFrame(parent, text="③ 감시 설정", padding=10)
        box.pack(fill="x")
        rows = [
            ("정지 판단 시간(초)", "freeze", "이 시간 동안 변화가 없으면 정지"),
            ("화면 확인 간격(초)", "interval", "0.3~1.0 권장"),
            ("움직임 기준(%)", "motion", "바뀐 화면 비율이 이 값 이상이면 움직임 (낮을수록 민감)"),
            ("사용자 입력 대기(초)", "idle", "내가 마우스/키보드를 쓰는 중이면 클릭 보류"),
            ("클릭 후 재시도(초)", "retry", "이 시간 안에 안 움직이면 재클릭 (0=끔, 최대 3회)"),
            ("이미지 일치도(0~1)", "threshold", "이미지 인식 기준, 기본 0.85"),
        ]
        for r, (label, key, hint) in enumerate(rows):
            ttk.Label(box, text=label).grid(row=r, column=0, sticky="w", pady=3)
            ttk.Entry(box, textvariable=self.v[key], width=8).grid(row=r, column=1, sticky="w", padx=8)
            ttk.Label(box, text=hint, foreground="#666", wraplength=230, justify="left").grid(row=r, column=2, sticky="w")
        checks = [
            (self.b_use_images, "이미지가 보이면 바로 클릭 (영상 움직임 무관)"),
            (self.b_loop, "마지막 단계 후 1번부터 반복"),
            (self.b_restore, "클릭 후 마우스를 원래 위치로 되돌리기"),
            (self.b_minimize, "시작하면 창 최소화"),
        ]
        for i, (var, text) in enumerate(checks):
            ttk.Checkbutton(box, text=text, variable=var).grid(row=len(rows) + i, column=0, columnspan=3,
                                                              sticky="w", pady=(6 if i == 0 else 0, 0))

    def _build_controls(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=10)
        self.start_btn = ttk.Button(bar, text="감시 시작 (F8)", command=self.start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(bar, text="감시 중지 (F8)", command=self.stop, state="disabled")
        self.stop_btn.pack(side="left", padx=8)
        ttk.Label(bar, text="F8은 다른 창을 쓰는 중에도 동작합니다", foreground="#666").pack(side="left", padx=6)

    def _build_log(self, parent):
        box = ttk.LabelFrame(parent, text="상태", padding=10)
        box.pack(fill="both", expand=True)
        ttk.Label(box, textvariable=self.status_var, wraplength=420, font=(FONT, 10, "bold")).pack(anchor="w")
        self.log_text = tk.Text(box, height=7, width=56, wrap="word", state="disabled", font=(FONT, 9))
        self.log_text.pack(fill="both", expand=True, pady=(8, 0))

    # ------------------------------------------------------------ settings
    def _load_vars(self):
        s = self.cfg.settings
        self.v["freeze"].set(f"{s.freeze_seconds:g}")
        self.v["interval"].set(f"{s.interval:g}")
        self.v["motion"].set(f"{s.motion_percent:g}")
        self.v["idle"].set(f"{s.idle_wait:g}")
        self.v["retry"].set(f"{s.retry_seconds:g}")
        self.v["threshold"].set(f"{s.threshold:g}")
        self.b_use_images.set(s.use_images)
        self.b_loop.set(s.loop)
        self.b_restore.set(s.restore_cursor)
        self.b_minimize.set(s.minimize_on_start)

    @staticmethod
    def _num(var, name, lo, hi):
        try:
            value = float(var.get().strip())
        except ValueError:
            raise ValueError(f"{name}: 숫자를 입력하세요.")
        if not lo <= value <= hi:
            raise ValueError(f"{name}: {lo:g} ~ {hi:g} 범위로 입력하세요.")
        return value

    def _apply_settings(self, show_error=True) -> bool:
        try:
            freeze = self._num(self.v["freeze"], "정지 판단 시간", 0.5, 3600)
            interval = self._num(self.v["interval"], "화면 확인 간격", 0.1, 5)
            motion = self._num(self.v["motion"], "움직임 기준", 0.01, 50)
            idle = self._num(self.v["idle"], "사용자 입력 대기", 0, 60)
            retry = self._num(self.v["retry"], "클릭 후 재시도", 0, 3600)
            threshold = self._num(self.v["threshold"], "이미지 일치도", 0.5, 0.99)
            if 0 < retry < 3:
                raise ValueError("클릭 후 재시도: 0(끔) 또는 3초 이상으로 입력하세요.")
        except ValueError as exc:
            if show_error:
                messagebox.showerror("설정 확인", str(exc))
            return False
        s = self.cfg.settings
        s.freeze_seconds, s.interval, s.motion_percent = freeze, interval, motion
        s.idle_wait, s.retry_seconds, s.threshold = idle, retry, threshold
        s.use_images, s.loop = self.b_use_images.get(), self.b_loop.get()
        s.restore_cursor, s.minimize_on_start = self.b_restore.get(), self.b_minimize.get()
        return True

    def _save(self):
        try:
            self.cfg.save(self.config_path)
        except OSError as exc:
            self._log(f"설정 저장 실패: {exc}")

    # -------------------------------------------------------------- region
    def _grab(self, rect):
        try:
            with ScreenGrabber() as g:
                return g.grab_region(rect)
        except Exception as exc:
            self._log(f"화면 캡처 실패: {exc}")
            return None

    def _show_photo(self, key, label, frame, w, h, empty_text, empty_width):
        if frame is None:
            self._photos.pop(key, None)
            label.configure(image="", text=empty_text, width=empty_width)
            return
        try:
            photo = make_photo(frame, w, h)
        except Exception:
            label.configure(image="", text="미리보기 오류", width=empty_width)
            return
        self._photos[key] = photo
        label.configure(image=photo, text="", width=0)

    def _refresh_region(self, frame=None):
        r = self.cfg.region
        self.region_text.set("영역 미지정" if not r else f"X={r[0]}, Y={r[1]}  크기 {r[2]}×{r[3]}")
        self._show_photo("region", self.region_img, frame, 200, 112, "미리보기 없음", 18)

    def pick_region(self):
        select_region(self.root, self._on_region,
                      "동영상이 재생되는 영역을 드래그하세요\n(Esc / 우클릭: 취소)")

    def _on_region(self, rect):
        if not rect:
            return
        self.cfg.region = list(rect)
        self._save()
        self._refresh_region(self._grab(rect))
        self._log(f"감시 영역 지정: X={rect[0]}, Y={rect[1]}, {rect[2]}×{rect[3]}")

    def refresh_region_preview(self):
        if not self.cfg.region:
            messagebox.showinfo("감시 영역", "먼저 감시 영역을 지정하세요.")
            return
        rect = tuple(self.cfg.region)
        self.root.withdraw()

        def go():
            try:
                frame = self._grab(rect)
            finally:
                self.root.deiconify()
            self._refresh_region(frame)

        self.root.after(250, go)

    # --------------------------------------------------------------- steps
    def _image_path(self, i):
        return self.images_dir / f"step{i + 1}.png"

    def _refresh_step(self, i):
        step, w = self.cfg.steps[i], self.step_widgets[i]
        frame = imread_unicode(self.images_dir / step.image) if step.image else None
        self._show_photo(f"step{i}", w["img"], frame, 112, 63, "이미지 없음", 14)
        if step.has_click():
            w["coord"].set(f"클릭 좌표: ({step.click_x}, {step.click_y})")
        elif step.image:
            w["coord"].set("이미지가 보이면 그 중앙 클릭")
        else:
            w["coord"].set("미설정 (건너뜀)")

    def _store_image(self, i, frame):
        try:
            self.images_dir.mkdir(parents=True, exist_ok=True)
            imwrite_unicode(self._image_path(i), frame)
        except OSError as exc:
            messagebox.showerror("이미지 저장", f"이미지를 저장하지 못했습니다.\n{exc}")
            return
        self.cfg.steps[i].image = self._image_path(i).name
        self._save()
        self._refresh_step(i)
        self._log(f"{i + 1}번 이미지 등록 ({frame.shape[1]}×{frame.shape[0]})")

    def capture_image(self, i):
        select_region(self.root, partial(self._on_image_rect, i),
                      f"{i + 1}번으로 등록할 화면 부분을 드래그하세요\n(Esc / 우클릭: 취소)")

    def _on_image_rect(self, i, rect):
        if not rect:
            return
        frame = self._grab(rect)
        if frame is not None:
            self._store_image(i, frame)

    def load_image(self, i):
        path = filedialog.askopenfilename(
            title=f"{i + 1}번 이미지 선택",
            filetypes=[("이미지 파일", "*.png *.jpg *.jpeg *.bmp"), ("모든 파일", "*.*")])
        if not path:
            return
        frame = imread_unicode(path)
        if frame is None:
            messagebox.showerror("이미지 선택", "이미지를 읽을 수 없습니다.")
            return
        self._store_image(i, frame)

    def clear_image(self, i):
        try:
            self._image_path(i).unlink(missing_ok=True)
        except OSError:
            pass
        self.cfg.steps[i].image = ""
        self._save()
        self._refresh_step(i)

    def pick_click(self, i):
        pick_point(self.root, partial(self._on_click_point, i),
                   f"{i + 1}번에서 클릭할 위치를 클릭하세요\n(Esc / 우클릭: 취소)")

    def _on_click_point(self, i, pt):
        if not pt:
            return
        self.cfg.steps[i].click_x, self.cfg.steps[i].click_y = int(pt[0]), int(pt[1])
        self._save()
        self._refresh_step(i)
        self._log(f"{i + 1}번 클릭 좌표 지정: ({pt[0]}, {pt[1]})")

    def clear_click(self, i):
        self.cfg.steps[i].click_x = self.cfg.steps[i].click_y = None
        self._save()
        self._refresh_step(i)

    # --------------------------------------------------------- run control
    @property
    def running(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def start(self):
        if self.running:
            return
        if not self._apply_settings():
            return
        if not self.cfg.region:
            messagebox.showwarning("감시 영역 필요", "먼저 '영역 드래그로 지정'으로 동영상 영역을 지정하세요.")
            return
        plans = build_plans(self.cfg, self.images_dir, self._log)
        if not plans:
            messagebox.showwarning("단계 설정 필요", "1~3번 중 하나 이상에 클릭 좌표나 이미지를 설정하세요.")
            return
        self._save()
        self.stop_event.clear()
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status_var.set("감시 중...")
        self._log("단계: " + " → ".join(p.label for p in plans))
        self.worker = threading.Thread(target=self._run_engine, args=(plans,), daemon=True)
        self.worker.start()
        if self.cfg.settings.minimize_on_start:
            self.root.iconify()

    def stop(self):
        if self.running:
            self.stop_event.set()

    def toggle(self):
        self.stop() if self.running else self.start()

    def _run_engine(self, plans):
        result = ("error", "알 수 없는 오류")
        grabber = None
        try:
            grabber = ScreenGrabber()  # 감시 스레드 안에서 생성
            s = self.cfg.settings
            engine = Engine(
                region=self.cfg.region, plans=plans, settings=s, grabber=grabber,
                clicker=lambda x, y: winapi.click(x, y, restore_cursor=s.restore_cursor),
                idle_fn=winapi.idle_seconds, log=self._log,
                status=lambda text: self.ui_queue.put(("status", text)))
            result = engine.run(self.stop_event)
        except Exception as exc:
            self.logger.error(traceback.format_exc())
            result = ("error", f"오류: {exc}")
        finally:
            if grabber is not None:
                grabber.close()
        self.ui_queue.put(("done", result[0], result[1]))

    def _on_done(self, kind, message):
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        self.status_var.set(message)
        if kind != "stopped":
            self.root.deiconify()
            self.root.lift()
            winapi.beep()

    # ------------------------------------------------------------- plumbing
    def _log(self, message: str):
        """어느 스레드에서 불러도 안전."""
        self.logger.info(message)
        self.ui_queue.put(("log", f"[{time.strftime('%H:%M:%S')}] {message}"))

    def _append_log(self, line: str):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        if int(self.log_text.index("end-1c").split(".")[0]) > 500:
            self.log_text.delete("1.0", "100.0")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll(self):
        try:
            while True:
                item = self.ui_queue.get_nowait()
                kind = item[0]
                if kind == "log":
                    self._append_log(item[1])
                elif kind == "status":
                    if self.running:
                        self.status_var.set(item[1])
                elif kind == "toggle":
                    self.toggle()
                elif kind == "done":
                    self._on_done(item[1], item[2])
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _on_tk_error(self, exc, val, tb):
        self.logger.error("".join(traceback.format_exception(exc, val, tb)))
        self._append_log(f"[오류] {val}")

    def close(self):
        self.stop_event.set()
        self.hotkeys.stop()
        if self._apply_settings(show_error=False):
            self._save()
        self.root.destroy()


def run():
    root = tk.Tk()
    App(root)
    root.mainloop()
