"""Grab primary-monitor screenshots for the hit test: F9 = shoot, Esc = quit."""
import ctypes
import time
from pathlib import Path

import mss
import mss.tools

VK_F9, VK_ESCAPE = 0x78, 0x1B
SHOT_COUNT = 10
SHOTS_DIR = Path(__file__).parent / "shots"


def is_down(virtual_key: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(virtual_key) & 0x8000)


def wait_for_tap() -> int:
    """Block until F9 or Esc is pressed and released; return which."""
    while True:
        for key in (VK_F9, VK_ESCAPE):
            if is_down(key):
                while is_down(key):
                    time.sleep(0.02)
                return key
        time.sleep(0.02)


def main() -> None:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # real pixels, not scaled
    SHOTS_DIR.mkdir(exist_ok=True)
    with mss.MSS() as screen:
        for index in range(1, SHOT_COUNT + 1):
            print(f"[{index}/{SHOT_COUNT}] F9 to capture, Esc to stop", flush=True)
            if wait_for_tap() == VK_ESCAPE:
                return
            shot = screen.grab(screen.monitors[1])
            path = SHOTS_DIR / f"{index:02d}.png"
            mss.tools.to_png(shot.rgb, shot.size, output=str(path))
            print(f"saved {path.name}", flush=True)


if __name__ == "__main__":
    main()
