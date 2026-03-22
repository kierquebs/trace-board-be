"""
Unified board data model.

Every parser converts its native format into these dataclasses.
The to_json() method on ParsedBoard produces the exact payload
sent to the frontend — nothing more, nothing less.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Point:
    x: float
    y: float

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y}


@dataclass
class BoundingBox:
    x: float
    y: float
    width: float
    height: float

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


@dataclass
class ParsedPin:
    id: str                     # Unique within board, e.g. "U1_1"
    part_id: str                # Parent part id
    name: str                   # Pin name/number, e.g. "1", "A3", "GND"
    net_id: str                 # Net this pin belongs to (empty string if unconnected)
    net_name: str               # Human-readable net name
    position: Point
    side: str                   # "top" | "bottom"
    diameter: float = 0.0       # Pin pad diameter (board units)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "part_id": self.part_id,
            "name": self.name,
            "net_id": self.net_id,
            "net_name": self.net_name,
            "position": self.position.to_dict(),
            "side": self.side,
            "diameter": self.diameter,
        }


@dataclass
class ParsedPart:
    id: str                     # Unique part id, e.g. "U1", "C45"
    name: str                   # Reference designator, e.g. "U1"
    side: str                   # "top" | "bottom"
    bounds: BoundingBox
    part_type: str = ""         # Package type, e.g. "0402", "BGA256"
    value: str = ""             # Component value, e.g. "10uF"
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "side": self.side,
            "bounds": self.bounds.to_dict(),
            "part_type": self.part_type,
            "value": self.value,
            "description": self.description,
        }


@dataclass
class ParsedNail:
    """Test point / probe nail."""
    id: str
    probe_number: int
    position: Point
    net_id: str
    net_name: str
    side: str = "top"
    diameter: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "probe_number": self.probe_number,
            "position": self.position.to_dict(),
            "net_id": self.net_id,
            "net_name": self.net_name,
            "side": self.side,
            "diameter": self.diameter,
        }


# Ground net name patterns (case-insensitive)
_GROUND_PATTERNS = re.compile(
    r"^(gnd|ground|vss|agnd|dgnd|pgnd|chassis|earth|gndd|gndp)$",
    re.IGNORECASE,
)

# Power net name patterns
_POWER_PATTERNS = re.compile(
    r"^(vcc|vdd|vref|vbat|vsys|vbus|v\d|pp\w+|pwr|power|3v3|5v|12v|1v8|1v2|pvcc|pvdd)",
    re.IGNORECASE,
)


@dataclass
class ParsedNet:
    id: str
    name: str
    pin_ids: list[str] = field(default_factory=list)
    nail_ids: list[str] = field(default_factory=list)

    @property
    def is_ground(self) -> bool:
        return bool(_GROUND_PATTERNS.match(self.name))

    @property
    def is_power(self) -> bool:
        return not self.is_ground and bool(_POWER_PATTERNS.match(self.name))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "pin_ids": self.pin_ids,
            "nail_ids": self.nail_ids,
            "is_ground": self.is_ground,
            "is_power": self.is_power,
        }


@dataclass
class ParsedBoard:
    format: str                             # "brd2", "brd_landrex", "bv", etc.
    outline: list[Point] = field(default_factory=list)
    parts: list[ParsedPart] = field(default_factory=list)
    pins: list[ParsedPin] = field(default_factory=list)
    nails: list[ParsedNail] = field(default_factory=list)
    nets: list[ParsedNet] = field(default_factory=list)

    # Board bounding box (computed from outline or part extents)
    width: float = 0.0
    height: float = 0.0

    def to_json(self) -> dict:
        """
        Serialize to the exact JSON structure the frontend expects.
        This is what gets cached in Redis and sent over the wire.
        """
        return {
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "outline": [p.to_dict() for p in self.outline],
            "parts": [p.to_dict() for p in self.parts],
            "pins": [p.to_dict() for p in self.pins],
            "nails": [n.to_dict() for n in self.nails],
            "nets": [n.to_dict() for n in self.nets],
        }

    @property
    def stats(self) -> dict:
        return {
            "part_count": len(self.parts),
            "pin_count": len(self.pins),
            "net_count": len(self.nets),
            "format": self.format,
        }


@dataclass
class ParseResult:
    success: bool
    board: Optional[ParsedBoard] = None
    error: str = ""
