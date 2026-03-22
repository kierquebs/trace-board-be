"""
BV / BVR boardview parser — Microsoft Access JET database variant.

Some boardview tools export .bv files as Access 97/2000 (.mdb) databases
instead of the plain-text BRDVIEW format.  This parser uses the mdbtools
CLI (mdb-export) to extract the three tables:

    Layout  — board outline points (X, Y in inches)
    Pin     — part pins with net assignments (X, Y in inches)
    Nail    — test-point nails (X, Y in inches)

Parts and nets are derived from the Pin table (no dedicated tables).

Coordinates in all three tables are in **inches** and are converted to
**mils** (×1000) to match the unified ParsedBoard coordinate system.

Requires: mdbtools (apt: mdbtools)
"""
from __future__ import annotations

import csv
import io
import logging
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile

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

# Inches → mils conversion factor
_MILS = 1_000.0


def parse(file_bytes: bytes, filename: str) -> ParseResult:
    if not file_bytes:
        return ParseResult(success=False, error="Empty file")
    try:
        board = _parse_mdb(file_bytes, filename)
        return ParseResult(success=True, board=board)
    except _MdbToolsNotFound:
        return ParseResult(
            success=False,
            error="mdbtools not installed — cannot parse MDB boardview files. "
                  "Install with: apt-get install mdbtools",
        )
    except Exception as exc:
        logger.exception("BV-MDB parse failed for %s", filename)
        return ParseResult(success=False, error=str(exc))


class _MdbToolsNotFound(RuntimeError):
    pass


def _mdb_export(db_path: str, table: str) -> list[dict[str, str]]:
    """Run mdb-export and return rows as list of dicts."""
    try:
        result = subprocess.run(
            ["mdb-export", db_path, table],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        raise _MdbToolsNotFound("mdb-export not found")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"mdb-export failed for table {table!r}: {exc.stderr.strip()}")

    reader = csv.DictReader(io.StringIO(result.stdout))
    return list(reader)


def _decode_side(tb: str) -> str:
    """'(T)' → 'top', '(B)' → 'bottom'."""
    return "bottom" if tb.strip().upper() in ("(B)", "B", "2", "BOT", "BOTTOM") else "top"


def _normalise_net(name: str) -> str:
    cleaned = name.strip()
    if cleaned in ("", "?", "---", "NC", "UNCONNECTED"):
        return ""
    return cleaned.upper()


def _parse_mdb(file_bytes: bytes, filename: str) -> ParsedBoard:  # noqa: C901
    # Write bytes to a temp file so mdb-export can open it
    suffix = Path(filename).suffix or ".bv"
    with NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        layout_rows = _mdb_export(tmp_path, "Layout")
        pin_rows = _mdb_export(tmp_path, "Pin")
        nail_rows = _mdb_export(tmp_path, "Nail")
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    # ------------------------------------------------------------------
    # Build outline from Layout table
    # ------------------------------------------------------------------
    outline: list[Point] = []
    for row in layout_rows:
        try:
            x = float(row["X"]) * _MILS
            y = float(row["Y"]) * _MILS
            outline.append(Point(x, y))
        except (KeyError, ValueError):
            continue

    # ------------------------------------------------------------------
    # Build parts + pins + nets from Pin table
    # ------------------------------------------------------------------
    part_index: dict[str, ParsedPart] = {}
    parts: list[ParsedPart] = []
    pins: list[ParsedPin] = []
    net_map: dict[str, ParsedNet] = {}

    for row in pin_rows:
        part_name = row.get("Part", "").strip()
        pin_num = row.get("Pin", "").strip()
        pin_name = row.get("Name", "").strip()
        net_name = row.get("Net", "").strip()
        tb = row.get("TB", "")

        try:
            px = float(row["X"]) * _MILS
            py = float(row["Y"]) * _MILS
        except (KeyError, ValueError):
            continue

        pin_side = _decode_side(tb)
        net_id = _normalise_net(net_name)
        pin_id = f"{part_name}_{pin_num}"

        # Ensure parent part exists
        if part_name and part_name not in part_index:
            part = ParsedPart(
                id=part_name,
                name=part_name,
                side=pin_side,
                bounds=BoundingBox(x=px, y=py, width=0.0, height=0.0),
            )
            parts.append(part)
            part_index[part_name] = part

        pin = ParsedPin(
            id=pin_id,
            part_id=part_name,
            name=pin_name,
            net_id=net_id,
            net_name=net_name,
            position=Point(px, py),
            side=pin_side,
            diameter=0.0,
        )
        pins.append(pin)

        if net_id:
            if net_id not in net_map:
                net_map[net_id] = ParsedNet(id=net_id, name=net_name)
            net_map[net_id].pin_ids.append(pin_id)

        # Expand part bounding box
        if part_name in part_index:
            _expand_bounds(part_index[part_name].bounds, px, py)

    # ------------------------------------------------------------------
    # Build nails from Nail table
    # ------------------------------------------------------------------
    nails: list[ParsedNail] = []
    for idx, row in enumerate(nail_rows):
        net_name = row.get("NetName", "").strip()
        tb = row.get("TB", "")
        grid = row.get("Grid", "").strip()

        try:
            nx = float(row["X"]) * _MILS
            ny = float(row["Y"]) * _MILS
        except (KeyError, ValueError):
            continue

        net_id = _normalise_net(net_name)
        nail_id = f"nail_{grid or idx}"

        nail = ParsedNail(
            id=nail_id,
            probe_number=idx,
            position=Point(nx, ny),
            net_id=net_id,
            net_name=net_name,
            side=_decode_side(tb),
            diameter=0.0,
        )
        nails.append(nail)

        if net_id:
            if net_id not in net_map:
                net_map[net_id] = ParsedNet(id=net_id, name=net_name)
            net_map[net_id].nail_ids.append(nail_id)

    # ------------------------------------------------------------------
    # Compute board dimensions
    # ------------------------------------------------------------------
    board_width = 0.0
    board_height = 0.0

    if outline:
        xs = [p.x for p in outline]
        ys = [p.y for p in outline]
        board_width = max(xs) - min(xs)
        board_height = max(ys) - min(ys)
    elif pins:
        xs = [p.position.x for p in pins]
        ys = [p.position.y for p in pins]
        board_width = max(xs) - min(xs)
        board_height = max(ys) - min(ys)

    return ParsedBoard(
        format="bv_mdb",
        outline=outline,
        parts=parts,
        pins=pins,
        nails=nails,
        nets=list(net_map.values()),
        width=board_width,
        height=board_height,
    )


def _expand_bounds(bounds: BoundingBox, x: float, y: float, padding: float = 20.0) -> None:
    if bounds.width == 0 and bounds.height == 0:
        bounds.x = x - padding
        bounds.y = y - padding
        bounds.width = padding * 2
        bounds.height = padding * 2
        return
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
