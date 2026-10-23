"""Text-rendering primitives shared by the analyzer text reports (kicad_core): the severity
normaliser, the text-report severity bucket, and small formatting fragments. Stdlib only."""


SEVERITY_ALIASES = {
    # Legacy uppercase pre-v1.3 taxonomy
    "CRITICAL": "error",
    "HIGH": "error",
    "MEDIUM": "warning",
    "LOW": "info",
    "INFO": "info",
    # Lowercase legacy variants
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "info",
    # v1.4 normalized vocab (pass-through)
    "error": "error",
    "warning": "warning",
    "info": "info",
}


def normalize_severity(sev):
    """Map any severity string to the v1.4 normalized vocabulary.

    Accepts legacy uppercase (CRITICAL/HIGH/MEDIUM/LOW/INFO) and v1.4
    lowercase (error/warning/info). Returns one of {"error", "warning",
    "info"}. Returns "info" for None, non-string, or unknown input.

    Use this anywhere a consumer reads `finding["severity"]` — analyzer
    outputs may carry either taxonomy depending on the producer code
    path (EMC + voltage_derating still emit legacy uppercase via
    _normalize_severity, schematic+pcb+thermal emit v1.4 lowercase).
    """
    if not isinstance(sev, str):
        return "info"
    return SEVERITY_ALIASES.get(
        sev, SEVERITY_ALIASES.get(sev.upper(), "info"))


def severity_bucket(severity: str) -> str:
    """Text-report bucket. Differs from `normalize_severity` on `WARN` (→ warning here) and accepts `ERROR`; kept as a named adapter (U5)."""
    s = (severity or '').upper()
    if s in ('CRITICAL', 'HIGH', 'ERROR'):
        return 'error'
    if s in ('MEDIUM', 'WARNING', 'WARN'):
        return 'warning'
    return 'info'


def plural(n: int, noun: str) -> str:
    return f'{n} {noun}{"s" if n != 1 else ""}'


def finding_line(idx, severity, rule_id, summary) -> str:
    return f'  [{idx}] {severity} {rule_id}: {summary}'


def wrap_lines(text: str, width: int = 70, first: str = "    ", cont: str = "      ") -> list[str]:
    return [(first if i == 0 else cont) + text[i:i + width] for i in range(0, len(text), width)]


def fmt_signed(value, digits: int = 1) -> str:
    return f"{value:+.{digits}f}"


def fmt_g4(value) -> str:
    return f"{value:.4g}"
