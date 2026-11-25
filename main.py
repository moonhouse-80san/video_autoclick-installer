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

    app.navigation_menu = ttk.Frame(app.outer)
    app.navigation_menu.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    ttk.Label(app.navigation_menu, text="메뉴:").pack(side="left", padx=(0, 6))
    ttk.Button(
        app.navigation_menu,
        text=f"버전 관리 ({vac.gui.APP_VERSION})",
        command=lambda: _open_url(app, RELEASES_URL),
    ).pack(side="left", padx=(0, 4))
    ttk.Button(app.navigation_menu, text="제작자", command=lambda: _show_creator(app)).pack(side="left", padx=(0, 4))
    ttk.Button(app.navigation_menu, text="사용설명서", command=lambda: _open_url(app, MANUAL_URL)).pack(side="left", padx=(0, 4))
    ttk.Button(app.navigation_menu, text="홈페이지", command=lambda: _open_url(app, HOMEPAGE_URL)).pack(side="left")


def _install_navigation_menu() -> None:
    """기존 UI에 접기 시 숨길 수 있는 메뉴를 추가합니다."""
    vac.gui.APP_TITLE = "동영상 정지 감지 오토클릭"
    build_ui = vac.gui.App._build_ui

    def build_ui_with_navigation(app):
        build_ui(app)
        app.creator_link_lbl.destroy()
        _add_navigation_menu(app)

    vac.gui.App._build_ui = build_ui_with_navigation


def main() -> None:
    enable_dpi_awareness()
    _install_navigation_menu()
    vac.gui.run()


if __name__ == "__main__":
    main()
