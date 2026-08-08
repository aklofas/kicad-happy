# Contributing to kicad-happy

Thanks for your interest in contributing. This guide covers the project structure, how to write and test changes, and how to validate them against the test harness.

## Project structure

```
skills/
├── kicad/           # Core analysis skill (schematic, PCB, Gerber, thermal, diff, what-if)
│   ├── SKILL.md     # Skill definition with triggers and usage docs
│   ├── scripts/     # Python analysis scripts (zero-dep, Python 3.10+)
│   └── references/  # Deep methodology guides (18 files)
├── datasheets/      # Structured extraction pipeline — per-MPN cache, quality scoring, consumer API
├── emc/             # EMC pre-compliance (44 rules, 18 categories)
├── spice/           # SPICE simulation (ngspice/LTspice/Xyce)
├── bom/             # BOM management
├── digikey/         # DigiKey API integration
├── mouser/          # Mouser API integration
├── lcsc/            # LCSC/JLCPCB parts (no auth)
├── element14/       # element14/Newark/Farnell API
├── jlcpcb/          # JLCPCB fab rules and BOM/CPL format
└── pcbway/          # PCBWay fab rules
```

Each skill has a `SKILL.md` with YAML frontmatter (name, description, triggers) and reference documentation. The analysis engine is entirely in Python — the SKILL.md files are instructions for AI agents that use the scripts.

### Key files

| File | LOC | Purpose |
|------|-----|---------|
| `kicad/scripts/analyze_schematic.py` | ~9,500 | S-expression parser + schematic analysis orchestrator |
| `kicad/scripts/signal_detectors.py` | ~4,400 | Core signal path detectors (regulators, filters, opamps, dividers, crystals, protection) |
| `kicad/scripts/domain_detectors.py` | ~6,100 | Domain-specific detectors (Ethernet, USB-C, BMS, motor drive, sensors, audio, LEDs, etc.) |
| `kicad/scripts/validation_detectors.py` | ~1,300 | Validation detectors (pull-ups, voltage mismatch, protocol buses, power sequencing, feedback stability) |
| `kicad/scripts/lookup_detectors.py` | ~700 | v1.4 datasheet-backed detectors (AM-001, OV-001, FT-001, PM-001, EX-001 via Phase 2 lookup API) |
| `kicad/scripts/analyze_pcb.py` | ~6,700 | PCB layout analysis (footprints, tracks, vias, zones, DFM, assembly checks, connectivity graph) |
| `kicad/scripts/analyze_gerbers.py` | ~1,700 | Gerber/Excellon verification |
| `kicad/scripts/cross_analysis.py` | ~1,100 | Schematic + PCB cross-domain checks |
| `kicad/scripts/finding_schema.py` | ~680 | Rich finding factory, `Det` constants, consumer helpers, trust_summary aggregation |
| `kicad/scripts/output_filters.py` | ~470 | Stage/audience filtering for all analyzers |
| `kicad/scripts/kicad_utils.py` | ~2,000 | Shared utilities (component classification, value parsing, net detection, switching frequencies) |
| `kicad/scripts/kicad_types.py` | ~120 | `AnalysisContext` dataclass — shared state for all detectors |
| `kicad/scripts/sexp_parser.py` | ~230 | S-expression parser shared by schematic and PCB analyzers |
| `kicad/scripts/analyzer_envelope.py` | ~300 | Typed envelope dataclasses (Finding, Assessment, TrustSummary, InputsBlock, CompatBlock) — single source of truth for analyzer output shape |
| `emc/scripts/emc_rules.py` | ~4,250 | 44 EMC rule implementations |
| `emc/scripts/emc_formulas.py` | ~1,400 | Radiation formulas, harmonic analysis, PDN impedance |
| `emc/scripts/emc_spice.py` | ~710 | SPICE-enhanced PDN, filter insertion loss, harmonic FFT |
| `datasheets/scripts/datasheet_extract_cache.py` | ~540 | Per-MPN extraction cache manager |
| `datasheets/scripts/datasheet_features.py` | ~380 | Consumer API for analyzers (get_regulator_features, get_mcu_features, etc.) — v1.4 dual-cache-read path |
| `datasheets/scripts/datasheet_lookup.py` | ~240 | v1.4 typed `lookup(mpn) → DatasheetFacts` facade with staleness detection |
| `datasheets/datasheet_types/` | — | v1.4 typed access layer (DatasheetFacts, SpecValue, Pin, Pinout, trust_gating helpers) |
| `kicad/review/scripts/merge_annotations.py` | — | Review overlay merge: validates + applies review annotations to `analysis/merged/<analyzer>.json` |

### Zero-dependency policy

All analysis scripts use Python 3.10+ standard library only. No pip install, no Docker, no KiCad installation needed. This is a hard requirement — it means the scripts run anywhere with a Python interpreter.

Optional dependencies (`requests`, `playwright`, `pdftotext`) are only used for datasheet downloading and web-scraping / PDF-text-extraction fallbacks. They are never imported by the core analysis path.

## How signal detectors work

The analysis pipeline runs in three phases:

1. **Parse** — `analyze_schematic.py` reads the KiCad S-expression file, extracts components, nets, and pins, and builds an `AnalysisContext` object.

2. **Detect** — `analyze_signal_paths()` calls each detector function in order. Each detector receives the `AnalysisContext` (and sometimes prior detector results for cross-referencing) and returns a list of findings.

3. **Report** — Results are assembled into JSON output or consumed by the agent to write a design review.

### AnalysisContext

Every detector receives an `AnalysisContext` (`kicad_types.py`) — a dataclass containing:

- `components` — list of all parsed components
- `nets` — dict of net name to net info (pins, labels)
- `comp_lookup` — dict of reference to component (O(1) lookup)
- `parsed_values` — dict of reference to parsed numeric value
- `known_power_rails` — set of net names connected to power symbols
- `ref_pins` — reverse index: reference to {pin_num: (net_name, net_id)}
- `pin_net` — forward index: (reference, pin_num) to (net_name, net_id)
- `nq` — optional `NetlistQueries` object for multi-hop net tracing
- Helper methods: `is_power_net()`, `is_ground()`, `get_two_pin_nets()`

### Writing a new detector

Detectors live in one of two files:

- `signal_detectors.py` — core circuit analysis (regulators, filters, dividers, opamps, transistors, crystals, protection, current sense, decoupling)
- `domain_detectors.py` — domain-specific / application-level detectors (interfaces, peripherals, power path, sensors, audio, LEDs)

A detector function follows this pattern, emitting findings via the `make_finding()` factory in `finding_schema.py`:

```python
from finding_schema import make_finding, Det

def detect_my_circuit(ctx: AnalysisContext, prior_results=None) -> list[dict]:
    """Detect [circuit type] and validate [what]."""
    findings = []
    for comp in ctx.components:
        # 1. Identify candidate components by type, lib_id, value, or reference prefix
        if not _is_candidate(comp):
            continue
        # 2. Trace connected nets to find related components
        neighbors = _get_net_components(ctx, net_name, comp["reference"])
        # 3. Compute derived values (voltage, frequency, current, etc.)
        # 4. Check against rules/thresholds
        # 5. Emit a rich finding (factory enforces severity / confidence / evidence_source enums)
        findings.append(make_finding(
            detector=Det.MY_CIRCUIT,
            rule_id="MC-001",
            category="signal",
            severity="warning",          # error | warning | info
            confidence="deterministic",  # deterministic | heuristic | datasheet-backed
            evidence_source="topology",  # see finding_schema for the full enum
            summary=f"{comp['reference']}: ...",
            recommendation="...",
            components=[comp["reference"]],
            report_context={"value": parsed_value, ...},
        ))
    return findings
```

Then register the new `Det` constant in `finding_schema.py` and call the detector from `analyze_schematic.py`'s `analyze_signal_paths()`, where the detector call order is defined.

### Adding an EMC rule

EMC rules live in `emc/scripts/emc_rules.py`. Each rule:

1. Has an ID (e.g., `DC-006`) following the category prefix convention
2. Receives schematic JSON, PCB JSON, and config
3. Returns findings built via `_make_finding()` with `severity` (`error`, `warning`, `info`), `confidence` (`deterministic`, `heuristic`, `datasheet-backed`), and an `evidence_source` tag
4. Should include an equation tag comment (e.g., `# EQ-097: ...`) inside the function body above the math expression, with a `# Source:` citation line

All formulas should reference a primary source (textbook, app note, standard) in the equation tag.

## How to add a new skill

1. Create `skills/<name>/SKILL.md` with YAML frontmatter:

```yaml
---
name: my-skill
description: One paragraph describing what this skill does and when to use it. Include trigger phrases.
---
```

2. Add any scripts to `skills/<name>/scripts/`
3. Add a symlink in `.agents/skills/`: `ln -s ../../skills/<name> .agents/skills/<name>`
    *   **Antigravity CLI / Gemini:** Run `agy plugin install .` to install/update the local plugin.
    *   **opencode:** No per-skill registration needed — `.opencode/opencode.json` points the loader at the whole `skills/` tree, so new skills under `skills/<name>/SKILL.md` are auto-discovered.
4. Update the manual install lists in `README.md` (Claude Code, Codex, Antigravity/Gemini, and opencode sections)
5. Validate:
    *   **Claude Code:** `claude plugin validate .`
    *   **Antigravity CLI:** Run `agy plugin validate .` to verify plugin structure and skills.
    *   **opencode:** Run `/skills list` in an active session to verify the new skill appears.
    *   **All skills:** `python3 .github/scripts/check_skill_metadata.py` (description ≤ 1024 chars; CI runs this on every PR).

Keep SKILL.md language agent-neutral — use "the agent" instead of "Claude", "use web search" instead of "WebSearch", etc.

### SKILL.md description length cap

Every skill's frontmatter `description:` must stay under **1024 characters** — the strictest cap shipped by any supported platform (Codex). Skills over this are rejected on load by Codex and silently truncated elsewhere. CI gates on this via `.github/scripts/check_skill_metadata.py`. To run it locally before committing:

```bash
python3 .github/scripts/check_skill_metadata.py
```

Reports current length + buffer for every skill, warns when buffer drops below 50 chars, fails when any skill is over the cap. To enable as a git pre-commit hook so it runs automatically on `git commit`:

```bash
ln -sf ../../.github/scripts/check_skill_metadata.py .git/hooks/pre-commit
```

The `bom` and `kicad` skills' descriptions are currently the closest to the cap (their trigger-phrase lists are the longest); be conservative when adding phrases there.

## Running the analysis scripts

```bash
# Schematic analysis
python3 skills/kicad/scripts/analyze_schematic.py <file>.kicad_sch
python3 skills/kicad/scripts/analyze_schematic.py <file>.kicad_sch --output analysis.json

# PCB layout analysis
python3 skills/kicad/scripts/analyze_pcb.py <file>.kicad_pcb
python3 skills/kicad/scripts/analyze_pcb.py <file>.kicad_pcb --full --output pcb.json

# Gerber verification
python3 skills/kicad/scripts/analyze_gerbers.py <gerber_dir>/

# EMC pre-compliance (requires schematic + PCB JSON)
python3 skills/emc/scripts/analyze_emc.py --schematic sch.json --pcb pcb.json

# Thermal analysis
python3 skills/kicad/scripts/analyze_thermal.py --schematic sch.json --pcb pcb.json
```

All scripts exit 0 on success. The schematic and PCB analyzers produce JSON to stdout (or to a file with `--output`). EMC and thermal produce a structured risk report.

## Test harness

Changes to any analysis script must be validated against the [test harness](https://github.com/aklofas/kicad-happy-testharness) — a corpus of 5,829 real-world KiCad projects spanning hobby boards, production hardware, motor controllers, RF frontends, battery management systems, IoT devices, audio amplifiers, and more. KiCad 5 through 10.

### What the harness checks

| Layer | What it catches | How |
|-------|----------------|-----|
| **Crash testing** | Parser errors, unhandled exceptions, edge cases | Runs every analyzer against every file in the corpus |
| **Regression assertions** | Output drift, lost detections, changed values | 2.3M+ assertions on known-good outputs |
| **Bugfix guards** | Previously fixed bugs returning | Targeted assertions on specific past failures |
| **Equation audits** | Formula correctness | 107 equations tracked with primary source citations |
| **Constant audits** | Magic numbers drifting | 105+ switching frequencies + other constants tracked, 0 critical-risk |
| **Schema drift** | Analyzer `--schema` output diverging from emitted JSON | Symmetric-difference check across all 8 analyzers |

### Running the harness

The harness lives in a separate repo (`kicad-happy-testharness`). After making changes:

```bash
# Clone the harness (if you haven't already)
git clone https://github.com/aklofas/kicad-happy-testharness.git

# Run schematic analyzer across full corpus (parallel)
python3 run/run_schematic.py --jobs 16

# Run EMC analyzer across full corpus
python3 run/run_emc.py --jobs 16

# Run regression assertions
python3 regression/run_checks.py --type schematic
python3 regression/run_checks.py --type emc
```

The target is 100% pass rate across all assertion types. Any regression should be investigated — not suppressed.

### When to re-seed assertions

If your change intentionally changes analyzer output (new fields, changed detection logic, corrected calculations), you'll need to re-seed affected assertions. The harness RUNBOOK covers this in detail. The key principle: re-seed only the assertions your change affects, and verify the new values are correct before committing.

### Writing a test plan for new features

For significant new features, write a test plan that the harness can execute:

1. Create a `TODO-<feature>-test-plan.md` in the harness repo root
2. Define phases with specific pass/fail criteria
3. Include corpus-wide checks (crash rate, false positive rate, detection count)
4. Include targeted checks on specific repos where the feature should trigger

The harness agent executes test plans and reports results. After validation, the test plan file is deleted and results are archived.

## Code style

- **Python 3.10+ compatibility** — modern type hints (`X | None`, `list[int]`) are fine. Walrus operators and `match` statements are allowed. Avoid PEP 695 `type` aliases (3.12-only).
- **No external dependencies** in analysis scripts — stdlib only.
- **Functions over classes** — detectors are plain functions that take `AnalysisContext` and return lists.
- **Inline comments for equations** — tag with `# EQ-NNN: formula_name (source)` so the harness can track them.
- **No dead code** — if it's not called, delete it. The harness catches regressions; you don't need commented-out fallbacks.

## Submitting changes

1. Fork the repo and create a feature branch
2. Make your changes
3. Run the analysis scripts on at least one real KiCad project to sanity-check
4. Run the test harness if you have it set up (or describe your testing in the PR)
5. Open a PR — the GitHub Action will run deterministic analysis as a CI check

For changes to signal detectors or EMC rules, include in the PR description:
- How many repos in the corpus the detector fires on (if known)
- Any false positive mitigation you've done
- The primary source for any new formulas or thresholds

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
