# tools/tests/test_opamp_w4.py
"""Op-amp stages: non-inverting gain 1 + Rf/Rg, parallel feedback parts as one equivalent,
one detection id per op-amp unit.  Gains are the textbook formulas by hand: inverting
-Rf/Ri, non-inverting 1 + Rf/Rg; ids are sha256 prefixes of the identity string."""
import hashlib, sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
import signal_detectors as sd  # noqa: E402
from detection_schema import compute_detection_id  # noqa: E402
from diff_engine import diff_schematic  # noqa: E402
from finding_schema import sort_findings  # noqa: E402


def _ctx(components, nets, lib_symbols=None, rails=("+5V", "+2V5")):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    for c in components:
        c.setdefault("lib_id", "")
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
    return build_analysis_context(components, full, lib_symbols or {}, known_power_rails=set(rails))


def _r(ref, value):
    return {"reference": ref, "type": "resistor", "value": value, "lib_id": "Device:R"}


def _oa(ref, value="TL071", unit=1):
    return {"reference": ref, "type": "ic", "value": value,
            "lib_id": f"Amplifier_Operational:{value}", "unit": unit}


def _p(ref, pin):
    return (ref, pin, "~", "passive")


def _opamps(components, nets, lib_symbols=None):
    return sd.detect_opamp_circuits(_ctx(components, nets, lib_symbols))


class NonInverting(unittest.TestCase):
    def test_rf_and_rg_to_ground_with_signal_on_plus(self):
        # Rf 100k, Rg 10k to GND: 1 + 100k/10k = 11.0
        oa = _opamps([_oa("U3"), _r("R7", "100k"), _r("R8", "10k")],
                     {"OUT": [("U3", "6", "OUT", "output"), _p("R7", "1")],
                      "INN": [("U3", "2", "-", "input"), _p("R7", "2"), _p("R8", "1")],
                      "GND": [_p("R8", "2")], "SIG": [("U3", "3", "+", "input")]})
        self.assertEqual(len(oa), 1)
        self.assertEqual(oa[0]["configuration"], "non_inverting")
        self.assertEqual(oa[0]["gain"], 11.0)
        self.assertEqual(oa[0]["gain_dB"], 20.8)
        self.assertEqual(oa[0]["input_resistor"], {"ref": "R8", "ohms": 10000.0})
        self.assertEqual(oa[0]["feedback_resistor"], {"ref": "R7", "ohms": 100000.0})

    def test_resistor_to_a_power_rail_is_bias_not_rg(self):
        # R8 from - to +2V5 sets a bias point; it is not the gain-setting ground leg
        oa = _opamps([_oa("U3"), _r("R7", "100k"), _r("R8", "10k")],
                     {"OUT": [("U3", "6", "OUT", "output"), _p("R7", "1")],
                      "INN": [("U3", "2", "-", "input"), _p("R7", "2"), _p("R8", "1")],
                      "+2V5": [_p("R8", "2")], "SIG": [("U3", "3", "+", "input")]})
        self.assertEqual(oa[0]["configuration"], "transimpedance_or_buffer")
        self.assertNotIn("gain", oa[0])
        self.assertNotIn("input_resistor", oa[0])

    def test_plus_on_ground_is_not_non_inverting(self):
        # + grounded, Rf and a ground leg on -: no signal enters, no gain stage claimed
        oa = _opamps([_oa("U3"), _r("R7", "100k"), _r("R8", "10k")],
                     {"OUT": [("U3", "6", "OUT", "output"), _p("R7", "1")],
                      "INN": [("U3", "2", "-", "input"), _p("R7", "2"), _p("R8", "1")],
                      "GND": [_p("R8", "2"), ("U3", "3", "+", "input")]})
        self.assertEqual(oa[0]["configuration"], "transimpedance_or_buffer")
        self.assertNotIn("gain", oa[0])


def _pot(ref, value):
    return {"reference": ref, "type": "resistor", "value": value, "lib_id": "Device:R_Potentiometer"}


class AdjustableGain(unittest.TestCase):
    """A potentiometer in the gain network, or another resistor beside Rf or the gain leg,
    makes the gain adjustable: the configuration stays, no single gain is claimed."""

    def test_rheostat_across_rf_leaves_gain_unset(self):
        # 33k Rf with a 50k rheostat across it (pin 1 on -, pins 2 and 3 on OUT), Rg 2.2k:
        # the gain spans 1.0 .. 1 + (33k || 50k)/2.2k = 10.04, never 1 + 33k/2.2k = 16
        oa = _opamps([_oa("U1"), _r("R16", "33k"), _r("R10", "2.2k"), _pot("RV1", "50k")],
                     {"OUT": [("U1", "6", "OUT", "output"), _p("R16", "1"), _p("RV1", "2"), _p("RV1", "3")],
                      "INN": [("U1", "2", "-", "input"), _p("R16", "2"), _p("R10", "1"), _p("RV1", "1")],
                      "AGND": [_p("R10", "2")], "SIG": [("U1", "3", "+", "input")]},
                     )
        self.assertEqual(oa[0]["configuration"], "non_inverting")
        self.assertNotIn("gain", oa[0])
        self.assertNotIn("gain_dB", oa[0])
        self.assertEqual(oa[0]["input_resistor"], {"ref": "R10", "ohms": 2200.0})

    def test_rheostat_as_rf_leaves_gain_unset(self):
        # RV5 100k as Rf (pin 1 on -, pins 2 and 3 on OUT), Rg 100k: gain 1 .. 2, not a fixed 2.0
        oa = _opamps([_oa("U3"), _pot("RV5", "100k"), _r("R21", "100k")],
                     {"OUT": [("U3", "1", "OUT", "output"), _p("RV5", "2"), _p("RV5", "3")],
                      "INN": [("U3", "2", "-", "input"), _p("RV5", "1"), _p("R21", "2")],
                      "GND": [_p("R21", "1")], "SIG": [("U3", "3", "+", "input")]})
        self.assertEqual(oa[0]["configuration"], "non_inverting")
        self.assertNotIn("gain", oa[0])

    def test_rheostat_as_rg_leaves_gain_unset(self):
        # Rf 100k, ground leg a 10k rheostat (pins 1 and 2 on -, pin 3 on GND)
        oa = _opamps([_oa("U3"), _r("R7", "100k"), _pot("RV1", "10k")],
                     {"OUT": [("U3", "6", "OUT", "output"), _p("R7", "1")],
                      "INN": [("U3", "2", "-", "input"), _p("R7", "2"), _p("RV1", "1"), _p("RV1", "2")],
                      "GND": [_p("RV1", "3")], "SIG": [("U3", "3", "+", "input")]})
        self.assertEqual(oa[0]["configuration"], "non_inverting")
        self.assertNotIn("gain", oa[0])

    def test_inverting_with_trimmer_across_ri_leaves_gain_unset(self):
        # Ri 10k with a 3-pin trimmer from the same signal net to -: adjustable inverting gain
        oa = _opamps([_oa("U1"), _r("R1", "100k"), _r("R2", "10k"), _pot("RV2", "20k")],
                     {"OUT": [("U1", "1", "OUT", "output"), _p("R1", "1")],
                      "INN": [("U1", "2", "-", "input"), _p("R1", "2"), _p("R2", "2"), _p("RV2", "2")],
                      "SIG": [_p("R2", "1"), _p("RV2", "1")], "NC1": [_p("RV2", "3")],
                      "GND": [("U1", "3", "+", "input")]})
        self.assertEqual(oa[0]["configuration"], "inverting")
        self.assertNotIn("gain", oa[0])

    def test_offset_trim_on_the_rails_keeps_the_gain(self):
        # A trimmer between the rails with its wiper on - biases the input; the gain stays -10
        oa = _opamps([_oa("U1"), _r("R1", "100k"), _r("R2", "10k"), _pot("RV3", "10k")],
                     {"OUT": [("U1", "1", "OUT", "output"), _p("R1", "1")],
                      "INN": [("U1", "2", "-", "input"), _p("R1", "2"), _p("R2", "2"), _p("RV3", "2")],
                      "SIG": [_p("R2", "1")], "+5V": [_p("RV3", "1")], "GND": [_p("RV3", "3"), ("U1", "3", "+", "input")]})
        self.assertEqual((oa[0]["configuration"], oa[0]["gain"]), ("inverting", -10.0))


class Unchanged(unittest.TestCase):
    def test_unity_follower(self):
        oa = _opamps([_oa("U1")], {"OUT": [("U1", "1", "OUT", "output"), ("U1", "2", "-", "input")],
                                   "SIG": [("U1", "3", "+", "input")]})
        self.assertEqual((oa[0]["configuration"], oa[0]["gain"]), ("buffer", 1.0))

    def test_inverting_minus_ten(self):
        # -100k/10k = -10.0
        oa = _opamps([_oa("U1"), _r("R1", "100k"), _r("R2", "10k")],
                     {"OUT": [("U1", "1", "OUT", "output"), _p("R1", "1")],
                      "INN": [("U1", "2", "-", "input"), _p("R1", "2"), _p("R2", "2")],
                      "SIG": [_p("R2", "1")], "GND": [("U1", "3", "+", "input")]})
        self.assertEqual((oa[0]["configuration"], oa[0]["gain"]), ("inverting", -10.0))
        self.assertEqual(oa[0]["input_resistor"], {"ref": "R2", "ohms": 10000.0})

    def test_open_loop(self):
        oa = _opamps([_oa("U1")], {"OUT": [("U1", "1", "OUT", "output")],
                                   "INN": [("U1", "2", "-", "input")],
                                   "SIG": [("U1", "3", "+", "input")]})
        self.assertEqual(oa[0]["configuration"], "comparator_or_open_loop")


class ParallelFeedback(unittest.TestCase):
    def test_parallel_rf_is_one_equivalent(self):
        # Rf = 100k || 200k = 66.667k, Ri = 10k: -66.667k/10k = -6.667
        oa = _opamps([_oa("U2", "TL072"), _r("R4", "100k"), _r("R5", "200k"), _r("R6", "10k")],
                     {"OUT": [("U2", "1", "OUT", "output"), _p("R4", "1"), _p("R5", "1")],
                      "INN": [("U2", "2", "-", "input"), _p("R4", "2"), _p("R5", "2"), _p("R6", "2")],
                      "GND": [("U2", "3", "+", "input")], "SIG": [_p("R6", "1")]})
        self.assertEqual((oa[0]["configuration"], oa[0]["gain"]), ("inverting", -6.667))
        self.assertEqual(oa[0]["feedback_resistor"]["ref"], "R4")
        self.assertEqual(oa[0]["feedback_resistor"]["parallel_refs"], ["R4", "R5"])
        self.assertAlmostEqual(oa[0]["feedback_resistor"]["ohms"], 200000.0 / 3)

    def test_parallel_rg_is_one_equivalent(self):
        # Rg = 20k || 20k = 10k, Rf 30k: 1 + 30k/10k = 4.0
        oa = _opamps([_oa("U3"), _r("R7", "30k"), _r("R8", "20k"), _r("R9", "20k")],
                     {"OUT": [("U3", "6", "OUT", "output"), _p("R7", "1")],
                      "INN": [("U3", "2", "-", "input"), _p("R7", "2"), _p("R8", "1"), _p("R9", "1")],
                      "GND": [_p("R8", "2"), _p("R9", "2")], "SIG": [("U3", "3", "+", "input")]})
        self.assertEqual((oa[0]["configuration"], oa[0]["gain"]), ("non_inverting", 4.0))
        self.assertEqual(oa[0]["input_resistor"],
                         {"ref": "R8", "ohms": 10000.0, "parallel_refs": ["R8", "R9"]})


def _tl072_units(rf2):
    """TL072 U1: unit 1 non-inverting (Rf R1 30k, Rg R2 10k), unit 2 inverting (Rf R3, Ri R4 10k)."""
    lib = {"Amplifier_Operational:TL072": {"unit_pins": {
        1: [{"number": "1"}, {"number": "2"}, {"number": "3"}],
        2: [{"number": "5"}, {"number": "6"}, {"number": "7"}],
        3: [{"number": "4"}, {"number": "8"}]}}}
    comps = [_oa("U1", "TL072", 1), _oa("U1", "TL072", 2),
             _r("R1", "30k"), _r("R2", "10k"), _r("R3", rf2), _r("R4", "10k")]
    nets = {"OUTA": [("U1", "1", "OUT", "output"), _p("R1", "1")],
            "INA-": [("U1", "2", "-", "input"), _p("R1", "2"), _p("R2", "1")],
            "SIGA": [("U1", "3", "+", "input")],
            "GND": [_p("R2", "2"), ("U1", "5", "+", "input"), ("U1", "4", "V-", "power_in")],
            "INB-": [("U1", "6", "-", "input"), _p("R3", "2"), _p("R4", "2")],
            "OUTB": [("U1", "7", "OUT", "output"), _p("R3", "1")],
            "SIGB": [_p("R4", "1")], "+5V": [("U1", "8", "V+", "power_in")]}
    oa = sd.detect_opamp_circuits(_ctx(comps, nets, lib))
    for o in oa:
        o["detection_id"] = compute_detection_id(o, "opamp_circuits")
    return sort_findings(oa)


class UnitIdentity(unittest.TestCase):
    def test_units_have_distinct_ids_and_unit_one_keeps_its_id(self):
        oa = {o["unit"]: o for o in _tl072_units("47k")}
        self.assertEqual(sorted(oa), [1, 2])
        old_id = "opamp_circuits:" + hashlib.sha256(b"opamp_circuits::U1").hexdigest()[:12]
        self.assertEqual(oa[1]["detection_id"], old_id)
        self.assertNotEqual(oa[2]["detection_id"], oa[1]["detection_id"])

    def test_single_unit_id_unchanged(self):
        oa = _opamps([_oa("U9")], {"OUT": [("U9", "1", "OUT", "output"), ("U9", "2", "-", "input")],
                                   "SIG": [("U9", "3", "+", "input")]})
        self.assertEqual(compute_detection_id(oa[0], "opamp_circuits"),
                         "opamp_circuits:" + hashlib.sha256(b"opamp_circuits::U9").hexdigest()[:12])

    def test_diff_reports_a_change_in_unit_two(self):
        # Unit 2's Rf 47k -> 100k: gain -4.7 -> -10.0; unit 1 unchanged
        base = {"findings": _tl072_units("47k")}
        head = {"findings": _tl072_units("100k")}
        mods = diff_schematic(base, head, 0.0)["signal_analysis"]["opamp_circuits"]["modified"]
        self.assertEqual(len(mods), 1)
        self.assertEqual(mods[0]["head_item"]["unit"], 2)
        gain = [(c["base"], c["head"]) for c in mods[0]["changes"] if c["field"] == "gain"]
        self.assertEqual(gain, [(-4.7, -10.0)])


if __name__ == "__main__":
    unittest.main()
