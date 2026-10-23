"""Shared argparse flag declarations for the analyzer and consumer CLIs (kicad_core). Stdlib only.

Each helper declares exactly what the CLIs declared inline, so help text, defaults and
argument order are unchanged when a CLI calls the helper at the position of the old line.
"""

STAGES = ['schematic', 'layout', 'pre_fab', 'bring_up']
AUDIENCES = ['designer', 'reviewer', 'manager']

_ONLY_DETERMINISTIC_ANALYZER_HELP = (
    'Accepted for consistency; analyzers never write llm_* fields. '
    'Honored by downstream consumers (Phase 4 spec §3.4).')
_ONLY_DETERMINISTIC_CONSUMER_HELP = (
    "Read raw analysis/<run>/<analyzer>.json instead of "
    "analysis/merged/<run>/<analyzer>.json. "
    "Strips Layer 2 overlays for CI/offline use (Phase 4 spec §3.4).")


def add_stage_audience_args(parser) -> None:
    parser.add_argument('--stage', default=None, choices=list(STAGES),
                        help='Filter findings by review stage')
    parser.add_argument('--audience', default=None, choices=list(AUDIENCES),
                        help='Audience level for summaries and --text output')


def add_only_deterministic_arg(parser, *, consumer: bool = False) -> None:
    parser.add_argument('--only-deterministic', action='store_true',
                        help=(_ONLY_DETERMINISTIC_CONSUMER_HELP if consumer
                              else _ONLY_DETERMINISTIC_ANALYZER_HELP))


def add_schema_arg(parser, help: str = "Print JSON output schema and exit") -> None:
    parser.add_argument("--schema", action="store_true", help=help)


def add_output_arg(parser, help: str = "Output JSON file (default: stdout)") -> None:
    parser.add_argument("--output", "-o", help=help)


def add_compact_arg(parser, help: str = "Compact JSON output") -> None:
    parser.add_argument("--compact", action="store_true", help=help)


def add_text_arg(parser, help: str) -> None:
    parser.add_argument("--text", action="store_true", help=help)


def add_config_arg(parser) -> None:
    parser.add_argument("--config", default=None,
                        help="Path to .kicad-happy.json project config file")
