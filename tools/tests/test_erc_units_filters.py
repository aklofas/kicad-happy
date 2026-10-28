"""Missing units and footprint filters as KiCad 10.0.7 ERC reports them. Expected values come
from eeschema/erc/erc.cpp (TestMissingUnits: the library's unit count, pins of a missing unit plus
the common unit-0 pins, unannotated references never grouped; TestFootprintFilters: lower-case
match, a filter with ':' matches lib:name, wx wildcards * and ? only) and erc_settings.cpp
(missing_power_pin error, missing_unit/input/bidi warning, footprint_filter ignored)."""
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

from schematic.audits import validate_footprint_filters  # noqa: E402
from schematic.pipeline import analyze_schematic  # noqa: E402


def _pin(num, kind, x=0, y=0):
    return (f'(pin {kind} line (at {x} {y} 0) (length 2.54) '
            f'(name "P{num}" (effects (font (size 1.27 1.27)))) '
            f'(number "{num}" (effects (font (size 1.27 1.27)))))')


def _lib(name, subs, filters=""):
    short = name.split(":")[-1]
    body = " ".join(f'(symbol "{short}_{suffix}" {items})' for suffix, items in subs)
    fp = f' (property "ki_fp_filters" "{filters}" (at 0 0 0))' if filters else ""
    return (f'(symbol "{name}" (in_bom yes) (on_board yes)'
            f' (property "Reference" "U" (at 0 0 0)) (property "Value" "{short}" (at 0 0 0)){fp} {body})')


def _opamp_unit(u):
    base = 3 * (u - 1)
    return (f"{u}_1", _pin(base + 1, "output", 5, 0) + _pin(base + 2, "input", -5, 2)
            + _pin(base + 3, "input", -5, -2))


# LM324: four amplifiers (units 1-4) and the supply (unit 5, two power inputs).
LM324 = _lib("Amplifier_Operational:LM324",
             [_opamp_unit(u) for u in range(1, 5)]
             + [("5_1", _pin(13, "power_in", 0, 5) + _pin(14, "power_in", 0, -5))])
# Unit 3 draws a box and has no pins of its own; KiCad still counts it.
GRAPHIC = _lib("t:G", [("1_1", _pin(1, "passive")), ("2_1", _pin(2, "passive")),
                       ("3_1", "(rectangle (start -2 -2) (end 2 2) (stroke (width 0)) (fill (type none)))")])
# Two gates with a common bidirectional pin in unit 0.
COMMON = _lib("t:C", [("0_1", _pin(9, "bidirectional")), ("1_1", _pin(1, "passive")),
                      ("2_1", _pin(2, "passive"))])


def _placed(lib_id, ref, unit, n, extra="", footprint=""):
    return (f'(symbol (lib_id "{lib_id}") (at {20 * n} 100 0) (unit {unit}) {extra}'
            f' (in_bom yes) (on_board yes) (uuid "00000000-0000-0000-0000-0000000001{n:02d}")'
            f' (property "Reference" "{ref}" (at 0 0 0)) (property "Value" "V" (at 0 0 0))'
            f' (property "Footprint" "{footprint}" (at 0 0 0)))')


def _analyze(libs, placed):
    body = " ".join(_placed(*p) for p in placed)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.kicad_sch")
        with open(path, "w", encoding="utf-8") as f:
            f.write('(kicad_sch (version 20250114) (generator "eeschema")'
                    ' (uuid "00000000-0000-0000-0000-0000000000aa") (paper "A4")'
                    f' (lib_symbols {" ".join(libs)}) {body})')
        with redirect_stderr(StringIO()):
            return analyze_schematic(path)


def _units(result):
    """{type: (severity, missing_units)} of the unit records."""
    return {r["type"]: (r["severity"], r["missing_units"])
            for r in result.get("instance_consistency_warnings") or [] if "missing_units" in r}


class MissingUnitsTest(unittest.TestCase):
    def test_missing_power_unit(self):
        r = _analyze([LM324], [("Amplifier_Operational:LM324", "U1", u, u) for u in range(1, 5)])
        self.assertEqual(_units(r), {"missing_unit": ("warning", [5]),
                                     "missing_power_pin": ("error", [5])})

    def test_all_units_placed(self):
        r = _analyze([LM324], [("Amplifier_Operational:LM324", "U1", u, u) for u in range(1, 6)])
        self.assertEqual(_units(r), {})

    def test_first_unit_only(self):
        r = _analyze([LM324], [("Amplifier_Operational:LM324", "U1", 1, 1)])
        self.assertEqual(_units(r), {"missing_unit": ("warning", [2, 3, 4, 5]),
                                     "missing_input_pin": ("warning", [2, 3, 4]),
                                     "missing_power_pin": ("error", [5])})

    def test_record_shape(self):
        r = _analyze([LM324], [("Amplifier_Operational:LM324", "U1", u, u) for u in range(1, 5)])
        rec = next(x for x in r["instance_consistency_warnings"] if x["type"] == "missing_unit")
        self.assertEqual(rec["component"], "U1")
        self.assertEqual(rec["lib_id"], "Amplifier_Operational:LM324")
        self.assertEqual(rec["placed_units"], [1, 2, 3, 4])

    def test_unannotated_reference_is_not_grouped(self):
        r = _analyze([LM324], [("Amplifier_Operational:LM324", "SWF?", 1, 1)])
        self.assertEqual(_units(r), {})

    def test_graphics_only_unit_counts(self):
        r = _analyze([GRAPHIC], [("t:G", "U1", 1, 1), ("t:G", "U1", 2, 2)])
        self.assertEqual(_units(r), {"missing_unit": ("warning", [3])})

    def test_common_pins_belong_to_every_missing_unit(self):
        r = _analyze([COMMON], [("t:C", "U1", 1, 1)])
        self.assertEqual(_units(r), {"missing_unit": ("warning", [2]),
                                     "missing_bidi_pin": ("warning", [2])})

    def test_placed_count_equal_to_unit_count_is_not_checked(self):
        # KiCad compares the number of placed units with the unit count before the sets.
        r = _analyze([COMMON], [("t:C", "U1", 1, 1), ("t:C", "U1", 1, 2)])
        self.assertEqual(_units(r), {})

    def test_dnp_units_still_count(self):
        # ERC groups every symbol (SYMBOL_FILTER_ALL); DNP does not exclude it.
        r = _analyze([COMMON], [("t:C", "U1", 1, 1, "(dnp yes)")])
        self.assertEqual(_units(r)["missing_unit"], ("warning", [2]))


def _fp(footprint, filters, ref="U1"):
    comps = [{"reference": ref, "type": "ic", "lib_id": "t:X", "footprint": footprint}]
    return validate_footprint_filters(comps, {"t:X": {"ki_fp_filters": filters}})


class FootprintFilterTest(unittest.TestCase):
    def test_case_insensitive(self):
        self.assertEqual(_fp("Resistor_SMD:R_0603_1608Metric", "r_*"), [])

    def test_filter_without_colon_matches_the_name_only(self):
        (rec,) = _fp("SOIC_Custom:QFN-16", "*SOIC*")
        self.assertEqual(rec["severity"], "info")

    def test_filter_with_colon_matches_lib_and_name(self):
        self.assertEqual(len(_fp("68000:2x01 finger", "Connector*:*_2x??_*")), 1)
        self.assertEqual(_fp("Connector_PinHeader:PinHeader_2x05_P2.54mm", "Connector*:*_2x??_*"), [])

    def test_brackets_are_literal(self):
        self.assertEqual(_fp("x:A[1]", "A[1]"), [])
        self.assertEqual(len(_fp("x:A1", "A[1]")), 1)

    def test_empty_footprint_is_skipped(self):
        self.assertEqual(_fp("", "R_*"), [])

    def test_every_record_is_info(self):
        recs = _analyze([_lib("t:R", [("1_1", _pin(1, "passive"))], "R_*")],
                        [("t:R", "R1", 1, 1, "", "Capacitor_SMD:C_0603")])["footprint_filter_warnings"]
        self.assertEqual([(r["component"], r["severity"]) for r in recs], [("R1", "info")])


if __name__ == "__main__":
    unittest.main()
