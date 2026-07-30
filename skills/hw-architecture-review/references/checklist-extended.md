# Extended architecture checklist

## Interface ownership columns

| Signal / bus | Electrical class | Driver | Receiver | Power domain | Sheet | Verify gate |
|--------------|------------------|--------|----------|--------------|-------|-------------|
| | HS / SB / PWR / DBG | | | | | |

## Hierarchy decision tree

1. Single flat schematic sufficient for customer PDF? → Prefer flat + clear titles.
2. Need industrial multi-sheet presentation? → Hierarchical **index** OK if children exported **directly**.
3. Need hierarchical netlist ERC as electrical proof? → Sibling Sheetfile + coherent pins/labels; budget a dedicated milestone.
4. Never score hollow-index ERC=0 as silicon readiness.

## Commercial pattern axes (example)

1. Passive vs switch/retimer
2. External power injection
3. Dual-slot rail distribution
4. 3V3VAUX presence
5. REFCLK sourcing model
6. PERST direction
7. Tx/Rx seating / lane swap class
8. SI practice / length
9. Bring-up observability (TP)
10. Documented max power
