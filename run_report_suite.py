"""Run the fixed, seeded five-profile 1024x1024 report suite."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
FINAL = RESULTS / "report_submission"
STAGING = RESULTS / "report_submission.in_progress"
GRC = ROOT / "xband_leo_image_link_simple.grc"
LEGACY_GRC = ROOT / "xband_leo_image_link.grc"
CONFIG = ROOT / "simulation_config.json"
GENERATED = ROOT / "xband_leo_image_link_simple.py"
PYTHON = Path("/root/radioconda/bin/python")
GRCC = Path("/root/radioconda/bin/grcc")
SOURCE = ROOT / "input" / "earth_observation_libya_modis_20120417.jpg"
SOURCE_URL = "https://eoimages.gsfc.nasa.gov/images/imagerecords/77000/77682/libya_tmo_2012108_lrg.jpg"
SOURCE_PAGE = "https://earthobservatory.nasa.gov/images/77682/dust-off-the-libya-coast"
SOURCE_CREDIT = "NASA Earth Observatory; Terra MODIS image by Jeff Schmaltz, LANCE/EOSDIS MODIS Rapid Response"
AWGN_SEED = 42
MILD_SNR_DB = 12.0
MODERATE_SNR_DB = 5.0
PROFILE_NAMES = {
    0: "Clean",
    1: "Orbital Doppler only",
    2: "Doppler plus mild seeded AWGN (12 dB)",
    3: "Doppler plus moderate seeded AWGN (5 dB)",
    4: "Full propagation plus seeded kTB noise",
}
PROFILE_DIRS = {
    0: "00_clean",
    1: "01_doppler",
    2: "02_doppler_mild_awgn",
    3: "03_doppler_moderate_awgn",
    4: "04_full_seeded_channel",
}
COMMANDS: list[dict] = []


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def run_command(
    command: list[str], *, log: Path | None = None, env: dict[str, str] | None = None, timeout: int = 900
) -> subprocess.CompletedProcess[str]:
    started = utc_now()
    start = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    elapsed = time.monotonic() - start
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(completed.stdout, encoding="utf-8")
    COMMANDS.append(
        {
            "command": command,
            "working_directory": str(ROOT),
            "started_utc": started,
            "runtime_seconds": elapsed,
            "return_code": completed.returncode,
            "log": str(log.relative_to(STAGING)) if log and STAGING in log.parents else None,
        }
    )
    if completed.returncode:
        raise RuntimeError(f"Command failed ({completed.returncode}): {' '.join(command)}\n{completed.stdout[-2000:]}")
    return completed


def replace_grc_variable(text: str, name: str, value: str) -> str:
    pattern = re.compile(
        rf"(- name: {re.escape(name)}\n  id: variable\n  parameters: \{{[^\n]*?value: )([^,}}]+)(\}})"
    )
    result, count = pattern.subn(rf"\g<1>{value}\g<3>", text, count=1)
    if count != 1:
        raise RuntimeError(f"Could not set GRC variable {name}")
    return result


def grc_snapshot(original: str, *, profile: int, width: int, height: int) -> str:
    values = {
        "rate_scale": "'1.0'",
        "channel_profile": f"'{profile}'",
        "mild_snr_db": f"'{MILD_SNR_DB:.1f}'",
        "moderate_snr_db": f"'{MODERATE_SNR_DB:.1f}'",
        "awgn_seed": f"'{AWGN_SEED}'",
        "image_width": f"'{width}'",
        "image_height": f"'{height}'",
    }
    result = original
    for name, value in values.items():
        result = replace_grc_variable(result, name, value)
    return result


def configure(base: dict, *, profile: int, width: int, height: int) -> None:
    config = json.loads(json.dumps(base))
    config.update(
        {
            "rate_mode": "full",
            "rate_scale": 1.0,
            "width": width,
            "height": height,
            "channels": 3,
            "image_fit": "stretch",
            "source_image": str(SOURCE.relative_to(ROOT)),
            "source_image_url": SOURCE_URL,
            "source_image_page": SOURCE_PAGE,
            "source_image_credit": SOURCE_CREDIT,
        }
    )
    config["rates"] = {
        "information_rate": 15_000_000.0,
        "coded_bit_rate": 30_000_000.0,
        "symbol_rate": 15_000_000.0,
        "sample_rate": 30_000_000.0,
        "occupied_bandwidth": 20_250_000.0,
    }
    config["grc_defaults"].update(
        {
            "channel_profile": profile,
            "mild_snr_db": MILD_SNR_DB,
            "moderate_snr_db": MODERATE_SNR_DB,
            "awgn_seed": AWGN_SEED,
        }
    )
    config["deterministic_noise"] = {
        "implementation": "GNU Radio analog complex Gaussian noise source plus complex adder",
        "seed": AWGN_SEED,
        "grleo_internal_noise": 0,
        "mild_sample_snr_db": MILD_SNR_DB,
        "moderate_sample_snr_db": MODERATE_SNR_DB,
        "full_profile": "seeded kTB amplitude",
    }
    write_json(CONFIG, config)


def expected_instantiated(profile: int, width: int, height: int, taps_energy: float) -> dict:
    nominal_power = 0.25 * taps_energy / 2.0
    thermal = math.sqrt(1000 * 1.38e-23 * 290.0 * 20_250_000.0 * 10 ** (1.0 / 10))
    if profile < 2:
        noise = 0.0
    elif profile in (2, 3):
        snr = MILD_SNR_DB if profile == 2 else MODERATE_SNR_DB
        noise = math.sqrt(nominal_power / 10 ** (snr / 10))
    else:
        noise = thermal
    return {
        "rate_scale": 1.0,
        "channel_profile": profile,
        "mild_snr_db": MILD_SNR_DB,
        "moderate_snr_db": MODERATE_SNR_DB,
        "awgn_seed": AWGN_SEED,
        "information_rate": 15_000_000.0,
        "coded_bit_rate": 30_000_000.0,
        "symbol_rate": 15_000_000.0,
        "sample_rate": 30_000_000.0,
        "image_width": width,
        "image_height": height,
        "channel_doppler": 7 if profile >= 1 else 0,
        "channel_fspl": 5 if profile == 4 else 0,
        "channel_atmosphere": 1 if profile == 4 else 0,
        "channel_rain": 4 if profile == 4 else 0,
        "channel_pointing": 6 if profile == 4 else 0,
        "channel_noise": 0,
        "nominal_sample_power": nominal_power,
        "awgn_noise_amplitude": noise,
    }


def verify_generated(profile: int, width: int, height: int, output: Path) -> dict:
    code = (
        "import json; import xband_leo_image_link_simple as m; app=m.Qt.QApplication([]); "
        "tb=m.xband_leo_image_link_simple(); print('INSTANTIATED='+json.dumps({"
        "'rate_scale':tb.rate_scale,'channel_profile':tb.channel_profile,'mild_snr_db':tb.mild_snr_db,"
        "'moderate_snr_db':tb.moderate_snr_db,'awgn_seed':tb.awgn_seed,"
        "'information_rate':tb.information_rate,'coded_bit_rate':tb.coded_bit_rate,"
        "'symbol_rate':tb.symbol_rate,'sample_rate':tb.sample_rate,'image_width':tb.image_width,"
        "'image_height':tb.image_height,'channel_doppler':tb.channel_doppler,"
        "'channel_fspl':tb.channel_fspl,'channel_atmosphere':tb.channel_atmosphere,"
        "'channel_rain':tb.channel_rain,'channel_pointing':tb.channel_pointing,"
        "'channel_noise':tb.channel_noise,'nominal_sample_power':tb.nominal_sample_power,"
        "'awgn_noise_amplitude':tb.awgn_noise_amplitude,'rrc_taps_energy':sum(x*x for x in tb.rrc_taps)})); "
        "tb.stop(); tb.wait()"
    )
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    completed = run_command([str(PYTHON), "-c", code], log=output.with_suffix(".log"), env=env)
    lines = [line for line in completed.stdout.splitlines() if line.startswith("INSTANTIATED=")]
    if len(lines) != 1:
        raise RuntimeError("Generated-flowgraph verification did not return instantiated parameters")
    actual = json.loads(lines[0].split("=", 1)[1])
    expected = expected_instantiated(profile, width, height, actual.pop("rrc_taps_energy"))
    for key, expected_value in expected.items():
        actual_value = actual[key]
        if isinstance(expected_value, float):
            if not math.isclose(actual_value, expected_value, rel_tol=1e-12, abs_tol=1e-15):
                raise RuntimeError(f"Instantiated {key}={actual_value}, expected {expected_value}")
        elif actual_value != expected_value:
            raise RuntimeError(f"Instantiated {key}={actual_value}, expected {expected_value}")
    write_json(output, {"verification": "passed", "actual_instantiated_values": actual})
    return actual


def clean_runtime_outputs() -> None:
    for path in (
        ROOT / "working" / "rx_decoded_bits.bin",
        ROOT / "working" / "rx_image.rgb",
        RESULTS / "channel_log.csv",
        RESULTS / "recovered_image.png",
        RESULTS / "comparison.png",
        RESULTS / "metrics.json",
        RESULTS / "console_summary.txt",
    ):
        path.unlink(missing_ok=True)


def channel_stats(path: Path) -> dict:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise RuntimeError(f"Channel CSV is empty: {path}")
    headings = {
        "range": "Slant Range (km)",
        "elevation": "Elevation (degrees)",
        "path_loss": "Path Loss (dB)",
        "atmospheric_loss": "Atmospheric Loss (dB)",
        "rainfall_loss": "Rainfall Loss (dB)",
        "pointing_loss": "Pointing Loss (dB)",
        "doppler": "Doppler Shift (Hz)",
        "link_margin": "Link Margin (dB)",
    }
    result: dict[str, object] = {"sample_count": len(rows)}
    for short, heading in headings.items():
        values = [float(row[heading]) for row in rows]
        result[f"{short}_min"] = min(values)
        result[f"{short}_max"] = max(values)
    result["first_timestamp_utc"] = rows[0]["Elapsed Time (us)"]
    result["last_timestamp_utc"] = rows[-1]["Elapsed Time (us)"]
    return result


def copy_artifact(source: Path, target_dir: Path) -> None:
    if not source.is_file() or source.stat().st_size == 0:
        raise RuntimeError(f"Required artifact missing or empty: {source}")
    shutil.copy2(source, target_dir / source.name)


def reconstruct_available(config: dict, decoded: Path) -> tuple[int, int]:
    framing = config["framing"]
    start = int(framing["payload_start_bit"])
    total = int(framing["payload_bits"])
    bits = np.frombuffer(decoded.read_bytes(), dtype=np.uint8)
    available = max(0, min(total, bits.size - start))
    available -= available % 8
    if available <= 0:
        raise RuntimeError("Decoded stream contains no byte-aligned payload prefix")
    received = np.packbits(bits[start : start + available], bitorder="big").tobytes()
    (ROOT / "working" / "rx_image.rgb").write_bytes(received)
    return available, total


def create_incomplete_images(config: dict, available_bits: int) -> None:
    width, height = int(config["width"]), int(config["height"])
    transmitted = np.frombuffer((ROOT / "working" / "tx_image.rgb").read_bytes(), dtype=np.uint8)
    received = np.frombuffer((ROOT / "working" / "rx_image.rgb").read_bytes(), dtype=np.uint8)
    shown = np.empty_like(transmitted)
    shown[: received.size] = received
    shown[received.size :] = np.resize(np.array([96, 176], dtype=np.uint8), shown.size - received.size)
    original_image = Image.fromarray(transmitted.reshape(height, width, 3), "RGB")
    recovered_image = Image.fromarray(shown.reshape(height, width, 3), "RGB")
    recovered_image.save(RESULTS / "recovered_image.png")
    from reconstruct_image import labeled_comparison

    labeled_comparison(original_image, recovered_image).save(RESULTS / "comparison.png")
    write_json(
        RESULTS / "incomplete_recovery.json",
        {
            "payload_bits_available": available_bits,
            "payload_bits_total": int(config["framing"]["payload_bits"]),
            "visualization": "Unavailable suffix is marked with alternating gray values and excluded from metrics.",
        },
    )


def freeze_run(
    base_config: dict,
    original_grc: str,
    target: Path,
    *,
    profile: int,
    width: int,
    height: int,
    run_label: str,
) -> dict:
    if target.exists():
        raise RuntimeError(f"Refusing to overwrite immutable run folder: {target}")
    target.mkdir(parents=True)
    started = utc_now()
    configure(base_config, profile=profile, width=width, height=height)
    run_command([str(PYTHON), "prepare_image.py"], log=target / "prepare_image.log")
    snapshot = target / GRC.name
    snapshot.write_text(grc_snapshot(original_grc, profile=profile, width=width, height=height), encoding="utf-8")
    shutil.copy2(CONFIG, target / CONFIG.name)
    run_command([str(GRCC), "-o", str(ROOT), str(snapshot)], log=target / "grcc.log")
    shutil.copy2(GENERATED, target / GENERATED.name)
    actual = verify_generated(profile, width, height, target / "instantiated_parameters.json")
    clean_runtime_outputs()
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "offscreen"
    runtime_code = (
        "import xband_leo_image_link_simple as m; app=m.Qt.QApplication([]); "
        "tb=m.xband_leo_image_link_simple(); tb.start(); tb.wait(); tb.stop()"
    )
    runtime_start = time.monotonic()
    run_command([str(PYTHON), "-u", "-c", runtime_code], log=target / "flowgraph_console.log", env=env)
    runtime_seconds = time.monotonic() - runtime_start
    decoded = ROOT / "working" / "rx_decoded_bits.bin"
    channel_csv = RESULTS / "channel_log.csv"
    if not decoded.is_file() or not channel_csv.is_file() or channel_csv.stat().st_size == 0:
        raise RuntimeError("Flowgraph did not produce decoded bits and a nonempty channel CSV")
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    required = int(config["framing"]["payload_start_bit"]) + int(config["framing"]["payload_bits"])
    incomplete = decoded.stat().st_size < required
    if not incomplete:
        run_command([str(PYTHON), "reconstruct_image.py", "--source", "decoded"], log=target / "reconstruct_image.log")
        available_bits = int(config["framing"]["payload_bits"])
    elif profile == 4:
        available_bits, _ = reconstruct_available(config, decoded)
        create_incomplete_images(config, available_bits)
        (target / "reconstruct_image.log").write_text(
            f"Incomplete decoded stream: {decoded.stat().st_size} bits; {required} required.\n",
            encoding="utf-8",
        )
    else:
        raise RuntimeError(f"Profile {profile} decoded {decoded.stat().st_size} bits; {required} are required")
    run_command([str(PYTHON), "calculate_results.py"], log=target / "calculate_results.log")
    artifacts = [
        CONFIG,
        ROOT / "input" / "normalized_source.png",
        ROOT / "working" / "tx_image.rgb",
        ROOT / "working" / "tx_framed_bits.bin",
        decoded,
        ROOT / "working" / "rx_image.rgb",
        channel_csv,
        RESULTS / "metrics.json",
        RESULTS / "console_summary.txt",
        RESULTS / "recovered_image.png",
        RESULTS / "comparison.png",
    ]
    if incomplete:
        artifacts.append(RESULTS / "incomplete_recovery.json")
    for artifact in artifacts:
        copy_artifact(artifact, target)
    metrics = json.loads((target / "metrics.json").read_text(encoding="utf-8"))
    channel = channel_stats(target / "channel_log.csv")
    record = {
        "run_label": run_label,
        "profile_number": profile,
        "profile_name": PROFILE_NAMES[profile],
        "configured_sample_snr_db": MILD_SNR_DB if profile == 2 else MODERATE_SNR_DB if profile == 3 else None,
        "noise_seed": AWGN_SEED,
        "started_utc": started,
        "completed_utc": utc_now(),
        "runtime_seconds": runtime_seconds,
        "run_status": "incomplete_decoded_stream" if incomplete else "complete",
        "failure": f"Decoded output has {decoded.stat().st_size} bits; {required} required." if incomplete else None,
        "decoded_bit_items": decoded.stat().st_size,
        "required_bits_through_payload": required,
        "payload_coverage": available_bits / int(config["framing"]["payload_bits"]),
        "instantiated": actual,
        "metrics": metrics,
        "channel": channel,
    }
    write_json(target / "run_manifest.json", record)
    hashes = {
        path.name: sha256(path)
        for path in sorted(target.iterdir())
        if path.is_file() and path.name != "artifact_sha256.json"
    }
    write_json(target / "artifact_sha256.json", hashes)
    print(
        f"{run_label}: status={record['run_status']}, BER={metrics['ber']:.6g}, "
        f"exact={metrics['exact_file_match']}, runtime={runtime_seconds:.2f}s",
        flush=True,
    )
    return record


def save_figure(fig: plt.Figure, stem: str) -> None:
    folder = STAGING / "figures"
    folder.mkdir(exist_ok=True)
    fig.savefig(folder / f"{stem}.svg", bbox_inches="tight")
    fig.savefig(folder / f"{stem}.pdf", bbox_inches="tight")
    fig.savefig(folder / f"{stem}.png", dpi=300, bbox_inches="tight")
    plt.close(fig)


def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def numeric_series(path: Path, heading: str) -> np.ndarray:
    return np.array([float(row[heading]) for row in csv_rows(path)], dtype=float)


def make_figures(records: list[dict]) -> None:
    plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.25})
    floor = 0.5 / 25_165_824
    bers = [record["metrics"]["ber"] for record in records]
    fig, ax = plt.subplots(figsize=(6.8, 3.8))
    plotted = [max(value, floor) for value in bers]
    bars = ax.bar([f"P{r['profile_number']}" for r in records], plotted, color="0.75", edgecolor="black")
    for bar, hatch in zip(bars, ["//", "..", "xx", "--", "\\\\"]):
        bar.set_hatch(hatch)
    ax.set_yscale("log")
    ax.set_ylabel("Post-Viterbi payload BER")
    ax.set_title("BER by fixed channel profile")
    for index, value in enumerate(bers):
        ax.annotate("0 observed" if value == 0 else f"{value:.2e}", (index, plotted[index]), xytext=(0, 5), textcoords="offset points", ha="center")
    ax.set_ylim(floor / 3, max(plotted) * 8)
    save_figure(fig, "figure_1_ber_by_profile")

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7.2, 5.7))
    for record, style in zip(records, [":", "-", "--", "-.", (0, (3, 1, 1, 1))]):
        path = STAGING / "profiles" / PROFILE_DIRS[record["profile_number"]] / "channel_log.csv"
        doppler = numeric_series(path, "Doppler Shift (Hz)")
        elevation = numeric_series(path, "Elevation (degrees)")
        t = np.arange(doppler.size) / 1000.0
        suffix = " logged only" if record["profile_number"] == 0 else ""
        ax1.plot(t, doppler / 1000, linestyle=style, color="black", label=f"P{record['profile_number']}{suffix}")
        ax2.plot(t, elevation, linestyle=style, color="black", label=f"P{record['profile_number']}")
    ax1.set_ylabel("Logged Doppler (kHz)")
    ax1.set_title("Orbital Doppler versus simulated time")
    ax1.legend(fontsize=7)
    ax2.set_xlabel("Simulated time from first CSV sample (s)")
    ax2.set_ylabel("Elevation (degrees)")
    ax2.set_title("Elevation versus simulated time")
    ax2.legend(fontsize=7)
    fig.tight_layout()
    save_figure(fig, "figure_2_doppler_elevation")

    full_path = STAGING / "profiles" / PROFILE_DIRS[4] / "channel_log.csv"
    path_loss = numeric_series(full_path, "Path Loss (dB)")
    t = np.arange(path_loss.size) / 1000.0
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 5.7), sharex=True)
    axes[0].plot(t, path_loss, color="black")
    axes[0].set_ylabel("FSPL (dB)")
    axes[0].set_title("Full-profile free-space path loss")
    axes[0].ticklabel_format(axis="y", style="plain", useOffset=False)
    for heading, label, style in (
        ("Atmospheric Loss (dB)", "Atmosphere", "-"),
        ("Rainfall Loss (dB)", "Rain", "--"),
        ("Pointing Loss (dB)", "Pointing", ":"),
    ):
        axes[1].plot(t, numeric_series(full_path, heading), style, color="black", label=label)
    axes[1].set_xlabel("Simulated time from first CSV sample (s)")
    axes[1].set_ylabel("Additional loss (dB)")
    axes[1].set_title("Full-profile additional losses")
    axes[1].legend()
    fig.tight_layout()
    save_figure(fig, "figure_3_full_profile_losses")

    fig, axes = plt.subplots(5, 3, figsize=(9, 14))
    for row, record in enumerate(records):
        folder = STAGING / "profiles" / PROFILE_DIRS[record["profile_number"]]
        original = np.asarray(Image.open(folder / "normalized_source.png").convert("RGB"))
        recovered = np.asarray(Image.open(folder / "recovered_image.png").convert("RGB"))
        error = np.abs(original.astype(np.int16) - recovered.astype(np.int16)).astype(np.uint8)
        for column, (array, label) in enumerate(zip((original, recovered, error), ("Original", "Recovered", "Absolute error"))):
            axes[row, column].imshow(array)
            axes[row, column].set_title(f"P{record['profile_number']} {label}")
            axes[row, column].axis("off")
    fig.suptitle("Original, recovered, and absolute-error images", y=0.997)
    fig.tight_layout()
    save_figure(fig, "figure_4_image_comparisons")

    noise_records = [record for record in records if record["profile_number"] in (2, 3)]
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    x = [record["configured_sample_snr_db"] for record in noise_records]
    y = [max(record["metrics"]["ber"], floor) for record in noise_records]
    ax.semilogy(x, y, "o-", color="black", markerfacecolor="white")
    for snr, plotted_ber, record in zip(x, y, noise_records):
        text = "0 observed" if record["metrics"]["ber"] == 0 else f"{record['metrics']['ber']:.2e}"
        ax.annotate(text, (snr, plotted_ber), xytext=(0, 7), textcoords="offset points", ha="center")
    ax.set_xlabel("Configured sample-domain SNR (dB)")
    ax.set_ylabel("Post-Viterbi payload BER")
    ax.set_title("Fixed seeded-AWGN profiles (seed 42)")
    ax.set_xticks(sorted(x))
    ax.set_xlim(min(x) - 0.8, max(x) + 0.8)
    save_figure(fig, "figure_5_fixed_awgn_comparison")


def write_tables(records: list[dict]) -> None:
    profile_fields = [
        "profile_number", "profile_name", "run_status", "configured_sample_snr_db", "noise_seed",
        "ber", "bit_errors", "comparable_bits", "payload_coverage", "byte_errors", "pixels_with_error",
        "psnr_db", "exact_match", "decoded_bit_items", "runtime_seconds",
    ]
    channel_fields = [
        "profile_number", "profile_name", "elevation_min_deg", "elevation_max_deg", "range_min_km",
        "range_max_km", "doppler_min_hz", "doppler_max_hz", "path_loss_min_db", "path_loss_max_db",
        "atmospheric_loss_min_db", "atmospheric_loss_max_db", "rainfall_loss_min_db",
        "rainfall_loss_max_db", "pointing_loss_min_db", "pointing_loss_max_db",
        "link_margin_min_db", "link_margin_max_db",
    ]
    profile_rows, channel_rows = [], []
    for record in records:
        metrics, channel = record["metrics"], record["channel"]
        profile_rows.append(
            {
                "profile_number": record["profile_number"], "profile_name": record["profile_name"],
                "run_status": record["run_status"], "configured_sample_snr_db": record["configured_sample_snr_db"],
                "noise_seed": record["noise_seed"], "ber": metrics["ber"], "bit_errors": metrics["bit_errors"],
                "comparable_bits": metrics["total_received_comparable_bits"], "payload_coverage": record["payload_coverage"],
                "byte_errors": metrics["byte_errors"], "pixels_with_error": metrics["pixels_with_error"],
                "psnr_db": metrics["psnr_db"], "exact_match": metrics["exact_file_match"],
                "decoded_bit_items": record["decoded_bit_items"], "runtime_seconds": record["runtime_seconds"],
            }
        )
        channel_rows.append(
            {
                "profile_number": record["profile_number"], "profile_name": record["profile_name"],
                "elevation_min_deg": channel["elevation_min"], "elevation_max_deg": channel["elevation_max"],
                "range_min_km": channel["range_min"], "range_max_km": channel["range_max"],
                "doppler_min_hz": channel["doppler_min"], "doppler_max_hz": channel["doppler_max"],
                "path_loss_min_db": channel["path_loss_min"], "path_loss_max_db": channel["path_loss_max"],
                "atmospheric_loss_min_db": channel["atmospheric_loss_min"], "atmospheric_loss_max_db": channel["atmospheric_loss_max"],
                "rainfall_loss_min_db": channel["rainfall_loss_min"], "rainfall_loss_max_db": channel["rainfall_loss_max"],
                "pointing_loss_min_db": channel["pointing_loss_min"], "pointing_loss_max_db": channel["pointing_loss_max"],
                "link_margin_min_db": channel["link_margin_min"], "link_margin_max_db": channel["link_margin_max"],
            }
        )
    for path, fields, rows in (
        (STAGING / "profile_summary.csv", profile_fields, profile_rows),
        (STAGING / "channel_summary.csv", channel_fields, channel_rows),
    ):
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


def psnr_text(value: object) -> str:
    return "∞" if value == "Infinity" else f"{float(value):.2f}"


def write_report(records: list[dict]) -> None:
    results_rows = "\n".join(
        f"| {r['profile_number']} | {r['profile_name']} | {r['configured_sample_snr_db'] if r['configured_sample_snr_db'] is not None else '—'} | "
        f"{r['metrics']['ber']:.6g} | {r['metrics']['bit_errors']:,} | {r['payload_coverage']:.2%} | "
        f"{psnr_text(r['metrics']['psnr_db'])} | {'Yes' if r['metrics']['exact_file_match'] else 'No'} |"
        for r in records
    )
    channel_rows = "\n".join(
        f"| {r['profile_number']} | {r['channel']['elevation_min']:.3f}–{r['channel']['elevation_max']:.3f} | "
        f"{r['channel']['range_min']:.3f}–{r['channel']['range_max']:.3f} | "
        f"{r['channel']['doppler_min']:.2f}–{r['channel']['doppler_max']:.2f} | "
        f"{r['channel']['path_loss_min']:.3f}–{r['channel']['path_loss_max']:.3f} | "
        f"{r['channel']['link_margin_min']:.3f}–{r['channel']['link_margin_max']:.3f} |"
        for r in records
    )
    observations = []
    for record in records:
        if record["run_status"] == "complete":
            condition = "an exact RGB match" if record["metrics"]["exact_file_match"] else f"BER {record['metrics']['ber']:.3e}"
        else:
            condition = f"an incomplete decoded stream ({record['payload_coverage']:.2%} payload coverage) and comparable-prefix BER {record['metrics']['ber']:.3e}"
        observations.append(f"- Profile {record['profile_number']} produced {condition}.")
    full = records[4]
    report = f"""# Fixed seeded-noise X-band image-link results

## Methods and configuration

The simplified GNU Radio graph was run independently for five profiles with the existing NASA Terra/MODIS Libya image normalized to 1024×1024 RGB8. Every submitted graph instantiated a 15 Mbit/s information rate, 30 Mbit/s coded rate, 15 Msymbol/s QPSK symbol rate, and 30 MS/s complex sample rate. No payload whitening was used.

gr-leo supplies orbital Doppler and, in profile 4, FSPL, atmosphere, rain, and pointing loss. Its internal unseeded noise is disabled in every profile. A GNU Radio complex Gaussian source with seed 42 is added explicitly after gr-leo. Profiles 2 and 3 use fixed configured sample-domain SNRs of 12 and 5 dB; profile 4 uses the existing kTB amplitude derived from bandwidth, temperature, and receiver noise figure. No BER calibration sweep or result-driven tuning was performed. The configured sample SNR is not claimed as measured Eb/N₀.

**Table 1. Payload and image results.**

| Profile | Channel | Configured SNR (dB) | BER | Bit errors | Coverage | PSNR (dB) | Exact RGB |
|---:|---|---:|---:|---:|---:|---:|:---:|
{results_rows}

**Table 2. Logged channel extrema.**

| Profile | Elevation (deg) | Range (km) | Logged Doppler (Hz) | Path loss (dB) | Link margin (dB) |
|---:|---:|---:|---:|---:|---:|
{channel_rows}

## Objective results

{chr(10).join(observations)}

Profile 0 logs the orbit model's predicted Doppler but instantiates Doppler impairment enumeration zero, so the logged value is not applied. Profile 4 logged FSPL of {full['channel']['path_loss_min']:.3f}–{full['channel']['path_loss_max']:.3f} dB and link margin of {full['channel']['link_margin_min']:.3f}–{full['channel']['link_margin_max']:.3f} dB. These values follow representative educational assumptions and are not NOAA-20 hardware measurements.

## Figures

1. BER by fixed profile; observed zeros are plotted at 0.5/N only for logarithmic display.
2. Logged Doppler and elevation versus simulated time; profile 0 is marked logged-only.
3. Full-profile propagation losses.
4. Original, recovered, and absolute-error images for all profiles. If profile 4 is incomplete, unavailable bytes are visibly marked and excluded from metrics.
5. The two fixed seeded-AWGN results at 12 and 5 dB.

Each figure is supplied as SVG, PDF, and 300-DPI PNG.

## Image attribution

NASA Earth Observatory, “Dust off the Libya coast,” Terra/MODIS image by Jeff Schmaltz, LANCE/EOSDIS MODIS Rapid Response. [Source page]({SOURCE_PAGE}).

## Limitations

- The seeded AWGN profiles are reproducible simulations; their configured sample-domain SNR is not a calibrated receiver Eb/N₀ measurement.
- The full link is a NOAA-20-inspired educational model using representative antennas, transmit power, receiver, and weather assumptions.
- The model omits operational CCSDS/JPSS packetization and decoding, CRC, Reed–Solomon coding, hardware nonlinearities, and unspecified implementation losses.
- QT spectrum and constellation sinks remain runtime diagnostics; static report plots use only preserved payload metrics and gr-leo CSV data.
"""
    (STAGING / "report_results.md").write_text(report, encoding="utf-8")


def environment_versions() -> dict:
    code = (
        "import json,sys,PIL,numpy,matplotlib; from gnuradio import gr,leo; "
        "print(json.dumps({'python':sys.version.split()[0],'gnu_radio':gr.version(),"
        "'gnuradio_leo':getattr(leo,'__version__','1.0.0.post20250214+g8f62b92'),"
        "'pillow':PIL.__version__,'numpy':numpy.__version__,'matplotlib':matplotlib.__version__}))"
    )
    return json.loads(subprocess.check_output([str(PYTHON), "-c", code], cwd=ROOT, text=True))


def package_hashes(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "package_sha256.json"
    }


def main() -> None:
    if FINAL.exists() or STAGING.exists():
        raise RuntimeError("A report submission or in-progress folder already exists; refusing to overwrite it")
    if not SOURCE.is_file() or SOURCE.stat().st_size == 0:
        raise RuntimeError(f"NASA source image is missing: {SOURCE}")
    STAGING.mkdir(parents=True)
    original_config = CONFIG.read_text(encoding="utf-8")
    original_grc = GRC.read_text(encoding="utf-8")
    base_config = json.loads(original_config)
    legacy_hash_before = sha256(LEGACY_GRC)
    suite_started = utc_now()
    records: list[dict] = []
    try:
        source_dir = STAGING / "source"
        source_dir.mkdir()
        shutil.copy2(SOURCE, source_dir / SOURCE.name)
        with Image.open(SOURCE) as image:
            dimensions = list(image.size)
        write_json(
            source_dir / "source_metadata.json",
            {
                "title": "Dust off the Libya coast",
                "original_dimensions": dimensions,
                "source_page": SOURCE_PAGE,
                "download_url": SOURCE_URL,
                "sha256": sha256(SOURCE),
                "credit": SOURCE_CREDIT,
            },
        )

        validation_dir = STAGING / "validation" / "seeded_determinism"
        validation_dir.mkdir(parents=True)
        run_a = freeze_run(base_config, original_grc, validation_dir / "run_a", profile=2, width=256, height=256, run_label="determinism_run_a")
        run_b = freeze_run(base_config, original_grc, validation_dir / "run_b", profile=2, width=256, height=256, run_label="determinism_run_b")
        hash_a = sha256(validation_dir / "run_a" / "rx_decoded_bits.bin")
        hash_b = sha256(validation_dir / "run_b" / "rx_decoded_bits.bin")
        if hash_a != hash_b or run_a["metrics"] != run_b["metrics"]:
            raise RuntimeError("Seeded AWGN determinism regression produced different decoded hashes or metrics")
        write_json(validation_dir / "determinism_result.json", {"passed": True, "seed": AWGN_SEED, "decoded_sha256": hash_a, "metrics_identical": True})

        profiles_dir = STAGING / "profiles"
        profiles_dir.mkdir()
        for profile in range(5):
            record = freeze_run(
                base_config,
                original_grc,
                profiles_dir / PROFILE_DIRS[profile],
                profile=profile,
                width=1024,
                height=1024,
                run_label=f"profile_{profile}",
            )
            if profile in (0, 1) and not record["metrics"]["exact_file_match"]:
                raise RuntimeError(f"Profile {profile} failed the exact-RGB acceptance requirement")
            records.append(record)

        write_tables(records)
        make_figures(records)
        write_report(records)
        legacy_hash_after = sha256(LEGACY_GRC)
        if legacy_hash_after != legacy_hash_before:
            raise RuntimeError("Detailed legacy GRC changed during the suite")
        git_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        manifest = {
            "suite": "Fixed seeded-noise 1024x1024 GNU Radio report run",
            "started_utc": suite_started,
            "completed_utc": utc_now(),
            "git_commit": git_commit,
            "environment": {**environment_versions(), "platform": platform.platform(), "qt_platform": "offscreen"},
            "source": json.loads((source_dir / "source_metadata.json").read_text(encoding="utf-8")),
            "payload": {"width": 1024, "height": 1024, "channels": 3, "format": "RGB8", "bits": 25_165_824, "image_fit": "stretch", "payload_whitening": False},
            "rates": {"information_bit_s": 15_000_000, "coded_bit_s": 30_000_000, "symbol_s": 15_000_000, "sample_s": 30_000_000},
            "noise": {"implementation": "seeded complex Gaussian source after gr-leo", "seed": AWGN_SEED, "mild_sample_snr_db": MILD_SNR_DB, "moderate_sample_snr_db": MODERATE_SNR_DB, "grleo_internal_noise": 0, "full_profile": "seeded kTB amplitude"},
            "tle": base_config["tle"],
            "ground_station": base_config["ground_station"],
            "representative_link_assumptions": base_config["representative_link_assumptions"],
            "selected_pass": base_config["selected_pass"],
            "profiles": [{"number": number, "name": PROFILE_NAMES[number], "folder": f"profiles/{PROFILE_DIRS[number]}"} for number in range(5)],
            "determinism_validation": json.loads((validation_dir / "determinism_result.json").read_text(encoding="utf-8")),
            "commands": COMMANDS,
            "graph_hashes": {"simple_source_sha256": sha256(GRC), "detailed_legacy_before_sha256": legacy_hash_before, "detailed_legacy_after_sha256": legacy_hash_after},
            "archived_diagnostics": "results/diagnostics/unseeded_noise_aborted_20260719 (not part of this submission package)",
        }
        write_json(STAGING / "experiment_manifest.json", manifest)
    finally:
        GRC.write_text(original_grc, encoding="utf-8")
        CONFIG.write_text(original_config, encoding="utf-8")
        run_command([str(PYTHON), "prepare_image.py"], log=STAGING / "restore_prepare_image.log")
        run_command([str(GRCC), "-o", str(ROOT), str(GRC)], log=STAGING / "restore_grcc.log")
    manifest_path = STAGING / "experiment_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["completed_utc"] = utc_now()
    manifest["commands"] = COMMANDS
    write_json(manifest_path, manifest)
    write_json(STAGING / "package_sha256.json", package_hashes(STAGING))
    STAGING.rename(FINAL)
    print(f"Report package complete: {FINAL}", flush=True)


if __name__ == "__main__":
    main()
