# -*- coding: utf-8 -*-
"""동영상 정지 감지 오토클릭 (Windows 11) - 진입점"""
import vac
import vac.capture
import vac.config
import vac.detector
import vac.engine
import vac.gui
import vac.overlay
import vac.winapi
from vac.winapi import enable_dpi_awareness


def main() -> None:
    enable_dpi_awareness()  # Tk 창을 만들기 전에 반드시 먼저 호출
    vac.gui.run()


if __name__ == "__main__":
    main()
