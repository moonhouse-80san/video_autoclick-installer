# -*- coding: utf-8 -*-
"""동영상 정지 감지 오토클릭 (Windows 11) - 진입점"""
from vac.winapi import enable_dpi_awareness


def main() -> None:
    enable_dpi_awareness()  # Tk 창을 만들기 전에 반드시 먼저 호출
    from vac.gui import run
    run()


if __name__ == "__main__":
    main()
