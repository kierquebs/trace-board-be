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
from typing import Optional

from .models import (
    BoundingBox,
    ParsedBoard,
    ParsedNet,
    ParsedPin,
    ParsedPart,
    ParseResult,
    Point,
)

logger = logging.getLogger(__name__)

_SEP = 0xF7   # separator / padding byte


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
    parts_hdr: Optional[int] = None
    pins_hdr:  Optional[int] = None
    nets_hdr:  Optional[int] = None

    for i, line in enumerate(lines):
        d = _decode(line)
        if d.startswith('Parts:'):
            parts_hdr = i
        elif d.startswith('Pins:'):
            pins_hdr = i
        elif d.startswith('Nets:'):
            nets_hdr = i

    if parts_hdr is None or pins_hdr is None:
        raise ValueError("Cannot locate 'Parts:' or 'Pins:' section headers")

    p_start = parts_hdr + 1
    p_end   = pins_hdr          # exclusive
    q_start = pins_hdr + 1
    q_end   = nets_hdr if nets_hdr is not None else len(lines)

    logger.debug("Sections — parts [%d:%d]  pins [%d:%d]",
                 p_start, p_end, q_start, q_end)

    # ── Board outline (lines 7–11) ────────────────────────────────────────────
    outline: list[Point] = []
    for line in lines[7:12]:
        if not line:
            continue
        f = _split_fields(line)
        if len(f) >= 2:
            outline.append(Point(
                x=float(_int(_decode(f[0]))),
                y=float(_int(_decode(f[1]))),
            ))
    # Remove duplicate closing vertex if present
    if len(outline) >= 2 and outline[0].x == outline[-1].x and outline[0].y == outline[-1].y:
        outline = outline[:-1]

    # ── Parse PARTS (22-byte fixed-width lines) ───────────────────────────────
    # bytes  0–10: component name (0xf7 padded)
    # bytes 11–16: rotation/side flag
    # bytes 17–21: exclusive end index into PINS
    raw_parts: list[dict] = []
    for line in lines[p_start:p_end]:
        if len(line) < 22:
            continue
        name = _decode(line[0:11])
        if not name:
            continue
        side_raw = _decode(line[11:17])
        end_idx  = _int(_decode(line[17:22]), default=-1)
        if end_idx < 0:
            continue
        side = 'bottom' if side_raw == '5' else 'top'
        raw_parts.append({'name': name, 'side': side, 'end': end_idx})

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
            x        = int(_decode(f[0]))
            y        = int(_decode(f[1]))
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

        # Bounding box from pin positions + 20 mil margin
        if part_pin_objects:
            xs = [p.position.x for p in part_pin_objects]
            ys = [p.position.y for p in part_pin_objects]
            margin = 20.0
            bounds = BoundingBox(
                x=min(xs) - margin,
                y=min(ys) - margin,
                width=max(max(xs) - min(xs) + 2 * margin, 40.0),
                height=max(max(ys) - min(ys) + 2 * margin, 40.0),
            )
        else:
            bounds = BoundingBox(x=0, y=0, width=40, height=40)

        parts.append(ParsedPart(
            id=part_id,
            name=prec['name'],
            side=prec['side'],
            bounds=bounds,
        ))

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

    nets = [n for n in net_map.values() if n.pin_ids]

    logger.info(
        "Landrex BRD: %d parts, %d pins, %d nets, %.0f×%.0f mils",
        len(parts), len(pins), len(nets), board_w, board_h,
    )

    return ParsedBoard(
        format='brd_landrex',
        outline=outline,
        parts=parts,
        pins=pins,
        nails=[],
        nets=nets,
        width=board_w,
        height=board_h,
    )
