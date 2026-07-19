# Fixed seeded-noise X-band image-link results

## Methods and configuration

The simplified GNU Radio graph was run independently for five profiles with the existing NASA Terra/MODIS Libya image normalized to 1024×1024 RGB8. Every submitted graph instantiated a 15 Mbit/s information rate, 30 Mbit/s coded rate, 15 Msymbol/s QPSK symbol rate, and 30 MS/s complex sample rate. No payload whitening was used.

gr-leo supplies orbital Doppler and, in profile 4, FSPL, atmosphere, rain, and pointing loss. Its internal unseeded noise is disabled in every profile. A GNU Radio complex Gaussian source with seed 42 is added explicitly after gr-leo. Profiles 2 and 3 use fixed configured sample-domain SNRs of 12 and 5 dB; profile 4 uses the existing kTB amplitude derived from bandwidth, temperature, and receiver noise figure. No BER calibration sweep or result-driven tuning was performed. The configured sample SNR is not claimed as measured Eb/N₀.

**Table 1. Payload and image results.**

| Profile | Channel | Configured SNR (dB) | BER | Bit errors | Coverage | PSNR (dB) | Exact RGB |
|---:|---|---:|---:|---:|---:|---:|:---:|
| 0 | Clean | — | 0 | 0 | 100.00% | ∞ | Yes |
| 1 | Orbital Doppler only | — | 0 | 0 | 100.00% | ∞ | Yes |
| 2 | Doppler plus mild seeded AWGN (12 dB) | 12.0 | 0 | 0 | 100.00% | ∞ | Yes |
| 3 | Doppler plus moderate seeded AWGN (5 dB) | 5.0 | 0 | 0 | 100.00% | ∞ | Yes |
| 4 | Full propagation plus seeded kTB noise | — | 0.500026 | 10,076,689 | 80.08% | 9.07 | No |

**Table 2. Logged channel extrema.**

| Profile | Elevation (deg) | Range (km) | Logged Doppler (Hz) | Path loss (dB) | Link margin (dB) |
|---:|---:|---:|---:|---:|---:|
| 0 | 85.682–86.026 | 832.035–832.372 | 3902.85–6545.51 | 0.000–0.000 | 178.176–178.176 |
| 1 | 85.682–86.026 | 832.035–832.372 | 3902.85–6545.51 | 0.000–0.000 | 178.176–178.176 |
| 2 | 85.682–86.026 | 832.035–832.372 | 3902.85–6545.51 | 0.000–0.000 | 178.176–178.176 |
| 3 | 85.682–86.026 | 832.035–832.372 | 3902.85–6545.51 | 0.000–0.000 | 178.176–178.176 |
| 4 | 85.682–86.026 | 832.035–832.372 | 3902.85–6545.51 | 168.708–168.712 | 8.469–8.473 |

## Objective results

- Profile 0 produced an exact RGB match.
- Profile 1 produced an exact RGB match.
- Profile 2 produced an exact RGB match.
- Profile 3 produced an exact RGB match.
- Profile 4 produced an incomplete decoded stream (80.08% payload coverage) and comparable-prefix BER 5.000e-01.

Profile 0 logs the orbit model's predicted Doppler but instantiates Doppler impairment enumeration zero, so the logged value is not applied. Profile 4 logged FSPL of 168.708–168.712 dB and link margin of 8.469–8.473 dB. These values follow representative educational assumptions and are not NOAA-20 hardware measurements.

## Figures

1. BER by fixed profile; observed zeros are plotted at 0.5/N only for logarithmic display.
2. Logged Doppler and elevation versus simulated time; profile 0 is marked logged-only.
3. Full-profile propagation losses.
4. Original, recovered, and absolute-error images for all profiles. If profile 4 is incomplete, unavailable bytes are visibly marked and excluded from metrics.
5. The two fixed seeded-AWGN results at 12 and 5 dB.

Each figure is supplied as SVG, PDF, and 300-DPI PNG.

## Image attribution

NASA Earth Observatory, “Dust off the Libya coast,” Terra/MODIS image by Jeff Schmaltz, LANCE/EOSDIS MODIS Rapid Response. [Source page](https://earthobservatory.nasa.gov/images/77682/dust-off-the-libya-coast).

## Limitations

- The seeded AWGN profiles are reproducible simulations; their configured sample-domain SNR is not a calibrated receiver Eb/N₀ measurement.
- The full link is a NOAA-20-inspired educational model using representative antennas, transmit power, receiver, and weather assumptions.
- The model omits operational CCSDS/JPSS packetization and decoding, CRC, Reed–Solomon coding, hardware nonlinearities, and unspecified implementation losses.
- QT spectrum and constellation sinks remain runtime diagnostics; static report plots use only preserved payload metrics and gr-leo CSV data.
