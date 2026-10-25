"""Harness fixture root for tools tests: env KH_FIXTURES, no machine-local default.

Unset: fixture tests skip. Set: the root and every fixture a test asks for must
exist, otherwise the run fails (a wrong clone path must not skip the suite). A set
but missing root raises when this module is imported, so every test module that
uses it errors loudly.
"""
import os
import unittest
from pathlib import Path

_raw = os.environ.get("KH_FIXTURES")
FIXTURES = Path(_raw) if _raw else None
if FIXTURES is not None and not FIXTURES.is_dir():
    raise AssertionError(f"KH_FIXTURES={_raw!r} is not a directory")

_MISSING = Path("/nonexistent-kh-fixtures")


def fixture_path(*parts):
    """Path under the fixture root; a nonexistent path when the root is unset, so
    module-level constants never raise."""
    return (FIXTURES or _MISSING).joinpath(*parts)


def have(path):
    """skipUnless predicate: False only when KH_FIXTURES is unset; fails when it is
    set and `path` is missing."""
    if FIXTURES is None:
        return False
    if not Path(path).exists():
        raise AssertionError(f"fixture missing under KH_FIXTURES: {path}")
    return True


def fixture(*parts):
    """Existing path under the fixture root; skips when unset, fails when missing."""
    if FIXTURES is None:
        raise unittest.SkipTest("KH_FIXTURES not set (harness tests/fixtures)")
    p = fixture_path(*parts)
    if not p.exists():
        raise AssertionError(f"fixture missing under KH_FIXTURES: {p}")
    return p
