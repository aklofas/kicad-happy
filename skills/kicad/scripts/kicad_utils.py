"""
Compatibility facade for the pre-v3 `kicad_utils` module.

Every helper that used to live here moved into skills/kicad/scripts/kicad_core/
in the v3 refactor (fields, values, parts, classify, netnames, passives,
project, netquery). This module re-exports all 72 pre-v3 public names so
existing `from kicad_utils import ...` lines keep working; new code imports
from kicad_core directly. Scheduled for removal in round 9 once the facade
register (ARCHITECTURE.md) shows no remaining consumer.
"""
from kicad_core.fields import (  # noqa: F401
    normalize_field_name, MPN_FIELD_ALIASES_PRIMARY, MPN_FIELD_ALIASES_GENERIC,
    MPN_FIELD_ALIASES, DIGIKEY_FIELD_ALIASES, pick_field, get_property_ci,
    _pick_nonblank, pick_mpn, _get_property_ci_nonblank, get_mpn_property,
)

from kicad_core.classify import (  # noqa: F401
    classify_component, classify_ic_function, classify_connector,
    classify_jumper_default_state,
)
from kicad_core.netnames import (  # noqa: F401
    parse_voltage_from_net_name, USB_DATA_NET_MARKERS, _SIGNAL_PREFIXES, _POWER_PREFIXES,
    _SUPPLY_TAILS, _RAIL_TAILS_GATED, _VOLTAGE_SIGNAL_SUFFIXES, is_usb_data_net_name,
    is_power_net_name, is_ground_name,
)
from kicad_core.passives import (  # noqa: F401
    _CAP_PKG_RE, _CAP_PKG_EIA_RE, _CAP_ESR_TABLE, _CAP_ESL, extract_cap_package,
    estimate_cap_esr, estimate_cap_esl, classify_dielectric, _SHIELDED_PATTERNS,
    _SEMI_SHIELDED_PATTERNS, _UNSHIELDED_PATTERNS, classify_inductor_shielding,
    _DC_BIAS_DERATING, estimate_dc_bias_derating,
)
from kicad_core.values import (  # noqa: F401
    COORD_EPSILON, _MIL_MM, snap_to_mil_grid, format_frequency, parse_value,
    parse_tolerance, E12_DECADE, E24_DECADE, E96_DECADE, _E_SERIES, snap_to_e_series,
    _RATED_V_RE, parse_rated_voltage,
)
from kicad_core.parts import (  # noqa: F401
    _REGULATOR_VREF, _LOAD_TYPE_KEYWORDS, _OUTPUT_DRIVE_KEYWORDS, lookup_regulator_vref,
    _KNOWN_FREQS, lookup_switching_freq, match_known_switching,
)
from kicad_core.project import (  # noqa: F401
    find_project_settings_file, load_kicad_pro, is_referenced_as_child,
    _root_references_target, discover_root_schematic, resolve_project_input,
    extract_pro_net_classes, extract_pro_design_rules, extract_pro_text_variables,
    load_kicad_dru, load_lib_tables,
)
from kicad_core.netquery import get_two_pin_nets, build_net_id_map  # noqa: F401
