"""
Parser for Landrex .brd boardview format.

Encoding: Every byte encodes an ASCII character via:
    decoded_ascii = 255 - ((byte & 0x3F) << 2) - ((byte >> 6) & 3)

Equivalent to: invert the ASCII value, then bit-rotate:
    v = 255 - ascii
    byte = ((v & 3) << 6) | (v >> 2)

Field separator / padding: 0xf7  (decodes to space)

File structure (CRLF line endings):
    Lines  0–5:   Board header (version, name, metadata)
    Line   6:     Outline polygon point count
    Lines  7–11:  Outline polygon (4 corners + close)
    Line  12:     Blank
    Line  13:     'Parts:' section header
    Lines 14–N:   PARTS — fixed 22-byte lines per component
    Line  N+1:    'Pins:' section header
    Lines N+2–M:  PINS — variable-length lines, one per pin
    Line  M+1:    'Nets:' section header
    Lines M+2–:   NETS — net-ID-to-name table

PARTS line layout (22 bytes, no separator):
    bytes  0–10 (11 b): Component name, right-padded with 0xf7
    bytes 11–16  (6 b): Rotation/side field (decoded: '5'=bottom, '10'=top)
    bytes 17–21  (5 b): Exclusive end index into PINS array (decimal integer)

PINS line layout (variable, 5 fields separated by runs of 0xf7):
    Field 0: X coordinate (mils, decoded decimal integer)
    Field 1: Y coordinate (mils, decoded decimal integer)
    Field 2: Net ID (decoded decimal; '-99' = not in net table)
    Field 3: Component index (1-based into PARTS list)
    Field 4: Net name (decoded text)

Coordinate units: mils (thousandths of an inch).
Board origin is top-left; Y increases downward.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Optional

from .geometry import compute_part_geometry
from .models import (
    BoundingBox,
    ParsedBoard,
    ParsedNail,
    ParsedNet,
    ParsedPin,
    ParsedPart,
    ParseResult,
    Point,
)

logger = logging.getLogger(__name__)

_SEP = 0xF7   # separator / padding byte


# Maps reference-designator prefix → human-readable part category.
# Used to populate part_type when the binary format carries no label data.
_REFDES_TYPE: dict[str, str] = {
    'U':    'IC',
    'IC':   'IC',
    'C':    'Capacitor',
    'CAP':  'Capacitor',
    'R':    'Resistor',
    'RES':  'Resistor',
    'L':    'Inductor',
    'FL':   'Filter',
    'Q':    'Transistor',
    'D':    'Diode',
    'LED':  'LED',
    'F':    'Fuse',
    'J':    'Connector',
    'CN':   'Connector',
    'P':    'Connector',
    'SW':   'Switch',
    'S':    'Switch',
    'Y':    'Crystal',
    'XTAL': 'Crystal',
    'TR':   'Transformer',
    'TP':   'TestPoint',
}
_REFDES_PREFIX_RE = re.compile(r'^([A-Za-z]+)', re.ASCII)


# ── Decoding helpers ───────────────────────────────────────────────────────────

def _decode_byte(b: int) -> str:
    """Decode a single Landrex-encoded byte to its ASCII character."""
    return chr(255 - ((b & 0x3F) << 2) - ((b >> 6) & 3))


def _decode(data: bytes, strip: bool = True) -> str:
    """Decode a byte sequence, skipping separator bytes."""
    s = ''.join(_decode_byte(b) for b in data if b != _SEP)
    return s.rstrip() if strip else s


def _split_fields(line: bytes) -> list[bytes]:
    """Split a PINS line into fields on runs of 0xf7 bytes."""
    result: list[bytes] = []
    cur: list[int] = []
    for b in line:
        if b == _SEP:
            if cur:
                result.append(bytes(cur))
                cur = []
        else:
            cur.append(b)
    if cur:
        result.append(bytes(cur))
    return result


def _int(s: str, default: int = 0) -> int:
    try:
        return int(s)
    except (ValueError, TypeError):
        return default


def _decode_coord(raw: str) -> float:
    """
    Parse a coordinate string to float, handling integers, decimals, and
    scientific notation (e.g. '1350', '1350.0', '1.35e3').
    Returns 0.0 on any parse failure.
    """
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 0.0


def _parse_rotation_side(data: bytes) -> tuple[float, str]:
    """
    Decode the 6-byte rotation/side field from a PARTS line.

    Actual encoding (confirmed from binary inspection of J113 820-00165.brd):
        First decoded character  → side indicator: '5' = bottom, anything else = top
        Remaining characters     → rotation angle in degrees (integer string)

    Examples:
        '5'   → bottom, 0°
        '1'   → top, 0°
        '10'  → top, 0°    (explicit '0' rotation suffix)
        '135' → top, 35°   (side='1', angle=35)
        '580' → bottom, 80° (side='5', angle=80)
        '-99' → top, 0°    (sentinel for "no data")
    """
    val = _decode(data).strip()
    if not val or val.startswith('-'):
        # Empty or sentinel value ('-99') — no orientation data
        return 0.0, 'top'

    side = 'bottom' if val[0] == '5' else 'top'

    rotation = 0.0
    angle_str = val[1:]   # everything after the side character
    if angle_str:
        try:
            rotation = float(angle_str) % 360.0
        except ValueError:
            pass

    return rotation, side


def _geometric_rotation(pins: list) -> float | None:
    """
    Compute the orientation angle (in degrees) of a component from its pin
    positions. Only applied when the file does not store an explicit angle.

    For 2-pin passives: angle of the vector from pin 1 to pin 2, normalised
    to [0, 180) so that a horizontal part = 0° and a vertical part = 90°.
    Returns None when the geometry is ambiguous (single pin, all coincident).
    """
    import math

    if len(pins) < 2:
        return None

    if len(pins) == 2:
        dx = pins[1].position.x - pins[0].position.x
        dy = pins[1].position.y - pins[0].position.y
        if dx == 0 and dy == 0:
            return None
        angle = math.degrees(math.atan2(dy, dx)) % 180.0
        return round(angle, 1)

    # For multi-pin components compute the principal axis via the 2-D
    # moment of inertia (poor-man's PCA on the pin cloud).
    xs = [p.position.x for p in pins]
    ys = [p.position.y for p in pins]
    cx = sum(xs) / len(xs)
    cy = sum(ys) / len(ys)
    ixx = sum((y - cy) ** 2 for y in ys)
    ixy = sum((x - cx) * (y - cy) for x, y in zip(xs, ys))
    if ixx == 0 and ixy == 0:
        return None
    angle = math.degrees(0.5 * math.atan2(-2 * ixy, ixx)) % 180.0
    return round(angle, 1)


def _infer_part_type(name: str) -> str:
    """
    Derive a human-readable component category from the reference designator.
    Returns an empty string when the prefix is unknown.
    """
    m = _REFDES_PREFIX_RE.match(name)
    if not m:
        return ''
    prefix = m.group(1).upper()
    # Try full prefix first, then first character only
    return _REFDES_TYPE.get(prefix) or _REFDES_TYPE.get(prefix[:1], '')


# ── Public entry point ─────────────────────────────────────────────────────────

def parse(file_bytes: bytes, filename: str) -> ParseResult:
    """Parse a Landrex .brd boardview file. Always returns a ParseResult."""
    try:
        board = _parse_internal(file_bytes)
        return ParseResult(success=True, board=board)
    except Exception as exc:
        logger.exception("Landrex BRD parse failed for %s", filename)
        return ParseResult(success=False, error=str(exc))


# ── Internal parser ────────────────────────────────────────────────────────────

def _parse_internal(file_bytes: bytes) -> ParsedBoard:
    lines = file_bytes.split(b'\r\n')

    # ── Locate section headers ────────────────────────────────────────────────
    parts_hdr:  Optional[int] = None
    pins_hdr:   Optional[int] = None
    nets_hdr:   Optional[int] = None
    nails_hdr:  Optional[int] = None

    for i, line in enumerate(lines):
        d = _decode(line)
        if d.startswith('Parts:'):
            parts_hdr = i
        elif d.startswith('Pins:'):
            pins_hdr = i
        elif d.startswith('Nails:'):
            nails_hdr = i
        elif d.startswith('Nets:'):
            nets_hdr = i

    if parts_hdr is None or pins_hdr is None:
        raise ValueError("Cannot locate 'Parts:' or 'Pins:' section headers")

    p_start = parts_hdr + 1
    p_end   = pins_hdr          # exclusive
    q_start = pins_hdr + 1
    # Pins end at the first section boundary after Pins:
    _pins_end_candidates = [
        x for x in (nails_hdr, nets_hdr) if x is not None
    ]
    q_end = min(_pins_end_candidates) if _pins_end_candidates else len(lines)

    logger.debug("Sections — parts [%d:%d]  pins [%d:%d]  nails_hdr=%s",
                 p_start, p_end, q_start, q_end, nails_hdr)

    # ── Board outline ─────────────────────────────────────────────────────────
    # Starts at line 7 (first coordinate after the 'Format:' metadata header)
    # and runs up to the blank line immediately before the 'Parts:' header.
    # Simple boards use 4–5 points (lines 7–11); complex boards (e.g. J113)
    # can have hundreds of polygon vertices.
    outline: list[Point] = []
    for line in lines[7:parts_hdr]:
        if not line:
            continue
        f = _split_fields(line)
        if len(f) >= 2:
            outline.append(Point(
                x=_decode_coord(_decode(f[0])),
                y=_decode_coord(_decode(f[1])),
            ))
    # Remove duplicate closing vertex if present
    if len(outline) >= 2 and outline[0].x == outline[-1].x and outline[0].y == outline[-1].y:
        outline = outline[:-1]

    # ── Parse PARTS (22-byte fixed-width lines) ───────────────────────────────
    # bytes  0–10: component name (0xf7 padded)
    # bytes 11–16: rotation/side field ('5'=bottom, '10'=top; see _parse_rotation_side)
    # bytes 17–21: exclusive end index into PINS array
    # bytes 22+  : optional extended label fields (part_type, value) in some
    #              Landrex variants — read as decoded text and split on separators
    raw_parts: list[dict] = []
    for line in lines[p_start:p_end]:
        if len(line) < 22:
            continue
        name = _decode(line[0:11])
        if not name:
            continue
        rotation, side = _parse_rotation_side(line[11:17])
        end_idx = _int(_decode(line[17:22]), default=-1)
        if end_idx < 0:
            continue

        # Extended label data (bytes 22+): present in some file variants.
        # Split on separator runs and treat the first two tokens as
        # part_type and value respectively.
        part_type = _infer_part_type(name)   # fallback: infer from ref-des prefix
        value = ''
        if len(line) > 22:
            ext_tokens = [_decode(f) for f in _split_fields(line[22:]) if f]
            ext_tokens = [t for t in ext_tokens if t]
            if ext_tokens:
                part_type = ext_tokens[0]
            if len(ext_tokens) > 1:
                value = ext_tokens[1]

        raw_parts.append({
            'name': name,
            'side': side,
            'rotation': rotation,
            'end': end_idx,
            'part_type': part_type,
            'value': value,
        })

    # ── Parse PINS (variable-length, 5 fields) ────────────────────────────────
    # field0 = X (mils), field1 = Y (mils), field2 = net_id,
    # field3 = comp_index (1-based), field4 = net_name
    raw_pins: list[dict] = []
    for line in lines[q_start:q_end]:
        if not line:
            continue
        f = _split_fields(line)
        if len(f) < 5:
            continue
        try:
            x        = _decode_coord(_decode(f[0]))
            y        = _decode_coord(_decode(f[1]))
            net_id   = _int(_decode(f[2]), default=-99)
            comp_idx = _int(_decode(f[3]), default=0)
            net_name = _decode(f[4])
        except (ValueError, IndexError):
            continue
        raw_pins.append({
            'x': x, 'y': y,
            'net_id': net_id, 'comp': comp_idx, 'net': net_name,
        })

    # ── Assign pin slices to components ──────────────────────────────────────
    # PARTS field3 is the exclusive end of this component's pin slice.
    # Component k (1-based) → raw_pins[prev_end : parts[k-1]['end']]
    for i, rec in enumerate(raw_parts):
        prev = raw_parts[i - 1]['end'] if i > 0 else 0
        rec['_slice'] = (prev, rec['end'])

    # ── Build net registry ────────────────────────────────────────────────────
    # Collect net_name → ParsedNet, populate pin_ids incrementally
    net_map: dict[str, ParsedNet] = {}

    def _get_net(name: str, net_id: int) -> Optional[ParsedNet]:
        if not name or name in ('NC', 'UNCONNECTED', '---', ''):
            return None
        if name not in net_map:
            net_map[name] = ParsedNet(
                id=f"n{len(net_map)}",
                name=name,
            )
        # Update numeric ID if we have a real one
        if net_id > 0:
            net_map[name].id = str(net_id)
        return net_map[name]

    # ── Assemble ParsedPart / ParsedPin objects ───────────────────────────────
    parts:   list[ParsedPart] = []
    pins:    list[ParsedPin]  = []
    pin_ctr = 0

    for k, prec in enumerate(raw_parts):
        part_id  = prec['name']   # use the component designator as stable ID
        comp_num = k + 1
        s, e     = prec['_slice']
        part_pin_objects: list[ParsedPin] = []

        for prec2 in raw_pins[s:e]:
            net_name = prec2['net'] or ''
            pin_id   = f"{part_id}_{pin_ctr}"
            pin_ctr += 1

            net = _get_net(net_name, prec2['net_id'])
            net_id_str = net.id if net else ''

            pin = ParsedPin(
                id=pin_id,
                part_id=part_id,
                name=str(len(part_pin_objects) + 1),
                net_id=net_id_str,
                net_name=net_name,
                position=Point(x=float(prec2['x']), y=float(prec2['y'])),
                side=prec['side'],
            )
            part_pin_objects.append(pin)
            pins.append(pin)

            if net is not None:
                net.pin_ids.append(pin_id)

        # Bounding box derived from the exact extent of all pin positions,
        # plus a uniform courtyard margin.  Because pin coordinates are stored
        # in absolute board space (already rotation-transformed), no additional
        # rotation correction is needed here.
        if part_pin_objects:
            xs = [p.position.x for p in part_pin_objects]
            ys = [p.position.y for p in part_pin_objects]
            x_span = max(xs) - min(xs)
            y_span = max(ys) - min(ys)
            bounds = BoundingBox(
                x=min(xs),
                y=min(ys),
                width=x_span,
                height=y_span,
            )
        else:
            bounds = BoundingBox(x=0, y=0, width=0.0, height=0.0)

        # If the file carries no explicit rotation (0°), fall back to the
        # geometric orientation derived from the pin cloud.
        rotation = prec['rotation']
        if rotation == 0.0 and part_pin_objects:
            geo = _geometric_rotation(part_pin_objects)
            if geo is not None:
                rotation = geo

        parts.append(ParsedPart(
            id=part_id,
            name=prec['name'],
            side=prec['side'],
            bounds=bounds,
            rotation=rotation,
            part_type=prec['part_type'],
            value=prec['value'],
        ))

    # ── Parse NAILS (probe test points) ──────────────────────────────────────
    # Nail line layout (5 fields separated by runs of 0xf7):
    #   Field 0: probe number (integer)
    #   Field 1: X coordinate (mils)
    #   Field 2: Y coordinate (mils)
    #   Field 3: side code ('1' = top, '2' = bottom)
    #   Field 4: net name
    nails: list[ParsedNail] = []
    if nails_hdr is not None:
        n_start = nails_hdr + 1
        n_end = nets_hdr if (nets_hdr is not None and nets_hdr > nails_hdr) else len(lines)
        for line in lines[n_start:n_end]:
            if not line:
                continue
            f = _split_fields(line)
            if len(f) < 5:
                continue
            try:
                probe    = _int(_decode(f[0]))
                nx       = _decode_coord(_decode(f[1]))
                ny       = _decode_coord(_decode(f[2]))
                side_raw = _decode(f[3]).strip()
                net_name = _decode(f[4])
            except (ValueError, IndexError):
                continue

            nail_side = 'bottom' if side_raw == '2' else 'top'
            nail_id   = f"nail_{probe}_{len(nails)}"
            net_id_str = ''

            if net_name and net_name not in ('NC', 'UNCONNECTED', '---', ''):
                net = _get_net(net_name, -1)
                if net is not None:
                    net_id_str = net.id
                    net.nail_ids.append(nail_id)

            nails.append(ParsedNail(
                id=nail_id,
                probe_number=probe,
                position=Point(x=nx, y=ny),
                net_id=net_id_str,
                net_name=net_name,
                side=nail_side,
            ))

    # ── Compute geometry for each part ───────────────────────────────────────
    part_pin_positions: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for pin in pins:
        part_pin_positions[pin.part_id].append((pin.position.x, pin.position.y))

    for part in parts:
        positions = part_pin_positions.get(part.id, [])
        part.geometry = compute_part_geometry(part.name, positions)

    # ── Compute board dimensions from outline ─────────────────────────────────
    if outline:
        all_x = [p.x for p in outline]
        all_y = [p.y for p in outline]
        board_w = max(all_x) - min(all_x)
        board_h = max(all_y) - min(all_y)
    elif pins:
        all_x = [p.position.x for p in pins]
        all_y = [p.position.y for p in pins]
        board_w = max(all_x) - min(all_x)
        board_h = max(all_y) - min(all_y)
    else:
        board_w = board_h = 0.0

    nets = [n for n in net_map.values() if n.pin_ids or n.nail_ids]

    logger.info(
        "Landrex BRD: %d parts, %d pins, %d nails, %d nets, %.0f×%.0f mils",
        len(parts), len(pins), len(nails), len(nets), board_w, board_h,
    )

    return ParsedBoard(
        format='brd_landrex',
        outline=outline,
        parts=parts,
        pins=pins,
        nails=nails,
        nets=nets,
        width=board_w,
        height=board_h,
    )
