# Document Structure Reference

How kidoc generates documents from analysis data.

## Architecture

1. **Auto-run analyses** -- kidoc_scaffold.py runs schematic, PCB, EMC, and thermal analyzers automatically when source files exist. No manual pre-step needed.
2. **Skip-not-stub** -- sections that need missing data (e.g., thermal section without thermal JSON) return `None` and are omitted entirely. No empty stubs clutter the output.
3. **Markdown source of truth** -- the generated `.md` file is the canonical document. Edit it directly; re-scaffold and reconcile via git diff.
4. **Professional output** -- markdown renders to PDF (via ReportLab/svglib), DOCX, or ODT. CE Technical Files default to PDF/A.

## Section Registry

The scaffold maps section IDs to generator functions. Each document type declares its section list in `kidoc_templates.py`. Config can override the list per document.

## Hardware Design Description (HDD)

1. Front Matter -- title, revision history, TOC, acronyms
2. Executive Summary -- auto-generated from analysis stats (components, MCU, rails, PCB, EMC score)
3. System Overview -- architecture diagram, component stats table
4. Power System Design -- power tree diagram, regulator table, decoupling table
5. Signal Interfaces -- I2C/SPI/UART/CAN buses, level shifters
6. Analog Design -- voltage dividers, filters, crystals, opamps
7. Thermal Analysis -- thermal score, per-component Tj table (skipped without thermal data)
8. EMC Considerations -- risk score, findings by category, critical/high detail (skipped without EMC data)
9. PCB Design Details -- layer stats, board dimensions (skipped without PCB data)
10. Mechanical / Environmental -- board outline, mounting (skipped without PCB data)
11. BOM Summary -- full BOM table
12. Test and Debug -- debug interfaces, test strategy
13. Compliance and Standards -- target market, EMC test plan (skipped without EMC data + no market)
14. Appendix: Schematics -- rendered SVGs per sheet

## CE Technical File

1. Front Matter
2. Product Identification -- product info table from config
3. Essential Requirements -- directive-to-standard mapping (LVD, EMC, RoHS; RED if RF detected)
4. Harmonized Standards -- configurable list (defaults: EN 55032, 55035, 62368-1, IEC 63000)
5. Risk Assessment -- hazard table auto-populated from thermal/EMC/ESD data
6. EMC Analysis -- shared section
7. Thermal Analysis -- shared section
8. Declaration of Conformity -- pre-filled DoC template
9. BOM Summary
10. Appendix: Schematics

## Interface Control Document (ICD)

1. Front Matter
2. System Overview -- architecture diagram, stats
3. Interface List -- connector summary table from ESD audit
4. Connector Details -- per-connector pinout/signal table (filterable via config `connectors` field)
5. Signal Interfaces -- bus analysis, level shifters
6. Electrical Characteristics -- voltage domain table

## Design Review Package

1. Front Matter
2. Executive Summary
3. Review Summary -- cross-analyzer scorecard (fab gate, EMC, thermal, BOM completeness)
4. System Overview
5. Power System Design
6. EMC Analysis -- shared section
7. Thermal Analysis -- shared section
8. BOM Summary
9. Action Items -- editable tracking table

## Manufacturing Transfer Package

1. Front Matter
2. Assembly Overview -- component count breakdown (SMD/THT/DNP)
3. BOM Summary
4. PCB Fabrication Notes -- fab parameters with sensible defaults (skipped without PCB data)
5. Assembly Instructions -- narrative placeholder
6. Production Test Procedures -- 5-step checklist template
7. Appendix: Schematics
