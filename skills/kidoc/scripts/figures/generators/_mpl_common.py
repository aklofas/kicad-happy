"""Shared matplotlib helpers for chart generators.

Provides theme-aware styling, save helper, and color mappings.
All functions import matplotlib lazily so the module can be imported
for documentation even when matplotlib is not installed.
"""

from __future__ import annotations

import os
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from figures.lib.theme import FigureTheme

FIGSIZE = (8, 5)


def apply_theme(ax, theme: 'FigureTheme', title: str) -> None:
    """Apply FigureTheme colors to a matplotlib axes."""
    ax.set_title(title, fontsize=14, fontweight='bold',
                 color=theme.primary, pad=12)
    ax.set_facecolor(theme.bg_color)
    ax.figure.set_facecolor(theme.bg_color)
    ax.grid(True, linestyle='--', linewidth=0.5,
            color='#d0d0d0', alpha=0.7)
    ax.tick_params(labelsize=10)
    for spine in ax.spines.values():
        spine.set_color('#cccccc')
    ax.set_axisbelow(True)


def save_figure(fig, path: str) -> str:
    """Save figure as SVG and close.  Returns the output path."""
    import matplotlib.pyplot as plt
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fig.savefig(path, format='svg', bbox_inches='tight')
    plt.close(fig)
    return path


def severity_colors(theme: 'FigureTheme') -> dict:
    """EMC severity color map derived from theme."""
    return {
        'CRITICAL': '#c62828',
        'HIGH': '#ef6c00',
        'MEDIUM': '#f9a825',
        'LOW': theme.highlight,
        'INFO': '#78909c',
    }


def subcircuit_colors(theme: 'FigureTheme') -> dict:
    """SPICE subcircuit type color map."""
    return {
        'rc_filter': theme.highlight,
        'rl_filter': theme.highlight,
        'lc_filter': theme.highlight,
        'voltage_divider': '#43a047',
        'opamp': '#7b1fa2',
    }
