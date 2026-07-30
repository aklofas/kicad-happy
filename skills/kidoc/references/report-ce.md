# CE Technical File

## Purpose

EU regulatory submission package mapping design evidence to directive essential requirements. Structured for review by notified bodies.

## Audience

Notified bodies, regulatory consultants, compliance team.

## Sections

### Front Matter
- **Data source:** kidoc config (`project` fields)
- **Produces:** title page, revision history
- **Skipped when:** never

### Product Identification
- **Data source:** config `project` fields
- **Produces:** product info table (name, model, revision, manufacturer, intended use placeholder)
- **Skipped when:** never

### Essential Requirements
- **Data source:** schematic analysis (RF chain detection for RED directive)
- **Produces:** directive-to-standard mapping table (LVD, EMC, RoHS; RED if RF detected)
- **Skipped when:** never

### Harmonized Standards
- **Data source:** config `reports.documents[].standards` override, or defaults
- **Produces:** standards table with category and description
- **Skipped when:** never
- **Defaults:** EN 55032, EN 55035, EN 62368-1, EN IEC 63000

### Risk Assessment
- **Data source:** thermal analyzer, EMC analyzer, schematic `esd_coverage_audit`
- **Produces:** hazard table (electrical shock, overheating, EMI, ESD, mechanical) with auto-populated risk levels from analysis data
- **Skipped when:** never (unfilled cells remain for manual completion)

### EMC Analysis
- **Data source:** EMC analyzer JSON (shared section with HDD)
- **Produces:** risk score, findings by category, critical/high detail
- **Skipped when:** no EMC data available

### Thermal Analysis
- **Data source:** thermal analyzer JSON (shared section with HDD)
- **Produces:** thermal score, per-component table
- **Skipped when:** no thermal data available

### Declaration of Conformity
- **Data source:** config `project` fields
- **Produces:** pre-filled DoC template (LVD, EMC, RoHS directives, signature block)
- **Skipped when:** never

### BOM Summary
- **Data source:** schematic analysis `bom`
- **Produces:** BOM table
- **Skipped when:** never

### Appendix: Schematics
- **Data source:** rendered SVGs
- **Produces:** per-sheet SVG embeds
- **Skipped when:** never

## Data Requirements

| Source | Required | Provides |
|--------|----------|----------|
| Schematic analysis | Yes | Product ID, BOM, RF detection, ESD audit |
| EMC analysis | No | EMC section, risk assessment EMI rows |
| Thermal analysis | No | Thermal section, risk assessment overheating row |
| PCB analysis | No | Not directly used (EMC analyzer consumes it) |

## Customization

- `reports.documents[].standards` -- override the harmonized standards list
- `project.market` -- should be "EU" or "CE" for this document type
- PDF/A output enabled by default (`pdfa: True` in template)

## Example

```yaml
project:
  name: "IoT Sensor Node"
  number: "ISN-200"
  revision: "B"
  company: "Acme Electronics"
  market: "EU"
reports:
  documents:
    - type: ce_technical_file
      standards:
        - EN 55032
        - EN 55035
        - EN 62368-1
        - EN IEC 63000
        - EN 300 328
```
