# Hardware Design Description (HDD)

## Purpose

Comprehensive design document covering every subsystem of a hardware project. The primary engineering record for internal teams.

## Audience

Designing engineer, review board, future maintainers.

## Sections

### Front Matter
- **Data source:** kidoc config (`project` fields)
- **Produces:** title page, revision history table
- **Skipped when:** never (always generated)

### Executive Summary
- **Data source:** schematic analysis stats, EMC/thermal/PCB summaries
- **Produces:** auto-generated paragraph with component count, MCU, power rails, PCB dimensions, EMC score
- **Skipped when:** never (degrades gracefully with less data)

### System Overview
- **Data source:** schematic analysis `statistics`, architecture diagram SVG
- **Produces:** architecture diagram embed, component stats table (total/unique/nets/sheets/SMD/THT)
- **Skipped when:** never

### Power System Design
- **Data source:** schematic `findings[] (detector: power_regulators)`, `findings[] (detector: decoupling_analysis)`
- **Produces:** power tree diagram embed, regulator table (ref/part/topology/input/output/Vout), decoupling table (IC/rail/caps/total)
- **Skipped when:** never (shows empty state if no regulators detected)

### Signal Interfaces
- **Data source:** schematic `design_analysis.bus_analysis`, `findings[] (detector: level_shifters)`
- **Produces:** per-bus signal lists (I2C/SPI/UART/CAN), level shifter table
- **Skipped when:** never

### Analog Design
- **Data source:** schematic `findings[]` (detectors: voltage_dividers, rc_filters, lc_filters, crystal_circuits, opamp_circuits)
- **Produces:** divider ratio table, filter cutoff tables, crystal frequency list, opamp topology table
- **Skipped when:** never (shows "no analog subcircuits" if empty)

### Thermal Analysis
- **Data source:** thermal analyzer JSON
- **Produces:** score summary, per-component thermal table (Pdiss, Tj, margin)
- **Skipped when:** no thermal data available

### EMC Considerations
- **Data source:** EMC analyzer JSON
- **Produces:** risk score banner, findings-by-category table, critical/high findings detail table
- **Skipped when:** no EMC data available

### PCB Design Details
- **Data source:** PCB analyzer JSON
- **Produces:** layer/footprint/track/via stats table, board dimensions
- **Skipped when:** no PCB data available

### Mechanical / Environmental
- **Data source:** PCB analyzer JSON (board_outline)
- **Produces:** board dimensions
- **Skipped when:** no PCB data available

### BOM Summary
- **Data source:** schematic analysis `bom`
- **Produces:** BOM table (refs/value/footprint/MPN/qty), truncated at 50 rows
- **Skipped when:** never

### Test and Debug
- **Data source:** schematic `findings[] (detector: debug_interfaces)`
- **Produces:** debug interface table (ref/type/protocol)
- **Skipped when:** never

### Compliance and Standards
- **Data source:** EMC analyzer (test_plan), config (`project.market`)
- **Produces:** target market, EMC test plan reference
- **Skipped when:** no EMC data and no market configured

### Appendix: Schematics
- **Data source:** rendered SVGs in schematic cache directory
- **Produces:** per-sheet SVG embeds
- **Skipped when:** never (shows placeholder if SVGs missing)

## Data Requirements

| Source | Required | Provides |
|--------|----------|----------|
| Schematic analysis | Yes | All core sections |
| PCB analysis | No | PCB design, mechanical, exec summary enrichment |
| EMC analysis | No | EMC section, compliance section, exec summary score |
| Thermal analysis | No | Thermal section, exec summary |

## Customization

- `project.market` -- sets target market for compliance section
- `reports.documents[].sections` -- override the section list for this doc type
- `reports.revision_history` -- populates the revision history table
- `reports.branding` -- customize PDF colors, company name, logo, and header text

## Branding Configuration

The PDF generator's colors, company name, and header text are configurable via `reports.branding`. All fields are optional -- defaults produce the standard dark navy engineering document style.

```json
{
  "reports": {
    "branding": {
      "company_name": "Acme Electronics",
      "logo": "templates/logo.png",
      "colors": {
        "primary": "#1a1a2e",
        "accent": "#0f4c75",
        "highlight": "#1b6ca8",
        "table_header": "#1a3a5c",
        "table_alt_row": "#f4f8fb",
        "callout_bg": "#edf5fb",
        "callout_border": "#1b6ca8"
      },
      "header_left": "{company}",
      "header_right": "{number} Rev {rev}"
    }
  }
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `company_name` | `project.company` | Company name shown in headers and cover |
| `logo` | (none) | Path to logo image for cover page |
| `colors.primary` | `#1a1a2e` | Dark navy used for header bars and H1 text |
| `colors.accent` | `#0f4c75` | Accent blue used for H2 text and table rules |
| `colors.highlight` | `#1b6ca8` | Teal used for H3 text, accent lines, callout borders |
| `colors.table_header` | `#1a3a5c` | Table header row background |
| `colors.table_alt_row` | `#f4f8fb` | Alternating table row background |
| `header_left` | `{company}` | Left header text template |
| `header_right` | `{number} Rev {rev}` | Right header text template |

## Example

```yaml
project:
  name: "Widget Controller"
  number: "WC-100"
  revision: "A"
  company: "Acme Electronics"
  market: "EU"
reports:
  documents:
    - type: hdd
      formats: [pdf, docx]
```
