"""Reconstruct the received RGB payload and create a comparison image."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "simulation_config.json"
TX_RGB = ROOT / "working" / "tx_image.rgb"
RX_RGB = ROOT / "working" / "rx_image.rgb"
RECOVERED = ROOT / "results" / "recovered_image.png"
COMPARISON = ROOT / "results" / "comparison.png"


def read_config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read {CONFIG}: {exc}") from exc


def read_exact(path: Path, expected: int) -> bytes:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RuntimeError(f"Cannot read {path}: {exc}") from exc
    if len(data) < expected:
        raise ValueError(f"{path} has {len(data)} bytes; {expected} are required")
    # The GRC Head block limits normal output. Any surplus is ignored only to
    # tolerate a previously interrupted append-mode experiment.
    return data[:expected]


def labeled_comparison(original: Image.Image, recovered: Image.Image) -> Image.Image:
    original_array = np.asarray(original, dtype=np.int16)
    recovered_array = np.asarray(recovered, dtype=np.int16)
    error = Image.fromarray(np.abs(original_array - recovered_array).astype(np.uint8), "RGB")
    labels = ("Original image", "Recovered image", "Absolute error image")
    header = 28
    canvas = Image.new("RGB", (original.width * 3, original.height + header), "white")
    draw = ImageDraw.Draw(canvas)
    for index, (label, panel) in enumerate(zip(labels, (original, recovered, error))):
        x_position = index * original.width
        draw.text((x_position + 8, 7), label, fill="black")
        canvas.paste(panel, (x_position, header))
    return canvas


def main() -> None:
    config = read_config()
    width = int(config["width"])
    height = int(config["height"])
    channels = int(config["channels"])
    if channels != 3 or config.get("pixel_format") != "RGB8":
        raise ValueError("Only RGB8 payloads with three channels are supported")
    expected = width * height * channels
    if int(config["payload_bytes"]) != expected:
        raise ValueError("Image dimensions do not agree with payload_bytes")

    transmitted = read_exact(TX_RGB, expected)
    received = read_exact(RX_RGB, expected)
    original = Image.fromarray(np.frombuffer(transmitted, np.uint8).reshape(height, width, 3), "RGB")
    recovered = Image.fromarray(np.frombuffer(received, np.uint8).reshape(height, width, 3), "RGB")

    RECOVERED.parent.mkdir(parents=True, exist_ok=True)
    recovered.save(RECOVERED, format="PNG")
    labeled_comparison(original, recovered).save(COMPARISON, format="PNG")
    print(f"Recovered {width} x {height} RGB8 image from {expected} received bytes")
    print(f"Saved {RECOVERED.relative_to(ROOT)} and {COMPARISON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
