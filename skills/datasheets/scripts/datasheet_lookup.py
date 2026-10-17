"""Facade: the extraction-cache reader lives in datasheet_types.cache_reader.

Kept for scripts-dir importers (`from datasheet_lookup import lookup`) and
the harness tests that bind these names; retires in v3 round 9.
"""
import sys
from pathlib import Path

# datasheet_types is a sibling package under skills/datasheets/; add the
# parent dir once so a plain `import datasheet_lookup` from scripts/ works.
_TYPES_PARENT = str(Path(__file__).resolve().parent.parent)
if _TYPES_PARENT not in sys.path:
    sys.path.insert(0, _TYPES_PARENT)

from datasheet_types.cache_reader import (  # noqa: E402,F401
    _UNSAFE_CHAR,
    STALE_PDF_HASH_MISMATCH,
    STALE_PDF_MISSING,
    CacheContext,
    _compute_pdf_sha256,
    _resolve_pdf_path,
    cache_path_for,
    lookup,
    sanitize_mpn,
)
