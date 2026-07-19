# NOAA-20-Inspired X-Band LEO Image Link

> A NOAA-20-inspired X-band direct-broadcast image-link simulation implemented in GNU Radio Companion. The model uses representative QPSK data-rate and convolutional-coding parameters and applies orbit-dependent propagation impairments using gr-leo. It is a system-level educational simulation and not a complete operational NOAA-20 HRD decoder.

This repository contains two editable GNU Radio Companion implementations:

- `xband_leo_image_link_simple.grc` is the recommended, single-receiver flowgraph.
- `xband_leo_image_link.grc` is the unchanged detailed reference with manual framing, two receiver branches, and additional diagnostics.

Both graphs keep all communications DSP on the GRC canvas. There are no Embedded Python Blocks and no hand-written `gr.top_block`. FPGA processing and operational CCSDS/JPSS decoding are future work only.

## Simplified architecture

```text
Image preparation
→ convolutional coding
→ QPSK modulation
→ gr-leo X-band channel
→ synchronized QPSK receiver
→ Viterbi decoding
→ image reconstruction
```

The visible main path is:

```text
Framed Bit File Source
→ Extended Encoder
→ Repack Bits 1→2
→ Differential Encoder
→ QPSK Constellation Encoder
→ RRC Interpolating FIR
→ amplitude control
→ Throttle
→ gr-leo Channel Model
→ AGC
→ RRC matched FIR
→ FLL Band-Edge
→ Gardner Symbol Sync
→ fourth-order Costas Loop
→ QPSK Constellation Decoder
→ Differential Decoder
→ Repack Bits 2→1
→ coded-stream alignment
→ hard-to-soft conversion
→ Extended Decoder (Viterbi)
→ Decoded Bit File Sink
```

It has 22 main-path blocks when file I/O and representation adapters are counted. It contains one synchronized receiver, two GUI sinks (`Received Spectrum` and `Recovered Constellation`), and no receiver selector.

## Verified environment

Validation used:

- GNU Radio 3.10.12.0
- `gnuradio-leo` 1.0.0.post20250214+g8f62b92
- Python 3.13.14

This package exposes gr-leo as `from gnuradio import leo`. The installed package contained `leo_channel.grc`; its GRC YAML and source were inspected for the exact block IDs and parameters used here.

```bat
gnuradio-companion --help
python -c "from gnuradio import gr, blocks, digital, filter, fec, qtgui; print('GNU Radio', gr.version())"
python -c "from gnuradio import leo; print('gr-leo import OK:', leo.__file__)"
dir "%CONDA_PREFIX%\share\gnuradio\examples\leo"
```

If gr-leo is absent, install it explicitly from a Radioconda Prompt:

```bat
conda install ryanvolz::gnuradio-leo
```

The project does not install or modify the environment automatically.

## Windows Radioconda workflow

From the repository directory:

```bat
python prepare_image.py
python find_noaa20_pass.py
gnuradio-companion xband_leo_image_link_simple.grc
```

Generate and run without opening GRC:

```bat
grcc -o . xband_leo_image_link_simple.grc
python xband_leo_image_link_simple.py
python reconstruct_image.py --source decoded
python calculate_results.py
```

The File Sink uses `Append = Off`. Before a restarted or interrupted experiment, stale outputs may be removed explicitly:

```bat
del working\rx_decoded_bits.bin working\rx_image.rgb results\channel_log.csv 2>nul
```

To reconstruct output from the detailed legacy graph, use `python reconstruct_image.py --source legacy`. Automatic mode refuses to use a decoded stream older than the current transmit payload.

## External image framing

`prepare_image.py` reads the image dimensions and source path from `simulation_config.json`, normalizes the image to RGB8, and writes:

```text
input/normalized_source.png
working/tx_image.rgb
working/tx_framed_bits.bin
```

The framed-bit file stores one logical bit per byte (`0x00` or `0x01`) in this order:

```text
training bits + raw RGB payload bits + tail bits
```

Image bytes are expanded MSB first. The deterministic training octet is `0,1,1,0,1,0,0,1`; the tail octet is `1,0,0,1,0,1,1,0`. Four 8,192-bit terminated-code frames are used for both acquisition training and tail protection by default. The configuration records `training_bits`, `payload_start_bit`, `payload_bits`, `tail_bits`, and `framed_bits`.

The simple graph writes the entire available Viterbi output to `working/rx_decoded_bits.bin`. `reconstruct_image.py` validates its age and bit values, skips the configured training section, extracts exactly `payload_bits`, packs MSB first, and creates:

```text
working/rx_image.rgb
results/recovered_image.png
results/comparison.png
```

For the 256×256 test, the synchronizers consume one 8,192-bit terminated frame from the finite acquisition/tail allowance. The measured decoded output is 1,630,208 bits; the required training plus payload is 1,605,632 bits. No image-based or arbitrary payload crop occurs in GNU Radio.

## Configurable image resolution

The default debug configuration is 256×256 RGB8. To run 1024×1024, set `width` and `height` in `simulation_config.json`, then mirror those values in the visible GRC variables `image_width` and `image_height`. Payload length is derived from width, height, and three RGB channels; it is not hardcoded as `256 * 256 * 3`.

The included demonstration source is:

```text
input/earth_observation_libya_modis_20120417.jpg
```

It is a [NASA Earth Observatory Terra/MODIS image of dust off the Libya coast](https://earthobservatory.nasa.gov/images/77682/dust-off-the-libya-coast), acquired April 17, 2012. Attribution is recorded in `simulation_config.json`. Select its local path as `source_image`, set 1024×1024 in the configuration and GRC variables, then rerun preparation.

## Rates and coding

These relationships are visible GRC variables:

```python
information_rate = reference_information_rate * rate_scale
coded_bit_rate = information_rate / code_rate
symbol_rate = coded_bit_rate / bits_per_symbol
sample_rate = symbol_rate * samples_per_symbol
occupied_bandwidth = symbol_rate * (1 + rolloff)
```

| Quantity | Practical default (`rate_scale=0.1`) | Full inspired (`rate_scale=1.0`) |
|---|---:|---:|
| Information rate | 1.5 Mbit/s | 15 Mbit/s |
| Coded bit rate | 3.0 Mbit/s | 30 Mbit/s |
| QPSK symbol rate | 1.5 Msymbol/s | 15 Msymbol/s |
| Complex sample rate | 3.0 MS/s | 30 MS/s |
| Occupied bandwidth | 2.025 MHz | 20.25 MHz |

For full-rate reports, set `rate_scale` and the derived `rates` values in `simulation_config.json` as well as the visible GRC variable. Finite simulations may run slower than real time. Disable the two GUI sinks in GRC for long runs if required.

The code is rate 1/2, constraint length 7, terminated at state zero, with conceptual octal generators 171 and 133. GNU Radio 3.10 uses the corresponding bit-reversed decimal representation `[109, 79]` in the visible encoder and decoder definition blocks. QPSK is Gray coded, uses two samples per symbol, and has RRC roll-off 0.35. Differential encoding and decoding occur exactly once.

## Ready-made QPSK block evaluation

The installed Constellation Modulator accepts packed byte input. Source inspection showed its internal `packed_to_unpacked_bb(bits_per_symbol, GR_MSB_FIRST)`, built-in pre-differential map, differential encoder, mapper, and RRC resampler. It was tested after a required Repack Bits 1→8 block as part of the candidate ready-made transmitter/receiver path. That clean regression produced BER 0.4887, so mapping compatibility remained ambiguous and the modulator was rejected.

The installed Constellation Receiver was then tested with the proven explicit transmitter while retaining AGC, matched filtering, FLL, and Gardner synchronization. Its clean regression produced BER 0.3798; it was also rejected. The final simple graph therefore retains the explicit modulation chain and `Costas Loop → Constellation Decoder`. The receiver mapping was not changed merely to force either candidate to pass.

## gr-leo X-band channel

The central visible configuration area contains:

- satellite TX and RX antenna objects
- ground-station TX and RX antenna objects
- NOAA-20-inspired Satellite object
- Zawiya Tracker object
- LEO Model Definition
- LEO Channel Model

The carrier is 7.812 GHz. The approximate ground station is 32.75° N, 12.73° E, 20 m above mean sea level; altitude is a simulation assumption. Representative assumptions—not official NOAA-20 hardware—are a 5 dBi satellite TX antenna, 2.4 m ground dish, 55% aperture efficiency, 30 dBm satellite power, 1 dB receiver noise figure, and 290 K receiver temperature.

Channel profiles are selected by the visible `channel_profile` variable:

| Profile | Impairments |
|---:|---|
| 0 | Clean; all propagation impairments and noise disabled |
| 1 | Orbital Doppler only |
| 2 | Doppler and gr-leo Gaussian link noise |
| 3 | Doppler, FSPL, gas, rain, pointing loss, and noise |

The installed Link Margin option calculates a logged diagnostic from transmit power, antenna gains, loss, and noise floor. Source inspection confirms it does not rescale the complex stream. The visible `full_link_voltage_scale` represents the assumed TX power and antenna voltage terms for profile 3.

This gr-leo version logs time, slant range, elevation, path loss, atmospheric loss, rainfall loss, pointing loss, Doppler shift, and link margin. It does not log range rate.

## Orbit snapshot

The frozen TLE is used without replacement:

```text
NOAA 20
1 43013U 17073A   26198.87431143  .00000023  00000-0  32041-4 0  9995
2 43013  98.7772 138.0652 0001490 121.5711 238.5610 14.19516763448824
```

Its epoch is `2026-07-17T20:59:00.507552Z`. `find_noaa20_pass.py` selected the pass from `2026-07-18T00:55:40.507552Z` to `2026-07-18T01:11:00.507552Z`, with calculated maximum elevation 86.203°. The fixed GRC interval begins at `2026-07-18T01:03:17.507552Z`.

## Executed validation

All rows below were produced by commands executed in the stated GNU Radio environment.

| Test | Result |
|---|---|
| Legacy graph generation and reduced-rate clean baseline | Pass; BER 0; exact RGB match |
| Simple graph generation, final architecture | Pass |
| Ready-made Modulator + Receiver, reduced-rate clean | Rejected; BER 0.4887 |
| Explicit transmitter + ready-made Receiver, reduced-rate clean | Rejected; BER 0.3798 |
| Final simple graph, 256×256 reduced-rate clean | Pass; BER 0; exact RGB match |
| Final simple graph, 256×256 full-rate clean | Pass; BER 0; exact RGB match |
| Final simple graph, 256×256 full-rate Doppler | Pass; BER 0; 108 varying CSV Doppler samples |
| Detailed synchronized graph, reduced-rate Doppler recheck | Pass; BER 0; exact RGB match |
| Final simple graph, 1024×1024 Earth image, full-rate clean | Pass; BER 0; exact RGB match |

The simple full-rate Doppler run logged 6,377.4–6,545.51 Hz over its short finite transfer. The detailed reduced-rate synchronized comparison logged 4,830.73–6,545.51 Hz over 1,092 samples.

Debug-image RGB SHA-256:

```text
04cdb87c58cead80d7cae947078b77da5f6b9da79b78c690d7a53b59d76a049a
```

1024×1024 Earth-observation RGB SHA-256:

```text
230db23a35f5b7bc79d2861a5698a19a7df99d94b90f9e9f1f15ce051d9b2c4d
```

Run artifacts are preserved under `results/baseline`, `results/simple_clean_reduced`, `results/simple_clean_full_rate`, `results/simple_doppler_full_rate`, `results/legacy_doppler_recheck`, and `results/earth_observation_1024_full_rate`.

## Limitations

- The finite synchronized output loses one terminated tail frame; the protected image payload is complete and hash-verifiable.
- Noise-sweep image triplets and profile 3 were not rerun for this simplification and are not claimed as newly validated.
- The model is a raw RGB physical-layer demonstration, not a complete link budget or hardware implementation.
- It contains no FPGA, digital downconversion, channel decimation, packet headers, CRC, Reed–Solomon, CCSDS, JPSS packetization, or operational NOAA-20 decoding.
- The frozen TLE and representative antennas provide reproducibility, not a claim about a current pass or official NOAA-20 hardware.
