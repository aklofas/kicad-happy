# tools/tests/test_datasheet_verify_checks.py
import json, os, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "datasheets" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
import datasheet_verify as dv  # noqa: E402


class CapRecommendation(unittest.TestCase):
    # (text, count, farads): the count is the number multiplying a
    # capacitance; the digit of an EIA class-2 code (X5R, X7R, X7S) is a
    # temperature code, and "max 10mm" / "10x10mm" are not quantities.
    CASES = [
        ("10uF ceramic, X5R or X7R", 1, 10e-6),
        ("4.7uF X7R", 1, 4.7e-6),
        ("100nF max 10mm", 1, 100e-9),
        ("22uF ceramic x2, X5R or X7R", 2, 22e-6),
        ("22uF ceramic x2", 2, 22e-6),
        ("2 x 10uF", 2, 10e-6),
        ("2x 10uF X7R", 2, 10e-6),
        ("2×22µF", 2, 22e-6),
        ("10µF X5R × 3", 3, 10e-6),
        ("100nF per VDD pin", 1, 100e-9),
        ("1uF X7S, 0402 package", 1, 1e-6),
        ("47uF max ESR 10mOhm", 1, 47e-6),
        ("0.1uF x 4 near pins", 4, 0.1e-6),
        ("10x10mm pad, 10uF", 1, 10e-6),
    ]

    def test_count_and_value(self):
        for text, count, farads in self.CASES:
            with self.subTest(text=text):
                r = dv._parse_cap_recommendation(text)
                self.assertEqual(r["count"], count)
                self.assertAlmostEqual(r["min_farads"], farads, delta=farads * 1e-6)


def _ldo(tmp, pins, recs, caps, ground="GND"):
    """LDO U1: VIN on +5V, GND pin on `ground`, VOUT on +3V3; caps are
    (ref, farads, net_a, net_b), with "GND" standing for `ground`."""
    ext = {"extraction_metadata": {"extraction_score": 9.0}, "pins": pins,
           "application_circuit": recs}
    with open(os.path.join(tmp, "LDO1.json"), "w", encoding="utf-8") as fh:
        json.dump(ext, fh)
    u1 = {"reference": "U1", "type": "ic", "mpn": "LDO1",
          "pin_nets": {"1": "+5V", "2": ground, "3": "+3V3"}}
    comps, lookup, pv = [u1], {"U1": u1}, {}
    nets = {n: {"pins": [{"component": "U1", "pin_number": p}]}
            for p, n in u1["pin_nets"].items()}
    for ref, farads, a, b in caps:
        a, b = (ground if n == "GND" else n for n in (a, b))
        c = {"reference": ref, "type": "capacitor", "value": "10uF",
             "pin_nets": {"1": a, "2": b}}
        comps.append(c)
        lookup[ref] = c
        pv[ref] = farads
        nets[a]["pins"].append({"component": ref, "pin_number": "1"})
        nets[b]["pins"].append({"component": ref, "pin_number": "2"})
    return [(f["requirement_key"], f["severity"], f["actual_count"],
             [c["ref"] for c in f["actual_caps"]])
            for f in dv.verify_decoupling(comps, nets, tmp, lookup, pv)]


DIRECTED = [{"number": "1", "name": "VIN", "type": "power", "direction": "input"},
            {"number": "2", "name": "GND", "type": "ground", "direction": "passive"},
            {"number": "3", "name": "VOUT", "type": "power", "direction": "output"}]
# The extraction schema gives power and ground pins direction "passive"; the
# role then comes from the pin's function, else its name.
PASSIVE = [{"number": "1", "name": "IN", "function": "VIN", "type": "power", "direction": "passive"},
           {"number": "2", "name": "GND", "type": "ground", "direction": "passive"},
           {"number": "3", "name": "VOUT", "type": "power", "direction": "passive"}]
RECS = {"input_cap_recommended": "10uF", "output_cap_recommended": "10uF"}


class DecouplingRoles(unittest.TestCase):
    def check(self, caps, expected):
        for pins in (DIRECTED, PASSIVE):
            with self.subTest(pins=pins[0]["direction"]), tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(_ldo(tmp, pins, RECS, caps), expected)

    def test_input_cap_only_misses_the_output_recommendation(self):
        self.check([("C1", 10e-6, "+5V", "GND")],
                   [("output_cap_recommended", "error", 0, [])])

    def test_both_caps_satisfy_both(self):
        self.check([("C1", 10e-6, "+5V", "GND"), ("C2", 10e-6, "+3V3", "GND")], [])

    def test_cap_between_vin_and_vout_is_not_a_bypass_cap(self):
        self.check([("C1", 10e-6, "+5V", "+3V3")],
                   [("input_cap_recommended", "error", 0, []),
                    ("output_cap_recommended", "error", 0, [])])

    def test_output_cap_on_vout_does_not_satisfy_vin(self):
        self.check([("C2", 10e-6, "+3V3", "GND")],
                   [("input_cap_recommended", "error", 0, [])])

    def test_cap_to_the_ics_own_ground_pin_net_counts(self):
        # PGND2 is not a ground name, but it is the net on U1's GND pin.
        for pins in (DIRECTED, PASSIVE):
            with self.subTest(pins=pins[0]["direction"]), tempfile.TemporaryDirectory() as tmp:
                got = _ldo(tmp, pins, RECS, [("C1", 10e-6, "+5V", "GND"), ("C2", 10e-6, "+3V3", "GND")],
                           ground="PGND2")
                self.assertEqual(got, [])

    def test_passive_supply_pin_gets_a_decoupling_check(self):
        pins = [{"number": "1", "name": "VDD", "type": "power", "direction": "passive"},
                {"number": "2", "name": "VSS", "type": "ground", "direction": "passive"}]
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_ldo(tmp, pins, {"decoupling_cap": "100nF x2"},
                                  [("C1", 100e-9, "+5V", "GND")]),
                             [("decoupling_cap", "warning", 1, ["C1"])])


SV = lambda mx: [{"min": None, "typ": None, "max": mx, "unit": "V",
                  "condition": None, "notes": None, "evidence": None}]


def _pin(nums, name, typ="io", **kw):
    return dict({"numbers": nums, "name": name, "type": typ, "power_domain": "VDD",
                 "absolute_max": None, "recommended": None, "is_5v_tolerant": None}, **kw)


class PinAdapter(unittest.TestCase):
    def test_grouped_numbers_per_pin_limits_and_5v_tolerance(self):
        # Domain VDD: abs max 4.0 V, recommended max 3.6 V. Every pin on +5V
        # except pin 1. Expected by hand: pin 2 (second number of the VDD
        # record) exceeds abs max 4.0; PA9 is inside its own 5.5/6.0 V
        # limits; PA10 is 5 V tolerant with no limit of its own (no check);
        # PA11 takes the domain abs max 4.0.
        ext = {"extraction": {"quality_score": 80}, "base": {
            "absolute_max": {"VDD_max": SV(4.0)}, "recommended_operating": {"VDD": SV(3.6)},
            "pinout": [_pin(["1", "2"], "VDD", "power"),
                       _pin(["30"], "PA9", recommended=SV(5.5), absolute_max=SV(6.0)),
                       _pin(["31"], "PA10", is_5v_tolerant=True),
                       _pin(["32"], "PA11")]}}
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "MCU1.json"), "w", encoding="utf-8") as fh:
                json.dump(ext, fh)
            comps = [{"reference": "U1", "type": "ic", "mpn": "MCU1",
                      "pin_nets": {"1": "+3V3", "2": "+5V", "30": "+5V", "31": "+5V", "32": "+5V"}}]
            got = sorted((f["type"], f["severity"], f["pin_number"])
                         for f in dv.verify_pin_voltages(comps, {}, tmp, {}))
        self.assertEqual(got, [("pin_voltage_abs_max_exceeded", "error", "2"),
                               ("pin_voltage_abs_max_exceeded", "error", "32")])

    def test_per_pin_recommended_beats_the_domain(self):
        # 3.6 V domain op max, 4.0 V abs; the pin's own recommended max is
        # 3.0 V, so a 3.3 V net exceeds it (margin to 4.0 V abs = 17.5 %).
        ext = {"extraction": {"quality_score": 80}, "base": {
            "absolute_max": {"VDD_max": SV(4.0)}, "recommended_operating": {"VDD": SV(3.6)},
            "pinout": [_pin(["7"], "VREF", recommended=SV(3.0))]}}
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "MCU2.json"), "w", encoding="utf-8") as fh:
                json.dump(ext, fh)
            comps = [{"reference": "U1", "type": "ic", "mpn": "MCU2", "pin_nets": {"7": "+3V3"}}]
            got = [(f["type"], f["severity"], f["operating_max_V"], f["abs_max_V"])
                   for f in dv.verify_pin_voltages(comps, {}, tmp, {})]
        self.assertEqual(got, [("pin_voltage_operating_exceeded", "warning", 3.0, 4.0)])


if __name__ == "__main__":
    unittest.main()
