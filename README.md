# NOAA-20-Inspired X-Band Image Link

> A NOAA-20-inspired X-band direct-broadcast image-link simulation implemented in GNU Radio Companion. The model uses representative QPSK data-rate and convolutional-coding parameters and applies orbit-dependent propagation impairments using gr-leo. It is a system-level educational simulation and not a complete operational NOAA-20 HRD decoder.

The source of truth is `xband_leo_image_link.grc`. Every communications and DSP stage is a standard GNU Radio or `gr-leo` block on the Companion canvas. There are no Embedded Python Blocks and no hand-written `gr.top_block` implementation.

## Verified environment

The submitted graph was generated and exercised in an isolated environment containing:

- GNU Radio 3.10.12.0
- `gnuradio-leo` 1.0.0.post20250214+g8f62b92
- Python 3.13.14

This package exposes `gr-leo` as `from gnuradio import leo`; the older top-level `import leo` check fails. The installed data package contained `leo_channel.grc`. The historical `upsat_leo.grc` and `upsat_leo_nogui.grc` files were absent from the installed example directory, but were inspected in the exact package source commit.

`gnuradio-companion --version` is not implemented by this GNU Radio build. Use the runtime query below instead.

```bat
gnuradio-companion --help
python -c "from gnuradio import gr, blocks, digital, filter, fec, qtgui; print('GNU Radio', gr.version())"
python -c "from gnuradio import leo; print('gr-leo import OK:', leo.__file__)"
dir "%CONDA_PREFIX%\share\gnuradio\examples\leo"
```

If `gnuradio-leo` is missing, install it explicitly in the Radioconda Prompt:

```bat
conda install ryanvolz::gnuradio-leo
```

The project never installs or modifies the user's environment automatically.

## Project workflow on Windows Radioconda

Open a Radioconda Prompt and run:

```bat
cd xband_image_link
python prepare_image.py
python find_noaa20_pass.py
gnuradio-companion xband_leo_image_link.grc
```

In GRC, inspect the variables, generate the Python file, and run the graph. The source is finite, but the QT window remains open for inspection; close it after the plots stabilize. File Sink blocks have **Append file = Off**, so normal runs overwrite prior outputs. After an interrupted experiment, it is still prudent to clear stale files before restarting:

```bat
del working\rx_bits.bin working\rx_image.rgb results\channel_log.csv 2>nul
```

Command-line generation uses the syntax verified with GNU Radio 3.10.12.0:

```bat
grcc -o . xband_leo_image_link.grc
python xband_leo_image_link.py
python reconstruct_image.py
python calculate_results.py
```

## Canvas organization and block inventory

The canvas is arranged left-to-right as image source, transmitter, LEO channel, receiver, and output/metrics. The exact installed GRC block IDs used are:

- `blocks_file_source`, `blocks_file_sink`, `blocks_repack_bits_bb`
- `blocks_vector_source_x`, `blocks_stream_mux`, `blocks_skiphead`, `blocks_head`
- `variable_cc_encoder_def`, `fec_extended_encoder`
- `variable_cc_decoder_def`, `fec_extended_decoder`
- `variable_constellation`, `digital_constellation_encoder_bc`, `digital_constellation_decoder_cb`
- `digital_diff_encoder_bb`, `digital_diff_decoder_bb`
- `interp_fir_filter_xxx`, `fir_filter_xxx`
- `analog_agc_xx`, `digital_fll_band_edge_cc`, `digital_symbol_sync_xx`, `digital_costas_loop_cc`
- `variable_antenna`, `variable_satellite`, `variable_tracker`, `variable_leo_model_def`, `leo_channel_model`
- QT constellation, frequency, and time sinks for the required diagnostic displays

The primary synchronized receive path is:

```text
gr-leo output
→ AGC
→ RRC matched filter
→ FLL Band-Edge
→ Gardner Symbol Sync
→ fourth-order Costas Loop
→ QPSK Constellation Decoder
→ differential ambiguity removal
→ hard-bit sign mapping
→ terminated Viterbi decoder
→ MSB-first byte packing
→ RGB File Sink
```

`receiver_path = 1` selects this path. `receiver_path = 0` selects a fixed-phase, fixed-timing calibration branch with matched-filter decimation but no carrier or timing synchronization. The latter is intentionally used to demonstrate Doppler failure.

## Rates and pulse shaping

The following relationships are visible GRC variables:

```python
information_rate = reference_information_rate * rate_scale
coded_bit_rate = information_rate / code_rate
symbol_rate = coded_bit_rate / bits_per_symbol
sample_rate = symbol_rate * samples_per_symbol
occupied_bandwidth = symbol_rate * (1 + rolloff)
```

The submitted default is practical mode, `rate_scale = 0.1`:

| Quantity | Practical | Full inspired rate |
|---|---:|---:|
| Information rate | 1.5 Mbit/s | 15 Mbit/s |
| Coded bit rate | 3.0 Mbit/s | 30 Mbit/s |
| QPSK symbol rate | 1.5 Msymbol/s | 15 Msymbol/s |
| Complex sample rate | 3.0 MS/s | 30 MS/s |
| Occupied bandwidth | 2.025 MHz | 20.25 MHz |

Set `rate_scale = 1.0` for the full inspired rate. Disable the six QT GUI sink blocks for long or full-rate runs. Repeating the image is intentionally disabled for deterministic single-image tests.

Both RRC filters use roll-off 0.35, two samples per symbol, an 11-symbol span, and 23 odd-length taps. The built-in QPSK object's points are scaled by 1/2 in the visible amplitude-normalization block, producing unit average symbol power before any profile-specific physical voltage scaling.

## Bit ordering, QPSK, and convolutional code

Image bytes are unpacked MSB first and repacked consistently at the receiver. The installed QPSK constellation is Gray coded; the explicit differential encoder/decoder pair removes the Costas-loop quadrant ambiguity. Its unscaled point order is `(-√2-j√2), (√2-j√2), (-√2+j√2), (√2+j√2)` and its pre-differential map is `[0, 2, 3, 1]`.

The convolutional code is rate 1/2 with constraint length 7. The conceptual generators are octal 171 and 133. GNU Radio's installed CC example uses the bit-reversed decimal representation `[109, 79]`, which is used by both definition blocks. Each 1024-byte codeword is terminated at state zero. Since 196,608 bytes is exactly 192 codewords, no payload padding is required.

Four deterministic codewords precede the image and four follow it. They provide acquisition time and preserve the end of the finite FIR response. Correlation of the transmitted and synchronized coded-bit diagnostic streams measured a 64-coded-bit acquisition offset. That measured value is the visible `sync_coded_bit_skip`; it is not an image-based crop. The fixed calibration path removes 22 coded bits, calculated from the two 23-tap RRC filter group delays.

## Framing status

The executable graph is **Milestone A**, a fixed-length raw RGB stream divided internally into terminated 1024-byte FEC codewords. It is fully working and hash-verifiable, but it does not yet implement the requested access-code/header/CRC protocol.

The reserved Milestone B format in `simulation_config.json` is:

```text
32-bit access code 0x1ACFFC1D
32-bit big-endian frame sequence number
32-bit big-endian payload length in bytes
up to 1024 payload bytes
32-bit CRC
```

This is an academic demonstration format and is not JPSS or CCSDS compatible. No claim is made that Milestone B is implemented by the submitted graph.

## Orbit and ground station

The frozen TLE is used without replacement:

```text
NOAA 20
1 43013U 17073A   26198.87431143  .00000023  00000-0  32041-4 0  9995
2 43013  98.7772 138.0652 0001490 121.5711 238.5610 14.19516763448824
```

Its epoch is `2026-07-17T20:59:00.507552Z`. The SGP4 helper selected a pass over the approximate Zawiya station from `2026-07-18T00:55:40.507552Z` to `2026-07-18T01:11:00.507552Z`, with calculated maximum elevation 86.203°. The ten-second GRC observation is centered on culmination. Station coordinates are 32.75° N, 12.73° E, and 20 m above mean sea level; the altitude is a simulation assumption.

## Official-inspired and assumed parameters

Reference values supplied for the educational model are the 7.812 GHz carrier, 15 Mbit/s information rate, QPSK, rate-1/2 coding, 15 Msymbol/s, two samples per symbol, and 0.35 roll-off.

The following are representative academic assumptions, not NOAA-20 hardware specifications:

- satellite custom TX antenna: 5 dBiC, 60° beamwidth, zero initial pointing error
- ground RX antenna: 2.4 m parabolic reflector, 55% aperture efficiency
- satellite transmit power: 30 dBm
- ground receiver noise figure: 1 dB
- ground effective receiver temperature: 290 K
- local rainfall rate for the optional full profile: 25 mm/h

The Satellite RX and ground TX antennas are present because the installed `gr-leo` Satellite and Tracker objects require both directions; they do not participate in downlink attenuation.

## Channel profiles

Change the visible integer `channel_profile`, regenerate, and rerun:

| Profile | Impairments |
|---:|---|
| 0 | Clean verification; all impairments and noise disabled |
| 1 | Orbital Doppler only |
| 2 | Doppler plus gr-leo white Gaussian noise |
| 3 | Doppler, FSPL, ITU gas loss, local rain loss, pointing loss, and noise |

For Profile 2, `noise_test_snr_db` controls an explicit pre-channel voltage scale derived from the installed implementation's `kTB`, noise figure, and bandwidth convention. Suggested sweep points must be calibrated on the target Windows build because the gr-leo random source exposes no seed and synchronization can acquire differently between runs.

The installed Link Margin option is diagnostic only. Source inspection shows that it computes an SNR-like logged value from transmit power, antenna gains, total loss, and noise floor. It does **not** change the complex samples or prevent underflow. The installed source also contains a TODO warning around this calculation. Profile 3 therefore uses a visible, derived `full_link_voltage_scale` for TX power and antenna voltage gains. Its `sqrt(1000)` factor matches the installed noise block's conversion before voltage generation; it is documented on the canvas rather than being an unexplained receiver gain.

The CSV produced by this installed version contains exactly:

```text
Elapsed Time (us), Slant Range (km), Elevation (degrees),
Path Loss (dB), Atmospheric Loss (dB), Rainfall Loss (dB),
Pointing Loss (dB), Doppler Shift (Hz), Link Margin (dB)
```

Range rate is not a CSV column in this version.

## Validation results

The following tests were executed against the generated graph:

| Test | Result |
|---|---|
| Image prepare/direct reconstruction | Pass; exact RGB SHA-256 match |
| GRC generation with `grcc -o .` | Pass |
| Full coded, pulse-shaped, clean gr-leo loopback | Pass; BER 0 |
| Clean recovered RGB hash | Pass; exact match |
| Doppler only, calibration path without synchronization | BER 0.363814 |
| Doppler only, FLL + Gardner + Costas | BER 0; exact match |
| gr-leo CSV output | Pass; 1,092 data rows in the single-image interval |
| Full representative channel, initial unscaled diagnostic | Ran; BER 0.5 |
| Full representative channel with derived physical scale | Not completed reliably in this test container |

During the Doppler test the CSV reported 4.831–6.546 kHz across the approximately 1.09 s image transfer. Thus Doppler produced a measured frequency shift and the receiver synchronization reduced BER from 0.363814 to zero.

The clean RGB SHA-256 is:

```text
04cdb87c58cead80d7cae947078b77da5f6b9da79b78c690d7a53b59d76a049a
```

## Known limitations

- Milestone B access-code/header/CRC framing is specified but not implemented.
- Noise sweep image triplets were not validated reproducibly because the installed gr-leo noise generator offers no exposed seed.
- The full representative link profile requires further calibration on Windows Radioconda; do not cite it as a validated NOAA-20 link budget.
- The model does not implement JPSS packetization, CCSDS synchronization, interleaving, scrambling, or an operational HRD decoder.
- The selected TLE and ground-station assumptions are reproducible simulation inputs, not a claim about a live pass or official receiving facility.
