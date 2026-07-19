"""Normalize an image and serialize its raw RGB payload for GNU Radio."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, UnidentifiedImageError


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "input" / "input_image.png"
NORMALIZED = ROOT / "input" / "normalized_source.png"
TX_RGB = ROOT / "working" / "tx_image.rgb"
TX_FRAMED_BITS = ROOT / "working" / "tx_framed_bits.bin"
CONFIG = ROOT / "simulation_config.json"


def load_config() -> dict:
    if not CONFIG.exists():
        return {}
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read {CONFIG}: {exc}") from exc


def normalize_image(path: Path, size: tuple[int, int]) -> Image.Image:
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError(f"Input image is missing or empty: {path}")
    try:
        with Image.open(path) as source:
            source.load()
            return source.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"Unsupported or unreadable image {path}: {exc}") from exc


def payload_bits(payload: bytes) -> bytes:
    """Expand raw bytes into one-byte MSB-first logical bit items."""
    lookup = tuple(bytes((value >> shift) & 1 for shift in range(7, -1, -1)) for value in range(256))
    expanded = bytearray()
    for value in payload:
        expanded.extend(lookup[value])
    return bytes(expanded)


def framing_metadata(config: dict, payload_bit_count: int) -> tuple[dict, bytes, bytes]:
    frame_bytes = int(config["convolutional_code"]["frame_payload_bytes"])
    training_frames = int(config["grc_defaults"]["training_frames"])
    if frame_bytes <= 0 or training_frames <= 0:
        raise ValueError("frame_payload_bytes and training_frames must be positive")
    frame_bits = frame_bytes * 8
    training_bits = training_frames * frame_bits
    tail_bits = training_bits
    training = bytes((0, 1, 1, 0, 1, 0, 0, 1)) * (training_bits // 8)
    tail = bytes((1, 0, 0, 1, 0, 1, 1, 0)) * (tail_bits // 8)
    metadata = {
        "frame_payload_bytes": frame_bytes,
        "frame_bits": frame_bits,
        "training_frames": training_frames,
        "training_bits": training_bits,
        "payload_start_bit": training_bits,
        "payload_bits": payload_bit_count,
        "tail_bits": tail_bits,
        "framed_bits": training_bits + payload_bit_count + tail_bits,
    }
    if metadata["framed_bits"] % frame_bits:
        raise ValueError("Framed stream length must be an integer number of convolutional-code frames")
    return metadata, training, tail


def main() -> None:
    config = load_config()
    input_path = ROOT / str(config.get("source_image", DEFAULT_INPUT.relative_to(ROOT)))
    width = int(config.get("width", 256))
    height = int(config.get("height", 256))
    channels = int(config.get("channels", 3))
    if width <= 0 or height <= 0 or channels != 3:
        raise ValueError("Image dimensions must be positive and channels must equal 3 for RGB8")

    image = normalize_image(input_path, (width, height))
    payload = image.tobytes("raw", "RGB")
    expected_bytes = width * height * channels
    if len(payload) != expected_bytes:
        raise RuntimeError(f"RGB serialization produced {len(payload)} bytes, expected {expected_bytes}")

    TX_RGB.parent.mkdir(parents=True, exist_ok=True)
    NORMALIZED.parent.mkdir(parents=True, exist_ok=True)
    image.save(NORMALIZED, format="PNG")
    TX_RGB.write_bytes(payload)
    image_bits = payload_bits(payload)
    framing, training, tail = framing_metadata(config, len(image_bits))
    TX_FRAMED_BITS.write_bytes(training + image_bits + tail)

    config.update(
        {
            "width": width,
            "height": height,
            "channels": channels,
            "pixel_format": "RGB8",
            "payload_bytes": len(payload),
            "payload_bits": len(payload) * 8,
            "bit_order": "MSB first",
            "tx_rgb_sha256": hashlib.sha256(payload).hexdigest(),
            "normalized_source": "input/normalized_source.png",
            "source_image": str(input_path.relative_to(ROOT)).replace("\\", "/"),
            "framing": framing,
        }
    )
    CONFIG.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {width} x {height} RGB8 image ({len(payload)} bytes)")
    print(f"Framed stream: {framing['framed_bits']} one-byte logical bits")
    print(f"SHA-256: {config['tx_rgb_sha256']}")


if __name__ == "__main__":
    main()
