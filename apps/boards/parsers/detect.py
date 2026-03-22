"""
Board file format detection.

Detection order matters — BRD format has two very different variants
(Landrex binary and TOPTEST plain-text) that share the same extension.
We inspect file bytes to tell them apart.
"""
from enum import Enum
from pathlib import Path


class BoardFormat(str, Enum):
    BRD2 = "brd2"               # TOPTEST plain-text .brd
    BRD_LANDREX = "brd_landrex" # Landrex binary-encoded .brd
    BV = "bv"                   # .bv / .bvr text format (BRDVIEW)
    BV_MDB = "bv_mdb"           # .bv / .bvr Microsoft Access JET database
    FZ = "fz"                   # .fz XOR-encrypted (Asus)
    ASC = "asc"                 # Plain ASCII
    CAD = "cad"                 # GenCAD
    CST = "cst"                 # CAST/Samsung
    UNKNOWN = "unknown"


# JET/MDB magic — "Standard Jet DB" appears at byte offset 4
_BV_MDB_MAGIC = b"Standard Jet DB"

# Magic bytes / text markers for each format
_BRD2_MARKERS = (
    b"BRD2",
    b"BRDOUT",
    b"COMPONENT",
    b"NET_LIST",
)

_BV_MARKERS = (
    b"BRDVIEW",
    b"BOARD_FILE",
    b"FORMAT BV",
)

_CAD_MARKERS = (
    b"$HEADER",
    b"GENCAD",
)


def detect_format(file_bytes: bytes, filename: str) -> BoardFormat:
    """
    Inspect file content and name to determine board format.
    Extension provides a hint but content signature is authoritative.
    """
    ext = Path(filename).suffix.lower()
    header = file_bytes[:512]   # Read first 512 bytes for detection

    # -----------------------------------------------------------------
    # Extension-based disambiguation for known single-extension formats
    # -----------------------------------------------------------------
    if ext == ".fz":
        return BoardFormat.FZ

    if ext == ".asc":
        return BoardFormat.ASC

    if ext in (".cad",):
        return BoardFormat.CAD

    if ext == ".cst":
        return BoardFormat.CST

    if ext in (".bv", ".bvr"):
        # Distinguish JET/MDB binary .bv from plain-text BRDVIEW .bv
        if _BV_MDB_MAGIC in file_bytes[:32]:
            return BoardFormat.BV_MDB
        return BoardFormat.BV

    # -----------------------------------------------------------------
    # .brd files: two very different formats share this extension
    # Detect by content signature
    # -----------------------------------------------------------------
    if ext == ".brd":
        # BRD2 / TOPTEST — starts with ASCII text markers
        header_text = header.upper()
        if any(marker in header_text for marker in _BRD2_MARKERS):
            return BoardFormat.BRD2

        # Landrex binary — does NOT start with ASCII text
        # It begins with binary-encoded data (byte rotation/XOR scheme)
        # Heuristic: high density of non-printable bytes in first 64 bytes
        non_printable = sum(1 for b in header[:64] if b < 0x20 or b > 0x7E)
        if non_printable > 20:
            return BoardFormat.BRD_LANDREX

        # Fallback for BRD files that look like text but didn't match BRD2
        return BoardFormat.BRD2

    # -----------------------------------------------------------------
    # Fallback: try content signatures regardless of extension
    # -----------------------------------------------------------------
    header_upper = header.upper()

    if any(marker in header_upper for marker in _BRD2_MARKERS):
        return BoardFormat.BRD2

    if any(marker in header_upper for marker in _BV_MARKERS):
        return BoardFormat.BV

    if any(marker in header_upper for marker in _CAD_MARKERS):
        return BoardFormat.CAD

    return BoardFormat.UNKNOWN
