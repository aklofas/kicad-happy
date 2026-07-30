"""Monte Carlo tolerance histogram generator.

Shows distribution of tolerance analysis results with mean, nominal,
+-1 sigma band, and +-3 sigma markers.
Requires matplotlib (available in venv).
"""

from __future__ import annotations

from typing import Optional

from figures.registry import register
from figures.lib.theme import FigureTheme


@register(name="monte_carlo", output="monte_carlo.svg",
          requires=("matplotlib",))
class MonteCarloGenerator:
    """Monte Carlo tolerance analysis histogram."""

    @staticmethod
    def prepare(analysis: dict, config: dict) -> dict | None:
        results = analysis.get('simulation_results', [])
        if not results:
            return None

        for r in results:
            ta = r.get('tolerance_analysis', {})
            stats = ta.get('statistics', {})
            if not stats:
                continue
            for metric_name, s in stats.items():
                if all(k in s for k in ('mean', 'std', 'min', 'max', 'nominal')):
                    return {
                        'mean': s['mean'],
                        'std': s['std'],
                        'nominal': s['nominal'],
                        'spread_pct': s.get('spread_pct', 0),
                        'p3sigma_lo': s.get('p3sigma_lo', s['mean'] - 3 * s['std']),
                        'p3sigma_hi': s.get('p3sigma_hi', s['mean'] + 3 * s['std']),
                        'metric_name': metric_name,
                        'subcircuit_type': r.get('subcircuit_type', 'circuit'),
                        'values': s.get('_values'),
                    }
        return None

    @staticmethod
    def render(data: dict, output_path: str,
               theme: Optional[FigureTheme] = None) -> str | None:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from .._mpl_common import apply_theme, save_figure, FIGSIZE

        theme = theme or FigureTheme()

        mean = data['mean']
        std = data['std']
        nominal = data['nominal']
        spread_pct = data.get('spread_pct', 0)
        p3lo = data['p3sigma_lo']
        p3hi = data['p3sigma_hi']
        metric_name = data['metric_name']
        subcircuit_type = data['subcircuit_type']

        mc_values = data.get('values')
        if not mc_values:
            import numpy as np
            rng = np.random.default_rng(42)
            mc_values = rng.normal(mean, std, 1000).tolist()

        fig, ax = plt.subplots(figsize=FIGSIZE)

        n_bins = min(40, max(15, len(mc_values) // 10))
        ax.hist(mc_values, bins=n_bins, color=theme.highlight, alpha=0.6,
                edgecolor='white', linewidth=0.5, density=True)

        ax.axvline(mean, color=theme.primary, linewidth=1.5, linestyle='-',
                   label=f'Mean: {mean:.4g}')
        if abs(nominal - mean) / max(abs(nominal), 1e-12) > 0.001:
            ax.axvline(nominal, color='#43a047', linewidth=1.2, linestyle='--',
                       label=f'Nominal: {nominal:.4g}')

        ax.axvspan(mean - std, mean + std, alpha=0.12, color=theme.highlight,
                   label=f'\u00b11\u03c3: {std:.4g}')
        ax.axvline(p3lo, color='#c62828', linewidth=1, linestyle=':',
                   label='\u00b13\u03c3 bounds')
        ax.axvline(p3hi, color='#c62828', linewidth=1, linestyle=':')

        pretty_metric = (metric_name.replace('_', ' ')
                         .replace('hz', 'Hz').replace('db', 'dB'))
        pretty_type = subcircuit_type.replace('_', ' ').title()

        ax.set_xlabel(pretty_metric.title(), fontsize=11)
        ax.set_ylabel('Density', fontsize=11)
        ax.legend(fontsize=9, loc='upper right')

        title = f'Monte Carlo: {pretty_type} \u2014 {pretty_metric.title()}'
        if spread_pct:
            title += f' (spread {spread_pct:.1f}%)'
        apply_theme(ax, theme, title)
        return save_figure(fig, output_path)
