# Constraint card template

| ID | Constraint | Value | Owner | Unlocks |
|----|------------|-------|-------|---------|
| C-PCB | PCB SoT | `board_4layer.kicad_pcb` | HW lead | — |
| C-SCH-CUST | Customer sch | `sheets/00_….kicad_sch` | HW lead | — |
| C-SCH-ARCH | Archival sch | `flat.kicad_sch` | HW lead | — |
| C-CU | Copper freeze | ON after fab GO | HW lead | Evidence ECO |
| C-FAB | CAM package | `…_uncond_go.zip` | MFG | Re-export |
| C-WRITE | Agent write | MCP write / API only | Tools | — |
| C-CLAIM | EQ>95 | Needs lab SI + silicon | Lead | MEASURE |
