"""EMC severity bar chart generator.

Horizontal stacked bars showing EMC findings by category and severity.
Requires matplotlib (available in venv).
"""

from __future__ import annotations

from typing import Optional

from figures.registry import register
from figures.lib.theme import FigureTheme


@register(name="emc_severity", output="emc_severity.svg",
          requires=("matplotlib",))
class EmcSeverityGenerator:
    """EMC findings severity distribution chart."""

    @staticmethod
    def prepare(analysis: dict, config: dict) -> dict | None:
        findings = analysis.get('findings', [])
        if not findings:
            return None

        categories: dict[str, dict[str, int]] = {}
        for f in findings:
            cat = f.get('category', 'other')
            sev = f.get('severity', 'INFO').upper()
            categories.setdefault(cat, {})
            categories[cat][sev] = categories[cat].get(sev, 0) + 1

        if not categories:
            return None

        sorted_cats = sorted(categories.keys(),
                             key=lambda c: sum(categories[c].values()),
                             reverse=True)

        return {
            'categories': [
                {
                    'name': cat,
                    'pretty_name': cat.replace('_', ' ').title(),
                    'counts': categories[cat],
                }
                for cat in sorted_cats
            ],
        }

    @staticmethod
    def render(data: dict, output_path: str,
               theme: Optional[FigureTheme] = None) -> str | None:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import matplotlib.ticker as ticker
        from .._mpl_common import apply_theme, save_figure, severity_colors, FIGSIZE

        theme = theme or FigureTheme()
        cats = data.get('categories', [])
        if not cats:
            return None

        sev_colors = severity_colors(theme)
        severity_order = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO']
        pretty_names = [c['pretty_name'] for c in cats]

        fig, ax = plt.subplots(figsize=FIGSIZE)
        y_pos = range(len(cats))
        left = [0] * len(cats)

        for sev in severity_order:
            counts = [c['counts'].get(sev, 0) for c in cats]
            if sum(counts) == 0:
                continue
            color = sev_colors.get(sev, '#78909c')
            ax.barh(y_pos, counts, left=left, label=sev.capitalize(),
                    color=color, alpha=0.85, height=0.6)
            left = [l + c for l, c in zip(left, counts)]

        ax.set_yticks(y_pos)
        ax.set_yticklabels(pretty_names, fontsize=10)
        ax.set_xlabel('Number of Findings', fontsize=11)
        ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
        ax.legend(fontsize=9, loc='lower right')
        ax.invert_yaxis()

        apply_theme(ax, theme, 'EMC Findings by Category')
        return save_figure(fig, output_path)
