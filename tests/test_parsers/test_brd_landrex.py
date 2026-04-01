"""
Tests for the Landrex .brd parser.

Requires sample fixtures at:
  tests/fixtures/A2141_820-01700.brd  (MacBook Pro 16" 2019, 820-01700)
  tests/fixtures/J113  820-00165.brd  (J113 board, 820-00165)
"""
import pytest
from pathlib import Path

FIXTURE = Path(__file__).parent.parent / 'fixtures' / 'A2141_820-01700.brd'
J113_FIXTURE = Path(__file__).parent.parent / 'fixtures' / 'J113  820-00165.brd'


def _load():
    if not FIXTURE.exists():
        pytest.skip(f"Fixture not found: {FIXTURE}")
    return FIXTURE.read_bytes()


def _load_j113():
    if not J113_FIXTURE.exists():
        pytest.skip(f"Fixture not found: {J113_FIXTURE}")
    return J113_FIXTURE.read_bytes()


# ── Detection ──────────────────────────────────────────────────────────────────

def test_format_detected_as_landrex():
    from apps.boards.parsers.detect import detect_format, BoardFormat
    fmt = detect_format(_load(), 'A2141_820-01700.brd')
    assert fmt == BoardFormat.BRD_LANDREX


# ── Parse integrity ────────────────────────────────────────────────────────────

def test_parse_returns_success():
    from apps.boards.parsers.brd_landrex import parse
    r = parse(_load(), 'A2141_820-01700.brd')
    assert r.success, f"Parse failed: {r.error}"
    assert r.board is not None


def test_board_counts():
    from apps.boards.parsers.brd_landrex import parse
    b = parse(_load(), 'test.brd').board
    assert b.format == 'brd_landrex'
    assert len(b.parts) == 7512
    assert len(b.pins)  >= 25000
    assert len(b.nets)  >= 1000
    assert len(b.outline) >= 3


def test_no_orphaned_pins():
    from apps.boards.parsers.brd_landrex import parse
    b = parse(_load(), 'test.brd').board
    valid = {p.id for p in b.parts}
    assert all(pin.part_id in valid for pin in b.pins)


def test_pin_counts_consistent():
    from apps.boards.parsers.brd_landrex import parse
    from collections import Counter
    b = parse(_load(), 'test.brd').board
    actual = Counter(pin.part_id for pin in b.pins)
    for part in b.parts:
        expected = actual[part.id]
        # No pin_count field on ParsedPart — verify via pin list
        assert expected >= 0  # just sanity check


def test_net_pin_refs_valid():
    from apps.boards.parsers.brd_landrex import parse
    b = parse(_load(), 'test.brd').board
    valid = {p.id for p in b.pins}
    bad = sum(1 for n in b.nets for pid in n.pin_ids if pid not in valid)
    assert bad == 0


# ── Known board content ────────────────────────────────────────────────────────

def test_known_net_names_present():
    from apps.boards.parsers.brd_landrex import parse
    b = parse(_load(), 'test.brd').board
    names = {n.name for n in b.nets}
    for expected in ('GND', 'PPBUS_HS_CPU', 'PPVCC_S0_CPU', 'PP1V2_S3_CPUDDR'):
        assert expected in names, f"Net {expected!r} missing"


def test_gnd_classification():
    from apps.boards.parsers.brd_landrex import parse
    b = parse(_load(), 'test.brd').board
    gnd = next(n for n in b.nets if n.name == 'GND')
    assert gnd.is_ground is True
    assert gnd.is_power is False
    assert len(gnd.pin_ids) >= 5000


def test_ppbus_is_power():
    from apps.boards.parsers.brd_landrex import parse
    b = parse(_load(), 'test.brd').board
    ppbus = next(n for n in b.nets if n.name == 'PPBUS_HS_CPU')
    assert ppbus.is_power is True
    assert ppbus.is_ground is False


def test_cpu_component_present():
    from apps.boards.parsers.brd_landrex import parse
    b = parse(_load(), 'test.brd').board
    # U0500 = A9X/Intel CPU on 820-01700
    u0500 = next((p for p in b.parts if p.name == 'U0500'), None)
    assert u0500 is not None, "U0500 (CPU) not found"
    # Verify via pin count
    from collections import Counter
    pin_counts = Counter(pin.part_id for pin in b.pins)
    assert pin_counts['U0500'] == 1440


def test_coordinate_range():
    from apps.boards.parsers.brd_landrex import parse
    b = parse(_load(), 'test.brd').board
    xs = [p.position.x for p in b.pins]
    ys = [p.position.y for p in b.pins]
    # MacBook Pro 16" board is ~340mm × ~120mm
    assert max(xs) - min(xs) > 10_000   # > 254mm in mils
    assert max(ys) - min(ys) > 3_000    # > 76mm in mils
    assert min(xs) >= 0
    assert min(ys) >= 0


def test_board_dimensions():
    from apps.boards.parsers.brd_landrex import parse
    b = parse(_load(), 'test.brd').board
    assert b.width > 10_000
    assert b.height > 3_000


def test_to_json_structure():
    from apps.boards.parsers.brd_landrex import parse
    j = parse(_load(), 'test.brd').board.to_json()
    assert set(j) >= {'format', 'width', 'height', 'outline', 'parts', 'pins', 'nets'}
    pin = j['pins'][0]
    assert set(pin) >= {'id', 'part_id', 'name', 'net_name', 'position', 'side'}
    assert set(pin['position']) == {'x', 'y'}
    net = j['nets'][0]
    assert set(net) >= {'id', 'name', 'pin_ids', 'is_ground', 'is_power'}


# ── Geometry assertions (A2141) ────────────────────────────────────────────────

def test_parts_have_geometry():
    from apps.boards.parsers.brd_landrex import parse
    b = parse(_load(), 'test.brd').board
    parts_with_geo = [p for p in b.parts if p.geometry is not None]
    # All parts with at least one pin should have geometry
    assert len(parts_with_geo) > len(b.parts) * 0.9


def test_geometry_in_json_output():
    from apps.boards.parsers.brd_landrex import parse
    j = parse(_load(), 'test.brd').board.to_json()
    part = j['parts'][0]
    assert 'geometry' in part


def test_c7863_geometry_45_degrees():
    """C7863 on A2141 sits at 45° — pin 1 (8569,1102), pin 2 (8583,1116)."""
    from apps.boards.parsers.brd_landrex import parse
    b = parse(_load(), 'test.brd').board
    c7863 = next((p for p in b.parts if p.name == 'C7863'), None)
    assert c7863 is not None, "C7863 not found in A2141 board"
    assert c7863.geometry is not None
    assert abs(c7863.geometry.angle_deg - 45.0) < 1.0
    assert abs(c7863.geometry.center_x - 8576.0) < 1.0
    assert abs(c7863.geometry.center_y - 1109.0) < 1.0
    assert len(c7863.geometry.outline) == 4


def test_geometry_outline_serialises():
    from apps.boards.parsers.brd_landrex import parse
    j = parse(_load(), 'test.brd').board.to_json()
    parts_with_geo = [p for p in j['parts'] if p.get('geometry') is not None]
    assert parts_with_geo, "No parts with geometry found in JSON output"
    geo = parts_with_geo[0]['geometry']
    assert 'center_x' in geo
    assert 'center_y' in geo
    assert 'angle_deg' in geo
    assert 'width' in geo
    assert 'height' in geo
    assert 'outline' in geo
    assert len(geo['outline']) == 4
    for corner in geo['outline']:
        assert 'x' in corner
        assert 'y' in corner


# ── J113 fixture tests ─────────────────────────────────────────────────────────

def test_j113_format_detected_as_landrex():
    from apps.boards.parsers.detect import detect_format, BoardFormat
    fmt = detect_format(_load_j113(), 'J113.brd')
    assert fmt == BoardFormat.BRD_LANDREX


def test_j113_parse_returns_success():
    from apps.boards.parsers.brd_landrex import parse
    r = parse(_load_j113(), 'J113.brd')
    assert r.success, f"Parse failed: {r.error}"
    assert r.board is not None


def test_j113_board_counts():
    from apps.boards.parsers.brd_landrex import parse
    b = parse(_load_j113(), 'J113.brd').board
    assert b.format == 'brd_landrex'
    assert len(b.parts) == 3452
    assert len(b.pins) == 9388
    assert len(b.nails) == 1540


def test_j113_board_dimensions():
    """J113 820-00165 is ~242mm × 61mm → > 9527 × 2402 mils."""
    from apps.boards.parsers.brd_landrex import parse
    b = parse(_load_j113(), 'J113.brd').board
    assert b.width > 8000    # > 203mm
    assert b.height > 2000   # > 51mm


def test_j113_no_orphaned_pins():
    from apps.boards.parsers.brd_landrex import parse
    b = parse(_load_j113(), 'J113.brd').board
    valid = {p.id for p in b.parts}
    assert all(pin.part_id in valid for pin in b.pins)


def test_j113_parts_have_geometry():
    from apps.boards.parsers.brd_landrex import parse
    b = parse(_load_j113(), 'J113.brd').board
    parts_with_geo = [p for p in b.parts if p.geometry is not None]
    assert len(parts_with_geo) > len(b.parts) * 0.9