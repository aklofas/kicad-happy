# Manufacturing Transfer Package

## Purpose

Contract manufacturer handoff document. Contains everything a fab house and assembly house need to build and test the board.

## Audience

PCB fabrication house, assembly house, test technicians.

## Sections

### Front Matter
- **Data source:** kidoc config (`project` fields)
- **Produces:** title page, revision history
- **Skipped when:** never

### Assembly Overview
- **Data source:** schematic analysis `statistics`
- **Produces:** component count table (total, SMD, THT, DNP, unique parts)
- **Skipped when:** never

### BOM Summary
- **Data source:** schematic analysis `bom`
- **Produces:** BOM table (references, value, footprint, MPN, quantity)
- **Skipped when:** never

### PCB Fabrication Notes
- **Data source:** PCB analyzer JSON (`statistics`, `board_outline`)
- **Produces:** fab parameter table: board dimensions, copper layers, thickness (default 1.6mm), copper weight (default 1oz), surface finish (default HASL/ENIG), solder mask, silkscreen, min trace/space, min drill, IPC class (default Class 2)
- **Skipped when:** no PCB data available

### Assembly Instructions
- **Data source:** none (narrative placeholder)
- **Produces:** placeholder for: paste application, component placement, reflow profile, hand-solder steps, conformal coating, cleaning, sensitive component handling
- **Skipped when:** never

### Production Test Procedures
- **Data source:** none (pre-seeded checklist)
- **Produces:** 5-step test checklist template (visual inspection, power-on, functional test, programming, final inspection), plus narrative placeholder for pass/fail criteria
- **Skipped when:** never

### Appendix: Schematics
- **Data source:** rendered SVGs
- **Produces:** per-sheet SVG embeds
- **Skipped when:** never

## Data Requirements

| Source | Required | Provides |
|--------|----------|----------|
| Schematic analysis | Yes | Assembly overview, BOM |
| PCB analysis | No | Fab notes (dimensions, layers, stats) |
| EMC analysis | No | Not used |
| Thermal analysis | No | Not used |

## Customization

- `reports.documents[].sections` -- override section list
- Fab note defaults (1.6mm thickness, 1oz copper, HASL/ENIG, Class 2) should be manually updated to match actual board specs after generation

## Example

```yaml
reports:
  documents:
    - type: manufacturing
      formats: [pdf]
```

## Notes

- Thickness, copper weight, surface finish, min trace/space, and min drill default to common values. Update them to match your actual PCB stackup.
- Gerber file references and assembly drawing embeds can be added manually to the appendix.
