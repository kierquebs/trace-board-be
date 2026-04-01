"""
Shared geometry computation for PCB parts.

Computes center position, rotation angle, dimensions, and a rotated
bounding-box outline for each part based on its pin positions.

Algorithms ported from OpenBoardView's BoardView.cpp geometry routines.
All coordinates are in mils (thousandths of an inch).

No Django / DRF imports — pure Python only.
"""
from __future__ import annotations

import math
from typing import Optional

from .models import Geometry, Point


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _rotate_point(
    px: float, py: float,
    ox: float, oy: float,
    theta: float,
) -> tuple[float, float]:
    """Rotate (px, py) around origin (ox, oy) by angle theta (radians)."""
    tx, ty = px - ox, py - oy
    return (
        tx * math.cos(theta) - ty * math.sin(theta) + ox,
        tx * math.sin(theta) + ty * math.cos(theta) + oy,
    )


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """
    Compute the convex hull using Andrew's monotone chain algorithm.
    Returns vertices in counter-clockwise order.
    """
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o: tuple, a: tuple, b: tuple) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: list[tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    return lower[:-1] + upper[:-1]


# ---------------------------------------------------------------------------
# Geometry builders
# ---------------------------------------------------------------------------

def _single_pad_geometry(pin_pos: tuple[float, float]) -> Geometry:
    """Square pad centered on a single pin position."""
    px, py = pin_pos
    pad = 10.0
    return Geometry(
        center_x=px,
        center_y=py,
        angle_deg=0.0,
        width=pad * 2,
        height=pad * 2,
        outline=[
            Point(px - pad, py - pad),
            Point(px - pad, py + pad),
            Point(px + pad, py + pad),
            Point(px + pad, py - pad),
        ],
    )


def _two_pin_geometry(
    pin_positions: list[tuple[float, float]],
    part_name: str,
) -> Geometry:
    """
    Rotated bounding box for two-pin passives (C, R, L, D, F, ≤3 pins).

    Uses atan2 of the pin-to-pin vector for the rotation angle, then builds
    a rotated rectangle sized by package heuristics from OpenBoardView.
    """
    p0x, p0y = pin_positions[0]
    p1x, p1y = pin_positions[-1]

    dx = p1x - p0x
    dy = p1y - p0y
    angle = math.atan2(dy, dx)          # radians — this IS the rotation angle
    distance = math.sqrt(dx * dx + dy * dy)

    # Pad-radius heuristics keyed on component pitch (from OpenBoardView):
    pin_radius: float = 10.0           # default
    if 247 < distance < 253:
        pin_radius = 50.0              # SMC diode
    elif 195 < distance < 199:
        pin_radius = 50.0              # Inductor
    elif 165 < distance < 169:
        pin_radius = 35.0              # SMB diode
    elif 108 < distance < 112:
        pin_radius = 30.0              # 1206
    elif 101 < distance < 109:
        pin_radius = 30.0              # SMA diode / tant cap
    elif 64 < distance < 68:
        pin_radius = 25.0              # 0805
    elif 52 < distance < 57:
        pin_radius = 15.0              # 0603
    elif 28 < distance < 32:
        pin_radius = 10.0              # 0402
    elif 18 < distance < 22:
        pin_radius = 5.0               # 0201

    armx: float = pin_radius
    army: float = pin_radius

    prefix = part_name[0].upper() if part_name else ''

    # Special size overrides for large inductors and capacitors:
    if prefix == 'L' and distance > 50:
        army = distance / 2
        armx = 15.0
    elif prefix == 'C' and distance > 90:
        army = distance / 2 - distance / 4
        armx = 15.0

    # Build 4 corners of the rotated rectangle.
    # c0/c1 pivot around pin 0; c2/c3 pivot around pin 1.
    c0 = _rotate_point(p0x - armx, p0y - army, p0x, p0y, angle)
    c1 = _rotate_point(p0x - armx, p0y + army, p0x, p0y, angle)
    c2 = _rotate_point(p1x + armx, p1y + army, p1x, p1y, angle)
    c3 = _rotate_point(p1x + armx, p1y - army, p1x, p1y, angle)

    center_x = (p0x + p1x) / 2
    center_y = (p0y + p1y) / 2
    width = distance + 2 * armx
    height = 2 * army
    angle_deg = math.degrees(angle) % 360.0

    return Geometry(
        center_x=round(center_x, 1),
        center_y=round(center_y, 1),
        angle_deg=round(angle_deg, 1),
        width=round(width, 1),
        height=round(height, 1),
        outline=[
            Point(round(c0[0], 1), round(c0[1], 1)),
            Point(round(c1[0], 1), round(c1[1], 1)),
            Point(round(c2[0], 1), round(c2[1], 1)),
            Point(round(c3[0], 1), round(c3[1], 1)),
        ],
    )


def _multi_pin_ic_geometry(
    pin_positions: list[tuple[float, float]],
    pad_size: float = 10.0,
) -> Geometry:
    """
    Minimum bounding box for multi-pin ICs via convex hull + rotating calipers.

    For each convex hull edge, rotate all points so the edge is axis-aligned,
    compute the AABB, and keep the rotation that minimises rectangle area.
    Expands by pad_size on all sides before returning.
    """
    if len(pin_positions) == 1:
        return _single_pad_geometry(pin_positions[0])

    hull = _convex_hull(pin_positions)

    if len(hull) <= 1:
        return _single_pad_geometry(hull[0] if hull else pin_positions[0])

    # For a 2-point hull (all points collinear) consider both edge directions
    # so the perpendicular axis is also explored.
    if len(hull) == 2:
        edge_pairs: list[tuple[tuple, tuple]] = [
            (hull[0], hull[1]),
            (hull[1], hull[0]),
        ]
    else:
        n = len(hull)
        edge_pairs = [(hull[i], hull[(i + 1) % n]) for i in range(n)]

    best_area = float('inf')
    best_angle = 0.0
    best_rect: Optional[tuple[float, float, float, float]] = None

    for p0, p1 in edge_pairs:
        ex = p1[0] - p0[0]
        ey = p1[1] - p0[1]
        edge_angle = math.atan2(ey, ex)

        cos_a = math.cos(-edge_angle)
        sin_a = math.sin(-edge_angle)

        # Rotate all original pin positions (not just hull) for exact AABB
        rotated = [
            (p[0] * cos_a - p[1] * sin_a, p[0] * sin_a + p[1] * cos_a)
            for p in pin_positions
        ]

        min_x = min(r[0] for r in rotated)
        max_x = max(r[0] for r in rotated)
        min_y = min(r[1] for r in rotated)
        max_y = max(r[1] for r in rotated)

        area = (max_x - min_x) * (max_y - min_y)
        if area < best_area:
            best_area = area
            best_angle = edge_angle
            best_rect = (min_x, max_x, min_y, max_y)

    if best_rect is None:
        return _single_pad_geometry(pin_positions[0])

    min_x, max_x, min_y, max_y = best_rect

    # Expand by pad_size on all sides
    min_x -= pad_size
    max_x += pad_size
    min_y -= pad_size
    max_y += pad_size

    width = max_x - min_x
    height = max_y - min_y

    # Center in the rotated reference frame
    cx_rot = (min_x + max_x) / 2
    cy_rot = (min_y + max_y) / 2

    # Rotate center back to world coordinates
    cos_a = math.cos(best_angle)
    sin_a = math.sin(best_angle)
    center_x = cx_rot * cos_a - cy_rot * sin_a
    center_y = cx_rot * sin_a + cy_rot * cos_a

    angle_deg = math.degrees(best_angle) % 360.0

    # Compute 4 corners in rotated space then rotate back
    corners = []
    for rx, ry in [
        (min_x, min_y),
        (min_x, max_y),
        (max_x, max_y),
        (max_x, min_y),
    ]:
        wx = rx * cos_a - ry * sin_a
        wy = rx * sin_a + ry * cos_a
        corners.append(Point(round(wx, 1), round(wy, 1)))

    return Geometry(
        center_x=round(center_x, 1),
        center_y=round(center_y, 1),
        angle_deg=round(angle_deg, 1),
        width=round(width, 1),
        height=round(height, 1),
        outline=corners,
    )


# ---------------------------------------------------------------------------
# Public dispatch
# ---------------------------------------------------------------------------

def compute_part_geometry(
    part_name: str,
    pin_positions: list[tuple[float, float]],
) -> Optional[Geometry]:
    """
    Compute the geometry for a part given its name and pin positions.

    Dispatches to the appropriate algorithm:
    - 0 pins          → None
    - 1 pin (or all same position) → square pad
    - ≤3 pins, prefix C/R/L/D/F   → two-pin rotated rectangle
    - everything else              → minimum bounding box (rotating calipers)

    Returns None only when pin_positions is empty.
    """
    if not pin_positions:
        return None

    unique_pins = list(set(pin_positions))
    n = len(pin_positions)
    prefix = part_name[0].upper() if part_name else ''

    if n == 1 or len(unique_pins) == 1:
        return _single_pad_geometry(pin_positions[0])

    if n <= 3 and prefix in 'CRLDF':
        return _two_pin_geometry(pin_positions, part_name)

    return _multi_pin_ic_geometry(unique_pins)
