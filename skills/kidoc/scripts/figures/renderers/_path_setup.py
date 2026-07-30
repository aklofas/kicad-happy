"""Cross-skill import setup for renderer modules.

Adds the kidoc ``scripts/`` directory and the kicad skill's
``scripts/`` directory to ``sys.path`` so that ``sexp_parser``
(and other kicad utilities) can be imported.

Usage (at module level in any renderer)::

    from figures.renderers._path_setup import setup_kicad_imports
    setup_kicad_imports()
"""

from __future__ import annotations

import os
import sys

_setup_done = False


def setup_kicad_imports() -> None:
    """Add kidoc scripts/ and kicad scripts/ to sys.path."""
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    # renderers/ -> figures/ -> scripts/
    scripts_dir = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    # scripts/ -> kidoc/ -> skills/ -> kicad/scripts/
    kicad_scripts = os.path.join(scripts_dir, '..', '..', 'kicad', 'scripts')
    kicad_scripts = os.path.abspath(kicad_scripts)
    if os.path.isdir(kicad_scripts) and kicad_scripts not in sys.path:
        sys.path.insert(0, kicad_scripts)
