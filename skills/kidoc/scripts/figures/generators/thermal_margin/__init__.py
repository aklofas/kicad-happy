"""Thermal margin bar chart generator.

Shows junction temperature estimates stacked with margin to Tj_max.
Margin color-coded: green (>20C), yellow (10-20C), red (<10C).
Only includes components with Tj > 40C.

Requires matplotlib (available in venv).
"""

from __future__ import annotations

from collections import Counter
from typing import Optional

from figures.registry import register
from figures.lib.theme import FigureTheme


@register(name="thermal_margin", output="thermal_margin.svg",
          requires=("matplotlib",))
class ThermalMarginGenerator:
    """Thermal margin analysis bar chart."""

    @staticmethod
    def prepare(analysis: dict, config: dict) -> dict | None:
        assessments = analysis.get('thermal_assessments', [])
        if not assessments:
            return None

        hot = [a for a in assessments if a.get('tj_estimated_c', 0) > 40]
        if not hot:
            return None

        hot.sort(key=lambda a: a.get('tj_estimated_c', 0), reverse=True)

        tj_max_vals = [a.get('tj_max_c', 125) for a in hot]
        tj_max_common = Counter(tj_max_vals).most_common(1)[0][0]

        return {
            'components': [
                {
                    'ref': a.get('ref', '?'),
                    'tj_estimated_c': a.get('tj_estimated_c', 0),
                    'margin_c': a.get('margin_c', 0),
                    'tj_max_c': a.get('tj_max_c', 125),
                }
                for a in hot
            ],
            'tj_max_common': tj_max_common,
        }

    @staticmethod
    def render(data: dict, output_path: str,
               theme: Optional[FigureTheme] = None) -> str | None:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from .._mpl_common import apply_theme, save_figure, FIGSIZE

        theme = theme or FigureTheme()
        components = data.get('components', [])
        if not components:
            return None

        refs = [c['ref'] for c in components]
        tj_est = [c['tj_estimated_c'] for c in components]
        margins = [c['margin_c'] for c in components]
        tj_max_common = data.get('tj_max_common', 125)

        margin_colors = []
        for m in margins:
            if m < 10:
                margin_colors.append('#c62828')
            elif m < 20:
                margin_colors.append('#f9a825')
            else:
                margin_colors.append('#43a047')

        fig, ax = plt.subplots(figsize=FIGSIZE)
        x = range(len(refs))

        bars_tj = ax.bar(x, tj_est, label='Tj estimated',
                         color=theme.highlight, alpha=0.85)
        bars_margin = ax.bar(x, margins, bottom=tj_est,
                             label='Margin to Tj_max',
                             color=margin_colors, alpha=0.7)

        ax.axhline(y=tj_max_common, color='#c62828', linestyle='--',
                   linewidth=1.2, label=f'Tj_max ({tj_max_common}\u00b0C)')

        for bar, tj in zip(bars_tj, tj_est):
            ax.text(bar.get_x() + bar.get_width() / 2, tj / 2,
                    f'{tj:.0f}\u00b0C', ha='center', va='center',
                    fontsize=8, color='white', fontweight='bold')
        for bar, m, base in zip(bars_margin, margins, tj_est):
            if m > 5:
                ax.text(bar.get_x() + bar.get_width() / 2, base + m / 2,
                        f'+{m:.0f}\u00b0C', ha='center', va='center',
                        fontsize=8, color=theme.primary)

        ax.set_xticks(x)
        ax.set_xticklabels(refs, fontsize=10)
        ax.set_ylabel('Temperature (\u00b0C)', fontsize=11)
        ax.set_xlabel('Component', fontsize=11)
        ax.legend(fontsize=9, loc='upper right')

        apply_theme(ax, theme, 'Thermal Margin Analysis')
        return save_figure(fig, output_path)
