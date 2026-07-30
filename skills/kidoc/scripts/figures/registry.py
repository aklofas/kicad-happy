"""Figure generator registry.

Generators self-register via the ``@register`` class decorator.  Each
generator class provides:

- ``prepare(analysis, config) -> dict | list[tuple] | None``
- ``render(data, output_path, theme) -> str | None``

Auto-discovery in ``generators/__init__.py`` scans subdirectories via
``pkgutil``, so new generators are plug-and-play.

Zero external dependencies — Python 3.8+ stdlib only.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any, Callable, List, Sequence, Tuple, Type

_REGISTRY: List['GeneratorEntry'] = []


@dataclass
class GeneratorEntry:
    """Metadata for a registered figure generator."""

    name: str
    """Short identifier, e.g. ``"power_tree"``."""

    generator_cls: Type
    """Generator class with ``prepare()`` and ``render()`` static methods."""

    output: str
    """Default output filename (e.g. ``"power_tree.svg"``)."""

    requires: Tuple[str, ...] = ()
    """Python module names required at runtime, e.g. ``("matplotlib",)``.
    Generator is skipped if any is not importable."""

    multi_output: bool = False
    """True for generators producing N files (e.g. pinouts).
    ``prepare()`` returns ``list[tuple[str, dict]]``."""


def register(name: str, output: str,
             requires: Sequence[str] = (),
             multi_output: bool = False) -> Callable:
    """Class decorator to register a figure generator.

    Usage::

        @register("power_tree", "power_tree.svg")
        class PowerTreeGenerator:
            @staticmethod
            def prepare(analysis, config): ...
            @staticmethod
            def render(data, output_path, theme=None): ...
    """
    def decorator(cls: Type) -> Type:
        _REGISTRY.append(GeneratorEntry(
            name=name,
            generator_cls=cls,
            output=output,
            requires=tuple(requires),
            multi_output=multi_output,
        ))
        return cls
    return decorator


def get_registry() -> List[GeneratorEntry]:
    """Return all registered generators (import order)."""
    return list(_REGISTRY)


def check_requires(entry: GeneratorEntry) -> bool:
    """Check if a generator's runtime dependencies are available."""
    for mod_name in entry.requires:
        if importlib.util.find_spec(mod_name) is None:
            return False
    return True
