"""Reconstruct the received RGB payload and create a comparison image."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "simulation_config.json"
TX_RGB = ROOT / "working" / "tx_image.rgb"
RX_RGB = ROOT / "working" / "rx_image.rgb"
RX_DECODED_BITS = ROOT / "working" / "rx_decoded_bits.bin"
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
    return data[:expected]


def decoded_payload(config: dict) -> bytes:
    framing = config.get("framing")
    if not isinstance(framing, dict):
        raise ValueError("Configuration has no framing metadata; rerun prepare_image.py")
    if RX_DECODED_BITS.stat().st_mtime < TX_RGB.stat().st_mtime:
        raise RuntimeError("Decoded bit stream is older than tx_image.rgb; rerun the simple flowgraph")
    bits = np.frombuffer(RX_DECODED_BITS.read_bytes(), dtype=np.uint8)
    if bits.size and np.any(bits > 1):
        raise ValueError("Decoded stream must contain only one-byte 0 or 1 bit items")
    start = int(framing["payload_start_bit"])
    count = int(framing["payload_bits"])
    if bits.size < start + count:
        raise ValueError(f"Decoded stream has {bits.size} bits; {start + count} are required")
    # np.packbits with big bit order exactly reverses the MSB-first expansion.
    return np.packbits(bits[start : start + count], bitorder="big").tobytes()


def received_payload(config: dict, source: str, expected: int) -> bytes:
    use_decoded = source == "decoded" or (source == "auto" and RX_DECODED_BITS.exists())
    if use_decoded:
        payload = decoded_payload(config)
        if len(payload) != expected:
            raise ValueError(f"Decoded payload has {len(payload)} bytes; expected {expected}")
        RX_RGB.write_bytes(payload)
        return payload
    if source == "decoded":
        raise FileNotFoundError(f"Decoded bit stream is missing: {RX_DECODED_BITS}")
    return read_exact(RX_RGB, expected)


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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", choices=("auto", "decoded", "legacy"), default="auto",
        help="decoded uses the simple graph; legacy reads working/rx_image.rgb",
    )
    args = parser.parse_args()
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
    received = received_payload(config, args.source, expected)
    original = Image.fromarray(np.frombuffer(transmitted, np.uint8).reshape(height, width, 3), "RGB")
    recovered = Image.fromarray(np.frombuffer(received, np.uint8).reshape(height, width, 3), "RGB")

    RECOVERED.parent.mkdir(parents=True, exist_ok=True)
    recovered.save(RECOVERED, format="PNG")
    labeled_comparison(original, recovered).save(COMPARISON, format="PNG")
    print(f"Recovered {width} x {height} RGB8 image from {expected} received bytes")
    print(f"Saved {RECOVERED.relative_to(ROOT)} and {COMPARISON.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
