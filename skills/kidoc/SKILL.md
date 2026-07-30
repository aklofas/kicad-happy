---
name: kidoc
description: >-
  Generate professional engineering documentation from KiCad projects — Hardware
  Design Descriptions (HDD), CE Technical Files, Interface Control Documents
  (ICD), Design Review Packages, and Manufacturing Transfer Packages. Auto-runs
  schematic, PCB, EMC, and thermal analyses; renders schematic and PCB SVGs
  with subsystem cropping, focus dimming, net highlighting, and pin-net
  annotation; generates power tree, bus topology, and architecture block
  diagrams. Produces styled PDF with cover pages, TOC, and vector SVG
  embedding. Markdown source of truth — human-editable, version-controllable.
  Use for "generate documentation", "create report", "HDD", "CE technical
  file", "design review package", "ICD", "render schematic", "render layout",
  "generate block diagram", "manufacturing package", "generate PDF", or
  "custom report".
---

# kidoc — Engineering Documentation Skill

Generate professional engineering documentation from KiCad project files.

## Quick Start

One command generates the full scaffold — analyses, diagrams, renders, and markdown are all produced automatically:

```bash
python3 skills/kidoc/scripts/kidoc_scaffold.py \
  --project-dir /path/to/kicad/project \
  --type hdd \
  --output reports/HDD.md
```

This auto-detects `.kicad_sch` and `.kicad_pcb` files, runs schematic/PCB/EMC/thermal analyses, generates block diagrams and schematic SVG renders, and produces a structured markdown scaffold with pre-filled data tables and narrative placeholders.

To produce a PDF:

```bash
python3 skills/kidoc/scripts/kidoc_generate.py \
  --project-dir /path/to/kicad/project \
  --doc reports/HDD.md \
  --format pdf
```

Creates `reports/.venv/` automatically on first run (PDF/DOCX/ODT only — HTML is zero-dep).

## Workflow

1. **Generate scaffold** — `kidoc_scaffold.py` auto-runs all available analyses, renders schematics, generates diagrams, and writes the markdown scaffold.
2. **Fill narratives** — The agent reads the scaffold and writes engineering prose for each `<!-- NARRATIVE: section_name -->` placeholder. The engineer reviews and edits.
3. **Regenerate** — On re-run, data sections between `<!-- GENERATED: section_id -->` markers update from fresh analysis; user-written narrative content is preserved.
4. **Render output** — `kidoc_generate.py` produces PDF, HTML, DOCX, or ODT.

## Document Types

| Type | Name | Key Sections |
|------|------|-------------|
| `hdd` | Hardware Design Description | System overview, power, signals, analog, thermal, EMC, PCB, mechanical, BOM, test, compliance |
| `ce_technical_file` | CE Technical File | Product ID, essential requirements, harmonized standards, risk assessment, Declaration of Conformity |
| `design_review` | Design Review Package | Review summary (cross-analyzer scores), findings, action items |
| `icd` | Interface Control Document | Interface list, per-connector pinout details, electrical characteristics |
| `manufacturing` | Manufacturing Transfer Package | Assembly overview, PCB fab notes, assembly instructions, test procedures |
| `schematic_review` | Schematic Review Report | System overview, power, signals, analog, BOM, schematic appendix |
| `power_analysis` | Power Analysis Report | Power design, thermal, EMC, BOM |
| `emc_report` | EMC Pre-Compliance Report | EMC analysis, compliance, schematic appendix |

## Custom Reports

Use `--spec` to generate reports with arbitrary section ordering:

```bash
python3 skills/kidoc/scripts/kidoc_scaffold.py \
  --project-dir . --spec my-report.json --output reports/custom.md
```

Spec format (JSON):

```json
{
  "type": "custom",
  "title": "USB Interface Analysis",
  "sections": [
    {"id": "front_matter", "type": "front_matter"},
    {"id": "signal_interfaces", "type": "signal_interfaces"},
    {"id": "bom", "type": "bom_summary"}
  ]
}
```

Each section's `type` must match a known section type (same names used in the document types table above). The `id` field is a unique key for that section instance.

To see the full default spec for any built-in type:

```bash
python3 skills/kidoc/scripts/kidoc_spec.py --expand hdd
python3 skills/kidoc/scripts/kidoc_spec.py --list
```

The `--spec` flag also works with `kidoc_generate.py` (uses the spec title as fallback project name).

## Schematic and PCB Rendering

Rendering is integrated into the figure generation engine. The orchestrator and scaffold automatically render schematics and PCB views as part of document generation:

```bash
# Generate all figures (diagrams + schematic/PCB renders) from analysis JSON
python3 skills/kidoc/scripts/kidoc_diagrams.py --analysis schematic.json --output reports/figures/

# Full orchestration with spec, analysis, and project files
python3 skills/kidoc/scripts/kidoc_orchestrator.py --analysis schematic.json \
    --project-dir . --output reports/figures/
```

The figure generators support: full-sheet rendering (root + all sub-sheets), subsystem cropping (`focus_refs` in spec sections), net highlighting, pin-level net annotation, and all PCB layer presets. These options are configured in the document spec or passed through the analysis dict.

Rendering features available through the generator framework:
- **Crop**: Focus on a subsystem bounding box around specific component refs
- **Focus/dim**: Show focused components at full opacity, dim the rest to 15%
- **Highlight nets**: Color-trace specific nets via BFS
- **Pin nets**: Annotate pin-level net names at pin tips

For direct programmatic access, use `figures.renderers`:
```python
from figures.renderers import render_schematic, render_pcb
render_schematic('design.kicad_sch', 'output/', crop_refs=['R1', 'R2'], highlight_nets=['VCC'])
render_pcb('board.kicad_pcb', 'output/', preset_name='assembly-front')
```

Layer presets:

| Preset | Shows |
|--------|-------|
| `assembly-front` | Front silk, fab, pads, outline |
| `assembly-back` | Back silk, fab, pads, outline (mirrored) |
| `routing-front` | Front copper, pads, vias, outline |
| `routing-back` | Back copper, pads, vias, outline |
| `routing-all` | All copper layers, pads, vias, zones |
| `power` | Power planes, vias, zone outlines |

Additional options: `--highlight-nets`, `--crop-refs`, `--crop x,y,w,h`, `--mirror`, `--overlay annotations.json` (callout boxes with leader lines).

## Block Diagrams

```bash
python3 skills/kidoc/scripts/kidoc_diagrams.py --analysis schematic.json --all --output diagrams/
python3 skills/kidoc/scripts/kidoc_diagrams.py --analysis schematic.json --power-tree --output diagrams/
python3 skills/kidoc/scripts/kidoc_diagrams.py --analysis schematic.json --bus-topology --output diagrams/
python3 skills/kidoc/scripts/kidoc_diagrams.py --analysis schematic.json --architecture --output diagrams/
```

Generated from schematic analysis JSON. Power trees show regulator topology with inductor values, capacitor summaries, and output voltages.

## Output Formats

| Format | SVG Handling | Dependencies |
|--------|-------------|------|
| **Markdown** | Image references | Zero-dep |
| **HTML** | Inlined as vector | Zero-dep |
| **PDF** | Vector via svglib, custom converter fallback, raster fallback | Venv (`reports/.venv/`) |
| **DOCX** | Rasterized to 300 DPI PNG | Venv |
| **ODT** | Rasterized to 300 DPI PNG | Venv |

PDF output includes a styled cover page, table of contents, formatted tables with alternating rows, and vector SVG diagrams.

## Configuration

Report settings live in `.kicad-happy.json` under the `"reports"` key. Config files cascade: `~/.kicad-happy.json` (user-level defaults, e.g. company branding) merges with project-level config.

```jsonc
{
  "project": {
    "name": "Widget Board",
    "number": "HW-2024-042",
    "revision": "1.2",
    "company": "Acme Electronics",
    "author": "Jane Smith",
    "market": "eu"
  },
  "reports": {
    "classification": "Company Confidential",
    "documents": [
      {"type": "hdd", "output": "HDD-{project}-{rev}", "formats": ["pdf", "docx"]}
    ],
    "branding": {
      "logo": "templates/logo.png",
      "header_left": "{company}",
      "header_right": "{number} Rev {rev}"
    }
  }
}
```

## Writing Narratives

After generating a scaffold, fill the narrative placeholder sections with engineering prose.

### Workflow

1. Run the context builder to get focused data for each section:
   ```bash
   python3 skills/kidoc/scripts/kidoc_narrative.py \
     --analysis analysis/schematic.json \
     --section power_design
   ```
   Or build contexts for all narrative sections at once:
   ```bash
   python3 skills/kidoc/scripts/kidoc_narrative.py \
     --analysis analysis/schematic.json \
     --report reports/HDD.md
   ```

2. For each section, read the context and write prose that:
   - Explains **why**, not just **what** — engineering rationale, tradeoffs
   - References specific component values and part numbers
   - Uses quantitative language ("2.3ms hold-up time" not "adequate capacitance")
   - Flags deviations from datasheet recommendations
   - References SPICE validation results when available

3. Replace the italic placeholder `*[...]*` in the markdown with real prose.

4. On regeneration, data tables update automatically. Review narratives for consistency with any changed data.

### Style Guide

Write as a senior EE explaining to a peer:
- Lead with the key finding or decision
- Support with specific numbers from the analysis
- Note any risks or deviations
- Keep paragraphs to 3-5 sentences
- Don't repeat data that's already in tables

## Requirements

- **Python 3.9+** with `python3-venv` (for PDF/DOCX/ODT generation)
- **KiCad schematic file** (`.kicad_sch`, KiCad 6+) — for SVG rendering
- **Optional:** Analysis JSONs are auto-generated from `.kicad_sch`/`.kicad_pcb`; pre-generated JSONs in `analysis/` (or the path configured in `.kicad-happy.json`) are used if present. Generated figures (diagrams, schematic SVGs) are placed in `reports/figures/` for git tracking

## Limitations

- Schematic and PCB renderers support KiCad 6+ formats only (`.kicad_sch`, `.kicad_pcb`)
- Narrative sections require the agent or manual authoring — the scaffold provides structure and data, not prose
- SPICE simulation results require manual simulation setup (not auto-run by scaffold)
- PDF vector SVG embedding uses svglib when available; falls back to raster if svglib cannot parse a particular SVG

## Related Skills

| Skill | Relationship |
|-------|-------------|
| `kicad` | Produces schematic/PCB/thermal analysis JSON consumed by scaffolds |
| `emc` | Produces EMC analysis JSON for EMC sections |
| `spice` | SPICE simulation results appear in analog design sections |
| `bom` | BOM data appears in BOM summary sections |

Run the `kicad` skill's analyzers first, then `emc` and `spice` if available. The scaffold auto-runs `kicad` and `emc` analyses when source files are present, so manual pre-analysis is only needed for SPICE.
