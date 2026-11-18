"""Value parsing, E-series and coordinate units (kicad_core)."""
import math
import re


# Legacy .sch files use integer mils (1/1000 inch).  The conversion pipeline
# (mil * 0.0254 → round(4) → rotate via trig → round(4)) accumulates
# floating-point error that can move a point off its exact coordinate.  Snapping back to the
# nearest mil grid after all transforms eliminates the drift.
_MIL_MM = 0.0254  # 1 mil in mm

def snap_to_mil_grid(x_mm: float) -> float:
    """Snap a mm coordinate to the nearest mil grid point."""
    return round(x_mm / _MIL_MM) * _MIL_MM


def format_frequency(hz: float) -> str:
    """Format a frequency in Hz to a human-readable string with SI prefix."""
    if hz >= 1e9:
        return f"{hz / 1e9:.2f} GHz"
    elif hz >= 1e6:
        return f"{hz / 1e6:.2f} MHz"
    elif hz >= 1e3:
        return f"{hz / 1e3:.2f} kHz"
    else:
        return f"{hz:.2f} Hz"


# KiCad's simulator maps both micro signs to "u" and accepts five ohm signs as the unit
# (sim_model.cpp value inference).
_MICRO_SIGNS = str.maketrans({"\u00b5": "u", "\u03bc": "u"})
_OHM_SIGNS = str.maketrans({c: "\u03a9" for c in "\u2126\U0001d6c0\U0001d6fa\U0001d76e"})
_IMPEDANCE_SLASH = re.compile(
    r"\s*[0-9][0-9.,]*\s*(?:[RrZΩ]|[Oo][Hh][Mm][Ss]?)\s*/\s*[0-9][0-9.,]*\s*"
    r"(?:[mu]?A(?:[0-9]+)?|[kMG]?[Hh][Zz])(?![A-Za-z])")
_LOW_OHM_RATED = re.compile(
    r"\s*(?:0*[.,][0-9]+|0+)\s*(?:[RrΩ]|[Oo][Hh][Mm][Ss]?)\s*/\s*[0-9][0-9.,]*\s*[mu]?A(?![A-Za-z])")
_IMPEDANCE_AT = re.compile(r"[0-9]\s*(?:[RrΩ]|[Oo][Hh][Mm][Ss]?)\s*@\s*[0-9][0-9.,]*\s*[kKMG]?[Hh][Zz]")
# A resistor with its current rating ("1R/2A", "10R/0.5A") is a resistance, not ferrite notation.
_RESISTOR_RATED = re.compile(
    r"\s*[0-9][0-9.,]*\s*(?:[RrΩ]|[Oo][Hh][Mm][Ss]?)\s*/\s*[0-9][0-9.,]*\s*[mu]?A(?![A-Za-z])")
# A 3-digit mantissa group that ends the value with an SI prefix or a unit ("1 000k", "4 700R").
# V, A and W stay out: "47 100V" and "100 750mW" are a value and a rating.
_LAST_GROUP = re.compile(r"\d{3}(?:[.,]\d+)?(?:[pnumkKMGRr]?(?:[FHΩ]|[Oo]hms?)?)")
# A resistor, capacitor or inductor value followed by a comma and more fields with no space
# ("100nF,50V", "10k,1%"): the value needs a prefix or unit letter and at most one separator,
# so "1,000", "50V,10uF" and "0603,68nF" are left alone. Untyped, "20pF,16MHz" stays None so
# a crystal's frequency is still found.
_VALUE_THEN_FIELDS = re.compile(
    r"([+-]?(?:[0-9]{1,3}(?:[.,][0-9]+)?|[0-9]+(?:\.[0-9]+)?|[.,][0-9]+)"
    r"(?:[pnumkKMGRrNUP][0-9]*(?:[FHΩ]|[Oo]hms?)?|[FHΩ]|[Oo]hms?)),")
# Uppercase N, U and P read as nano, micro and pico on a capacitor ("100N", "4U7", "22P") and
# N and U on an inductor ("2U2"); on other parts "1N4148" or "50N06" is a part number. At most
# two digits may follow the letter, so "1N4148" stays a part number even on a capacitor.
# KiCad reads P as peta; no capacitor is petafarads.
_UPPER_PREFIX = re.compile(r"([0-9.]*[0-9])([NUP])([0-9]{0,2})")
_UPPER_PREFIX_TYPES = {"capacitor": "NUP", "inductor": "NU"}
# A capacitance with its voltage rating glued on ("1n50V", "220u25V", "10U16V"): the two or
# more digits after the prefix letter are the rating.
_GLUED_RATING = re.compile(r"([0-9.]*[0-9])([pnuNUP])([0-9]{2,})")
# A value written the way KiCad's library symbols are named: the type letter, then the value,
# then package or rating fields ("R_5k1_0402", "R-5k1-0402", "R5k1", "C_100n_0402"), or a value
# with package fields and no letter ("10k_0603"). The value field needs a prefix or unit letter,
# so a package code ("R_0603") or a plain number ("R_100") is not read as a value.
_TYPE_LETTER = {"resistor": "R", "capacitor": "C", "inductor": "L"}
_FIELD_VALUE = {
    "resistor": re.compile(r"[0-9]+(?:\.[0-9]+)?(?:[kKMmR][0-9]*R?|Ω|[Oo]hms?)(?:Ω|[Oo]hms?)?"),
    "capacitor": re.compile(r"[0-9]+(?:\.[0-9]+)?(?:[pnuNUP][0-9]*F?|F)"),
    "inductor": re.compile(r"[0-9]+(?:\.[0-9]+)?(?:[pnumNU][0-9]*H?|H)"),
}
# "10kR", "4k7R", "100mR": an SI prefix followed by R for ohms.
_PREFIX_THEN_R = re.compile(r"([0-9.]*[0-9][kKmMG][0-9]*)[Rr]")
_MANTISSA = re.compile(r"[+-]?[0-9][0-9.,]*|[+-]?[.,][0-9][0-9.,]*")


class AmbiguousValueSeparator(ValueError):
    """A value whose only separator is a comma that may be a decimal mark or a thousands separator."""


def _convert_separators(mantissa: str) -> str | None:
    """Return *mantissa* with '.' as the decimal mark, inferring the separators as KiCad does
    (sim_model.cpp convertSeparators): scanning right to left, a first separator at the start,
    after a lone leading 0 or followed by other than three digits is decimal; a repeated one is
    thousands. Returns None for an invalid mantissa. Where KiCad would fall back to its default,
    a lone '.' stays decimal and a lone ',' raises AmbiguousValueSeparator ('1,000')."""
    ambiguous = thousands = decimal = None
    thousands_found = decimal_found = False
    digits = 0
    for ii in range(len(mantissa) - 1, -1, -1):
        c = mantissa[ii]
        if c.isdigit():
            digits += 1
            continue
        if c not in ".,":
            digits = 0
            continue
        if decimal or thousands:
            if c == decimal:
                if thousands_found or decimal_found:
                    return None
                decimal_found = True
            elif digits != 3:
                return None
            else:
                thousands_found = True
        elif ambiguous:
            if c == ambiguous:
                thousands, thousands_found = c, True
                decimal = "," if c == "." else "."
            else:
                decimal, decimal_found = ambiguous, True
                thousands, thousands_found = c, True
        elif ii == 0 or (ii == 1 and mantissa[0] in "0+-") or digits != 3:
            decimal, decimal_found = c, True
            thousands = "," if c == "." else "."
        else:
            ambiguous = c
        digits = 0
    if not decimal and not thousands:
        if ambiguous == ",":
            raise AmbiguousValueSeparator(
                f"{mantissa!r}: ',' may be a decimal mark or a thousands separator")
        return mantissa
    return mantissa.replace(thousands, "").replace(decimal, ".")


def parse_value(value_str: str, component_type: str | None = None) -> float | None:
    """Parse an engineering-notation component value to a float.

    Handles: 10K, 4.7u, 100n, 220p, 1M, 2.2m, 47R, 0R1, 4K7, 1R0, 1Meg, 4,7k,
    10 μF, 4.7kΩ, etc. Returns None if unparseable, including a value whose only
    separator is an ambiguous comma ("1,000"; see ``ambiguous_separator``).

    If component_type is "capacitor" and the result is a bare plain number
    (no unit letter, no exponent), treat it as picofarads when >= 1.0 and as
    microfarads below (legacy KiCad 5 convention). An explicit F ("1F") or an
    exponent ("1e-6") is already in farads. A lowercase f is femto when a unit
    follows ("10fF") or the part is typed and not a capacitor. Uppercase N/U/P
    are nano/micro/pico on a capacitor and N/U on an inductor ("100N", "4U7").
    A typed resistor, capacitor or inductor written like a library symbol name
    reads its value field ("R_5k1_0402", "C_100n_0402", "10k_0603"); an SI prefix
    followed by R is ohms ("10kR", "100mR") on any part but a capacitor or inductor.
    """
    try:
        return _parse_value(value_str, component_type)
    except AmbiguousValueSeparator:
        return None


def ambiguous_separator(value_str: str) -> bool:
    """True when *value_str* is unparsed only because its separator is ambiguous."""
    try:
        _parse_value(value_str, None)
    except AmbiguousValueSeparator:
        return True
    return False


def _symbol_field_value(value: str, component_type: str | None) -> str:
    """The value field of a symbol-style value ("R_5k1_0402" -> "5k1"), else *value*."""
    letter = _TYPE_LETTER.get(component_type)
    if not letter:
        return value
    glued = False
    sep, body = "_", value
    if len(value) > 1 and value[0] == letter:
        if value[1] in "_-":
            sep, body = value[1], value[2:]
        else:
            glued, body = True, value[1:]
    elif "_" not in value:
        return value
    field = body.split(sep)[0]
    if not _FIELD_VALUE[component_type].fullmatch(field):
        return value
    # Without a separator the letter may be the decimal mark of a European value ("R330" is
    # 0.33 ohm), so "R5k1" needs an SI prefix after the letter.
    if glued and not re.search(r"[kKMmpnuNUP]", field):
        return value
    return field


def _parse_value(value_str: str, component_type: str | None) -> float | None:
    # EQ-068: SI prefix: p=1e-12 n=1e-9 u=1e-6 m=1e-3 k=1e3 M=1e6
    if not value_str:
        return None
    value_str = value_str.translate(_MICRO_SIGNS).translate(_OHM_SIGNS)
    # A ferrite's impedance with its test frequency or rated current ("600R/200mA",
    # "220Ω/100MHz") is not a resistance: None, like "120R@100MHz" below. A link or shunt
    # below 1 ohm with its current rating ("0R/2A", "0.1R/3A") keeps its value, as does any
    # resistor-typed part with a current rating ("1R/2A").
    if (_IMPEDANCE_SLASH.match(value_str) and not _LOW_OHM_RATED.match(value_str)
            and not (component_type == "resistor" and _RESISTOR_RATED.match(value_str))):
        return None
    # The split on spaces below would leave "600 Ohm @ 100MHz" as 600.
    if _IMPEDANCE_AT.search(value_str):
        return None

    value_str = _symbol_field_value(value_str.strip(), component_type)

    # Strip tolerance, voltage rating, package, and other suffixes
    # Common formats: "680K 1%", "220k/R0402", "22uF/6.3V/20%/X5R/C0603"
    # KiCad 9 uses space-separated units: "18 pF", "4.7 uF" — rejoin if
    # the second token starts with an SI prefix letter.
    parts = value_str.strip().split("/")[0].split()
    # KiCad drops spaces inside a mantissa: "78 182" is 78182, "1 000 000" is 1e6. The first
    # group must be 1-3 digits so a package code ("0402 100 OHM") does not start a join.
    if parts and re.fullmatch(r"[+-]?\d{1,3}", parts[0]):
        while len(parts) >= 2 and re.fullmatch(r"\d{3}", parts[1]):
            parts[0:2] = [parts[0] + parts[1]]
        if len(parts) >= 2 and _LAST_GROUP.fullmatch(parts[1]):
            parts[0:2] = [parts[0] + parts[1]]
    if len(parts) >= 2 and parts[1] and (parts[1][0] in "pnumkKMGRr" or parts[1] in ("F", "f", "fF", "fH")):
        s = parts[0] + parts[1]
    else:
        s = parts[0] if parts else ""
    # A comma-separated field list ("0.1uF, 50V", "100nF,50V") keeps its leading value.
    s = s.rstrip(",")
    fields = _VALUE_THEN_FIELDS.match(s) if component_type in ("resistor", "capacitor", "inductor") else None
    if fields:
        s = fields.group(1)
    # SPICE "Meg" is mega.
    s = re.sub(r"(?<=[0-9.,])[mM][eE][gG]", "M", s)
    m = _MANTISSA.match(s)
    if m and "," not in s[m.end():] and ("," in m.group() or m.group().count(".") > 1
                                         or re.search(r"\.\d{3}(?!\d)", m.group())):
        mantissa = _convert_separators(m.group())
        if mantissa is None:
            return None
        s = mantissa + s[m.end():]
    explicit_si = bool(re.fullmatch(r'[+-]?[0-9.]+(?:[eE][-+]?\d+)?F|[+-]?[0-9.]+[eE][-+]?\d+', s))
    femto = re.fullmatch(r"([+-]?[0-9.]+)f([FH]?)", s)
    if femto and (femto.group(2) or (component_type is not None and component_type != "capacitor")):
        try:
            return float(femto.group(1)) * 1e-15
        except ValueError:
            return None
    # Ferrite impedance notation ("120R@100MHz") is not a component value: None.
    if re.search(r'\d+[Rr]\s*@\s*\d', s):
        return None

    # Strip trailing unit words (mOhm, Ohm, ohm, ohms) before single-char stripping
    s = re.sub(r'[Oo]hms?$', '', s)
    unit_tail = s
    s = s.rstrip("FHΩVfhv%")         # strip trailing unit letters
    unit_tail = unit_tail[len(s):]

    if not s or "_" in s:
        # float() reads "330_0402" as 3300402: an underscore separates fields, never digits.
        return None
    if component_type not in ("capacitor", "inductor"):
        prefix_r = _PREFIX_THEN_R.fullmatch(s)
        if prefix_r:
            s = prefix_r.group(1)
    glued = _GLUED_RATING.fullmatch(s) if "V" in unit_tail.upper() else None
    if glued:
        if component_type is None:
            glued = None
        elif component_type != "capacitor":
            return None
        else:
            s = glued.group(1) + glued.group(2).lower()
    upper = None if glued else _UPPER_PREFIX.fullmatch(s)
    # A part number ("7406N", "50N06") has more than three significant integer digits before
    # the letter or a two-digit group with a leading zero after it; "1000U" and "1U0" are values.
    if upper and (len(upper.group(1).split(".")[0].strip("0")) > 3
                  or (len(upper.group(3)) == 2 and upper.group(3)[0] == "0")):
        upper = None
    # Digits glued to a voltage with no capacitor type ("1N50V") are not fraction digits.
    if (upper and upper.group(2) in _UPPER_PREFIX_TYPES.get(component_type, "")
            and not (upper.group(3) and "V" in unit_tail.upper())):
        s = upper.group(1) + upper.group(2).lower() + upper.group(3)

    # Multiplier map (SI prefixes used in EE)
    multipliers = {
        "p": 1e-12, "n": 1e-9, "u": 1e-6, "m": 1e-3,
        "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9,
        "R": 1, "r": 1,  # "R" as decimal point: 4R7 = 4.7, 0R1 = 0.1
    }

    # Handle prefix-first European notation: "u1" -> 0.1e-6, "p47" -> 0.47e-12
    # The letter replaces the decimal point; when it comes first, implied leading 0.
    if len(s) >= 2 and s[0] in multipliers and s[1:].isdigit():
        mult = multipliers[s[0]]
        try:
            return float(f"0.{s[1:]}") * mult
        except ValueError:
            pass

    # Handle embedded multiplier: "4K7" -> 4.7e3, "0R1" -> 0.1, "1R0" -> 1.0
    for suffix, mult in multipliers.items():
        if suffix in s and not s.endswith(suffix):
            idx = s.index(suffix)
            before = s[:idx]
            after = s[idx + 1:]
            if before.replace(".", "").isdigit() and after.isdigit():
                try:
                    return float(f"{before}.{after}") * mult
                except ValueError:
                    pass

    # Handle trailing multiplier: "10K", "100n", "4.7u"
    if s[-1] in multipliers:
        mult = multipliers[s[-1]]
        try:
            return float(s[:-1]) * mult
        except ValueError:
            return None

    # Plain number: "100", "47", "0.1"
    try:
        result = float(s)
        if component_type == "capacitor" and explicit_si and not unit_tail.startswith("F") \
                and result >= 1.0:
            # An exponent with no F ("1e3") is not a capacitance in farads.
            return None
        if component_type == "capacitor" and not explicit_si:
            # Bare integers >= 1 are picofarads in legacy schematics.
            # Bare decimals < 1 (0.1, 0.47, 0.22) are microfarads —
            # no real-world cap is 0.1 Farads in SMD packages.
            if result >= 1.0:
                result *= 1e-12
            else:
                result *= 1e-6
        return result
    except ValueError:
        return None


def parse_tolerance(value_str: str) -> float | None:
    """Extract tolerance percentage from a component value string.

    Returns tolerance as a fraction (0.01 for 1%, 0.05 for 5%, etc.),
    or None if no tolerance is found in the string.

    Examples:
        "680K 1%"                            -> 0.01
        "22uF/6.3V/20%/X5R"                 -> 0.20
        "10K 5%"                             -> 0.05
        "0.1uF/25V(10%)"                    -> 0.10
        ".1uF/X7R/+-10%"                    -> 0.10
        "0.02±1%"                            -> 0.01
        "02.0001_R0402_0R_1%"               -> 0.01
        "033uF_0603_Ceramic_Capacitor,_10%"  -> 0.10
        "100nF"                              -> None
    """
    if not value_str:
        return None
    # Split on all common delimiters: / space _ , ± - | and break on ( boundaries
    tokens = re.split(r'[/\s_,±|\-]+', value_str)
    for token in tokens:
        # Strip parentheses and +- prefixes
        cleaned = token.strip('()+-')
        m = re.match(r'^(\d*\.?\d+)\s*%$', cleaned)
        if m:
            return float(m.group(1)) / 100.0
        # Also try extracting from within parentheses: "25V(10%)" -> "10%"
        inner = re.search(r'\((\d*\.?\d+)\s*%\)', token)
        if inner:
            return float(inner.group(1)) / 100.0
    # Fallback: search entire string for number followed by %
    # Catches "20 %" (space-separated) and "5%T52" (no delimiter after %)
    m = re.search(r'(\d*\.?\d+)\s*%', value_str)
    if m:
        val = float(m.group(1)) / 100.0
        if 0.001 <= val <= 0.5:
            return val
    return None


# ---------------------------------------------------------------------------
# E-series standard component values (IEC 60063)
# ---------------------------------------------------------------------------

E12_DECADE = [1.0, 1.2, 1.5, 1.8, 2.2, 2.7, 3.3, 3.9, 4.7, 5.6, 6.8, 8.2]

E24_DECADE = [1.0, 1.1, 1.2, 1.3, 1.5, 1.6, 1.8, 2.0, 2.2, 2.4, 2.7, 3.0,
              3.3, 3.6, 3.9, 4.3, 4.7, 5.1, 5.6, 6.2, 6.8, 7.5, 8.2, 9.1]

E96_DECADE = [1.00, 1.02, 1.05, 1.07, 1.10, 1.13, 1.15, 1.18, 1.21, 1.24,
              1.27, 1.30, 1.33, 1.37, 1.40, 1.43, 1.47, 1.50, 1.54, 1.58,
              1.62, 1.65, 1.69, 1.74, 1.78, 1.82, 1.87, 1.91, 1.96, 2.00,
              2.05, 2.10, 2.15, 2.21, 2.26, 2.32, 2.37, 2.43, 2.49, 2.55,
              2.61, 2.67, 2.74, 2.80, 2.87, 2.94, 3.01, 3.09, 3.16, 3.24,
              3.32, 3.40, 3.48, 3.57, 3.65, 3.74, 3.83, 3.92, 4.02, 4.12,
              4.22, 4.32, 4.42, 4.53, 4.64, 4.75, 4.87, 4.99, 5.11, 5.23,
              5.36, 5.49, 5.62, 5.76, 5.90, 6.04, 6.19, 6.34, 6.49, 6.65,
              6.81, 6.98, 7.15, 7.32, 7.50, 7.68, 7.87, 8.06, 8.25, 8.45,
              8.66, 8.87, 9.09, 9.31, 9.53, 9.76]

_E_SERIES = {"E12": E12_DECADE, "E24": E24_DECADE, "E96": E96_DECADE}


def snap_to_e_series(value: float, series: str = "E96") -> tuple:
    """Snap a value to the nearest standard E-series value.

    Returns (snapped_value, error_pct) where error_pct = (snapped - value) / value * 100.
    Works across any decade (mOhm to MOhm, pF to uF, etc.).
    """
    if value <= 0:
        return (0.0, 0.0)
    # EQ-107: Log-decade snapping — normalize v into [1, 10) via
    #   10^⌊log₁₀(v)⌋, find nearest neighbour in the canonical decade
    #   table, scale back by decade.
    # Source: Self-evident — standard E-series (IEC 60063) value selection.
    #   IEC 60063 defines the E6/E12/E24/E48/E96/E192 tables as
    #   tolerance-based geometric progressions; snapping is nearest-neighbour
    #   on the log scale.
    decade = 10 ** math.floor(math.log10(value))
    normalized = value / decade
    decade_list = _E_SERIES.get(series, E96_DECADE)
    best = min(decade_list + [10.0], key=lambda e: abs(math.log10(e) - math.log10(normalized)))
    snapped = best * decade
    error_pct = (snapped - value) / value * 100 if value != 0 else 0.0
    return (snapped, round(error_pct, 2))


# Regex for rated voltage in value strings: "100nF/16V", "10uF 6.3V", "1nF/2kV", "4n7 300VAC".
_RATED_V_RE = re.compile(r'(\d+\.?\d*)\s*(k?)V(DC|AC)?(?:\b|[^a-zA-Z0-9])', re.IGNORECASE)


def _voltage_ratings(value_str):
    """(volts, plain, in_word) for each voltage rating in *value_str*: plain = written in V or
    VDC; in_word = its digits follow a letter, as in a part number ("ERJ-3EKF1001V")."""
    value_str = value_str or ""
    for m in _RATED_V_RE.finditer(value_str):
        volts = float(m.group(1)) * (1e3 if m.group(2) else 1)
        plain = not m.group(2) and (m.group(3) or "").upper() != "AC"
        yield volts, plain, m.start() > 0 and value_str[m.start() - 1].isalpha()


def parse_rated_voltage(value_str):
    """Extract rated voltage from a capacitor value string.

    Looks for patterns like '16V', '6.3V', '50 V' in the value string.
    Ignores implausible values (less than 1V or greater than 100V for standard MLCCs).

    Args:
        value_str: Component value string (e.g., '100nF/16V/X7R')

    Returns:
        Rated voltage in volts (float), or None if not found
    """
    v = next((v for v, plain, _ in _voltage_ratings(value_str) if plain), None)
    if v is not None and 1.0 <= v <= 100:
        return v
    return None


def highest_rated_voltage(value_str):
    """The highest voltage rating written in a value string ("1nF/2kV" → 2000.0), or None.
    Digits inside a part number are not a rating."""
    return max((v for v, _, in_word in _voltage_ratings(value_str) if not in_word), default=None)
