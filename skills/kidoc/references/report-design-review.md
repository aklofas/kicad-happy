# Design Review Package

## Purpose

Go/no-go decision support for design reviews. Aggregates results from all analyzers into a single scorecard with action item tracking.

## Audience

Lead engineers, project managers, quality team.

## Sections

### Front Matter
- **Data source:** kidoc config (`project` fields)
- **Produces:** title page, revision history
- **Skipped when:** never

### Executive Summary
- **Data source:** schematic stats, EMC/thermal/PCB summaries
- **Produces:** auto-generated project overview paragraph
- **Skipped when:** never

### Review Summary (Scorecard)
- **Data source:** all analyzers -- fab gate, EMC, thermal, schematic stats
- **Produces:** cross-analyzer scorecard table with status and details:
  - Fab Release Gate: pass/fail counts (if gate data available)
  - EMC Risk Score: score/100 with severity breakdown
  - Thermal Score: score/100 with count above 85C
  - BOM Completeness: MPN coverage ratio
- **Skipped when:** never (rows appear only for available data)

### System Overview
- **Data source:** schematic analysis `statistics`, architecture diagram
- **Produces:** architecture diagram, component stats table
- **Skipped when:** never

### Power System Design
- **Data source:** schematic `power_regulators`, `decoupling_analysis`
- **Produces:** power tree diagram, regulator table, decoupling table
- **Skipped when:** never

### EMC Analysis
- **Data source:** EMC analyzer JSON
- **Produces:** risk score, findings tables
- **Skipped when:** no EMC data available

### Thermal Analysis
- **Data source:** thermal analyzer JSON
- **Produces:** thermal score, per-component table
- **Skipped when:** no thermal data available

### BOM Summary
- **Data source:** schematic analysis `bom`
- **Produces:** BOM table
- **Skipped when:** never

### Action Items
- **Data source:** config (pre-seeded template row)
- **Produces:** action item table (finding/severity/owner/due date/status)
- **Skipped when:** never

## Data Requirements

| Source | Required | Provides |
|--------|----------|----------|
| Schematic analysis | Yes | Executive summary, system overview, BOM, scorecard |
| EMC analysis | No | Scorecard EMC row, EMC section |
| Thermal analysis | No | Scorecard thermal row, thermal section |
| Fab gate data | No | Scorecard fab gate row |

## Customization

- `reports.documents[].sections` -- override section list
- Action items table is manually edited after generation

## Example

```yaml
reports:
  documents:
    - type: design_review
      formats: [pdf]
```
