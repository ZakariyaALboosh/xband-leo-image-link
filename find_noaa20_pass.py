"""Select a reproducible NOAA-20 pass using the frozen project TLE."""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sgp4.api import Satrec, jday
from sgp4.conveniences import sat_epoch_datetime


ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "simulation_config.json"
UTC = timezone.utc


def load_config() -> dict:
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Cannot read {CONFIG}: {exc}") from exc


def julian_date(moment: datetime) -> tuple[float, float]:
    return jday(moment.year, moment.month, moment.day, moment.hour, moment.minute,
                moment.second + moment.microsecond / 1e6)


def ecef_position(position_teme: tuple[float, float, float], jd: float) -> tuple[float, float, float]:
    centuries = (jd - 2451545.0) / 36525.0
    gmst = math.radians((280.46061837 + 360.98564736629 * (jd - 2451545.0)
                         + 0.000387933 * centuries**2 - centuries**3 / 38710000.0) % 360.0)
    x_teme, y_teme, z_teme = position_teme
    return (math.cos(gmst) * x_teme + math.sin(gmst) * y_teme,
            -math.sin(gmst) * x_teme + math.cos(gmst) * y_teme, z_teme)


def ground_ecef(latitude_deg: float, longitude_deg: float, altitude_km: float) -> tuple[float, float, float]:
    latitude = math.radians(latitude_deg)
    longitude = math.radians(longitude_deg)
    semi_major = 6378.137
    eccentricity_sq = 6.69437999014e-3
    prime_vertical = semi_major / math.sqrt(1.0 - eccentricity_sq * math.sin(latitude) ** 2)
    return ((prime_vertical + altitude_km) * math.cos(latitude) * math.cos(longitude),
            (prime_vertical + altitude_km) * math.cos(latitude) * math.sin(longitude),
            (prime_vertical * (1.0 - eccentricity_sq) + altitude_km) * math.sin(latitude))


def elevation(satellite: Satrec, moment: datetime, station: dict) -> float:
    jd, fraction = julian_date(moment)
    error, position, _ = satellite.sgp4(jd, fraction)
    if error:
        raise RuntimeError(f"SGP4 propagation failed with code {error} at {moment.isoformat()}")
    sat_x, sat_y, sat_z = ecef_position(position, jd + fraction)
    gs_x, gs_y, gs_z = ground_ecef(station["latitude_deg"], station["longitude_deg"],
                                    station["altitude_m"] / 1000.0)
    dx, dy, dz = sat_x - gs_x, sat_y - gs_y, sat_z - gs_z
    latitude = math.radians(station["latitude_deg"])
    longitude = math.radians(station["longitude_deg"])
    east = -math.sin(longitude) * dx + math.cos(longitude) * dy
    north = (-math.sin(latitude) * math.cos(longitude) * dx
             - math.sin(latitude) * math.sin(longitude) * dy + math.cos(latitude) * dz)
    up = (math.cos(latitude) * math.cos(longitude) * dx
          + math.cos(latitude) * math.sin(longitude) * dy + math.sin(latitude) * dz)
    return math.degrees(math.atan2(up, math.hypot(east, north)))


def visible_passes(satellite: Satrec, station: dict, start: datetime,
                   duration: timedelta, step: timedelta) -> list[dict]:
    passes: list[dict] = []
    current: dict | None = None
    moment = start
    while moment <= start + duration:
        angle = elevation(satellite, moment, station)
        if angle > 0.0 and current is None:
            current = {"start": moment, "end": moment, "max_time": moment, "max_elevation_deg": angle}
        elif angle > 0.0 and current is not None:
            current["end"] = moment
            if angle > current["max_elevation_deg"]:
                current.update(max_time=moment, max_elevation_deg=angle)
        elif current is not None:
            passes.append(current)
            current = None
        moment += step
    if current is not None:
        passes.append(current)
    return passes


def iso_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def main() -> None:
    config = load_config()
    tle = config["tle"]
    station = config["ground_station"]
    satellite = Satrec.twoline2rv(tle["line1"], tle["line2"])
    epoch = sat_epoch_datetime(satellite).astimezone(UTC)
    candidates = visible_passes(satellite, station, epoch - timedelta(hours=12),
                                 timedelta(days=7), timedelta(seconds=10))
    if not candidates:
        raise RuntimeError("No visible NOAA-20 pass was found within seven days of the TLE epoch")
    preferred = [item for item in candidates if item["max_elevation_deg"] >= 20.0]
    selected = max(preferred or candidates, key=lambda item: item["max_elevation_deg"])
    # A short interval centered on culmination is sufficient for a single image.
    simulation_start = selected["max_time"] - timedelta(seconds=3)
    simulation_end = selected["max_time"] + timedelta(seconds=7)
    config["tle_epoch_utc"] = iso_utc(epoch)
    config["selected_pass"] = {
        "observation_start_utc": iso_utc(selected["start"]),
        "observation_end_utc": iso_utc(selected["end"]),
        "maximum_elevation_deg": round(selected["max_elevation_deg"], 3),
        "maximum_elevation_time_utc": iso_utc(selected["max_time"]),
        "simulation_start_utc": iso_utc(simulation_start),
        "simulation_end_utc": iso_utc(simulation_end),
        "tle": tle,
        "ground_station": station,
        "tle_epoch_utc": iso_utc(epoch),
    }
    CONFIG.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    print(f"Selected pass {iso_utc(selected['start'])} to {iso_utc(selected['end'])}")
    print(f"Maximum elevation: {selected['max_elevation_deg']:.2f} degrees")
    print(f"GRC interval: {iso_utc(simulation_start)} to {iso_utc(simulation_end)}")


if __name__ == "__main__":
    main()
