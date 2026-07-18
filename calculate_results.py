"""Calculate payload and image fidelity metrics for the simulated link."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "simulation_config.json"
TX_RGB = ROOT / "working" / "tx_image.rgb"
RX_RGB = ROOT / "working" / "rx_image.rgb"
METRICS = ROOT / "results" / "metrics.json"
SUMMARY = ROOT / "results" / "console_summary.txt"


def bit_errors(left: bytes, right: bytes) -> int:
    return sum((a ^ b).bit_count() for a, b in zip(left, right))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        transmitted = TX_RGB.read_bytes()
        received_all = RX_RGB.read_bytes()
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot load simulation data: {exc}") from exc

    expected = int(config["payload_bytes"])
    if len(transmitted) != expected:
        raise ValueError(f"Transmitted RGB has {len(transmitted)} bytes, expected {expected}")
    comparable = min(expected, len(received_all))
    received = received_all[:comparable]
    errors = bit_errors(transmitted[:comparable], received)
    byte_errors = sum(a != b for a, b in zip(transmitted[:comparable], received))
    tx_array = np.frombuffer(transmitted[:comparable], dtype=np.uint8)
    rx_array = np.frombuffer(received, dtype=np.uint8)
    absolute = np.abs(tx_array.astype(np.int16) - rx_array.astype(np.int16))
    complete_pixels = comparable // 3
    pixel_error_count = int(np.any(absolute[: complete_pixels * 3].reshape(-1, 3), axis=1).sum())
    mse = float(np.mean((tx_array.astype(np.float64) - rx_array.astype(np.float64)) ** 2)) if comparable else 0.0
    if not comparable:
        psnr: float | str | None = None
    elif mse == 0.0:
        psnr = "Infinity"
    else:
        psnr = 10.0 * math.log10(255.0**2 / mse)
    tx_hash = sha256(transmitted)
    rx_hash = sha256(received) if comparable == expected else "incomplete"

    metrics = {
        "total_transmitted_payload_bits": expected * 8,
        "total_received_comparable_bits": comparable * 8,
        "bit_errors": errors,
        "ber": errors / (comparable * 8) if comparable else None,
        "byte_errors": byte_errors,
        "byte_error_rate": byte_errors / comparable if comparable else None,
        "pixels_with_error": pixel_error_count,
        "pixel_error_rate": pixel_error_count / complete_pixels if complete_pixels else None,
        "mean_absolute_pixel_error": float(absolute.mean()) if comparable else None,
        "psnr_db": psnr,
        "transmitted_sha256": tx_hash,
        "received_sha256": rx_hash,
        "exact_file_match": comparable == expected and transmitted == received,
        "received_bytes_available": len(received_all),
    }
    rate = config["rates"]
    summary = f"""NOAA-20-Inspired X-Band Image Link Simulation

Information rate:       {rate['information_rate'] / 1e6:.3f} Mbit/s
QPSK symbol rate:       {rate['symbol_rate'] / 1e6:.3f} Msymbol/s
Complex sample rate:    {rate['sample_rate'] / 1e6:.3f} MS/s
Carrier frequency:      {config['carrier_frequency_hz'] / 1e9:.3f} GHz
Convolutional code:     Rate 1/2, K=7
Doppler model:          gr-leo orbital model
Compared payload bits:  {comparable * 8:,}
Bit errors:             {errors:,}
BER:                    {metrics['ber']:.3e}
Exact RGB match:        {'Yes' if metrics['exact_file_match'] else 'No'}
"""
    METRICS.parent.mkdir(parents=True, exist_ok=True)
    METRICS.write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    SUMMARY.write_text(summary, encoding="utf-8")
    print(summary, end="")


if __name__ == "__main__":
    main()
