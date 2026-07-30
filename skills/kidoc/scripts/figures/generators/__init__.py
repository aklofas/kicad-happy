"""Auto-discover figure generator sub-packages.

Each subdirectory under ``generators/`` is expected to contain an
``__init__.py`` that uses ``@register`` to register a generator class.
Importing this module triggers discovery of all generators.

Directories starting with ``_`` are skipped (reserved for shared
utilities like ``_mpl_common.py``).
"""

from __future__ import annotations

import importlib
import os
import pkgutil


def discover() -> None:
    """Import all generator sub-packages to trigger @register calls."""
    package_dir = os.path.dirname(os.path.abspath(__file__))
    for importer, modname, ispkg in pkgutil.iter_modules([package_dir]):
        if ispkg and not modname.startswith('_'):
            importlib.import_module(f'.{modname}', __package__)


# Auto-discover on import.
discover()
