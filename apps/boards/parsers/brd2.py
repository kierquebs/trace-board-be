"""
BRD2 / TOPTEST parser.

Plain-text .brd format used by TOPTEST board testers.
Section structure:

  BRD2
  [optional header lines]

  BRDOUT <w> <h> <num_components>
  COMPONENT <name> <x> <y> <side> <rotation>
    PIN <num> <net> <x> <y>
    ...
  NET_LIST
    NET <name> <pin_count>
      <component> <pin>
      ...

Reference: OpenBoardView BRD2File.cpp
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict

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

# Section header patterns
_RE_BRDOUT = re.compile(
    r"^BRDOUT\s+(\S+)\s+(\S+)(?:\s+(\d+))?", re.IGNORECASE
)
_RE_COMPONENT = re.compile(
    r"^COMPONENT\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(\S+))?", re.IGNORECASE
)
_RE_PIN = re.compile(
    r"^\s+PIN\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(\S+))?", re.IGNORECASE
)
_RE_NET = re.compile(r"^NET\s+(\S+)(?:\s+(\d+))?", re.IGNORECASE)
_RE_NAIL = re.compile(
    r"^NAIL\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)(?:\s+(\S+))?", re.IGNORECASE
)
_RE_OUTLINE = re.compile(r"^OUTLINE\s+(.*)", re.IGNORECASE)


def parse(file_bytes: bytes, filename: str) -> ParseResult:
    if not file_bytes or not file_bytes.strip():
        return ParseResult(success=False, error="Empty file")
    try:
        text = file_bytes.decode("utf-8", errors="replace")
        board = _parse_text(text)
        return ParseResult(success=True, board=board)
    except Exception as exc:
        logger.exception("BRD2 parse failed for %s", filename)
        return ParseResult(success=False, error=str(exc))


def _parse_text(text: str) -> ParsedBoard:  # noqa: C901
    lines = text.splitlines()

    parts: list[ParsedPart] = []
    pins: list[ParsedPin] = []
    nails: list[ParsedNail] = []
    nets: list[ParsedNet] = []
    outline: list[Point] = []
    board_width = 0.0
    board_height = 0.0

    # Lookup: net_name → ParsedNet (populated during component/pin pass,
    # enriched with pin_ids during net-list pass)
    net_map: dict[str, ParsedNet] = {}
    # Lookup: (part_name, pin_name) → pin_id  (for net-list cross-reference)
    pin_lookup: dict[tuple[str, str], str] = {}

    current_part: ParsedPart | None = None
    in_net_list = False
    current_net: ParsedNet | None = None
    nail_counter = 0

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "#", ";")):
            continue

        upper = stripped.upper()

        # ---------------------------------------------------------------
        # Board dimensions
        # ---------------------------------------------------------------
        m = _RE_BRDOUT.match(stripped)
        if m:
            try:
                board_width = float(m.group(1))
                board_height = float(m.group(2))
            except ValueError:
                pass
            continue

        # ---------------------------------------------------------------
        # Component definition
        # ---------------------------------------------------------------
        m = _RE_COMPONENT.match(stripped)
        if m and not in_net_list:
            name = m.group(1)
            try:
                x = float(m.group(2))
                y = float(m.group(3))
            except ValueError:
                x, y = 0.0, 0.0
            side_raw = (m.group(4) or "T").upper()
            side = "bottom" if side_raw in ("B", "BOT", "BOTTOM", "2") else "top"

            current_part = ParsedPart(
                id=name,
                name=name,
                side=side,
                bounds=BoundingBox(x=x, y=y, width=0.0, height=0.0),
            )
            parts.append(current_part)
            continue

        # ---------------------------------------------------------------
        # Pin under current component
        # ---------------------------------------------------------------
        m = _RE_PIN.match(line)  # Use original line to preserve leading whitespace
        if m and current_part and not in_net_list:
            pin_name = m.group(1)
            net_name = m.group(2)
            try:
                px = float(m.group(3))
                py = float(m.group(4))
            except ValueError:
                px, py = current_part.bounds.x, current_part.bounds.y

            net_id = _normalise_net_name(net_name)
            pin_id = f"{current_part.id}_{pin_name}"

            pin = ParsedPin(
                id=pin_id,
                part_id=current_part.id,
                name=pin_name,
                net_id=net_id,
                net_name=net_name,
                position=Point(px, py),
                side=current_part.side,
            )
            pins.append(pin)
            pin_lookup[(current_part.id, pin_name)] = pin_id

            # Ensure net exists in map
            if net_id and net_id not in net_map:
                net_map[net_id] = ParsedNet(id=net_id, name=net_name)
            if net_id:
                net_map[net_id].pin_ids.append(pin_id)

            # Expand part bounding box
            _expand_bounds(current_part.bounds, px, py)
            continue

        # ---------------------------------------------------------------
        # Nail / test point
        # ---------------------------------------------------------------
        m = _RE_NAIL.match(stripped)
        if m:
            nail_counter += 1
            try:
                probe = int(m.group(1))
                net_name = m.group(2)
                nx = float(m.group(3))
                ny = float(m.group(4))
            except ValueError:
                continue
            side_raw = (m.group(5) or "T").upper()
            side = "bottom" if side_raw in ("B", "BOT", "BOTTOM", "2") else "top"

            net_id = _normalise_net_name(net_name)
            nail_id = f"nail_{probe}"

            nail = ParsedNail(
                id=nail_id,
                probe_number=probe,
                position=Point(nx, ny),
                net_id=net_id,
                net_name=net_name,
                side=side,
            )
            nails.append(nail)

            if net_id and net_id not in net_map:
                net_map[net_id] = ParsedNet(id=net_id, name=net_name)
            if net_id:
                net_map[net_id].nail_ids.append(nail_id)
            continue

        # ---------------------------------------------------------------
        # NET_LIST section header
        # ---------------------------------------------------------------
        if upper == "NET_LIST":
            in_net_list = True
            current_part = None
            current_net = None
            continue

        # ---------------------------------------------------------------
        # Outline
        # ---------------------------------------------------------------
        m = _RE_OUTLINE.match(stripped)
        if m:
            coords = m.group(1).split()
            it = iter(coords)
            for x_str, y_str in zip(it, it):
                try:
                    outline.append(Point(float(x_str), float(y_str)))
                except ValueError:
                    pass
            continue

    # ------------------------------------------------------------------
    # Compute geometry for each part
    # ------------------------------------------------------------------
    part_pin_positions: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for pin in pins:
        part_pin_positions[pin.part_id].append((pin.position.x, pin.position.y))

    for part in parts:
        positions = part_pin_positions.get(part.id, [])
        part.geometry = compute_part_geometry(part.name, positions)

    # ------------------------------------------------------------------
    # Derive bounding box from part positions if outline missing
    # ------------------------------------------------------------------
    if not outline and parts:
        min_x = min(p.bounds.x for p in parts)
        min_y = min(p.bounds.y for p in parts)
        max_x = max(p.bounds.x + p.bounds.width for p in parts)
        max_y = max(p.bounds.y + p.bounds.height for p in parts)
        outline = [
            Point(min_x, min_y),
            Point(max_x, min_y),
            Point(max_x, max_y),
            Point(min_x, max_y),
        ]
        if not board_width:
            board_width = max_x - min_x
        if not board_height:
            board_height = max_y - min_y

    nets = list(net_map.values())

    return ParsedBoard(
        format="brd2",
        outline=outline,
        parts=parts,
        pins=pins,
        nails=nails,
        nets=nets,
        width=board_width,
        height=board_height,
    )


def _normalise_net_name(name: str) -> str:
    """Convert net name to a stable id (strip whitespace, uppercase)."""
    return name.strip().upper() if name.strip() not in ("", "?", "---", "NC") else ""


def _expand_bounds(bounds: BoundingBox, x: float, y: float, padding: float = 0.0) -> None:
    """Grow a part's bounding box to include a new pin position."""
    if bounds.width == 0 and bounds.height == 0:
        return  # First pin sets anchor — bounds will be set from x,y delta
    # We accumulate min/max by storing current max in width/height temporarily
    cur_max_x = bounds.x + bounds.width
    cur_max_y = bounds.y + bounds.height
    new_min_x = min(bounds.x, x - padding)
    new_min_y = min(bounds.y, y - padding)
    new_max_x = max(cur_max_x, x + padding)
    new_max_y = max(cur_max_y, y + padding)
    bounds.x = new_min_x
    bounds.y = new_min_y
    bounds.width = new_max_x - new_min_x
    bounds.height = new_max_y - new_min_y
