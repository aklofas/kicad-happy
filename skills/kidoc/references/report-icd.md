# Interface Control Document (ICD)

## Purpose

Integration guide for teams connecting to the board. Documents every external interface with pinouts, signal levels, and electrical characteristics.

## Audience

Firmware engineers, systems engineers, external integrators.

## Sections

### Front Matter
- **Data source:** kidoc config (`project` fields)
- **Produces:** title page, revision history
- **Skipped when:** never

### System Overview
- **Data source:** schematic analysis `statistics`, architecture diagram
- **Produces:** architecture diagram, component stats table
- **Skipped when:** never

### Interface List
- **Data source:** schematic `findings[] (detector: esd_coverage_audit)`
- **Produces:** summary table of all external connectors (ref, type, interface, signal count, ESD risk level)
- **Skipped when:** never (shows placeholder if no connectors detected)

### Connector Details
- **Data source:** schematic `esd_coverage_audit`, `ic_pin_analysis`, config `connectors` filter
- **Produces:** per-connector subsection with interface type, signal table (signal name, direction, voltage level, ESD protected), and narrative placeholder for protocol/timing details
- **Skipped when:** never (shows placeholder if no connector data)

### Signal Interfaces
- **Data source:** schematic `design_analysis.bus_analysis`, `findings[] (detector: level_shifters)`
- **Produces:** per-bus signal lists, level shifter table
- **Skipped when:** never

### Electrical Characteristics
- **Data source:** schematic `design_analysis.power_domains`
- **Produces:** voltage domain table (domain name, nominal/min/max placeholders)
- **Skipped when:** never

## Data Requirements

| Source | Required | Provides |
|--------|----------|----------|
| Schematic analysis | Yes | All sections |
| PCB analysis | No | Not used |
| EMC analysis | No | Not used |

## Customization

- `reports.documents[].connectors` -- list of connector references to include (e.g., `["J1", "J3"]`). When set, only those connectors appear in the Connector Details section. When omitted, all detected connectors are included.
- `reports.documents[].sections` -- override section list

## Example

```yaml
reports:
  documents:
    - type: icd
      formats: [pdf, docx]
      connectors: ["J1", "J2", "J5"]
```

## Notes

- Pinout SVG diagrams (visual pin maps per connector) are planned but not yet implemented.
- Direction and voltage level columns in the connector signal table require manual completion -- the schematic analyzer detects signal names but not always direction.
