"""Figure generation framework for engineering documentation.

Generators live in ``generators/`` subdirectories and self-register
via ``@register``.  The ``run_all()`` pipeline handles:
prepare → hash-check → render with per-figure JSON caching.

Usage::

    from figures import run_all, FigureTheme

    outputs = run_all(analysis, config, output_dir, theme=theme)
"""

from __future__ import annotations

from .lib.theme import FigureTheme
from .runner import run_all

# Auto-discover all generators (triggers @register decorators).
from . import generators  # noqa: F401

__all__ = [
    'FigureTheme',
    'run_all',
]
