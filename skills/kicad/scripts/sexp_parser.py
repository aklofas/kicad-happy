"""Facade (v3 round 3): the S-expression parser lives in kicad_core/sexp.py.

Kept for external importers (harness ``validate/verify_parser.py``, user scripts);
retires in round 9. Product code imports ``kicad_core.sexp`` directly.
"""
import sys
from pathlib import Path

# standalone load by file path (harness spec_from_file_location, docs)
if str(Path(__file__).parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent))
from kicad_core.sexp import (  # noqa: F401
    _BRACE_ESCAPES, _BRACE_RE, _find_deep_acc, _parse_tokens, _tokenize, _unescape_braces,
    find_all, find_deep, find_first, get_at, get_properties, get_property, get_value, get_xy,
    has_flag, parse, parse_file,
)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python sexp_parser.py <file.kicad_sch|.kicad_pcb>")
        sys.exit(1)
    tree = parse_file(sys.argv[1])
    print(f"Parsed {sys.argv[1]}: root node = {tree[0] if isinstance(tree, list) else tree}")
    print(f"Top-level children: {len(tree) - 1}")
