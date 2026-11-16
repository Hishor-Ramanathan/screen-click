"""Hit test: can each vision model point at a named UI element?

For every case in cases.json, send the scaled-down screenshot to each model,
map its {x,y} back to screen pixels and count a hit if it lands in the bbox.
Coordinate conventions differ by model family, so each answer is scored under
all of them and the report names the one the model actually follows.
"""
import base64
import io
import json
import statistics
import time
from pathlib import Path

import sys

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent.parent))
from screen_click import LONG_SIDE, OLLAMA_URL, to_point  # noqa: E402

BENCH_DIR = Path(__file__).parent
# qwen3.5 thinks by default; thinking burns minutes and adds nothing to pointing.
MODELS = {"qwen3.5:4b": {"think": False}, "qwen2.5vl:7b": {}}

# Each convention maps a model answer (x, y) to a fraction of the image (0..1).
CONVENTIONS = {
    "pixels": lambda x, y, w, h: (x / w, y / h),
    "norm1000": lambda x, y, w, h: (x / 1000, y / 1000),
    "norm1": lambda x, y, w, h: (x, y),
}


def scaled_png(path: Path) -> tuple[str, int, int, int, int]:
    """Return (base64 png, sent width, sent height, screen width, screen height)."""
    image = Image.open(path)
    screen_w, screen_h = image.size
    image.thumbnail((LONG_SIDE, LONG_SIDE))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode(), *image.size, screen_w, screen_h


def ask(client: httpx.Client, model: str, target: str, image_b64: str, w: int, h: int) -> dict:
    prompt = (
        f"This screenshot is {w}x{h} pixels. Find the UI element: \"{target}\". "
        'Reply with JSON only: {"point_2d": [x, y]} at the centre of that element.'
    )
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt, "images": [image_b64]}],
        "format": "json",
        "stream": False,
        "options": {"temperature": 0},
        **MODELS[model],
    }
    response = client.post(OLLAMA_URL, json=body, timeout=300)
    response.raise_for_status()
    return json.loads(response.json()["message"]["content"])


def is_hit(fraction: tuple[float, float], screen_w: int, screen_h: int, bbox: list[int]) -> bool:
    x, y = fraction[0] * screen_w, fraction[1] * screen_h
    left, top, right, bottom = bbox
    return left <= x <= right and top <= y <= bottom


def main() -> None:
    cases = json.loads((BENCH_DIR / "cases.json").read_text())
    report = {}
    with httpx.Client() as client:
        for model in MODELS:
            hits = dict.fromkeys(CONVENTIONS, 0)
            latencies, answers = [], []
            for case in cases:
                image_b64, w, h, screen_w, screen_h = scaled_png(BENCH_DIR / "shots" / case["file"])
                started = time.perf_counter()
                answer, x, y = None, None, None
                try:
                    answer = ask(client, model, case["target"], image_b64, w, h)
                    x, y = to_point(answer)
                except (httpx.HTTPError, StopIteration, ValueError, TypeError) as error:
                    answer = {"raw": answer, "error": repr(error)}
                latencies.append(time.perf_counter() - started)
                answers.append({"file": case["file"], "target": case["target"], "answer": answer})
                if x is None:
                    continue
                for name, to_fraction in CONVENTIONS.items():
                    hits[name] += is_hit(to_fraction(x, y, w, h), screen_w, screen_h, case["bbox"])
            best = max(hits, key=hits.get)
            report[model] = {
                "hits": hits[best], "of": len(cases), "convention": best, "all_conventions": hits,
                "median_s": round(statistics.median(latencies), 1), "answers": answers,
            }
            print(f"{model:14} {hits[best]}/{len(cases)} via {best:8} median {report[model]['median_s']}s  {hits}")
    (BENCH_DIR / "results.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
