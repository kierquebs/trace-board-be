"""
BV / BVR boardview parser.

Handles the BRDVIEW text format (.bv, .bvr).
Section structure:

    BRDVIEW <version>
    [FILEINFO
     width <w>
     height <h>]
    PARTS
      <name> <cx> <cy> <rotation> <side> <pin_count>
      ...
    ENDPARTS
    PINS
      <part_name> <pin_name> <net_name> <x> <y> <side> <diameter>
      ...
    ENDPINS
    NAILS
      <probe_number> <net_name> <x> <y> <side> <diameter>
      ...
    ENDNAILS
    NETS
      <net_name> <pin_count>
        <part_name> <pin_name>
        ...
      ...
    ENDNETS

Side encoding: 1 or T = top, 2 or B = bottom.

Reference: OpenBoardView BVRFile.cpp
"""
from __future__ import annotations

import logging
from collections import defaultdict

from .geometry import compute_part_geometry
from .models import (
    BoundingBox,
    ParsedBoard,
    ParsedNail,
    ParsedNet,
    ParsedPart,
    ParsedPin,
    ParseResult,
    Point,
)

logger = logging.getLogger(__name__)

# Section sentinel tokens
_SECTION_PARTS = "PARTS"
_SECTION_PINS = "PINS"
_SECTION_NAILS = "NAILS"
_SECTION_NETS = "NETS"
_SECTION_FILEINFO = "FILEINFO"
_END_TOKENS = frozenset({"ENDPARTS", "ENDPINS", "ENDNAILS", "ENDNETS", "ENDFILEINFO"})


def parse(file_bytes: bytes, filename: str) -> ParseResult:
    if not file_bytes:
        return ParseResult(success=False, error="Empty file")
    try:
        text = file_bytes.decode("utf-8", errors="replace")
        board = _parse_text(text)
        return ParseResult(success=True, board=board)
    except Exception as exc:
        logger.exception("BV parse failed for %s", filename)
        return ParseResult(success=False, error=str(exc))


def _parse_text(text: str) -> ParsedBoard:  # noqa: C901
    lines = text.splitlines()

    parts: list[ParsedPart] = []
    pins: list[ParsedPin] = []
    nails: list[ParsedNail] = []
    net_map: dict[str, ParsedNet] = {}

    board_width = 0.0
    board_height = 0.0

    # part_name → ParsedPart (for bounding-box expansion during PINS pass)
    part_index: dict[str, ParsedPart] = {}

    section: str = ""

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "#", ";")):
            continue

        upper = stripped.upper()

        # ---------------------------------------------------------------
        # Section transitions
        # ---------------------------------------------------------------
        if upper in _END_TOKENS:
            section = ""
            continue

        if upper == _SECTION_PARTS:
            section = _SECTION_PARTS
            continue

        if upper == _SECTION_PINS:
            section = _SECTION_PINS
            continue

        if upper == _SECTION_NAILS:
            section = _SECTION_NAILS
            continue

        if upper == _SECTION_NETS:
            section = _SECTION_NETS
            continue

        if upper == _SECTION_FILEINFO:
            section = _SECTION_FILEINFO
            continue

        # ---------------------------------------------------------------
        # Skip BRDVIEW header line
        # ---------------------------------------------------------------
        if upper.startswith("BRDVIEW"):
            continue

        # ---------------------------------------------------------------
        # FILEINFO — optional board dimensions
        # ---------------------------------------------------------------
        if section == _SECTION_FILEINFO:
            tokens = stripped.split()
            if len(tokens) >= 2:
                key = tokens[0].lower()
                try:
                    if key == "width":
                        board_width = float(tokens[1])
                    elif key == "height":
                        board_height = float(tokens[1])
                except ValueError:
                    pass
            continue

        # ---------------------------------------------------------------
        # PARTS — <name> <cx> <cy> <rotation> <side> [<pin_count>]
        # ---------------------------------------------------------------
        if section == _SECTION_PARTS:
            tokens = stripped.split()
            if len(tokens) < 5:
                continue
            name = tokens[0]
            try:
                cx = float(tokens[1])
                cy = float(tokens[2])
                # tokens[3] = rotation (ignored for display)
                side = _decode_side(tokens[4])
            except (ValueError, IndexError):
                continue

            part = ParsedPart(
                id=name,
                name=name,
                side=side,
                bounds=BoundingBox(x=cx, y=cy, width=0.0, height=0.0),
            )
            parts.append(part)
            part_index[name] = part
            continue

        # ---------------------------------------------------------------
        # PINS — <part_name> <pin_name> <net_name> <x> <y> <side> [<diameter>]
        # ---------------------------------------------------------------
        if section == _SECTION_PINS:
            tokens = stripped.split()
            if len(tokens) < 6:
                continue
            part_name = tokens[0]
            pin_name = tokens[1]
            net_name = tokens[2]
            try:
                px = float(tokens[3])
                py = float(tokens[4])
                pin_side = _decode_side(tokens[5])
                diameter = float(tokens[6]) if len(tokens) >= 7 else 0.0
            except (ValueError, IndexError):
                continue

            net_id = _normalise_net(net_name)
            pin_id = f"{part_name}_{pin_name}"

            pin = ParsedPin(
                id=pin_id,
                part_id=part_name,
                name=pin_name,
                net_id=net_id,
                net_name=net_name,
                position=Point(px, py),
                side=pin_side,
                diameter=diameter,
            )
            pins.append(pin)

            # Register net and add pin
            if net_id:
                if net_id not in net_map:
                    net_map[net_id] = ParsedNet(id=net_id, name=net_name)
                net_map[net_id].pin_ids.append(pin_id)

            # Expand parent part bounding box
            if part_name in part_index:
                _expand_bounds(part_index[part_name].bounds, px, py)
            continue

        # ---------------------------------------------------------------
        # NAILS — <probe_number> <net_name> <x> <y> <side> [<diameter>]
        # ---------------------------------------------------------------
        if section == _SECTION_NAILS:
            tokens = stripped.split()
            if len(tokens) < 5:
                continue
            try:
                probe = int(tokens[0])
                net_name = tokens[1]
                nx = float(tokens[2])
                ny = float(tokens[3])
                nail_side = _decode_side(tokens[4])
                diameter = float(tokens[5]) if len(tokens) >= 6 else 0.0
            except (ValueError, IndexError):
                continue

            net_id = _normalise_net(net_name)
            nail_id = f"nail_{probe}"

            nail = ParsedNail(
                id=nail_id,
                probe_number=probe,
                position=Point(nx, ny),
                net_id=net_id,
                net_name=net_name,
                side=nail_side,
                diameter=diameter,
            )
            nails.append(nail)

            if net_id:
                if net_id not in net_map:
                    net_map[net_id] = ParsedNet(id=net_id, name=net_name)
                net_map[net_id].nail_ids.append(nail_id)
            continue

        # NETS section is informational only — pin/net associations are
        # already built from the PINS pass above, so we skip it.

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
    # Derive board outline and dimensions from part extents if not given
    # ------------------------------------------------------------------
    all_x: list[float] = []
    all_y: list[float] = []

    for p in parts:
        all_x.append(p.bounds.x)
        all_y.append(p.bounds.y)
        if p.bounds.width:
            all_x.append(p.bounds.x + p.bounds.width)
        if p.bounds.height:
            all_y.append(p.bounds.y + p.bounds.height)

    for pin in pins:
        all_x.append(pin.position.x)
        all_y.append(pin.position.y)

    outline: list[Point] = []
    if all_x and all_y:
        min_x, max_x = min(all_x), max(all_x)
        min_y, max_y = min(all_y), max(all_y)
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

    return ParsedBoard(
        format="bv",
        outline=outline,
        parts=parts,
        pins=pins,
        nails=nails,
        nets=list(net_map.values()),
        width=board_width,
        height=board_height,
    )


def _decode_side(raw: str) -> str:
    """Normalise side token to 'top' or 'bottom'."""
    return "bottom" if raw.upper() in ("2", "B", "BOT", "BOTTOM") else "top"


def _normalise_net(name: str) -> str:
    """Return stable net id; empty string for unconnected markers."""
    cleaned = name.strip()
    if cleaned in ("", "?", "---", "NC", "UNCONNECTED"):
        return ""
    return cleaned.upper()


def _expand_bounds(bounds: BoundingBox, x: float, y: float, padding: float = 0.0) -> None:
    """Grow a part's bounding box to encompass a pin position.

    Parts are initialised with their PARTS-section center as (x, y) and
    width=height=0, so the first call expands from that anchor outward.
    """
    cur_max_x = bounds.x + bounds.width
    cur_max_y = bounds.y + bounds.height
    bounds.x = min(bounds.x, x - padding)
    bounds.y = min(bounds.y, y - padding)
    bounds.width = max(cur_max_x, x + padding) - bounds.x
    bounds.height = max(cur_max_y, y + padding) - bounds.y
