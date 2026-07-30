"""Narrative configuration: section titles, writing guidance, and questions.

Pure data module — no logic, no imports.  Used by kidoc_narrative.py
to populate LLM context packages.
"""

from __future__ import annotations


# ======================================================================
# Section title mapping
# ======================================================================

SECTION_TITLES = {
    'system_overview': 'System Overview',
    'power_design': 'Power System Design',
    'signal_interfaces': 'Signal Interfaces',
    'analog_design': 'Analog Design',
    'thermal_analysis': 'Thermal Analysis',
    'emc_analysis': 'EMC Considerations',
    'pcb_design': 'PCB Design Details',
    'bom_summary': 'BOM Summary',
    'test_debug': 'Test and Debug',
    'executive_summary': 'Executive Summary',
    'compliance': 'Compliance and Standards',
    'mechanical_environmental': 'Mechanical / Environmental',
    # CE Technical File
    'ce_product_identification': 'Product Identification',
    'ce_essential_requirements': 'Essential Requirements',
    'ce_risk_assessment': 'Risk Assessment',
    # Design Review
    'review_summary': 'Review Summary',
    'review_action_items': 'Action Items',
    # ICD
    'icd_interface_list': 'Interface List',
    'icd_connector_details': 'Connector Details',
    'icd_electrical_characteristics': 'Electrical Characteristics',
    # Manufacturing
    'mfg_assembly_overview': 'Assembly Overview',
    'mfg_pcb_fab_notes': 'PCB Fabrication Notes',
    'mfg_assembly_instructions': 'Assembly Instructions',
    'mfg_test_procedures': 'Production Test Procedures',
}


# ======================================================================
# Per-section writing guidance
# ======================================================================

WRITING_GUIDANCE = {
    'system_overview': (
        "Write a concise overview of the system architecture. Explain what the "
        "board does, its key functional blocks, and how they connect. Reference "
        "specific component counts and key ICs by part number. Keep it to 2-3 "
        "paragraphs. Don't repeat the data table — explain what it means."
    ),
    'power_design': (
        "Explain the power distribution architecture. For each regulator, state "
        "the input source, output voltage, topology, and why that topology was "
        "chosen (efficiency for buck, simplicity for LDO). Reference specific "
        "component values and datasheet recommendations. Flag any deviations "
        "from reference designs. Discuss thermal considerations for high-power "
        "regulators."
    ),
    'signal_interfaces': (
        "Describe each communication bus: what devices are connected, what "
        "protocol is used, and any notable configuration (pull-up values, "
        "termination, address assignments). Reference specific component "
        "references and net names."
    ),
    'analog_design': (
        "For each analog subcircuit (filters, dividers, opamp stages), explain "
        "the design intent, calculated performance (cutoff frequency, gain, "
        "output voltage), and any SPICE validation results. Use quantitative "
        "language — 'the RC filter sets a -3dB point at 1.02 kHz' not "
        "'appropriate filtering is provided.'"
    ),
    'thermal_analysis': (
        "Summarize thermal analysis results. Identify components with the "
        "smallest thermal margins. Discuss the adequacy of thermal management "
        "(heat sinking, copper area, airflow). Reference specific junction "
        "temperatures and maximum ratings."
    ),
    'emc_analysis': (
        "Summarize EMC findings by severity. Highlight critical and high-risk "
        "findings with specific mitigation recommendations. Reference rule IDs "
        "and affected components. Discuss the overall EMC risk level and "
        "readiness for pre-compliance testing."
    ),
    'pcb_design': (
        "Describe the PCB stackup, layer usage, and key routing decisions. "
        "Reference board dimensions, layer count, and critical design rules. "
        "Discuss any DFM concerns."
    ),
    'bom_summary': (
        "Summarize the BOM: total unique parts, component types breakdown, "
        "any missing MPNs that need resolution. Note any single-source or "
        "long-lead-time components if known."
    ),
    'test_debug': (
        "Describe the test and debug strategy: available debug interfaces, "
        "test point placement, production test sequence, and programming "
        "access. Reference specific connector references and protocols."
    ),
    'executive_summary': (
        "Write a 1-2 paragraph executive summary. State what the board is, "
        "its key specifications, and the overall assessment (design maturity, "
        "risk level, readiness for next phase). Reference specific numbers "
        "from the analysis. This is the most important section — it's what "
        "decision-makers read."
    ),
    'compliance': (
        "List applicable standards and certification requirements. Discuss "
        "pre-compliance test results and gaps. Reference EMC risk score "
        "and specific findings that affect certification."
    ),
    'mechanical_environmental': (
        "Describe the physical design: board dimensions, mounting method, "
        "enclosure constraints, connector placement. State the operating "
        "temperature range and environmental requirements."
    ),
    # CE Technical File
    'ce_product_identification': (
        "Describe the product's intended use, target environment "
        "(indoor/outdoor, industrial/consumer), and user profile."
    ),
    'ce_essential_requirements': (
        "For each directive, describe how the design meets the essential "
        "requirements. Reference test reports, analysis data, and specific "
        "design features that ensure compliance."
    ),
    'ce_risk_assessment': (
        "Describe risk mitigation measures for each identified hazard. "
        "Reference specific design features, test results, and component "
        "ratings that address each risk."
    ),
    # Design Review
    'review_summary': (
        "Provide an overall assessment of design readiness. Highlight "
        "critical risks, summarize analyzer scores, and recommend go/no-go "
        "for the next design phase."
    ),
    'review_action_items': (
        "List action items from the review. Assign severity, owners, and "
        "due dates. Prioritize items that block fabrication."
    ),
    # ICD
    'icd_connector_details': (
        "For each connector, describe the interface protocol, signal levels, "
        "timing requirements, and mating connector specification."
    ),
    'icd_electrical_characteristics': (
        "Specify voltage levels, impedance, current limits, and timing "
        "requirements for each interface."
    ),
    # Manufacturing
    'mfg_assembly_overview': (
        "Describe assembly requirements: lead-free/leaded process, reflow "
        "profile, hand-solder requirements, special handling instructions."
    ),
    'mfg_pcb_fab_notes': (
        "Specify impedance control requirements, stackup details, material "
        "(FR-4/Rogers), and any special fabrication instructions."
    ),
    'mfg_assembly_instructions': (
        "Describe the assembly sequence: paste application, component "
        "placement, reflow, hand-solder steps, cleaning, conformal coating."
    ),
    'mfg_test_procedures': (
        "Describe pass/fail criteria for each test step. Include expected "
        "voltages, test fixture requirements, and failure modes."
    ),
}


# ======================================================================
# Section questions — specific questions to address per section
# ======================================================================

SECTION_QUESTIONS = {
    'system_overview': [
        "What is the primary function of this board?",
        "What are the key functional blocks and how do they interconnect?",
        "What are the main ICs and their roles?",
    ],
    'power_design': [
        "What is the input voltage source and range?",
        "Why was each regulator topology chosen (LDO vs. buck vs. boost)?",
        "Are output capacitor values consistent with datasheet recommendations?",
        "What is the worst-case power dissipation in each regulator?",
        "Is there adequate input decoupling?",
    ],
    'signal_interfaces': [
        "What communication protocols are used and between which devices?",
        "Are pull-up/termination resistor values appropriate for the bus speed?",
        "Is there adequate ESD protection on external interfaces?",
    ],
    'analog_design': [
        "What is the design intent of each analog subcircuit?",
        "Do calculated values (cutoff, gain, ratio) match the design targets?",
        "Have tolerances been analyzed for critical circuits?",
    ],
    'thermal_analysis': [
        "Which components have the smallest thermal margin?",
        "Is the total board dissipation manageable without forced airflow?",
        "Are thermal vias or heatsinks needed for any component?",
    ],
    'emc_analysis': [
        "What is the overall EMC risk level?",
        "Which findings are most likely to cause certification failure?",
        "What are the top mitigation priorities?",
    ],
    'pcb_design': [
        "Is the layer count adequate for the routing complexity?",
        "Are there impedance-controlled traces that need stackup specification?",
        "Are there any DFM violations or concerns?",
    ],
    'bom_summary': [
        "How many unique parts are there and is this reasonable for the design?",
        "Are there missing MPNs that need resolution before ordering?",
        "Are there any single-source or long-lead-time components?",
    ],
    'executive_summary': [
        "What does this board do in one sentence?",
        "What is the design maturity level (prototype, pre-production, production)?",
        "What are the top risks or open items?",
    ],
}
