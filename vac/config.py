"""설정 저장/불러오기. exe로 묶었을 때도 같은 폴더(또는 %APPDATA%)에 저장됩니다."""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "VideoAutoClick"
STEP_COUNT = 3


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller exe
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """config.json / images / 로그 저장 위치. 쓰기 불가하면 %APPDATA%로 대체."""
    base = _app_dir()
    try:
        (base / "images").mkdir(parents=True, exist_ok=True)
        probe = base / ".write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return base
    except OSError:
        alt = Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
        (alt / "images").mkdir(parents=True, exist_ok=True)
        return alt


@dataclass
class Step:
    image: str = ""  # images 폴더 안의 파일명
    click_x: int | None = None
    click_y: int | None = None

    def has_click(self) -> bool:
        return self.click_x is not None and self.click_y is not None


@dataclass
class Settings:
    freeze_seconds: float = 5.0     # 이 시간 동안 변화가 없으면 '정지'
    interval: float = 0.5           # 화면 비교 주기
    motion_percent: float = 0.3     # 바뀐 픽셀 비율(%)이 이 값 이상이면 '움직임'
    idle_wait: float = 1.0          # 사용자가 마우스/키보드를 쓰는 중이면 클릭 보류
    retry_seconds: float = 15.0     # 클릭 후 이 시간 동안 안 움직이면 재시도 (0=끔)
    threshold: float = 0.85         # 이미지 일치도
    use_images: bool = True         # 이미지가 화면에 보일 때만 클릭
    loop: bool = False              # 마지막 단계 후 1번부터 반복
    restore_cursor: bool = True     # 클릭 후 마우스를 원래 위치로
    minimize_on_start: bool = True  # 시작 시 창 최소화


def _coerce(default, value):
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        return float(value) if isinstance(default, float) else int(value)
    return default


def _int_or_none(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass
class Config:
    region: list[int] | None = None  # [left, top, width, height] (화면 픽셀)
    steps: list[Step] = field(default_factory=lambda: [Step() for _ in range(STEP_COUNT)])
    settings: Settings = field(default_factory=Settings)

    def save(self, path: Path) -> None:
        data = {
            "region": self.region,
            "steps": [asdict(s) for s in self.steps],
            "settings": asdict(self.settings),
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path) -> "Config":
        cfg = cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cfg
        if not isinstance(raw, dict):
            return cfg

        reg = raw.get("region")
        if (isinstance(reg, list) and len(reg) == 4
                and all(_int_or_none(v) is not None for v in reg) and reg[2] > 0 and reg[3] > 0):
            cfg.region = list(reg)

        steps = raw.get("steps")
        if isinstance(steps, list):
            for i, item in enumerate(steps[:STEP_COUNT]):
                if not isinstance(item, dict):
                    continue
                image = item.get("image", "")
                x, y = _int_or_none(item.get("click_x")), _int_or_none(item.get("click_y"))
                if x is None or y is None:
                    x = y = None
                cfg.steps[i] = Step(image=image if isinstance(image, str) else "", click_x=x, click_y=y)

        saved = raw.get("settings")
        if isinstance(saved, dict):
            for key, value in saved.items():
                if hasattr(cfg.settings, key):
                    setattr(cfg.settings, key, _coerce(getattr(cfg.settings, key), value))
        return cfg
