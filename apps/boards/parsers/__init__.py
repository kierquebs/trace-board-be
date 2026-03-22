"""
Parser registry.

Usage:
    from apps.boards.parsers import parse_board_file

    result = parse_board_file(file_bytes, "iphone15.brd")
    if result.success:
        board_json = result.board.to_json()
"""
from __future__ import annotations

import logging

from .detect import BoardFormat, detect_format
from .models import ParseResult

logger = logging.getLogger(__name__)


def parse_board_file(file_bytes: bytes, filename: str) -> ParseResult:
    """
    Detect format and dispatch to the correct parser.
    Always returns a ParseResult — never raises.
    """
    if not file_bytes:
        return ParseResult(success=False, error="Empty file")

    fmt = detect_format(file_bytes, filename)
    logger.info("Detected format %s for %s (%d bytes)", fmt, filename, len(file_bytes))

    try:
        parser_fn = _REGISTRY.get(fmt)
        if parser_fn is None:
            return ParseResult(
                success=False,
                error=f"Unsupported format: {fmt}. "
                      f"Supported formats: {', '.join(f.value for f in _REGISTRY)}",
            )
        return parser_fn(file_bytes, filename)

    except Exception as exc:
        logger.exception("Unexpected error parsing %s", filename)
        return ParseResult(success=False, error=f"Parse error: {exc}")


def _load_registry() -> dict:
    """
    Lazy-import parsers to keep startup fast.
    Add new parsers here as they are implemented.
    """
    from . import brd2  # noqa: F401 — always available

    registry = {
        BoardFormat.BRD2: brd2.parse,
    }

    # Import optional parsers — skip gracefully if not yet implemented
    try:
        from . import brd_landrex
        registry[BoardFormat.BRD_LANDREX] = brd_landrex.parse
    except ImportError:
        pass

    try:
        from . import bv
        registry[BoardFormat.BV] = bv.parse
    except ImportError:
        pass

    try:
        from . import fz
        registry[BoardFormat.FZ] = fz.parse
    except ImportError:
        pass

    try:
        from . import asc
        registry[BoardFormat.ASC] = asc.parse
    except ImportError:
        pass

    return registry


_REGISTRY: dict = _load_registry()


__all__ = ["parse_board_file", "detect_format", "BoardFormat"]
