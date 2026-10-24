# kicad-happy

AI-powered electronics design review skills for KiCad 5-10. This document is auto-loaded into the Gemini CLI context and carries project-specific guidance for agents working in this repo.

## Agent guidelines

1. **Skill activation**: invoke `activate_skill` before running the Python scripts in this repo. Each skill's `SKILL.md` carries procedural guidance, triggers, and constraints that aren't in the main system prompt.
2. **Context efficiency**:
    - **Search first**: use `grep_search` to find points of interest in `.kicad_sch` and `.kicad_pcb` files — they routinely exceed 10,000 lines.
    - **Targeted reads**: avoid reading whole schematic/PCB files. Use line numbers from `grep_search` for surgical `read_file` calls.
    - **Trust analyzer output**: the Python analysis scripts are the source of truth for design data. Don't guess circuit behavior from raw S-expressions when a detector already covers it.
3. **Validation**: a change isn't done until the relevant `analyze_*.py` script has been re-run and produces no new warnings or regressions.

## Skills

| Skill | Purpose |
|-------|---------|
| kicad | Core analysis — schematic parsing, PCB layout review, Gerber verification, thermal, diff, what-if |
| datasheets | Structured datasheet extraction — per-MPN cache, quality scoring, consumer API for other skills |
| emc | EMC pre-compliance — 44 rules across 18 categories |
| spice | SPICE simulation — auto-generated testbenches, Monte Carlo tolerance |
| bom | BOM management — multi-supplier pricing, order file export |
| digikey | DigiKey API — component search, datasheet download, `--mpn-list` batch mode |
| mouser | Mouser API — component search, `--mpn-list` batch mode |
| lcsc | LCSC/JLCPCB parts — community API, no auth required, `--mpn-list` batch mode |
| element14 | element14/Newark/Farnell API — `--mpn-list` batch mode |
| jlcpcb | JLCPCB fab rules, BOM/CPL format |
| pcbway | PCBWay fab rules, turnkey assembly |

## Running analysis

```bash
# Schematic analysis
python3 skills/kicad/scripts/analyze_schematic.py <file>.kicad_sch
python3 skills/kicad/scripts/analyze_schematic.py <file>.kicad_sch --output analysis.json

# PCB layout analysis
python3 skills/kicad/scripts/analyze_pcb.py <file>.kicad_pcb
python3 skills/kicad/scripts/analyze_pcb.py <file>.kicad_pcb --full --output pcb.json

# EMC pre-compliance (requires schematic + PCB JSON)
python3 skills/emc/scripts/analyze_emc.py --schematic sch.json --pcb pcb.json

# Gerber verification
python3 skills/kicad/scripts/analyze_gerbers.py <gerber_dir>/
```

All scripts are zero-dependency (Python 3.10+ stdlib only). No `pip install` needed.

## Code structure

- `skills/kicad/scripts/analyze_schematic.py` — Schematic parser and analysis orchestrator (~9,500 LOC)
- `skills/kicad/scripts/signal_detectors.py` — Core signal path detectors (~4,400 LOC)
- `skills/kicad/scripts/domain_detectors.py` — Domain-specific detectors (~6,100 LOC)
- `skills/kicad/scripts/validation_detectors.py` — Validation detectors (pull-ups, voltage levels, protocol buses, feedback stability) (~1,300 LOC)
- `skills/kicad/scripts/lookup_detectors.py` — v1.4 datasheet-backed detectors (AM-001, OV-001, FT-001, PM-001, EX-001) via Phase 2 lookup API (~700 LOC)
- `skills/kicad/scripts/analyze_pcb.py` — PCB layout analyzer (~6,700 LOC)
- `skills/kicad/scripts/analyzer_envelope.py` — Typed envelope dataclasses (Finding, Assessment, TrustSummary, InputsBlock, CompatBlock) — single source of truth for analyzer output shape
- `skills/kicad/scripts/finding_schema.py` — Rich finding factory, `Det` constants, consumer helpers, trust_summary aggregation
- `skills/kicad/scripts/cross_analysis.py` — Schematic + PCB cross-domain checks (~1,100 LOC)
- `skills/emc/scripts/emc_rules.py` — 44 EMC rule implementations (~4,250 LOC)
- `skills/kicad/scripts/kicad_types.py` — `AnalysisContext` dataclass shared by all detectors
- `skills/kicad/references/` — 18 deep methodology guides
- `skills/datasheets/` — Extraction pipeline + v1.4 typed `lookup()` entry point with `datasheet_types/` access layer (DatasheetFacts, SpecValue, Pin, Pinout, trust_gating helpers)
- `skills/kicad/review/` — v2.0 Deep Review infrastructure: schemas (design_context, review_annotations, deep_review), merge/validate/build-plan scripts, prompt scaffold for design_context input; Deep Review evidence gate at `deep_review_gate.py`

## Documentation reference

- `CONTRIBUTING.md` — How detectors work, how to add skills, test harness usage
- `VALIDATION.md` — Test methodology and corpus statistics
- `CHANGELOG.md` — Release history
- `datasheet-extraction.md`, `emc-precompliance.md`, `spice-integration.md` — Deep-dive guides for each major skill
