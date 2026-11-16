"""screen-click: an MCP tool that clicks a UI element by name and answers in text.

1. UI Automation: click an on-screen element whose accessible Name matches.
2. Vision fallback: screenshot the primary monitor, ask a local Ollama vision
   model where the target is, click there.
The screenshot only ever goes to Ollama; the caller gets a one-line result.
"""
import base64
import ctypes
import io
import json
import os
from _ctypes import COMError

ctypes.windll.shcore.SetProcessDpiAwareness(2)  # before any UI import: physical pixels everywhere

import httpx
import mss
import uiautomation as uia
from mcp.server.mcpserver import MCPServer
from PIL import Image
from uiautomation.uiautomation import _AutomationClient  # raw IUIAutomation, for a native name search

OLLAMA_URL = os.environ.get("SCREEN_CLICK_OLLAMA", "http://localhost:11434") + "/api/chat"
VISION_MODEL = os.environ.get("SCREEN_CLICK_MODEL", "qwen3.5:4b")
# How each model reports positions (measured in bench/run.py): pixels of the image
# it was sent, or a 0-1000 grid over that image.
COORDINATES = {"qwen3.5:4b": "norm1000", "qwen2.5vl:7b": "pixels"}
LONG_SIDE = 1280


def to_point(answer: dict) -> tuple[float, float]:
    """Take the first [x, y] point in a model answer, or the centre of a [x1, y1, x2, y2] box."""
    numbers = next(v for v in answer.values() if isinstance(v, list) and len(v) in (2, 4))
    x1, y1, x2, y2 = map(float, numbers * 2 if len(numbers) == 2 else numbers)
    return (x1 + x2) / 2, (y1 + y2) / 2


def to_fraction(x: float, y: float, sent_w: int, sent_h: int, convention: str) -> tuple[float, float]:
    """Model coordinates -> fraction (0..1) of the image, independent of its size."""
    if convention == "norm1000":
        return x / 1000, y / 1000
    return x / sent_w, y / sent_h


def click_at(x: int, y: int) -> None:
    left_down, left_up = 0x0002, 0x0004
    ctypes.windll.user32.SetCursorPos(x, y)
    ctypes.windll.user32.mouse_event(left_down, 0, 0, 0, 0)
    ctypes.windll.user32.mouse_event(left_up, 0, 0, 0, 0)


class AccessibilityFinder:
    """Finds a visible element by Name in the UI Automation trees of the top-level windows."""

    NAME_CONTAINS_IGNORE_CASE = 1 | 2  # PropertyConditionFlags_IgnoreCase | _MatchSubstring
    TREE_SCOPE_DESCENDANTS = 4
    # Windows whose UIA tree is huge and exposes nothing clickable: searching Unreal
    # took 14 s and found none of its buttons. These go straight to vision.
    # ponytail: static list; measure-and-remember slow windows if more apps show up.
    SKIPPED_WINDOW_CLASSES = {"UnrealWindow"}

    def find(self, target: str) -> uia.Control | None:
        """Front-most window with a match wins; inside it, an exact Name beats a substring."""
        wanted = target.strip()
        with uia.UIAutomationInitializerInThread():
            automation = _AutomationClient.instance().IUIAutomation
            condition = automation.CreatePropertyConditionEx(
                uia.PropertyId.NameProperty, wanted, self.NAME_CONTAINS_IGNORE_CASE)
            for window in uia.GetRootControl().GetChildren():  # top-level windows, front to back
                if window.IsOffscreen or window.ClassName in self.SKIPPED_WINDOW_CLASSES:
                    continue
                try:
                    found = window.Element.FindAll(self.TREE_SCOPE_DESCENDANTS, condition)
                except COMError:  # window not answering UIA; skip it
                    continue
                matches = [uia.Control.CreateControlFromElement(found.GetElement(i)) for i in range(found.Length)]
                matches = [control for control in matches if self._is_clickable(control)]
                if matches:
                    exact = [c for c in matches if c.Name.casefold() == wanted.casefold()]
                    return (exact or matches)[0]
        return None

    @staticmethod
    def _is_clickable(control: uia.Control) -> bool:
        rect = control.BoundingRectangle
        return not control.IsOffscreen and rect.width() > 0 and rect.height() > 0


class VisionLocator:
    """Asks the Ollama vision model where the target is on the primary monitor."""

    def locate(self, target: str) -> tuple[int, int]:
        with mss.MSS() as screen:
            monitor = screen.monitors[1]
            shot = screen.grab(monitor)
        image = Image.frombytes("RGB", shot.size, shot.rgb)
        image.thumbnail((LONG_SIDE, LONG_SIDE))
        sent_w, sent_h = image.size
        x, y = to_point(self._ask(target, image))
        fx, fy = to_fraction(x, y, sent_w, sent_h, COORDINATES[VISION_MODEL])
        if not (0 <= fx <= 1 and 0 <= fy <= 1):
            raise ValueError(f"model pointed off-screen ({x}, {y})")
        return monitor["left"] + round(fx * monitor["width"]), monitor["top"] + round(fy * monitor["height"])

    @staticmethod
    def _ask(target: str, image: Image.Image) -> dict:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        prompt = (
            f"This screenshot is {image.width}x{image.height} pixels. Find the UI element: \"{target}\". "
            'Reply with JSON only: {"point_2d": [x, y]} at the centre of that element.'
        )
        response = httpx.post(OLLAMA_URL, timeout=180, json={
            "model": VISION_MODEL,
            "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(buffer.getvalue()).decode()]}],
            "format": "json",
            "stream": False,
            "think": False,
            "options": {"temperature": 0},
        })
        response.raise_for_status()
        return json.loads(response.json()["message"]["content"])


server = MCPServer("screen-click")


@server.tool()
def click(target: str) -> str:
    """Click a UI element on screen by its visible name or a short description
    (e.g. "Save", "Content Drawer button"). Tries Windows UI Automation first,
    then a local vision model. Returns a one-line text result, never an image."""
    control = AccessibilityFinder().find(target)
    if control is not None:
        rect = control.BoundingRectangle
        x, y = rect.xcenter(), rect.ycenter()
        click_at(x, y)
        return f"clicked '{control.Name}' ({control.ControlTypeName}) via UI Automation at ({x}, {y})"
    try:
        x, y = VisionLocator().locate(target)
    except (httpx.HTTPError, StopIteration, ValueError, TypeError, KeyError) as error:
        return f"not clicked: '{target}' not in UI Automation tree and vision failed: {error!r}"
    click_at(x, y)
    return f"clicked '{target}' via vision ({VISION_MODEL}) at ({x}, {y})"


if __name__ == "__main__":
    server.run()
