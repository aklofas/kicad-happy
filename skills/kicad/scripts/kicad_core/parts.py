"""Known-part knowledge tables: regulator Vref and switching frequencies (kicad_core). Sources and verification dates are in the table comments. Also holds typical MLCC ESL/ESR by package and LED forward voltage by colour."""
import re
from collections.abc import Iterable


# Load-switch and power-distribution-switch part-number prefixes (lowercase), matched by
# is_load_switch_part. Shared by the power-path detector, the rail-source switch chain, VM-001 and
# the regulator screen, which must not record them as LDOs.
LOAD_SWITCH_KEYWORDS = (
    "tps229", "tps2291", "tps2293", "tps2295",
    "tps2281", "tps2283", "tps2285",
    "tps2211", "tps2219", "tps2221",
    "tps22918", "tps22919", "tps22810",
    "tps205", "tps206", "ap217", "mt9700",
    "sy628",
    "rt9742", "rt9701", "ap2281", "ap2191",
    "stmps2", "ncp380", "ncp381",
    "mic20",                                   # Microchip MIC20xx power-distribution switches
    "sip32",                                   # Vishay SiP32xxx load switches
    "ap2280", "ap2261", "ap2265", "ap255",     # Diodes AP2280x / AP2261x / AP2265x / AP255x
    "fpf",                                     # onsemi FPFxxxx load switches
)
# A family prefix where a part number starts: "AP22653W6", "U_MIC2025", not "SAP2171" or "TDA2002".
_LOAD_SWITCH_PREFIX = re.compile(r"(?<![a-z0-9])(?:" + "|".join(LOAD_SWITCH_KEYWORDS) + ")")


def is_load_switch_part(value: str, symbol: str, mpn: str = "") -> bool:
    """True when the value or MPN starts a load-switch family part number. The symbol name
    (a lib_id without its library nickname) decides only when neither names a part: an
    LP5907 drawn on a MIC20XX symbol is an LDO."""
    named = False
    for text in (value or "", mpn or ""):
        if _LOAD_SWITCH_PREFIX.search(text.lower()):
            return True
        # the core, not the whole value: a '/NOPB' ordering suffix does not make a label
        core = part_number_core(text)
        named = named or (bool(core) and not is_label_like_value(core))
    return not named and bool(_LOAD_SWITCH_PREFIX.search((symbol or "").lower()))

# "load switching" (a buck's light-load mode) does not name a load switch.
_LOAD_SWITCH_WORDS = re.compile(r"\b(?:load|power|power distribution) switch(?:es)?\b", re.I)


def names_load_switch(text: str) -> bool:
    """True when *text* calls the part a load, power or power-distribution switch."""
    return bool(_LOAD_SWITCH_WORDS.search(text or ""))


# Regulator Vref lookup table — maps part number prefixes to their internal
# reference voltage.  Used by the feedback divider Vout estimator instead of
# guessing from a list.  Lookup uses longest-prefix-match so that specific
# entries (e.g. LMR51420=0.6V) beat broader ones (e.g. LMR514=0.8V).
# When a part isn't found here the analyzer falls back to the heuristic sweep.
# Sources: DigiKey parametric data + manufacturer datasheets (verified 2026-04-12)
_REGULATOR_VREF: dict[str, float] = {
    # TI switching regulators — verified against TI datasheets + DigiKey 2026-04-12
    "TPS6100": 0.5,                                               # TPS61000/01 FB = 0.5V
    # TPS6102x/3x members differ: one key per adjustable member, no family key (the fixed
    # TPS61024-27 and TPS61031/32 have no feedback reference)
    "TPS61020": 0.5,   "TPS61028": 0.5,   "TPS61029": 0.5,       # VFB = 500 mV (TPS6102x SLVS451G p5, Electrical Characteristics)
    "TPS61021": 0.795,                                            # TPS61021A VREF = 795 mV PWM mode (SLVSDM0 p5)
    "TPS61022": 0.6,                                              # VREF = 600 mV PWM mode (SLVSDX7D p5)
    "TPS61023": 0.595,                                            # VREF = 595 mV PWM mode (SLVSF14B p5)
    "TPS61030": 0.5,                                              # VFB = 500 mV (TPS6103x SLUS534G p5)
    "TPS5430": 1.221,  "TPS5450": 1.221,  "TPS5410": 1.221,     # TPS5430/50/10 Vref = 1.221V
    "TPS54160": 0.8,   "TPS54260": 0.8,   "TPS54360": 0.8,      # TPS541x0/542x0/543x0 FB = 0.8V
    "TPS54040": 0.8,   "TPS54060": 0.8,                          # TPS54040/60 Vref = 0.8V
    "TPS54302": 0.596, "TPS54308": 0.596,                        # TPS54302/08 FB = 0.596V (verified)
    "TPS54202": 0.596,                                            # VFB = 0.596 V (SLVSD26C p5; TPS54202H SLVSDG7A p5)
    "TPS54560": 0.8,                                              # reference = 0.8 V (SLVSBN0A p5; TPS54560B SLVSF00 p5)
    # TPS56 family — split per DigiKey verification (was single 'TPS56': 0.6)
    "TPS56339": 0.8,   "TPS56637": 0.6,                          # TPS56339 = 0.8V, TPS56637 = 0.6V
    "TPS560200": 0.8,                                             # TPS560200 VSENSE = 0.8V
    "TPS560430": 1.0,                                             # TPS560430 VOUT accuracy (integrated FB)
    # TPS561/562/563/564 members differ: one key per member, no family key
    "TPS561201": 0.768, "TPS561208": 0.768,                       # VFBTH = 768 mV continuous mode (SLVSC95A p5)
    "TPS561243": 0.6,                                             # VFB = 600 mV (SLUSFG9A p5)
    "TPS562200": 0.765, "TPS563200": 0.765,                       # VFB(TH) = 765 mV continuous mode (TPS56x200 SLVSCB0E p7)
    "TPS562201": 0.768, "TPS562208": 0.768,                       # VFBTH = 768 mV continuous mode (SLVSD91D p5)
    "TPS562202": 0.804,                                           # VFBTH = 804 mV continuous mode (SLUSE28 p6; TPS562202S SLUSED6 p5)
    "TPS562207": 0.804,                                           # VFBTH = 804 mV (SLUSDR7B p6)
    "TPS562212": 0.6,                                             # VFB = 0.6 V (SLUSEI0 p5)
    "TPS563201": 0.768, "TPS563208": 0.768,                       # VFBTH = 768 mV continuous mode (SLVSD90B p6)
    "TPS563202S": 0.806,                                          # VFBTH = 806 mV continuous mode (SLUSED8 p6)
    "TPS563240": 0.6,                                             # VFB = 600 mV continuous mode (SLVSE74A p5)
    "TPS563249": 0.6,                                             # VFB = 600 mV (SLVSE54A p5)
    "TPS564247": 0.6,                                             # VREF = 600 mV (SLUSEN2 p5)
    "TPS564257": 0.6,                                             # VREF = 600 mV (TPS56425x SLUSEQ6A p5)
    "TPS5633": 0.8,                                               # TPS563300 = 0.8V
    "TPS5652": 0.6,                                               # TPS565242 VREF = 600 mV (SLUSEN1A p5)
    "TPS565201": 0.76,                                            # VFBTH = 760 mV (SLVSE71 p5)
    "TPS565208": 0.76,                                            # VFBTH = 760 mV (SLVSE72B p5)
    "TPS566": 0.6,                                                # TPS566238 = 0.6V
    "TPS56A": 0.6,                                                # TPS56A37 = 0.6V
    # TPS63 buck-boost
    "TPS6300": 0.5,    "TPS6301": 0.5,                           # TPS63000/01 VFB = 0.5V
    "TPS6310": 0.5,                                               # TPS631000 VFB = 0.5V
    "TPS63020": 0.5,                                              # TPS63020 VFB = 500 mV (SLVS916I §6.5); TPS63021 is fixed 3.3 V
    # TI power modules
    "TPS82084": 0.8,   "TPS82085": 0.8,                          # TPS82084/85 VFB = 800 mV (SLVSCN4D §6.5)
    # TI LMR family
    "LMR51410": 0.6,   "LMR51420": 0.6,   "LMR51430": 0.6,       # LMR51410/20/30 Vref = 0.6V
    "LMR51440": 0.8,   "LMR51460": 0.8,                          # LMR51440/60 Vref = 0.8V
    "LMR51606": 0.8,   "LMR51610": 0.8,                          # LMR51606/10 VFB = 0.8 V (SLUSEY1B §6.5 p5)
    "LMR51625": 0.8,   "LMR51635": 0.8,                          # VFB = 0.8 V (SLUSF64B p5)
    "LMR50410": 1.0,                                              # VFB = 1 V (SLUSDW3A p5; -Q1 SLUSDW4A p5)
    "LMR336": 1.0,     "LMR338": 1.0,                            # LMR33630/60 Vref = 1.0V
    "LMR33640": 1.0,                                              # VFB = 1 V, ADJ option (SNVSB99C p6)
    "LM2731": 1.23,    "LM27313": 1.23,                           # VFB = 1.230 V (LM2731 SNVS217G p5; LM27313 SNVS487E p5)
    "LMR380": 1.0,                                                # LMR38010 VFB = 1.0V
    "LM258": 1.23,     "LM259": 1.23,                            # LM2596/LM2585 VFB = 1.23V (adj variants)
    "LMZ2": 0.795,                                                # LMZ23610 VFB = 0.795V
    "LM614": 1.0,      "LM619": 1.0,                             # LM61495 VFB = 1.0V
    # TI LDOs — TPS7A split per DigiKey verification (was single 'TPS7A': 1.19)
    "TPS7A49": 1.194,                                             # TPS7A4901 VFB = 1.194V
    "TPS7A45": 1.21,                                              # TPS7A4501 VFB = 1.21V
    "TPS7A47": 1.4,                                               # TPS7A4701 VFB = 1.4V
    "TPS7A25": 1.24,                                              # TPS7A25xx VFB = 1.24V
    "TPS7A26": 1.24,                                              # TPS7A2601 VFB = 1.24V
    "TPS7A92": 0.8,                                               # TPS7A92xx VFB = 0.8V
    "TPS7A70": 0.5,                                               # TPS7A7002 VFB = 0.5V
    "TPS7A73": 0.9,                                               # TPS7A7300 VFB = 0.9V
    "TPS7A30": 1.18,   "TPS7A33": 1.18,                          # TPS7A30xx/33xx negative, |Vref| = 1.18V
    "TPS7A16": 1.2,                                               # TPS7A1601 VFB = 1.2V
    "TLV759": 0.55,                                               # TLV759P (adjustable) FB = 0.55V
    "TPS736": 1.204,                                              # TPS73601/TPS736xx VFB = 1.204V
    "TPS73101": 1.204,                                            # VFB = 1.204 V (TPS731 SBVS034P p5)
    "TPS79301": 1.225,                                            # VFB = 1.225 V (TPS793 SLVS348L p6)
    "LM5122": 1.2,                                                # VREF = 1.2 V (LM5122 SNVS954H p8)
    # Analog Devices / Linear Tech
    "LTC3610": 0.6,                                               # VFB = 0.600 V (LTC3610 Rev. F p2)
    "LTC3620": 0.6,                                               # VFB = 0.6 V (LTC3620 Rev. A p2)
    "LT8610": 0.97,                                               # VFB = 0.970 V (LT8610 Rev. A p2; LT8610A/LT8610AB Rev. C p3)
    "LT8614": 0.97,                                               # VFB = 0.970 V (LT8614 Rev. H p3)
    "LT8640": 0.97,                                               # VFB = 0.970 V (LT8640/LT8640-1 Rev. F p3; LT8640A Rev. A p3; LT8640S/LT8643S Rev. C p3)
    "LT862": 0.97,                                                # LT8620 VFB = 0.970 V (LT8620 Rev. A p3)
    "LT8606": 0.778,                                              # VFB = 0.778 V (LT8606/LT8606B Rev. D p3)
    "LT8607": 0.778,                                              # VFB = 0.778 V (LT8607/LT8607B Rev. D p3)
    "LT8608": 0.778,                                              # VFB = 0.778 V (LT8608/LT8608B Rev. D p3)
    "LT8608S": 0.774,                                             # VFB = 0.774 V (LT8608S Rev. 0 p2)
    "LT8609": 0.782,                                              # VFB = 0.782 V (LT8609/LT8609A/LT8609B Rev. J p4)
    "LT8609S": 0.774,                                             # VFB = 0.774 V (LT8609S Rev. D p3)
    "LT871": 1.213,                                               # LT8710 FBX = 1.213V
    "LTM46": 0.6,                                                 # LTM4600 VFB = 0.6V
    "LTC3558": 0.8,                                               # LTC3558 VFB1/VFB2 = 800 mV (3558f)
    # Richtek
    "RT5": 0.6,         "RT6": 0.6,                              # family default (RT5785 VFB = 0.6V)
    "RT6150": 0.5,                                                # RT6150A/B VFB = 0.5V (DS6150A/B-06)
    "RT2875": 0.6,                                                # RT2875 VFB = 0.6V
    # MPS — split per DigiKey verification (was single 'MP2': 0.8)
    "MP1": 0.8,                                                    # MP1584 VFB = 0.8V
    "MP2307": 0.925,                                               # MP2307 VFB = 0.925V (DigiKey verified)
    "MP2315": 0.8,                                                 # MP2315 VFB = 0.8V
    "MP2338": 0.5,                                                 # MP2338 VFB = 0.5V (DigiKey verified)
    "MP2359": 0.81,                                                # MP2359 VFB = 0.81V (DigiKey verified)
    "MP2384": 0.6,                                                 # MP2384 VFB = 0.6V (DigiKey verified)
    "MP2403": 0.8,                                                 # MP2403 VFB = 0.8V
    "MP2451": 0.8,                                                 # MP2451 VFB = 0.8V
    "MP2459": 0.81,                                                # MP2459 VFB = 0.81V
    "MP2236": 0.6,                                                 # MP2236 VFB = 0.6V
    "MP2143": 0.6,                                                 # MP2143 VFB = 0.6V
    "MP2162": 0.6,                                                 # MP2162 VFB = 0.6V
    "MP2303": 0.8,                                                 # MP2303 VFB = 0.8V
    "MP28167": 1.0,                                                # MP28167 VFB = 1.0V (DigiKey verified)
    # Microchip — MIC29 kept for adjustable variant only
    "MIC29": 1.24,                                                # MIC29150/29300 adj Vref = 1.24V
    # Diodes Inc — AP73 split (was 'AP73': 0.6, 'AP736': 0.8)
    "AP633": 0.8,                                                 # AP63356/AP63357 VFB = 0.8V
    "AP632": 0.8,                                                 # AP63200/AP63203/AP63205 VFB = 0.8V
    "AP7335": 0.8,                                                # AP7335 adjustable VFB = 0.8V
    "AP7362": 0.6,     "AP7363": 0.6,                            # AP7362/63 adjustable VFB = 0.6V
    "AP7365": 0.8,     "AP7366": 0.8,                            # AP7365/66 adjustable VFB = 0.8V
    "AP2112": 0.8,                                                # AP2112 adjustable Vref = 0.8V
    "AP3015": 1.23,                                               # AP3015A VFB = 1.23V
    # ST
    "LD1117": 1.25,    "LDL1117": 1.25,   "LD33": 1.25,         # LD1117 family Vref = 1.25V
    # ON Semi
    "NCP1117": 1.25,                                              # NCP1117 Vref = 1.25V
    # SY (Silergy) — kept as-is, SY8088/8113 all 0.6V (verified clean)
    "SY8": 0.6,                                                   # SY8089/8113 FB = 0.6V
    # Maxim
    "MAX5035": 1.22,    "MAX5033": 1.22,                          # MAX5035/33 VFB = 1.22V
    "MAX1771": 1.5,     "MAX1709": 1.25,                          # MAX1771 Vref = 1.5V, MAX1709 VFB = 1.25V
    "MAX17760": 0.8,                                               # MAX17760 FB = 0.8V
    # ISL (Renesas/Intersil)
    "ISL854": 0.6,      "ISL850": 0.8,                            # ISL85410 = 0.6V, ISL85003 = 0.8V
    # XL (XLSEMI)
    "XL70": 1.25,                                                  # XL7015 VFB = 1.25V
    # TI misc
    "TPS6291": 0.8,                                                # TPS62912 VFB = 0.8V
    "LM2267": 1.285,                                               # LM22676 VFB = 1.285V (adj variant)
    # Generic adjustable regulators
    "LM317": 1.25,     "LM337": 1.25,
    "LM338": 1.24,                                                # VREF = 1.24 V typ (SNVS771D p7)
    "LM350": 1.25,                                                # VREF = 1.25 V (SNVS772B p2)
    "SPX1117": 1.25,                                              # VREF = 1.250 V (MaxLinear Rev. 2.2.0 p2)
    "AMS1117": 1.25,   "AMS1085": 1.25,
    "LM1117": 1.25,
    # Avia Semiconductor HX711 "24-Bit Analog-to-Digital Converter (ADC) for Weigh Scales" (English,
    # no revision number): analog-supply regulator VAVDD = VBG x (R1 + R2) / R1 (p.4)
    "HX711": 1.25,                                                 # VBG 1.25 V (Table 2 Key Electrical Characteristics, p.3)
    # REMOVED: LM78, LM79 — fixed-output only, suffix parser handles them
    # REMOVED: AP73 broad prefix — split into AP7335/AP7362/AP7363/AP7365/AP7366
    # REMOVED: AP736 broad prefix — split into AP7365/AP7366
    # REMOVED: MP2 broad prefix — split into per-MPN entries
    # REMOVED: TPS7A broad prefix — split into per-sub-family entries
    # REMOVED: TPS56 broad prefix — split into per-sub-family entries
}

# Keywords for classifying MOSFET/BJT load type from net names.
# Used by _classify_load() for transistor analysis and by net classification
# for the "output_drive" net class.  Keys are load type names, values are
# keyword tuples matched as substrings of the uppercased net name.
# Avoid short prefixes that appear inside unrelated words:
#   "SOL" matches MISO_LEVEL, ISOL → use SOLENOID only
#   "MOT" matches REMOTE → use MOTOR only
_LOAD_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "motor": ("MOTOR",),
    "heater": ("HEAT", "HTR", "HEATER"),
    "fan": ("FAN",),
    "solenoid": ("SOLENOID",),
    "valve": ("VALVE",),
    "pump": ("PUMP",),
    "relay": ("RELAY", "RLY"),
    "speaker": ("SPEAK", "SPK"),
    "buzzer": ("BUZZ", "BZR", "BUZZER"),
    "lamp": ("LAMP", "BULB"),
}

# Flattened keyword set for net classification (output_drive class).
# Includes LED/PWM which aren't load types but are output drive signals.
_OUTPUT_DRIVE_KEYWORDS: tuple[str, ...] = (
    "LED", "PWM",
    *{kw for kws in _LOAD_TYPE_KEYWORDS.values() for kw in kws},
)


def _regulator_candidates(value: str, lib_id: str, mpn: str) -> tuple[list[str], tuple[float | None, str]]:
    """The candidate names the Vref was taken from, and the lookup result.

    Value and lib_id part name come first; the MPN is consulted only when they
    give nothing, or when it names a longer table key (RT6150 over RT6).
    """
    candidates = [value.upper()]
    if ":" in lib_id:
        candidates.append(lib_id.split(":")[-1].upper())
    result = _lookup_vref(candidates)
    if mpn:
        mpn_candidates = [mpn.upper()]
        mpn_result = _lookup_vref(mpn_candidates)
        if result[0] is None:
            return mpn_candidates, mpn_result
        if result[1] == "lookup" and mpn_result[1] == "lookup":
            keys = [_longest_vref_key(c) or "" for c in (candidates + mpn_candidates)]
            if len(keys[-1]) > max(len(k) for k in keys[:-1]):
                return mpn_candidates, mpn_result
    return candidates, result


def lookup_regulator_vref(value: str, lib_id: str, mpn: str = "") -> tuple[float | None, str]:
    """Look up a regulator's internal Vref from its value, lib_id or MPN.

    Returns (vref, source) where source is "fixed_suffix" for a fixed-output
    part number, "lookup" for a table hit, or (None, "") if not found.  Tries
    the value field first (usually the part number), then the lib_id part name
    after the colon; the MPN is consulted when neither gives an answer or when
    it names a longer table key.
    """
    return _regulator_candidates(value, lib_id, mpn)[1]


# A package name in a part or symbol name (_SOT-23, SOT-89-10, _TO220) is not a voltage.
_PACKAGE_TOKEN = re.compile(
    r'[-_]?(?:SOT|SOD|SC|TO|DFN|QFN|SON|SOIC|SOP|MSOP|SSOP|TSSOP|HTSSOP|VSSOP|TSOT|'
    r'WSON|VSON|USON|UDFN|WDFN|XDFN|TDFN|VQFN|WQFN|LGA|BGA|DIP|PDIP|SIP|LQFP|TQFP|QFP|'
    r'DPAK|D2PAK)[-_]?\d+(?:[-_]\d+)?'
    r'|[-_](?:MLP|WLCSP|POWERPAD|SO|LFCSP|TSOP|HSOP|ESOP|DSBGA|UQFN|QSOP|PQFN|DDPAK)[-_]?\d{1,3}(?!\d)(?:[-_]\d{1,3}(?!\d))?')
# A two-digit suffix that is also a common supply voltage is read both ways in
# KiCad's library (AP7361C-12E is 1.2 V, LM1085-12 is 12 V; AP1117-15 is 1.5 V,
# LM3480-15 is 15 V; LM341T-05 is 5 V; NID30S48-24 is 24 V), so it gives no value.
_AMBIGUOUS_SUFFIXES = frozenset({"05", "09", "10", "12", "15", "24", "48"})
# Families whose data sheet gives the voltage of such a suffix (part-number prefix -> {suffix: V}).
_FIXED_SUFFIX_FAMILIES: dict[str, dict[str, float]] = {
    "LM2596": {"12": 12.0},                          # SNVS124E: 3.3-V, 5-V, 12-V and adjustable versions
    "LM2576": {"12": 12.0, "15": 15.0},              # SNVS107G: 3.3-V, 5-V, 12-V, 15-V and adjustable
    "LM2940": {"10": 10.0, "12": 12.0, "15": 15.0},  # SNVS769J ordering table: -5.0, -8.0, -9.0, -10, -12, -15
    "TL780": {"05": 5.0, "12": 12.0, "15": 15.0},    # SLVS055M: TL780-05, -12, -15
    "NCP1117": {"12": 12.0, "15": 1.5},              # onsemi NCP1117 ordering table: ST12T3G 12 V, ST15T3G 1.5 V
    "XL1509": {"12": 12.0},                          # XLSEMI XL1509: 3.3 V, 5 V, 12 V and adjustable versions
    "AP7361": {"10": 1.0, "12": 1.2, "15": 1.5},     # DS37274: AP7361C-10 1.0 V, -12 1.2 V, -15 1.5 V
    "LM2678": {"12": 12.0},                          # SNVS029L p1: 3.3 V, 5 V and 12 V fixed output and adjustable
    "LM2676": {"12": 12.0},                          # SNVS031N p1: 3.3 V, 5 V, 12 V fixed output and adjustable
    "LM2575": {"12": 12.0, "15": 15.0},              # SNVS106E p1 (LM2575/LM2575HV): 3.3 V, 5 V, 12 V, 15 V and adjustable
    "LM1085": {"12": 12.0},                          # SNVS038H p1: 3.3 V, 5.0 V, 12 V and adjustable
    "LM340": {"12": 12.0, "15": 15.0},               # SNOSBT0L p1: fixed 5 V, 12 V and 15 V options
}
# Fixed-output members of families whose adjustable members have a Vref key (part-number prefix -> Vout).
_FIXED_OUTPUT_PARTS: dict[str, float] = {
    "TPS61024": 3.0, "TPS61025": 3.3, "TPS61026": 5.0, "TPS61027": 5.0,  # SLVS451G p3 ordering table
    "TPS61031": 3.3, "TPS61032": 5.0,                                    # SLUS534G p3 device comparison table
    "LMR36506MSC5": 5.0, "LMR36506MSC3": 3.3,                            # LMR36506-Q1 SNVSB91C p3 device comparison table
    "LMR50410Y3": 3.3, "LMR50410Y5": 5.0,                                # LMR50410-Q1 SLUSDW4A p3 device comparison table
}
# SPX1117M3-L-<volts with the point written as a dash>/TR: -1-5, -1-8, -2-5, -3-3, -5-0 (MaxLinear
# SPX1117 Rev. 2.2.0 p3 ordering table); the bare SPX1117M3-L/TR is the adjustable part.
_SPX1117_CODE = re.compile(r"SPX1117[A-Z0-9]*-L-(1-5|1-8|2-5|3-3|5-0)(?!\d)")
# any other -L-<d>-<d> is a fixed part of unknown voltage: it has no adjustable reference either
_SPX1117_FIXED_NAME = re.compile(r"SPX1117[A-Z0-9]*-L-\d-\d")
# Table keys that name a part only when no digit follows: LM3509 and LM35000 are not LM350.
_WHOLE_NUMBER_KEYS = frozenset({"LM338", "LM350"})
# Analog Devices fixed-output order codes with a one-digit voltage code (part-number prefix -> {code: Vout}):
# LT8607EMSE-5 (LT8607 Rev. D p2), LT8609AEDDM-5 (LT8609 Rev. J p3), LT8610AEMSE-5 / LT8610ABEMSE-5
# (LT8610A/LT8610AB Rev. C p2) are 5 V; LTC3620-1 is 1.1 V (LTC3620 Rev. A p1). LT8640-1 is adjustable.
_ADI_FIXED_CODES: dict[str, dict[str, float]] = {
    "LT8607": {"5": 5.0}, "LT8609A": {"5": 5.0}, "LT8610A": {"5": 5.0}, "LTC3620": {"1": 1.1},
}
_ADI_FIXED_CODE = re.compile("(" + "|".join(_ADI_FIXED_CODES) + r")[A-Z0-9.]*-(\d)(?![\d.])")
# onsemi NCP1117 / NCV1117 / NCP1117LP order codes: ST (SOT-223) or DT (DPAK) and a voltage code
# (NCP1117/D Rev. 31 p12-13 ordering tables; NCP1117LP/D Rev. 6 p1 marking, p12 ordering table).
_NCP1117_CODE = re.compile(r"NC[PV]1117(LP)?(?:ST|DT)(285|\d{2})")
_NCP1117_VOLTS = {"12": 12.0, "15": 1.5, "18": 1.8, "19": 1.9, "20": 2.0, "25": 2.5, "285": 2.85,
                  "33": 3.3, "50": 5.0}
_NCP1117LP_VOLTS = {"15": 1.5, "18": 1.8, "25": 2.5, "33": 3.3, "50": 5.0}
# RECOM R-78 modules: R-78<series><Vout>-<Iout> (R-78E5.0-0.5 is 5 V at 0.5 A). Model Numbering, p1 of
# R-78xx-0.5 REV 6/2023, R-78xx-1.0 REV 5/2023, R-78B-1.5 REV 5/2020, R-78B-2.0 REV 5/2021,
# R-78C-1.0 REV 3/2019, R-78CK-0.5 Rev 1-2025, R-78E-0.5 REV 9/2025, R-78E-1.0 REV 9/2024,
# R-78HB-0.5 REV 5/2019; R-78K-1.0 Rev 6-2025 p2.
_R78_NAME = re.compile(r"R-78[A-Z]{0,2}\d")
_R78_CODE = re.compile(r"R-78(?:CK|HB|[BCEK])?(\d{1,2}(?:\.\d)?)(?![\d.])")


def is_r78_module(value: str, lib_id: str) -> bool:
    """True for a RECOM R-78 module, a switching regulator ("The R-78Cxx-1.0 series switching
    regulators", R-78C-1.0 REV 3/2019 p1; R-78E-0.5 REV 9/2025 p1; R-78xx-0.5 REV 6/2023 p1), named by
    its value or, under a value that names no other part, by its symbol."""
    v = (value or "").upper()
    if _R78_NAME.match(v):
        return True
    return bool(_R78_NAME.match((lib_id or "").split(":")[-1].upper())) and not (
        part_number_core(v) and not is_label_like_value(v))


def _fixed_part_vout(candidates: list[str]) -> float | None:
    """The output voltage a fixed-output part number names (TPS61025, NCP1117ST33T3G, R-78E5.0-0.5),
    or None. A later candidate (the lib_id part name) counts only when the earlier ones name no other
    part and read no voltage themselves: a symbol borrowed for another regulator (TC2117 or LDO_5V0
    on an NCP1117ST33T3G symbol) says nothing."""
    for i, candidate in enumerate(candidates):
        if i and any((part_number_core(c) and not is_label_like_value(c))
                     or _lookup_vref([c])[1] == "fixed_suffix" for c in candidates[:i]):
            return None
        m = _NCP1117_CODE.match(candidate)
        if m:
            return (_NCP1117LP_VOLTS if m.group(1) else _NCP1117_VOLTS).get(m.group(2))
        m = _R78_CODE.match(candidate)
        if m:
            return float(m.group(1))
        m = _SPX1117_CODE.match(candidate)
        if m:
            return float(m.group(1).replace("-", "."))
        m = _ADI_FIXED_CODE.match(candidate)
        if m and m.group(2) in _ADI_FIXED_CODES[m.group(1)]:
            return _ADI_FIXED_CODES[m.group(1)][m.group(2)]
        key = next((k for k in _FIXED_OUTPUT_PARTS if re.match(k + r"(?!\d)", candidate)), None)
        if key is not None:
            return _FIXED_OUTPUT_PARTS[key]
    return None


def fixed_vout_is_explicit(value: str, lib_id: str, mpn: str = "") -> bool:
    """True when the fixed output voltage lookup_regulator_vref reads is written out in the part
    number: -3.3, 3V3, an LM78xx/LM79xx code or a family's data-sheet suffix (LM2596S-12). A bare
    two-digit suffix read as an implied decimal (AP1117-33) is not: the same form is an order or
    reel code on adjustable parts (AP64501SP-13, -13 = 13-inch reel)."""
    candidates, result = _regulator_candidates(value, lib_id, mpn)
    return result[1] == "fixed_suffix" and _lookup_vref(candidates, bare_codes=False) == result


def _lookup_vref(candidates: list[str], bare_codes: bool = True) -> tuple[float | None, str]:
    # LM78xx/LM79xx fixed-output convention: voltage digits embedded without
    # separator. LM7805=5V, LM78L12=12V, LM78M05CT=5V, LM7805_TO220=5V; the
    # LM79xx parts are negative regulators (LM7905=-5V).
    # These families ONLY exist as fixed-output — no adjustable variant.
    for candidate in candidates:
        m = re.match(r'LM7([89])[A-Z]?(\d{2})', candidate)
        if m:
            v = int(m.group(2))
            if v in (5, 6, 8, 9, 10, 12, 15, 18, 24):
                return (-float(v) if m.group(1) == "9" else float(v)), "fixed_suffix"
    fixed_v = _fixed_part_vout(candidates)
    if fixed_v is not None:
        return fixed_v, "fixed_suffix"
    # Check for fixed-output voltage suffix (e.g., AMS1117-3.3, TLV1117LV-33,
    # RT9013-18GV — patterns: -3.3, -33, -3V3, -1V8)
    ambiguous = set()
    for candidate in candidates:
        # an R-78 module's -<Iout> suffix is its current (R-78E5.0-0.5)
        if _R78_NAME.match(candidate):
            continue
        raw = candidate
        candidate = _PACKAGE_TOKEN.sub("", candidate)
        m = re.search(r'[-_](\d+)V(\d+)', candidate)
        if m:
            return float(f"{m.group(1)}.{m.group(2)}"), "fixed_suffix"
        m = re.search(r'[-_](\d+\.\d+)(?:V)?(?=[^0-9]|$)', candidate)
        if m:
            fixed_v = float(m.group(1))
            if 0.5 <= fixed_v <= 60:
                return fixed_v, "fixed_suffix"
        m = re.search(r'[-_](\d{2})(?=[^0-9.]|$)', candidate)
        if m and m.group(1) in _AMBIGUOUS_SUFFIXES:
            family = next((f for f in _FIXED_SUFFIX_FAMILIES if re.match(f + r"(?!\d)", candidate)), None)
            if family and m.group(1) in _FIXED_SUFFIX_FAMILIES[family]:
                return _FIXED_SUFFIX_FAMILIES[family][m.group(1)], "fixed_suffix"
            # A fixed part of unknown voltage has no adjustable Vref either; a
            # suffix after a space is part of a description (LM317 (7-12V)).
            if " " not in candidate[:m.start()]:
                ambiguous.add(raw)
        elif m and bare_codes and m.group(1) != "13":
            # A two-digit suffix is an implied decimal, as in KiCad's library:
            # AP1117-33 is 3.3 V, LDK130-08 is 0.8 V. No fixed part is below
            # 0.5 V, so LC78_03-05 (a 3.3 V module) gives no value. -13 is
            # Diodes Inc.'s 13-inch reel code, not 1.3 V: AP64501SP-13 is the
            # adjustable AP64501 (DS41980 Rev. 5-2, Ordering Information); a
            # voltage code ahead of it is still read (AP7361C-33E-13 is 3.3 V).
            fixed_v = float(m.group(1)[0] + "." + m.group(1)[1])
            if fixed_v >= 0.5:
                return fixed_v, "fixed_suffix"
    for i, candidate in enumerate(candidates):
        if candidate in ambiguous:
            continue
        # a symbol borrowed for another part (TPS54202 on a TPS563200 symbol) says nothing about its Vref
        if i and any(part_number_core(c) and not is_label_like_value(c) for c in candidates[:i]):
            break
        key = _longest_vref_key(candidate)
        if key is not None:
            return _REGULATOR_VREF[key], "lookup"
    return None, ""


def _longest_vref_key(candidate: str) -> str | None:
    """The longest _REGULATOR_VREF prefix of *candidate*, or None."""
    best = None
    for prefix in _REGULATOR_VREF:
        if candidate.startswith(prefix.upper()) and len(prefix) > len(best or ""):
            if prefix == "SPX1117" and _SPX1117_FIXED_NAME.match(candidate):
                continue
            if prefix in _WHOLE_NUMBER_KEYS and candidate[len(prefix):len(prefix) + 1].isdigit():
                continue
            best = prefix
    return best


def part_number_core(part: str) -> str:
    """The part number without suffix letters, package or option codes:
    'TPS61023DRLR' -> 'TPS61023', 'LM2596S-ADJ' -> 'LM2596',
    'TPS7A4901DGNR' -> 'TPS7A4901'; '' when it does not start with one."""
    m = re.match(r"[A-Z]+\d+(?:[A-Z]\d+)*", part.upper())
    return m.group(0) if m else ""


# function words a designer writes in a Value field as a label ('LDO1', 'BUCK5V', 'U3V3')
_LABEL_WORDS = ("LDO", "BUCK", "BOOST", "DCDC", "PSU", "SMPS", "U")


def is_label_like_value(value: str) -> bool:
    """True when a Value reads as a label rather than a part number: it holds a
    space or '/' ('DCDC24V/5V NUM'), or its part-number core is a function word
    plus digits ('LDO1', 'BUCK5V', 'U3V3'). 'TPS61023DRLR', 'LM338_TO220' -> False."""
    v = (value or "").strip().upper()
    if not v:
        return False
    if re.search(r"[\s/]", v):
        return True
    m = re.match(r"([A-Z]+)\d", part_number_core(v))
    return bool(m) and m.group(1) in _LABEL_WORDS


# A key that is itself a fixed-output part name (LD33 is a 3.3 V part) names no part's Vref.
_FIXED_PART_KEYS = frozenset({"LD33"})
# Keys whose order codes carry an X option letter (TPS560430XDBVR; LM2731XMF and LM27313XMF,
# SNVS217G / SNVS487E ordering tables; LMR51606X / LMR51610X, the 400 kHz option, SLUSEY1B §4
# p3): there an X after the key is part of the part number, elsewhere it is a family wildcard
# (LM259X).
_X_OPTION_KEYS = frozenset({"TPS560430", "LM2731", "LM27313", "LMR51606", "LMR51610"})


def vref_key_covers_part(key: str, part: str) -> bool:
    """True when a _REGULATOR_VREF key names the whole part number of *part*
    (its value for that part), not a shorter family prefix: 'TPS61023' covers
    TPS61023DRLR, 'LMR336' does not cover LMR33630. A fixed-voltage code after
    the key (NCP1117ST33T3G, LD1117AV33) names another part, and a wildcard X
    (LM259X) names none."""
    core = part_number_core(part)
    if not (core and part.upper().startswith(key.upper()) and len(key) >= len(core)):
        return False
    if key.upper() in _FIXED_PART_KEYS:
        return False
    if key.upper() not in _X_OPTION_KEYS and re.match(r"[Xx]{1,2}(?![A-Za-z0-9])", part[len(key):]):
        return False
    return not re.match(r"[A-Za-z]{1,2}\d{2}(?!\d)", part[len(key):])


def regulator_vref_key(value: str, lib_id: str, mpn: str = "") -> tuple[str, str] | None:
    """(key, part): the _REGULATOR_VREF key that lookup_regulator_vref takes a
    "lookup" Vref from and the value, lib_id part name or MPN it matched (same
    candidate order), or None when the Vref is not a table hit."""
    candidates, (vref, source) = _regulator_candidates(value, lib_id, mpn)
    if source != "lookup":
        return None
    return next((k, c) for c in candidates if (k := _longest_vref_key(c)) is not None)


# ---------------------------------------------------------------------------
# Switching frequency lookup table — single source of truth for both
# signal_detectors.py and emc_rules.py.
# Sources: DigiKey parametric data + manufacturer datasheets (verified 2026-04-12).
# ~100 entries: 8 broad collision prefixes replaced with per-sub-family entries.
# ---------------------------------------------------------------------------
_KNOWN_FREQS = {
    # --- TPS54 family (was single 'TPS54': 570e3, now split per DigiKey) ---
    'TPS54331': 570e3,     # TPS54331/54531: 570kHz
    'TPS54531': 570e3,
    'TPS5430': 500e3,      # TPS5430: 500kHz (note: overlaps TPS54302 below)
    'TPS54302': 400e3,     # TPS54302: 400kHz
    'TPS54308': 350e3,     # TPS54308: 350kHz
    'TPS54202': 500e3,     # TPS54202: 500kHz
    'TPS5410': 500e3,      # TPS5410: 500kHz
    'TPS5450': 500e3,      # TPS5450: 500kHz
    'TPS5405': 500e3,      # TPS5405: 500kHz
    'TPS54560': 500e3,     # TPS54560: 500kHz
    'TPS54226': 700e3,     # TPS54226: 700kHz
    'TPS54294': 700e3,     # TPS54294: 700kHz
    'TPS54227': 700e3,     # TPS54227: 700kHz
    'TPS542951': 700e3,    # TPS542951: 700kHz
    'TPS54527': 650e3,     # TPS54527: 650kHz
    'TPS546D': 550e3,      # TPS546D24S: 550kHz
    # --- TPS62 family (was single 'TPS62': 2.5e6, now split) ---
    'TPS62130': 2.5e6,     # TPS62130/33/40 family: 2.5MHz
    'TPS62140': 2.5e6,
    'TPS62133': 2.5e6,
    'TPS62150': 2.5e6,
    'TPS6216': 2.25e6,     # TPS62160/61/62/63: 2.25MHz typ (differs from TPS62130/140/150 family at 2.5MHz)
    'TPS62203': 1.0e6,     # TPS62203/77: 1MHz
    'TPS62175': 1.0e6,
    'TPS62177': 1.0e6,
    'TPS62840': 1.8e6,     # TPS62840/42: 1.8MHz
    'TPS62842': 1.8e6,
    'TPS62823': 2.2e6,     # TPS6282x: 2.2MHz
    'TPS62826': 2.2e6,
    'TPS62824': 2.2e6,
    'TPS62827': 2.2e6,
    'TPS62410': 2.25e6,    # TPS62410/290/170 family: 2.25MHz
    'TPS62290': 2.25e6,
    'TPS62170': 2.25e6,
    'TPS62A01': 2.4e6,     # TPS62A01/A02: 2.4MHz
    'TPS62A02': 2.4e6,
    'TPS62065': 3.0e6,     # TPS62065: 3MHz
    'TPS62088': 4.0e6,     # TPS62088: 4MHz
    'TPS62237': 2.0e6,     # TPS62237: 2MHz
    # --- TPS61 family (was single 'TPS61': 1.0e6, now split) ---
    'TPS61023': 1.0e6,     # TPS61023: 1MHz
    'TPS61235': 1.0e6,     # TPS61235: 1MHz
    'TPS61090': 600e3,     # TPS61090/030/032: 600kHz
    'TPS61030': 600e3,
    'TPS61032': 600e3,
    'TPS61070': 1.2e6,     # TPS61070/170: 1.2MHz
    'TPS61170': 1.2e6,
    'TPS61021': 2.0e6,     # TPS61021A: 2MHz
    'TPS61230': 2.0e6,     # TPS61230: 2MHz
    'TPS61253': 3.5e6,     # TPS61253: 3.5MHz
    'TPS61240': 3.5e6,     # TPS61240: 3.5MHz
    'TPS61288': 500e3,     # TPS61288: 500kHz
    'TPS61391': 700e3,     # TPS61391: 700kHz
    # --- TPS56 family (was single 'TPS56': 500e3, now split) ---
    'TPS56339': 500e3,     # TPS56339/637: 500kHz
    'TPS56637': 500e3,
    'TPS563300': 500e3,    # TPS563300: 500kHz
    'TPS565208': 500e3,    # TPS565208/201: 500kHz
    'TPS565201': 500e3,
    'TPS562201': 580e3,    # TPS562201/563201/563202/562208: 580kHz
    'TPS563201': 580e3,
    'TPS563202': 580e3,
    'TPS562208': 580e3,
    'TPS566238': 600e3,    # TPS566238: 600kHz
    'TPS560200': 600e3,    # TPS560200: 600kHz
    'TPS565242': 600e3,    # TPS565242: 600kHz
    'TPS563200': 650e3,    # TPS563200: 650kHz
    'TPS562200': 650e3,    # TPS562200: 650kHz
    'TPS560430': 1.1e6,    # TPS560430: 1.1MHz
    'TPS562212': 1.2e6,    # TPS562212: 1.2MHz
    'TPS564247': 1.2e6,    # TPS564247: 1.2MHz
    'TPS564208': 560e3,    # TPS564208: 560kHz
    'TPS561243': 1.28e6,   # TPS561243: 1.28MHz
    'TPS563240': 1.4e6,    # TPS563240: 1.4MHz
    # --- TPS63 family (was single 'TPS63': 2.4e6, now split) ---
    'TPS63020': 2.4e6,     # TPS63020/070/etc: 2.4MHz
    'TPS63070': 2.4e6,
    'TPS63060': 2.4e6,
    'TPS6300': 1.5e6,      # TPS63000/01/02: 1.5MHz max (differs from TPS63020/60/70 family at 2.4MHz)
    'TPS63802': 2.1e6,     # TPS63802: 2.1MHz
    'TPS631000': 2.0e6,    # TPS631000/011: 2MHz
    'TPS631011': 2.0e6,
    'TPS630250': 2.5e6,    # TPS630250: 2.5MHz
    # --- TPS629 family (was single 'TPS629': 2.2e6, now split) ---
    'TPS62912': 2.2e6,     # TPS62912: 2.2MHz
    'TPS62913': 2.2e6,     # TPS62913: dual 1/2.2MHz, use typical
    'TPS629203': 2.5e6,    # TPS629203: 2.5MHz
    'TPS629206': 2.5e6,    # TPS629206: 2.5MHz
    'TPS629210': 2.5e6,    # TPS629210: 2.5MHz
    'TPS62932': 2.2e6,     # TPS62932/33: adjustable 200k-2.2MHz, use typical
    'TPS62933': 2.2e6,
    # --- ADP2 family (was single 'ADP2': 700e3, now split) ---
    'ADP2302': 700e3,      # ADP2302/03: 700kHz
    'ADP2303': 700e3,
    'ADP2301': 1.4e6,      # ADP2301: 1.4MHz
    'ADP2503': 2.5e6,      # ADP2503: 2.5MHz
    # --- LTC36 family (was single 'LTC36': 1.0e6, now split) ---
    'LTC3600': 1.0e6,      # LTC3600: 1MHz typ
    'LTC3601': 2.0e6,      # LTC3601: 2MHz
    # LTC3631/3632/3638/3642: DigiKey returned no freq param — keep unmatched
    # --- Clean families (no collisions, kept as-is) ---
    'LM259': 150e3,    # LM2596/2594: 150kHz (verified clean)
    'LM257': 52e3,     # LM2575/2576: 52kHz (verified clean)
    'MP2307': 340e3,   # MP2307: 340kHz
    'MP1584': 1.5e6,   # MP1584: 1.5MHz
    'MP2359': 1.4e6,   # MP2359: 1.4MHz
    'AP3012': 1.5e6,   # AP3012: 1.5MHz
    'RT8059': 1.5e6,   # RT8059: 1.5MHz
    'SY8208': 800e3,   # SY8208: 800kHz (prefix narrowed from 'SY820' to avoid matching SY8200 family at 500kHz)
    'MCP1640': 500e3,  # MCP1640: 500kHz
    'MCP1603': 2.0e6,  # MCP1603: 2MHz
    'XL6009': 400e3,   # XL6009: 400kHz
    'XL4015': 180e3,   # XL4015: 180kHz
    'MT3608': 1.2e6,   # MT3608: 1.2MHz
    'LM2675': 260e3,   # "LM2675 SIMPLE SWITCHER Power Converter" SNVS129G p7, Electrical Characteristics: fO 260kHz typ
    'MIC23050': 4.0e6, # "MIC23050 4MHz PWM Buck Regulator" M9999-092211-E p3, Electrical Characteristics: 4MHz typ
}

# Keys that name one part rather than a family prefix: a digit after the key (LM26750,
# MIC230500) makes it another part number.
_SINGLE_PART_FREQ_KEYS = frozenset({'LM2675', 'MIC23050'})


def _starts_with_freq_key(text: str, key: str) -> bool:
    """True when upper-case ``text`` starts with ``key`` (a ``_KNOWN_FREQS`` key)."""
    if not text.startswith(key):
        return False
    return key not in _SINGLE_PART_FREQ_KEYS or not text[len(key):len(key) + 1].isdigit()


def lookup_switching_freq(part_value: str) -> float | None:
    """Look up switching frequency from known regulator part numbers.

    Uses longest-prefix-first matching via startswith to avoid substring
    false positives. Returns frequency in Hz or None if unknown.
    """
    if not part_value:
        return None
    val = part_value.upper()
    # Sort prefixes longest-first so 'TPS54331' matches before 'TPS54'
    for prefix in sorted(_KNOWN_FREQS, key=len, reverse=True):
        if _starts_with_freq_key(val, prefix.upper()):
            return _KNOWN_FREQS[prefix]
    return None


def default_switching_freq(topology: str) -> float | None:
    """Fallback switching frequency estimate when part is unrecognized.

    Based on typical ranges for each topology. Conservative (low end)
    to avoid underestimating harmonic reach.
    """
    defaults = {
        'buck': 500e3,
        'boost': 500e3,
        'buck-boost': 300e3,
        'inverting': 300e3,
        'sepic': 300e3,
    }
    return defaults.get(topology.lower()) if topology else None


def match_known_switching(value: str, lib_id: str) -> bool:
    """Check if a part matches the known switching regulator table."""
    val_upper = value.upper()
    lib_part = lib_id.split(":")[-1].upper() if ":" in lib_id else ""
    for prefix in _KNOWN_FREQS:
        pu = prefix.upper()
        if _starts_with_freq_key(val_upper, pu) or _starts_with_freq_key(lib_part, pu):
            return True
    return False


# ---------------------------------------------------------------------------
# ESR/ESL lookup by package size (typical MLCC values)
# ---------------------------------------------------------------------------

# Typical ESL values for MLCC by package (Henries)
MLCC_ESL = {
    '0201': 0.3e-9,
    '0402': 0.5e-9,
    '0603': 0.7e-9,
    '0805': 0.9e-9,
    '1206': 1.1e-9,
    '1210': 1.2e-9,
    '1812': 1.5e-9,
    '2220': 1.8e-9,
}

# Typical ESR values for MLCC by package (Ohms) — X5R/X7R at 1 MHz
MLCC_ESR = {
    '0201': 0.5,
    '0402': 0.3,
    '0603': 0.1,
    '0805': 0.05,
    '1206': 0.03,
    '1210': 0.02,
    '1812': 0.02,
    '2220': 0.015,
}


# LED forward voltage by colour word in the value or the symbol name: (nominal V, floor V).
# Nominal is the datasheet typical at the rated current; floor is the lowest datasheet
# minimum sampled, below which the LED does not light (None: no floor check).
# Sources: Wurth 150060/150080, Kingbright APT2012, Lite-On LTST-C170/C190/C191/C193,
# Vishay VLMO1300/VLMTG1500, Broadcom HSMW-C170, Cree CLV1A-FKB, SunLED XZM2, OSRAM LY P47F.
# A bare "green" is two technologies (GaP/AlInGaP about 2.1 V, InGaN about 3.2 V): the
# nominal is the InGaN part most current green LEDs are, the floor the GaP minimum.
LED_VF_BY_COLOR: dict[str, tuple[float, float | None]] = {
    "red": (2.0, 1.5), "orange": (2.0, 1.8), "yellow": (2.1, 2.0), "amber": (2.0, 1.8),
    "green": (3.2, 2.1), "blue": (3.2, 2.5), "white": (3.2, 2.7), "uv": (3.5, 3.2),
    "ir": (1.2, None),
}
LED_VF_DEFAULT = 2.0
# "ir" where a word starts ("LED_IR", "IR204A", "XYC-IRA3212", "IRL81A"), not inside "wiring"
# or "kira", nor "IRQ" (interrupt indicator) or "IRNAS" (vendor name); searched in the value
# and the lib_id's symbol name, not its library nickname.
_LED_IR_WORD = re.compile(r"(?<![a-z])ir(?!q|nas)")


# Words of a value or symbol name: split at separators, digits and CamelCase ("BlueLED",
# "PCAmber", "warmWhite", "LED_Red_0805").
_WORD_TOKEN = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")
_LED_COLOR_ALIAS = {"infrared": "ir", "ultraviolet": "uv"}


def _led_color_words(text: str) -> set[str]:
    """Colour candidates of *text*; a word may carry an "LED" prefix or suffix ("LEDRED", "redled")."""
    words = set()
    for word in _WORD_TOKEN.findall(text):
        word = word.lower()
        if word != "led":
            if word.startswith("led"):
                word = word[3:]
            elif word.endswith("led"):
                word = word[:-3]
        words.add(_LED_COLOR_ALIAS.get(word, word))
    return words


def led_color(comp: dict) -> str | None:
    """First colour of LED_VF_BY_COLOR named by the LED's value, else its symbol name, or None.

    Colours are whole words, so "mirrored" is not red; the library nickname is not searched."""
    for text in (comp.get("value", ""), comp.get("lib_id", "").rpartition(":")[2]):
        words = _led_color_words(text)
        for color in LED_VF_BY_COLOR:
            if color in words or (color == "ir" and _LED_IR_WORD.search(text.lower())):
                return color
    return None


# P-channel MOSFETs a schematic may name only by part number. Every entry is a P-channel
# part in KiCad's Transistor_FET library or in its maker's datasheet (cited in
# tools/tests/test_pchannel_parts.py). Families mix the two channels (AO3400 N / AO3401 P,
# DMG2302 N / DMG2305 P, Si2302 N / Si2301 P), so an entry is a whole part number, never a
# family prefix; it may carry up to six ordering letters (A, UX, PBF, TRPBF) before a
# separator or the end.
_PCHANNEL_FET_PARTS = (
    # KiCad Transistor_FET library
    "AO3401", "AON6411", "BS250", "BSS83P", "BSS84", "CSD25302Q2", "CSD25402Q3A", "CSD25480F3",
    "DMG2301L", "DMP3013SFV", "DMP3099L", "DMP6050SSD", "FDN340P", "FDS9435A", "FQP27P06",
    "IRF4905", "IRF7324", "IRF7404", "IRF7606", "IRF9383M", "IRF9394M", "IRF9395M", "IRF9540N",
    "IRFTS9342", "IRLML5203", "IRLML6401", "IRLML6402", "IRLML9301", "NTR2101P", "PMN48XP",
    "QM6015D", "SI2319CDS", "SI2371EDS", "SI7141DP", "SI7617DN", "SIA449DJ", "SIA453EDJ",
    "SIS415DNT", "SIS443DN", "SISS27DN", "SQJQ131EL", "SUD08P06-155L", "SUD09P10-195",
    "SUD19P06-60", "SUD45P03-09", "SUD50P04-08", "SUD50P06-15", "SUD50P08-25L", "SUD50P10-43L",
    "TP0610", "TSM2301ACX", "VP0610", "ZXMP4A16G",
    # maker datasheets
    "AO3407", "AO3415", "AO3423", "AO4407A", "DMG2305UX", "FDN302P", "FDN360P", "FDS6673BZ",
    "FDV304P", "FQD5P20", "FQU5P20", "IRF5305", "IRFR5305", "IRFU5305", "IRLML2244", "NDT456P",
    "NTD25P03L", "NTR4171P", "SI2301CDS",
)
_PCHANNEL_FET_RE = re.compile(
    "(?:" + "|".join(re.escape(p) for p in sorted(_PCHANNEL_FET_PARTS, key=len, reverse=True))
    + r")[A-Z]{0,6}(?![A-Z0-9])")


def names_pchannel_fet(*names: str) -> bool:
    """True when a value, MPN or library symbol name starts with a known P-channel part number."""
    return any(_PCHANNEL_FET_RE.match((n or "").strip().upper()) for n in names)


# NPN bipolar transistors, each described as NPN in KiCad's Transistor_BJT library (cited in
# tools/tests/test_led_driver_pullup.py). A whole part number is not followed by another
# digit, nor by "BP" (the BC846BPN / BC847BPN complementary pairs).
_NPN_BJT_PARTS = (
    "2N2219", "2N3055", "2N3904", "2SC1815", "BC107", "BC108", "BC109", "BC237", "BC337",
    "BC338", "BC546", "BC547", "BC548", "BC549", "BC550", "BC817", "BC818", "BC846", "BC847",
    "BC848", "BC849", "BC850", "BCP56", "BCX56", "BD433", "BD435", "BD437", "BD441", "DTC114E",
    "DTC143Z", "DTC144E", "MJE13003", "MMBT2222", "MMBT3904", "MMBT5550", "MMBT5551", "MMBTA06",
    "MMBTA42", "MPSA42", "PMBT2222", "PN2222", "PZT2222", "PZT3904", "S8050", "SS8050",
    "TIP120", "TIP121", "TIP122", "TIP3055", "TIP41",
)
_NPN_BJT_RE = re.compile(
    "(?:" + "|".join(re.escape(p) for p in sorted(_NPN_BJT_PARTS, key=len, reverse=True))
    + r")(?![0-9])(?!BP)")


def names_npn_bjt(*names: str) -> bool:
    """True when a value, MPN or library symbol name starts with a known NPN part number."""
    return any(_NPN_BJT_RE.match((n or "").strip().upper()) for n in names)


# Current-sense amplifiers a schematic names by part number, matched where a part number
# starts (each family is cited in tools/tests/test_sense_amp_names.py). TI's INA bases
# INA138/139, INA168-170, INA18x-19x, INA2xx, INA30x-31x and INA38x are current-sense
# amplifiers and current/power monitors, bar the INA188 and INA217 instrumentation amps; a
# leading 2/3/4 is the dual/triple/quad of the same base (INA2180, INA3221, INA4181). The
# other INA bases (INA128, INA333, INA82x) are instrumentation or difference amplifiers, or
# monitors with an integrated shunt (INA7xx) that no external shunt reaches. Its digits
# keep INA out of words ("Trinamic"), so a letter may precede it (ModuleINA3221). Then
# Allegro ACS7xx Hall sensors, AD8210/17/18, MAX9938, MAX4080/81, MAX471, LTC6101-03,
# LTC4151 and Diodes ZXCT monitors; a whole part number is not followed by another digit
# (MAX4714 is an analog switch).
_SENSE_AMP_PN = re.compile(
    r"(?<![0-9])ina(?:[234](?=\d{3}(?!\d)))?(?!188|217)(?:1(?:3[89]|6[89]|70|[89]\d)|2\d\d|3(?:[01]\d|8\d))(?!\d)"
    r"|(?<![a-z0-9])(?:"
    r"(?:ad821[078]|max9938|max408[01]|max471|ltc610[123]|ltc4151)(?!\d)"
    r"|acs7|zxct"
    r")")


def names_sense_amp(*names: str) -> bool:
    """True when a value, MPN or library symbol name is a current-sense amplifier part number."""
    return any(_SENSE_AMP_PN.search((n or "").lower()) for n in names)


# Instrumentation amplifiers a schematic names by part number, matched where a part number
# starts (each family is cited in tools/tests/test_instrumentation_amps.py): AD620-AD625 and
# AD627 (the AD626 is a difference amp), AD8220-AD8229, AD8230-AD8233 and AD8235-AD8237
# (AD8232/AD8233 are ECG front ends built on one), AD8250/51/53, AD8293/95,
# AD8420/21/22/26/28/29, AD8553 (the AD8551/52/54 are op amps); TI INA101/103, INA110/111,
# INA114-116, INA118 (the INA117 is a difference amp), INA121/122, INA125/126, INA128/129,
# INA163/166, INA188, INA217, INA321/322, INA326/327, INA331-333, INA350/351, INA818/819,
# INA821, INA823, INA826-828, INA848/849, INA851, a leading 2 being the dual (INA2128);
# LT1101/02, LT1167/68, LT1789, LTC1100, LTC2053, LTC6800, LTC6915; MAX4194-97, MAX4208/09,
# MAX4460-62; PGA204-207, PGA280/281. A whole part number is not followed by another digit.
_INAMP_PN = re.compile(
    r"(?<![a-z0-9])(?:"
    r"ad62[0-57]|ad822\d|ad823[0-35-7]|ad825[013]|ad829[35]|ad842[012689]|ad8553"
    r"|ina2?(?:10[13]|11[014-68]|12[125689]|16[36]|188|217|32[1267]|33[1-3]|35[01]"
    r"|8(?:1[89]|2[136-8]|4[89]|51))"
    r"|lt110[12]|lt116[78]|lt1789|ltc1100|ltc2053|ltc6800|ltc6915"
    r"|max419[4-7]|max420[89]|max446[0-2]|pga20[4-7]|pga28[01]"
    r")(?!\d)")
# KiCad's own descriptions spell it "Instumentation" on some symbols.
_INAMP_WORDS = re.compile(r"\binstr?umentation amp|\bin-amp\b")


def is_instrumentation_amp(*names: str, library: str = "", description: str = "",
                           pin_names: Iterable[str] = ()) -> bool:
    """True for an instrumentation amplifier: from KiCad's Amplifier_Instrumentation library
    (``library`` is the lib_id's nickname), described as one, named by a known part number in
    a value, MPN or library symbol name, or with a pair of gain-resistor (RG) pins. Its gain
    is set by RG, not by op-amp feedback."""
    if (library or "").lower() == "amplifier_instrumentation":
        return True
    if _INAMP_WORDS.search((description or "").lower()):
        return True
    if any(_INAMP_PN.search((n or "").lower()) for n in names):
        return True
    rg = [n for n in pin_names
          if re.sub(r"[^a-z0-9]", "", (n or "").lower()) in ("rg", "rg1", "rg2", "rgp", "rgn")]
    return len(rg) >= 2
