# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in kicad-happy, please report it privately via [GitHub Security Advisories](https://github.com/aklofas/kicad-happy/security/advisories/new).

Do not open a public issue for security vulnerabilities.

## Scope

The analysis scripts (`analyze_schematic.py`, `analyze_pcb.py`, `analyze_gerbers.py`) parse untrusted KiCad files. Bugs that could cause code execution, path traversal, or information disclosure when parsing a malicious file are in scope.

The scripts are read-only by design — they never modify input files. The BOM management scripts write KiCad symbol properties when run; `--dry-run` previews the change without writing.
