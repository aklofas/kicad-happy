"""SPICE validation scatter plot generator.

Plots expected vs simulated values from SPICE results, colored by
subcircuit type, with tolerance band and perfect-match diagonal.
Requires matplotlib (available in venv).
"""

from __future__ import annotations

from typing import Optional

from figures.registry import register
from figures.lib.theme import FigureTheme


@register(name="spice_validation", output="spice_validation.svg",
          requires=("matplotlib",))
class SpiceValidationGenerator:
    """Expected vs simulated SPICE scatter plot."""

    @staticmethod
    def prepare(analysis: dict, config: dict) -> dict | None:
        results = analysis.get('simulation_results', [])
        if not results:
            return None

        points = []
        for r in results:
            expected = r.get('expected', {})
            simulated = r.get('simulated', {})
            stype = r.get('subcircuit_type', 'unknown')

            for metric in ('cutoff_hz', 'ratio', 'gain_db'):
                exp_val = expected.get(metric)
                sim_val = simulated.get(metric)
                if exp_val is not None and sim_val is not None:
                    label = ', '.join(r.get('components', [])[:2])
                    points.append({
                        'expected': exp_val,
                        'simulated': sim_val,
                        'type': stype,
                        'label': label,
                        'metric': metric,
                    })
                    break

        if not points:
            return None
        return {'points': points}

    @staticmethod
    def render(data: dict, output_path: str,
               theme: Optional[FigureTheme] = None) -> str | None:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from .._mpl_common import (apply_theme, save_figure,
                                    subcircuit_colors, FIGSIZE)

        theme = theme or FigureTheme()
        points = data.get('points', [])
        if not points:
            return None

        sc_colors = subcircuit_colors(theme)
        fig, ax = plt.subplots(figsize=FIGSIZE)

        all_vals = [p['expected'] for p in points] + [p['simulated'] for p in points]
        vmin = min(all_vals) * 0.8
        vmax = max(all_vals) * 1.2
        if vmin <= 0:
            pos = [v for v in all_vals if v > 0]
            vmin = min(pos) * 0.5 if pos else 0.1

        diag = [vmin, vmax]
        ax.plot(diag, diag, '--', color='#888888', linewidth=1,
                label='Perfect match')
        ax.fill_between(diag, [d * 0.9 for d in diag], [d * 1.1 for d in diag],
                        alpha=0.1, color=theme.highlight,
                        label='\u00b110% tolerance')

        by_type: dict[str, list] = {}
        for p in points:
            by_type.setdefault(p['type'], []).append(p)

        for stype, pts in by_type.items():
            color = sc_colors.get(stype, '#546e7a')
            xs = [p['expected'] for p in pts]
            ys = [p['simulated'] for p in pts]
            ax.scatter(xs, ys, c=color, s=60, alpha=0.85,
                       edgecolors='white', linewidths=0.5,
                       label=stype.replace('_', ' ').title(), zorder=5)
            for p in pts:
                if p['label']:
                    ax.annotate(p['label'],
                                (p['expected'], p['simulated']),
                                textcoords='offset points', xytext=(6, 6),
                                fontsize=7, color=theme.primary, alpha=0.8)

        if vmax / max(vmin, 1e-12) > 100:
            ax.set_xscale('log')
            ax.set_yscale('log')

        ax.set_xlabel('Expected Value', fontsize=11)
        ax.set_ylabel('Simulated Value', fontsize=11)
        ax.legend(fontsize=9, loc='upper left')

        apply_theme(ax, theme, 'SPICE Simulation Validation')
        return save_figure(fig, output_path)
