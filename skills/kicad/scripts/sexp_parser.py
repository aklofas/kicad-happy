"""Facade (v3 round 3): the S-expression parser lives in kicad_core/sexp.py.

Kept for external importers (harness ``validate/verify_parser.py``, user scripts);
retires in round 9. Product code imports ``kicad_core.sexp`` directly.
"""
from kicad_core.sexp import (  # noqa: F401
    _BRACE_ESCAPES, _BRACE_RE, _find_deep_acc, _parse_tokens, _tokenize, _unescape_braces,
    find_all, find_deep, find_first, get_at, get_properties, get_property, get_value, get_xy,
    has_flag, parse, parse_file,
)
