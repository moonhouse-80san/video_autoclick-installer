# -*- coding: utf-8 -*-
"""동영상 정지 감지 오토클릭 (Windows 11) - 진입점"""
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

import vac
import vac.capture
import vac.config
import vac.detector
import vac.engine
import vac.gui
import vac.overlay
import vac.winapi
from vac.winapi import enable_dpi_awareness


RELEASES_URL = "https://github.com/moonhouse-80san/video_autoclick-installer/releases"
MANUAL_URL = "https://github.com/moonhouse-80san/video_autoclick-installer/blob/master/%EC%82%AC%EC%9A%A9%EC%84%A4%EB%AA%85%EC%84%9C.txt"
CREATOR_URL = "https://moonhouse.co.kr/"
HOMEPAGE_URL = "https://moonhouse.co.kr/utils/623259"


def _open_url(app, url: str) -> None:
    try:
        webbrowser.open_new_tab(url)
    except Exception as exc:
        messagebox.showerror("웹페이지 열기", f"웹페이지를 열지 못했습니다.\n{exc}", parent=app.root)


def _show_creator(app) -> None:
    dialog = tk.Toplevel(app.root)
    dialog.title("제작자 정보")
    dialog.resizable(False, False)
    dialog.transient(app.root)
    body = ttk.Frame(dialog, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(body, text="제작자", font=("맑은 고딕", 10, "bold")).pack(anchor="w")
    ttk.Label(body, text="MoonHouse").pack(anchor="w", pady=(6, 12))
    buttons = ttk.Frame(body)
    buttons.pack(fill="x")
    ttk.Button(buttons, text="제작자 홈페이지", command=lambda: _open_url(app, CREATOR_URL)).pack(side="left")
    ttk.Button(buttons, text="닫기", command=dialog.destroy).pack(side="right")
    dialog.update_idletasks()
    x = app.root.winfo_rootx() + (app.root.winfo_width() - dialog.winfo_width()) // 2
    y = app.root.winfo_rooty() + (app.root.winfo_height() - dialog.winfo_height()) // 2
    dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
    dialog.grab_set()


def _add_navigation_menu(app) -> None:
    """헤더 바로 아래에 버전/제작자/설명서/홈페이지 메뉴를 배치합니다."""
    # 기존 좌우 패널을 한 줄 내리고 메뉴 공간을 확보합니다.
    app.outer.rowconfigure(1, weight=0)
    app.outer.rowconfigure(2, weight=1)
    app.left_panel.grid_configure(row=2)
    app.right_panel.grid_configure(row=2)

    menu = ttk.Frame(app.outer)
    menu.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    app.navigation_menu = menu
    ttk.Label(menu, text="메뉴:").pack(side="left", padx=(0, 6))
    ttk.Button(
        menu,
        text=f"버전 관리 ({vac.gui.APP_VERSION})",
        command=lambda: _open_url(app, RELEASES_URL),
    ).pack(side="left", padx=(0, 4))
    ttk.Button(menu, text="제작자", command=lambda: _show_creator(app)).pack(side="left", padx=(0, 4))
    ttk.Button(menu, text="사용설명서", command=lambda: _open_url(app, MANUAL_URL)).pack(side="left", padx=(0, 4))
    ttk.Button(menu, text="홈페이지", command=lambda: _open_url(app, HOMEPAGE_URL)).pack(side="left")


def _install_navigation_menu() -> None:
    """기존 UI를 만든 직후 메뉴를 추가해 실행 화면에 적용합니다."""
    # 창 제목 표시줄에는 프로그램명만 표시합니다.
    vac.gui.APP_TITLE = "동영상 정지 감지 오토클릭"
    build_ui = vac.gui.App._build_ui
    apply_left_panel_state = vac.gui.App._apply_left_panel_state

    def build_ui_with_navigation(app):
        build_ui(app)
        # 본 화면 우측 상단의 버전/제작자 표시는 제거합니다.
        app.creator_link_lbl.destroy()
        _add_navigation_menu(app)

    def apply_panel_state_with_menu(app, initial: bool = False):
        # 접기/펼치기 계산 전에 메뉴를 숨기거나 복원해 창 크기에도 반영합니다.
        menu = getattr(app, "navigation_menu", None)
        if menu is not None:
            if app._left_collapsed:
                menu.grid_remove()
            else:
                menu.grid()
        apply_left_panel_state(app, initial=initial)

    vac.gui.App._build_ui = build_ui_with_navigation
    vac.gui.App._apply_left_panel_state = apply_panel_state_with_menu


def main() -> None:
    enable_dpi_awareness()  # Tk 창을 만들기 전에 반드시 먼저 호출
    _install_navigation_menu()
    vac.gui.run()


if __name__ == "__main__":
    main()
