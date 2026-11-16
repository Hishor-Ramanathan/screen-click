# screen-click

A tiny Windows MCP server with one tool, `click(target)`, that clicks a UI element by name and answers in **text only** — no screenshot ever reaches the calling model, so a click costs a few tokens instead of an image.

1. **UI Automation** — native case-insensitive (substring) search for an element whose accessible Name matches, front-most window first. Fast (ms) for Win32/WinUI/browser chrome.
2. **Vision fallback** — screenshot of the primary monitor, scaled to 1280 px, sent to a local [Ollama](https://ollama.com) vision model that returns `{"point_2d": [x, y]}`; mapped back to screen pixels and clicked. Used for apps that expose nothing to UIA (e.g. Unreal Editor).

```
> click("Search")
clicked 'Search' (ButtonControl) via UI Automation at (796, 1050)
> click("File Explorer icon in the taskbar")
clicked 'File Explorer icon in the taskbar' via vision (qwen3.5:4b) at (1256, 1049)
```

## Setup

```sh
pip install -r requirements.txt
ollama pull qwen3.5:4b
claude mcp add -s user screen-click -e SCREEN_CLICK_OLLAMA=http://<ollama-host>:11434 -- python /path/to/screen_click.py
```

| Env var | Default |
|---|---|
| `SCREEN_CLICK_OLLAMA` | `http://localhost:11434` |
| `SCREEN_CLICK_MODEL` | `qwen3.5:4b` (`qwen2.5vl:7b` also supported) |

## Benchmark

`bench/capture.py` grabs screenshots (F9), `bench/cases.json` labels a target + bounding box per shot, `bench/run.py` scores each model's hits.

15 targets (10 Unreal Editor, 5 Windows Settings), 1920x1080, Ollama on CPU:

| Model | Hits | Coordinates | Median latency |
|---|---|---|---|
| `qwen3.5:4b` | **9/15** (2 more within 2 px of the box) | 0–1000 grid | 46 s |
| `qwen2.5vl:7b` | 6/15 | image pixels | 5 s |

Both find big labelled buttons; both miss small icons (panel close ×, taskbar icons in a crowded row).

## Limits

Windows only; vision sees the primary monitor only; UIA matching is by Name, so descriptive targets ("the blue Save icon") go to vision.
