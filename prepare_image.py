"""Normalize an image and serialize its raw RGB payload for GNU Radio."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, UnidentifiedImageError


ROOT = Path(__file__).resolve().parent
INPUT = ROOT / "input" / "input_image.png"
NORMALIZED = ROOT / "input" / "normalized_source.png"
TX_RGB = ROOT / "working" / "tx_image.rgb"
CONFIG = ROOT / "simulation_config.json"
IMAGE_SIZE = (256, 256)


def load_config() -> dict:
    if not CONFIG.exists():
        return {}
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read {CONFIG}: {exc}") from exc


def normalize_image(path: Path) -> Image.Image:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Input image is missing or empty: {path}")
    try:
        with Image.open(path) as source:
            source.load()
            return source.convert("RGB").resize(IMAGE_SIZE, Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"Unsupported or unreadable image {path}: {exc}") from exc


def main() -> None:
    image = normalize_image(INPUT)
    payload = image.tobytes("raw", "RGB")
    expected_bytes = IMAGE_SIZE[0] * IMAGE_SIZE[1] * 3
    if len(payload) != expected_bytes:
        raise RuntimeError(f"RGB serialization produced {len(payload)} bytes, expected {expected_bytes}")

    TX_RGB.parent.mkdir(parents=True, exist_ok=True)
    NORMALIZED.parent.mkdir(parents=True, exist_ok=True)
    image.save(NORMALIZED, format="PNG")
    TX_RGB.write_bytes(payload)

    config = load_config()
    config.update(
        {
            "width": IMAGE_SIZE[0],
            "height": IMAGE_SIZE[1],
            "channels": 3,
            "pixel_format": "RGB8",
            "payload_bytes": len(payload),
            "payload_bits": len(payload) * 8,
            "bit_order": "MSB first",
            "tx_rgb_sha256": hashlib.sha256(payload).hexdigest(),
            "normalized_source": "input/normalized_source.png",
        }
    )
    CONFIG.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {IMAGE_SIZE[0]} x {IMAGE_SIZE[1]} RGB8 image ({len(payload)} bytes)")
    print(f"SHA-256: {config['tx_rgb_sha256']}")


if __name__ == "__main__":
    main()
