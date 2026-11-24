"""전체 화면 반투명 오버레이: 마우스 드래그로 영역 지정 / 클릭으로 좌표 지정.

모든 좌표는 화면(가상 데스크톱) 실제 픽셀 기준입니다. winapi.enable_dpi_awareness()를
Tk() 생성 전에 호출해야 캡처/클릭 좌표와 어긋나지 않습니다.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable

from .capture import virtual_bounds

_REPAINT_DELAY_MS = 250  # 오버레이가 사라지고 화면이 다시 그려질 시간


def _run_overlay(root: tk.Tk, message: str, drag: bool, on_done: Callable) -> None:
    vl, vt, vw, vh, pl, pt = virtual_bounds()
    root.withdraw()
    try:
        top = tk.Toplevel(root)
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.attributes("-alpha", 0.35)
        top.configure(bg="black", cursor="crosshair")
        top.geometry(f"{vw}x{vh}+{vl}+{vt}")
        canvas = tk.Canvas(top, bg="black", highlightthickness=0, cursor="crosshair")
        canvas.pack(fill="both", expand=True)

        hint = tk.Toplevel(root)
        hint.overrideredirect(True)
        hint.attributes("-topmost", True)
        hint_var = tk.StringVar(value=message)
        tk.Label(hint, textvariable=hint_var, bg="#fff3b0", fg="#222222", justify="left",
                 font=("맑은 고딕", 12, "bold"), padx=16, pady=10).pack()
        hint.geometry(f"+{pl + 40}+{pt + 40}")
        top.update_idletasks()
        top.focus_force()
        canvas.focus_set()
    except tk.TclError:
        root.deiconify()
        on_done(None)
        return

    finished = {"v": False}

    def finish(result):
        if finished["v"]:
            return
        finished["v"] = True
        for w in (hint, top):
            try:
                w.destroy()
            except tk.TclError:
                pass

        def after_repaint():
            # on_done을 먼저 호출해야 메인 창이 캡처에 찍히지 않습니다.
            try:
                on_done(result)
            finally:
                root.deiconify()
                root.lift()

        root.after(_REPAINT_DELAY_MS, after_repaint)

    start: dict = {}
    rect_id = [None]

    def on_press(e):
        if drag:
            start.update(x=e.x_root, y=e.y_root, lx=e.x, ly=e.y)
            rect_id[0] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#ff2d2d", width=3)
        else:
            finish((e.x_root, e.y_root))

    def on_move(e):
        if drag and rect_id[0] is not None:
            canvas.coords(rect_id[0], start["lx"], start["ly"], e.x, e.y)
            hint_var.set(f"{message}\n{abs(e.x_root - start['x'])} × {abs(e.y_root - start['y'])} px")

    def on_release(e):
        if not drag or "x" not in start:
            return
        left, top_ = min(start["x"], e.x_root), min(start["y"], e.y_root)
        width, height = abs(e.x_root - start["x"]), abs(e.y_root - start["y"])
        finish((left, top_, width, height) if width >= 8 and height >= 8 else None)

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_move)
    canvas.bind("<ButtonRelease-1>", on_release)
    for widget in (top, canvas, hint):
        widget.bind("<Escape>", lambda e: finish(None))
    canvas.bind("<Button-3>", lambda e: finish(None))


def select_region(root: tk.Tk, on_done: Callable[[tuple[int, int, int, int] | None], None],
                  message: str = "마우스로 드래그해서 영역을 지정하세요\n(Esc / 우클릭: 취소)") -> None:
    _run_overlay(root, message, True, on_done)


def pick_point(root: tk.Tk, on_done: Callable[[tuple[int, int] | None], None],
               message: str = "클릭할 위치를 클릭하세요\n(Esc / 우클릭: 취소)") -> None:
    _run_overlay(root, message, False, on_done)
