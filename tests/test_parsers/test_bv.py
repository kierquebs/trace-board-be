"""
Tests for the BV/BVR boardview parser.
"""
import pytest
from apps.boards.parsers.bv import parse
from apps.boards.parsers.detect import detect_format, BoardFormat
from apps.boards.parsers import parse_board_file


# ─────────────────────────────────────────────────────────────────────────────
# Sample BV file content (in-memory fixtures)
# ─────────────────────────────────────────────────────────────────────────────

MINIMAL_BV = b"""\
BRDVIEW 4

PARTS
U1 1000 2000 0 1 3
U2 3000 4000 0 2 2
C1 500 800 0 1 2
ENDPARTS

PINS
U1 1 VCC 990 1990 1 50
U1 2 GND 1010 1990 1 50
U1 3 SDA 1030 1990 1 50
U2 1 GND 2990 3990 2 50
U2 2 SCL 3010 3990 2 50
C1 1 VCC 490 790 1 50
C1 2 GND 510 790 1 50
ENDPINS

NAILS
1 VCC 100 100 1 60
2 GND 200 100 1 60
3 SDA 300 100 1 60
ENDNAILS
"""

BV_WITH_FILEINFO = b"""\
BRDVIEW 4
FILEINFO
width 5000
height 3000
ENDFILEINFO

PARTS
R1 100 100 0 1 2
ENDPARTS

PINS
R1 1 NET_A 90 90 1 40
R1 2 NET_B 110 90 1 40
ENDPINS
"""

BV_WITH_NETS_SECTION = b"""\
BRDVIEW 4

PARTS
R1 200 200 0 1 2
R2 400 200 0 1 2
ENDPARTS

PINS
R1 1 SIGNAL 190 190 1 50
R1 2 GND 210 190 1 50
R2 1 SIGNAL 390 190 1 50
R2 2 VDD 410 190 1 50
ENDPINS

NETS
SIGNAL 2
  R1 1
  R2 1
GND 1
  R1 2
VDD 1
  R2 2
ENDNETS
"""

BV_SIDE_ENCODING = b"""\
BRDVIEW 4

PARTS
TOP_PART 100 100 0 1 1
BOT_PART 200 200 0 2 1
T_PART 300 300 0 T 1
B_PART 400 400 0 B 1
ENDPARTS

PINS
TOP_PART 1 GND 100 100 1 50
BOT_PART 1 GND 200 200 2 50
T_PART 1 GND 300 300 T 50
B_PART 1 GND 400 400 B 50
ENDPINS
"""


# ─────────────────────────────────────────────────────────────────────────────
# Detection tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBvDetection:
    def test_detects_bv_by_extension(self):
        fmt = detect_format(MINIMAL_BV, "board.bv")
        assert fmt == BoardFormat.BV

    def test_detects_bvr_by_extension(self):
        fmt = detect_format(MINIMAL_BV, "board.bvr")
        assert fmt == BoardFormat.BV

    def test_detects_bv_by_brdview_marker(self):
        content = b"BRDVIEW 4\nPARTS\nENDPARTS\n"
        fmt = detect_format(content, "mystery.bin")
        assert fmt == BoardFormat.BV

    def test_detects_bv_by_board_file_marker(self):
        content = b"BOARD_FILE some_value\n"
        fmt = detect_format(content, "test.bin")
        assert fmt == BoardFormat.BV


# ─────────────────────────────────────────────────────────────────────────────
# Core parser tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBvParser:
    def test_parse_succeeds(self):
        result = parse(MINIMAL_BV, "test.bv")
        assert result.success is True
        assert result.board is not None
        assert result.error == ""

    def test_board_format_field(self):
        result = parse(MINIMAL_BV, "test.bv")
        assert result.board.format == "bv"

    def test_parts_count(self):
        result = parse(MINIMAL_BV, "test.bv")
        assert len(result.board.parts) == 3

    def test_part_names(self):
        result = parse(MINIMAL_BV, "test.bv")
        names = {p.name for p in result.board.parts}
        assert names == {"U1", "U2", "C1"}

    def test_part_sides(self):
        result = parse(MINIMAL_BV, "test.bv")
        parts_by_name = {p.name: p for p in result.board.parts}
        assert parts_by_name["U1"].side == "top"   # side token 1
        assert parts_by_name["U2"].side == "bottom"  # side token 2

    def test_pins_count(self):
        result = parse(MINIMAL_BV, "test.bv")
        # U1: 3 pins, U2: 2 pins, C1: 2 pins = 7 total
        assert len(result.board.pins) == 7

    def test_pin_net_assignment(self):
        result = parse(MINIMAL_BV, "test.bv")
        pins_by_id = {p.id: p for p in result.board.pins}
        assert pins_by_id["U1_1"].net_name == "VCC"
        assert pins_by_id["U1_2"].net_name == "GND"
        assert pins_by_id["U1_3"].net_name == "SDA"

    def test_pin_side_from_pins_section(self):
        result = parse(MINIMAL_BV, "test.bv")
        pins_by_id = {p.id: p for p in result.board.pins}
        assert pins_by_id["U2_1"].side == "bottom"  # side token 2 in PINS

    def test_pin_diameter(self):
        result = parse(MINIMAL_BV, "test.bv")
        pins_by_id = {p.id: p for p in result.board.pins}
        assert pins_by_id["U1_1"].diameter == 50.0

    def test_nets_built_from_pins(self):
        result = parse(MINIMAL_BV, "test.bv")
        net_names = {n.name for n in result.board.nets}
        assert "VCC" in net_names
        assert "GND" in net_names
        assert "SDA" in net_names

    def test_gnd_net_pin_count(self):
        result = parse(MINIMAL_BV, "test.bv")
        nets_by_name = {n.name: n for n in result.board.nets}
        gnd = nets_by_name["GND"]
        # GND pins: U1.2, U2.1, C1.2 = 3 pins; nail_2 = 1 nail
        assert len(gnd.pin_ids) == 3
        assert len(gnd.nail_ids) == 1

    def test_gnd_net_is_ground(self):
        result = parse(MINIMAL_BV, "test.bv")
        nets_by_name = {n.name: n for n in result.board.nets}
        assert nets_by_name["GND"].is_ground is True

    def test_vcc_net_is_power(self):
        result = parse(MINIMAL_BV, "test.bv")
        nets_by_name = {n.name: n for n in result.board.nets}
        assert nets_by_name["VCC"].is_power is True

    def test_nails_count(self):
        result = parse(MINIMAL_BV, "test.bv")
        assert len(result.board.nails) == 3

    def test_nail_probe_numbers(self):
        result = parse(MINIMAL_BV, "test.bv")
        probes = {n.probe_number for n in result.board.nails}
        assert probes == {1, 2, 3}

    def test_nail_net_assignment(self):
        result = parse(MINIMAL_BV, "test.bv")
        nails_by_probe = {n.probe_number: n for n in result.board.nails}
        assert nails_by_probe[1].net_name == "VCC"
        assert nails_by_probe[2].net_name == "GND"

    def test_board_dimensions_derived(self):
        result = parse(MINIMAL_BV, "test.bv")
        # Dimensions computed from pin extents — must be > 0
        assert result.board.width > 0
        assert result.board.height > 0

    def test_outline_generated(self):
        result = parse(MINIMAL_BV, "test.bv")
        assert len(result.board.outline) == 4  # rectangular fallback

    def test_to_json_structure(self):
        result = parse(MINIMAL_BV, "test.bv")
        board_json = result.board.to_json()

        assert "format" in board_json
        assert "width" in board_json
        assert "height" in board_json
        assert "outline" in board_json
        assert "parts" in board_json
        assert "pins" in board_json
        assert "nails" in board_json
        assert "nets" in board_json

        for pin in board_json["pins"]:
            assert "id" in pin
            assert "part_id" in pin
            assert "net_id" in pin
            assert "net_name" in pin
            assert "position" in pin
            assert "x" in pin["position"]
            assert "y" in pin["position"]

        for net in board_json["nets"]:
            assert "id" in net
            assert "name" in net
            assert "pin_ids" in net
            assert "is_ground" in net
            assert "is_power" in net

    def test_empty_file_fails_gracefully(self):
        result = parse(b"", "empty.bv")
        assert result.success is False
        assert result.error

    def test_registry_dispatches_to_bv(self):
        result = parse_board_file(MINIMAL_BV, "board.bv")
        assert result.success is True
        assert result.board.format == "bv"


# ─────────────────────────────────────────────────────────────────────────────
# Edge case tests
# ─────────────────────────────────────────────────────────────────────────────

class TestBvEdgeCases:
    def test_fileinfo_dimensions_used(self):
        result = parse(BV_WITH_FILEINFO, "board.bv")
        assert result.success is True
        assert result.board.width == 5000.0
        assert result.board.height == 3000.0

    def test_nets_section_present_no_duplicate_pins(self):
        """NETS section should not cause duplicate pin_ids in net."""
        result = parse(BV_WITH_NETS_SECTION, "board.bv")
        assert result.success is True
        nets_by_name = {n.name: n for n in result.board.nets}
        signal_net = nets_by_name.get("SIGNAL")
        assert signal_net is not None
        # R1.1 and R2.1 both on SIGNAL — should be exactly 2
        assert len(signal_net.pin_ids) == 2

    def test_side_token_1_is_top(self):
        result = parse(BV_SIDE_ENCODING, "board.bv")
        parts_by_name = {p.name: p for p in result.board.parts}
        assert parts_by_name["TOP_PART"].side == "top"

    def test_side_token_2_is_bottom(self):
        result = parse(BV_SIDE_ENCODING, "board.bv")
        parts_by_name = {p.name: p for p in result.board.parts}
        assert parts_by_name["BOT_PART"].side == "bottom"

    def test_side_token_T_is_top(self):
        result = parse(BV_SIDE_ENCODING, "board.bv")
        parts_by_name = {p.name: p for p in result.board.parts}
        assert parts_by_name["T_PART"].side == "top"

    def test_side_token_B_is_bottom(self):
        result = parse(BV_SIDE_ENCODING, "board.bv")
        parts_by_name = {p.name: p for p in result.board.parts}
        assert parts_by_name["B_PART"].side == "bottom"

    def test_part_bounds_populated_from_pins(self):
        result = parse(MINIMAL_BV, "board.bv")
        parts_by_name = {p.name: p for p in result.board.parts}
        u1 = parts_by_name["U1"]
        # Bounds should be non-zero after pin expansion
        assert u1.bounds.width > 0
        assert u1.bounds.height > 0
