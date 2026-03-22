"""
Tests for the BRD2/TOPTEST parser.
"""
import pytest
from apps.boards.parsers.brd2 import parse
from apps.boards.parsers.detect import detect_format, BoardFormat
from apps.boards.parsers import parse_board_file


# ─────────────────────────────────────────────────────────────────────────────
# Sample BRD2 file content (minimal valid example)
# ─────────────────────────────────────────────────────────────────────────────

MINIMAL_BRD2 = b"""\
BRD2

BRDOUT 1500 1000 3

COMPONENT U1 100 200 T 0
  PIN 1 VCC 100 200
  PIN 2 GND 120 200
  PIN 3 SDA 140 200

COMPONENT U2 400 300 B 0
  PIN 1 GND 400 300
  PIN 2 SCL 420 300

COMPONENT C1 600 100 T 0
  PIN 1 VCC 600 100
  PIN 2 GND 610 100

NAIL 1 VCC 50 50 T
NAIL 2 GND 60 50 T
NAIL 3 SDA 70 50 T
"""

MULTI_NET_BRD2 = b"""\
BRD2
BRDOUT 2000 1500 2

COMPONENT R1 10 10 T 0
  PIN 1 NET_A 10 10
  PIN 2 NET_B 30 10

COMPONENT R2 50 10 T 0
  PIN 1 NET_A 50 10
  PIN 2 NET_C 70 10
"""


class TestBrd2Detection:
    def test_detects_brd2_format(self):
        fmt = detect_format(MINIMAL_BRD2, "board.brd")
        assert fmt == BoardFormat.BRD2

    def test_detects_by_brdout_keyword(self):
        content = b"BRDOUT 1000 800 5\nCOMPONENT C1..."
        fmt = detect_format(content, "test.brd")
        assert fmt == BoardFormat.BRD2


class TestBrd2Parser:
    def test_parse_succeeds(self):
        result = parse(MINIMAL_BRD2, "test.brd")
        assert result.success is True
        assert result.board is not None
        assert result.error == ""

    def test_board_dimensions(self):
        result = parse(MINIMAL_BRD2, "test.brd")
        assert result.board.width == 1500.0
        assert result.board.height == 1000.0

    def test_parts_count(self):
        result = parse(MINIMAL_BRD2, "test.brd")
        assert len(result.board.parts) == 3

    def test_part_names(self):
        result = parse(MINIMAL_BRD2, "test.brd")
        names = {p.name for p in result.board.parts}
        assert names == {"U1", "U2", "C1"}

    def test_part_sides(self):
        result = parse(MINIMAL_BRD2, "test.brd")
        parts_by_name = {p.name: p for p in result.board.parts}
        assert parts_by_name["U1"].side == "top"
        assert parts_by_name["U2"].side == "bottom"

    def test_pins_count(self):
        result = parse(MINIMAL_BRD2, "test.brd")
        # U1: 3 pins, U2: 2 pins, C1: 2 pins = 7 total
        assert len(result.board.pins) == 7

    def test_pin_net_assignment(self):
        result = parse(MINIMAL_BRD2, "test.brd")
        pins_by_id = {p.id: p for p in result.board.pins}
        vcc_pin = pins_by_id.get("U1_1")
        assert vcc_pin is not None
        assert vcc_pin.net_name == "VCC"

    def test_nets_built_from_pins(self):
        result = parse(MINIMAL_BRD2, "test.brd")
        net_names = {n.name for n in result.board.nets}
        assert "VCC" in net_names
        assert "GND" in net_names
        assert "SDA" in net_names

    def test_gnd_net_is_ground(self):
        result = parse(MINIMAL_BRD2, "test.brd")
        nets_by_name = {n.name: n for n in result.board.nets}
        assert nets_by_name["GND"].is_ground is True
        assert nets_by_name["VCC"].is_ground is False

    def test_vcc_net_is_power(self):
        result = parse(MINIMAL_BRD2, "test.brd")
        nets_by_name = {n.name: n for n in result.board.nets}
        assert nets_by_name["VCC"].is_power is True

    def test_nails_parsed(self):
        result = parse(MINIMAL_BRD2, "test.brd")
        assert len(result.board.nails) == 3

    def test_nail_probe_numbers(self):
        result = parse(MINIMAL_BRD2, "test.brd")
        probes = {n.probe_number for n in result.board.nails}
        assert probes == {1, 2, 3}

    def test_nail_net_assignment(self):
        result = parse(MINIMAL_BRD2, "test.brd")
        nails_by_probe = {n.probe_number: n for n in result.board.nails}
        assert nails_by_probe[1].net_name == "VCC"
        assert nails_by_probe[2].net_name == "GND"

    def test_gnd_net_pin_count(self):
        """GND net should collect all GND pins across all components."""
        result = parse(MINIMAL_BRD2, "test.brd")
        nets_by_name = {n.name: n for n in result.board.nets}
        gnd_net = nets_by_name["GND"]
        # GND appears in: U1.2, U2.1, C1.2, nail_2 = 3 pins + 1 nail
        assert len(gnd_net.pin_ids) == 3
        assert len(gnd_net.nail_ids) == 1

    def test_to_json_structure(self):
        """Verify the JSON output matches what the frontend expects."""
        result = parse(MINIMAL_BRD2, "test.brd")
        board_json = result.board.to_json()

        assert "format" in board_json
        assert "width" in board_json
        assert "height" in board_json
        assert "outline" in board_json
        assert "parts" in board_json
        assert "pins" in board_json
        assert "nails" in board_json
        assert "nets" in board_json

        # Each pin must have required fields for net tracing
        for pin in board_json["pins"]:
            assert "id" in pin
            assert "part_id" in pin
            assert "net_id" in pin
            assert "net_name" in pin
            assert "position" in pin
            assert "x" in pin["position"]
            assert "y" in pin["position"]

        # Each net must have pin_ids for net tracing
        for net in board_json["nets"]:
            assert "id" in net
            assert "name" in net
            assert "pin_ids" in net
            assert "is_ground" in net
            assert "is_power" in net

    def test_empty_file_fails_gracefully(self):
        result = parse(b"", "empty.brd")
        assert result.success is False
        assert result.error

    def test_registry_dispatches_to_brd2(self):
        """parse_board_file() should route BRD2 content correctly."""
        result = parse_board_file(MINIMAL_BRD2, "board.brd")
        assert result.success is True
        assert result.board.format == "brd2"

    def test_multi_net_connectivity(self):
        """NET_A should connect R1.1 and R2.1."""
        result = parse(MULTI_NET_BRD2, "multi.brd")
        assert result.success
        nets_by_name = {n.name: n for n in result.board.nets}
        net_a = nets_by_name.get("NET_A")
        assert net_a is not None
        assert len(net_a.pin_ids) == 2  # R1.1 and R2.1
