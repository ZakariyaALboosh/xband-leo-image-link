"""Generate the publication flowchart from the simplified GNU Radio graph."""

from __future__ import annotations

import argparse
from html import escape
import os
from pathlib import Path
import shutil
import sys

import yaml
from graphviz import Digraph


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GRC = ROOT / "xband_leo_image_link_simple.grc"
DEFAULT_OUTPUT = Path(__file__).resolve().parent
STEM = "xband_leo_image_link_high_level"
CAPTION = "High-level architecture of the GNU Radio image-transmission and LEO downlink simulation."

REQUIRED_BLOCKS = {
    "framed_bit_source": "blocks_file_source",
    "fec_encoder": "fec_extended_encoder",
    "differential_encoder": "digital_diff_encoder_bb",
    "qpsk_mapper": "digital_constellation_encoder_bc",
    "transmit_rrc": "interp_fir_filter_xxx",
    "amplitude_control": "blocks_multiply_const_vxx",
    "simulation_throttle": "blocks_throttle",
    "leo_channel": "leo_channel_model",
    "receiver_agc": "analog_agc_xx",
    "matched_rrc": "fir_filter_xxx",
    "coarse_fll": "digital_fll_band_edge_cc",
    "gardner_symbol_sync": "digital_symbol_sync_xx",
    "qpsk_phase_recovery": "digital_costas_loop_cc",
    "qpsk_decoder": "digital_constellation_decoder_cb",
    "differential_decoder": "digital_diff_decoder_bb",
    "viterbi_decoder": "fec_extended_decoder",
    "decoded_bit_sink": "blocks_file_sink",
    "received_spectrum_display": "qtgui_freq_sink_x",
    "recovered_constellation_display": "qtgui_const_sink_x",
}


def read_graph(path: Path) -> dict:
    try:
        graph = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RuntimeError(f"Cannot read GNU Radio graph {path}: {exc}") from exc
    blocks = {block["name"]: block for block in graph.get("blocks", [])}
    mismatches = [
        f"{name} ({blocks.get(name, {}).get('id', 'missing')} != {block_id})"
        for name, block_id in REQUIRED_BLOCKS.items()
        if blocks.get(name, {}).get("id") != block_id
    ]
    if mismatches:
        raise ValueError("Flowchart requirements do not match the GRC: " + ", ".join(mismatches))
    validate_parameters(blocks)
    return graph


def validate_parameters(blocks: dict[str, dict]) -> None:
    value = lambda name: blocks[name]["parameters"]["value"]
    checks = {
        "carrier_frequency": float(value("carrier_frequency")) == 7.812e9,
        "samples_per_symbol": int(value("samples_per_symbol")) == 2,
        "rolloff": float(value("rolloff")) == 0.35,
        "code_rate": float(value("code_rate")) == 0.5,
        "constraint_length": int(blocks["cc_encoder"]["parameters"]["k"]) == 7,
        "generator_polynomials": blocks["cc_encoder"]["parameters"]["polys"] == "[109, 79]",
        "costas_order": int(blocks["qpsk_phase_recovery"]["parameters"]["order"]) == 4,
        "channel_log": blocks["leo_channel"]["parameters"]["store_csv"] == "1",
    }
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        raise ValueError("Unexpected GRC parameters: " + ", ".join(failed))


def block_label(title: str, lines: list[str]) -> str:
    rows = [
        f'<TR><TD ALIGN="CENTER"><FONT POINT-SIZE="11"><B>{escape(title)}</B></FONT></TD></TR>',
        '<TR><TD HEIGHT="4"></TD></TR>',
    ]
    rows.extend(
        f'<TR><TD ALIGN="LEFT"><FONT POINT-SIZE="9">{escape(line)}</FONT></TD></TR>'
        for line in lines
    )
    return "<<TABLE BORDER=\"0\" CELLBORDER=\"0\" CELLPADDING=\"1\">" + "".join(rows) + "</TABLE>>"


def add_section(graph: Digraph, section: str, node: str, title: str, lines: list[str], fill: str) -> None:
    with graph.subgraph(name=f"cluster_{section.lower()}") as cluster:
        cluster.attr(
            label=section,
            color="#555555",
            fontname="Helvetica-Bold",
            fontsize="10",
            penwidth="1.1",
            style="rounded",
            margin="8",
        )
        cluster.node(node, label=block_label(title, lines), fillcolor=fill)


def build_flowchart(dpi: int | None = None) -> Digraph:
    graph = Digraph(STEM, engine="dot")
    graph.attr(
        rankdir="TB",
        newrank="true",
        bgcolor="white",
        pad="0.18",
        nodesep="0.22",
        ranksep="0.65",
        splines="ortho",
        outputorder="edgesfirst",
        fontname="Helvetica",
        fontsize="9",
        label=CAPTION,
        labelloc="b",
        labeljust="c",
    )
    if dpi:
        graph.attr(dpi=str(dpi))
    graph.attr(
        "node",
        shape="box",
        style="rounded,filled",
        color="#333333",
        fillcolor="#F2F2F2",
        fontname="Helvetica",
        margin="0.08,0.06",
        penwidth="1.1",
    )
    graph.attr("edge", color="#222222", penwidth="1.35", arrowsize="0.72")

    add_section(
        graph,
        "SOURCE",
        "source",
        "Prepared bit stream",
        ["RGB8, MSB first", "Training + payload + tail", "Logical-bit file"],
        "#F7F7F7",
    )
    add_section(
        graph,
        "TRANSMITTER",
        "transmitter",
        "Coded QPSK TX",
        [
            "Rate-1/2 convolutional coding",
            "K = 7; [109, 79]",
            "Differential Gray QPSK",
            "RRC: α = 0.35",
            "2 samples/symbol",
            "Amplitude scaling + pacing",
        ],
        "#EAEAEA",
    )
    add_section(
        graph,
        "CHANNEL",
        "channel",
        "gr-leo X-band channel",
        [
            "7.812 GHz carrier",
            "NOAA-20-inspired orbit",
            "Zawiya ground station",
            "Orbital Doppler",
            "Optional losses and noise",
        ],
        "#DCDCDC",
    )
    add_section(
        graph,
        "RECEIVER",
        "receiver",
        "Synchronized QPSK RX",
        [
            "AGC + matched RRC",
            "Band-edge FLL",
            "Gardner timing",
            "Fourth-order Costas loop",
            "QPSK decisions",
            "Differential decoding",
            "Rate-1/2 Viterbi decoder",
        ],
        "#EAEAEA",
    )
    add_section(
        graph,
        "OUTPUT",
        "output",
        "Decoded output",
        ["Logical-bit file", "External payload extraction", "RGB reconstruction"],
        "#F7F7F7",
    )

    with graph.subgraph(name="main_flow") as row:
        row.attr(rank="same")
        for node in ("source", "transmitter", "channel", "receiver", "output"):
            row.node(node)
    graph.edge("source", "transmitter")
    graph.edge("transmitter", "channel")
    graph.edge("channel", "receiver")
    graph.edge("receiver", "output")

    with graph.subgraph(name="cluster_measurements") as measurements:
        measurements.attr(
            label="MEASUREMENTS AND DIAGNOSTICS",
            color="#777777",
            fontname="Helvetica-Bold",
            fontsize="10",
            penwidth="1.0",
            style="rounded,dashed",
            margin="8",
        )
        measurements.attr("node", fontsize="9", fillcolor="#FAFAFA", penwidth="0.9")
        measurements.node("channel_log", "Channel CSV log\nrange, elevation, losses, Doppler, link margin")
        measurements.node("spectrum", "Received spectrum\nQT GUI frequency display")
        measurements.node("constellation", "Recovered constellation\nQT GUI constellation display")
        with measurements.subgraph() as row:
            row.attr(rank="same")
            row.node("channel_log")
            row.node("spectrum")
            row.node("constellation")
        measurements.edge("channel_log", "spectrum", style="invis", weight="4")
        measurements.edge("spectrum", "constellation", style="invis", weight="4")

    graph.edge("channel", "channel_log", style="dashed", color="#666666", penwidth="1.0")
    graph.edge("channel", "spectrum", style="dashed", color="#666666", penwidth="1.0")
    graph.edge("receiver", "constellation", style="dashed", color="#666666", penwidth="1.0")
    return graph


def render(output_dir: Path) -> list[Path]:
    if not shutil.which("dot"):
        environment_bin = Path(sys.executable).resolve().parent
        if not (environment_bin / "dot").is_file():
            raise RuntimeError("Graphviz 'dot' is not installed or available on PATH")
        os.environ["PATH"] = str(environment_bin) + os.pathsep + os.environ.get("PATH", "")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for file_format, dpi in (("svg", None), ("pdf", None), ("png", 300)):
        graph = build_flowchart(dpi=dpi)
        rendered = Path(
            graph.render(filename=STEM, directory=output_dir, format=file_format, cleanup=True)
        )
        outputs.append(rendered)
    return outputs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grc", type=Path, default=DEFAULT_GRC, help="simplified GRC source")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT, help="render directory")
    args = parser.parse_args()
    read_graph(args.grc.resolve())
    for output in render(args.output_dir.resolve()):
        print(f"Created {output}")


if __name__ == "__main__":
    main()
