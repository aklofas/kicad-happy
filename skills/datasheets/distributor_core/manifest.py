"""Datasheet manifest IO and filename primitives: manifest.json (index.json legacy read,
atomic replace, legacy sibling removed after a successful write), sanitize/friendly filenames."""

import json
import os
import re
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Filename sanitization
# ---------------------------------------------------------------------------

def sanitize_filename(name: str) -> str:
    """Convert a string to a safe filename component (without extension)."""
    # Replace filesystem-unsafe characters and commas
    name = re.sub(r'[/\\:*?"<>|,;]', "_", name)
    # Collapse whitespace and underscores
    name = re.sub(r"\s+", "_", name)
    name = re.sub(r"_+", "_", name).strip("_")
    # Truncate
    if len(name) > 200:
        name = name[:200]
    return name


def friendly_filename(mpn: str, description: str = "", manufacturer: str = "") -> str:
    """Build a human-readable filename from MPN and description.

    Examples:
        TPS61023DRLR_Boost_Converter.pdf
        BSS138LT1G_MOSFET_N-CH_50V_200mA.pdf
        GRPB032VWQS-RC_Conn_Header_SMD_6pos.pdf

    Falls back to just the sanitized MPN if no description is available.
    """
    base = sanitize_filename(mpn)
    if not description:
        return base

    # Clean up the description: trim common noise
    desc = description.strip()
    # Remove trailing manufacturer name if it's just repeated
    if manufacturer and desc.lower().endswith(manufacturer.lower()):
        desc = desc[: -len(manufacturer)].strip().rstrip(",").strip()
    # Truncate long descriptions to keep filenames reasonable
    if len(desc) > 80:
        desc = desc[:77].rsplit("_", 1)[0].rsplit(" ", 1)[0]
    desc = sanitize_filename(desc)
    if not desc:
        return base

    return f"{base}_{desc}"


# ---------------------------------------------------------------------------
# Manifest management (manifest.json; legacy index.json read for backward compat)
# ---------------------------------------------------------------------------

def _read_umask() -> int:
    mask = os.umask(0)
    os.umask(mask)
    return mask


# Read once at import: reading it later would briefly change the umask of every thread.
DEFAULT_FILE_MODE = 0o666 & ~_read_umask()

MANIFEST_FILENAME = "manifest.json"


LEGACY_MANIFEST_FILENAME = "index.json"


def _manifest_path(out_dir: Path) -> Path:
    """Return manifest path, preferring manifest.json but falling back to index.json."""
    new = out_dir / MANIFEST_FILENAME
    old = out_dir / LEGACY_MANIFEST_FILENAME
    if new.exists() or not old.exists():
        return new
    return old


def load_index(path: Path) -> dict:
    """Load existing manifest.json (or legacy index.json) or return empty."""
    path = _manifest_path(path.parent) if path.name in (MANIFEST_FILENAME, LEGACY_MANIFEST_FILENAME) else path
    if path.exists():
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"schematic": "", "last_sync": "", "parts": {}}


def save_index(path: Path, index: dict):
    """Write manifest atomically. Always writes manifest.json; removes any
    legacy index.json sibling after a successful write."""
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    new_path = parent / MANIFEST_FILENAME
    fd, tmp = tempfile.mkstemp(dir=str(parent), prefix="manifest.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)
        os.chmod(tmp, DEFAULT_FILE_MODE)
        os.replace(tmp, new_path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    old_path = parent / LEGACY_MANIFEST_FILENAME
    if old_path.exists() and old_path != new_path:
        try:
            old_path.unlink()
        except OSError:
            pass


def manifest_file_path(out_dir: Path, name: object) -> Path | None:
    """``out_dir / name`` for a manifest ``file`` value that is a plain leaf name and not a
    symlink; None for anything that could point outside ``out_dir``."""
    if not isinstance(name, str) or not name or name in (".", ".."):
        return None
    if name != os.path.basename(name) or "/" in name or "\\" in name:
        return None
    path = out_dir / name
    return None if path.is_symlink() else path


def _friendly_filename(mpn: str, description: str = "") -> str:
    """Build a human-readable filename (no extension) from MPN + description."""
    def _sanitize(s):
        s = re.sub(r'[/\\:*?"<>|,;]', "_", s)
        s = re.sub(r"\s+", "_", s)
        return re.sub(r"_+", "_", s).strip("_")

    base = _sanitize(mpn)
    if not description:
        return base
    desc = description.strip()
    if len(desc) > 80:
        desc = desc[:77].rsplit(" ", 1)[0]
    desc = _sanitize(desc)
    return f"{base}_{desc}" if desc else base
