# tools/tests/test_divider_rc_junction.py
"""Dividers name the resistors that sit on their nets, and a resistor into a junction
that a shared resistor to ground ties to another divider can still form an RC filter."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from signal_detectors import detect_rc_filters, detect_voltage_dividers  # noqa: E402


def _ctx(parts, ics=()):
    """Context for two-pin *parts* [(ref, type, value, net1, net2)] and IC pins [(ref, pin, name, net, pin_type)]."""
    comps, nets = [], {}
    lib = {"resistor": "Device:R", "capacitor": "Device:C"}
    for ref, typ, val, n1, n2 in parts:
        comps.append({"reference": ref, "lib_id": lib[typ], "value": val, "type": typ,
                      "pins": [{"number": "1", "name": ""}, {"number": "2", "name": ""}]})
        for num, net in (("1", n1), ("2", n2)):
            nets.setdefault(net, {"pins": []})["pins"].append(
                {"component": ref, "pin_number": num, "pin_name": ""})
    for ref in sorted({i[0] for i in ics}):
        pins = [i for i in ics if i[0] == ref]
        comps.append({"reference": ref, "lib_id": "Amplifier_Operational:OPA1612", "value": "OPA1612",
                      "type": "ic", "pins": [{"number": p, "name": name} for _, p, name, _, _ in pins]})
        for _, p, name, net, kind in pins:
            nets.setdefault(net, {"pins": []})["pins"].append(
                {"component": ref, "pin_number": p, "pin_name": name, "pin_type": kind})
    return build_analysis_context(comps, nets, {})


# A DAC output stage: R2 to ground first, so the divider search meets the ground end first
_DAC_STAGE = [
    ("R2", "resistor", "16.9k", "AGND", "MID"),
    ("R1", "resistor", "3.9k", "AOUT", "MID"),
    ("R3", "resistor", "150", "MID", "OP_IN"),
    ("C1", "capacitor", "120p", "OP_IN", "AGND"),
]
_OPAMP = [("U1", "3", "+IN", "OP_IN", "input"), ("U1", "1", "OUT", "OP_OUT", "output"),
          ("U1", "2", "-IN", "OP_OUT", "input")]
_DAC = [("U2", "1", "AOUT", "AOUT", "output")]


class DividerArms(unittest.TestCase):
    def test_each_arm_sits_on_the_nets_the_divider_names(self):
        ctx = _ctx(_DAC_STAGE, _OPAMP)
        vds = detect_voltage_dividers(ctx)["voltage_dividers"]
        self.assertTrue(vds)
        for vd in vds:
            with self.subTest(divider=vd["summary"]):
                top = set(ctx.get_two_pin_nets(vd["r_top"]["ref"]))
                bot = set(ctx.get_two_pin_nets(vd["r_bottom"]["ref"]))
                self.assertEqual(top, {vd["top_net"], vd["mid_net"]})
                self.assertEqual(bot, {vd["mid_net"], vd["bottom_net"]})


class JunctionRcFilter(unittest.TestCase):
    def test_series_resistor_after_a_divider_still_forms_its_rc_filter(self):
        ctx = _ctx(_DAC_STAGE, _OPAMP + _DAC)
        vds = detect_voltage_dividers(ctx)["voltage_dividers"]
        self.assertIn("Voltage divider R1/R2", [v["summary"] for v in vds])
        pairs = {(f["resistor"]["ref"], f["capacitor"]["ref"]) for f in detect_rc_filters(ctx, vds)}
        self.assertIn(("R3", "C1"), pairs)

    def test_resistor_feeding_the_junction_stays_out_of_rc_pairings(self):
        # A cap on the DAC output pairs with neither the feed resistor nor the load resistor
        ctx = _ctx(_DAC_STAGE + [("C3", "capacitor", "100p", "AOUT", "AGND")], _OPAMP + _DAC)
        vds = detect_voltage_dividers(ctx)["voltage_dividers"]
        pairs = {(f["resistor"]["ref"], f["capacitor"]["ref"]) for f in detect_rc_filters(ctx, vds)}
        self.assertEqual(pairs, {("R3", "C1")})

    def test_resistor_into_an_integrator_node_stays_out_of_rc_pairings(self):
        # R3 into the inverting input, with feedback R9 and C9 from that node to the output
        ctx = _ctx([("R2", "resistor", "16.9k", "AGND", "MID"),
                    ("R1", "resistor", "3.9k", "AOUT", "MID"),
                    ("R3", "resistor", "10k", "MID", "INV"),
                    ("R9", "resistor", "100k", "INV", "OP_OUT"),
                    ("C9", "capacitor", "10n", "INV", "OP_OUT")],
                   [("U1", "2", "-IN", "INV", "input"), ("U1", "1", "OUT", "OP_OUT", "output"),
                    ("U1", "3", "+IN", "AGND", "input")] + _DAC)
        vds = detect_voltage_dividers(ctx)["voltage_dividers"]
        pairs = {(f["resistor"]["ref"], f["capacitor"]["ref"]) for f in detect_rc_filters(ctx, vds)}
        self.assertNotIn(("R3", "C9"), pairs)

    def test_margining_resistor_on_feedback_does_not_free_the_feedback_resistor(self):
        # A third resistor on FB makes a junction; the output caps still pair with nothing
        ctx = _ctx([("R1", "resistor", "100k", "VOUT_NODE", "FB"),
                    ("R2", "resistor", "22k", "FB", "GND"),
                    ("R3", "resistor", "200k", "FB", "MARGIN"),
                    ("C1", "capacitor", "10u", "VOUT_NODE", "GND")],
                   [("U1", "4", "FB", "FB", "input"), ("U1", "5", "SW", "VOUT_NODE", "output"),
                    ("U2", "1", "DAC", "MARGIN", "output")])
        vds = detect_voltage_dividers(ctx)["voltage_dividers"]
        self.assertEqual(detect_rc_filters(ctx, vds), [])

    def test_cap_on_the_junction_pairs_with_none_of_its_resistors(self):
        # A bias divider on an ADC input with the signal resistor into the same node
        ctx = _ctx([("R1", "resistor", "22k", "+3V3", "ADC_IN"),
                    ("R2", "resistor", "22k", "ADC_IN", "GND"),
                    ("R3", "resistor", "10k", "SIG", "ADC_IN"),
                    ("C1", "capacitor", "2n2", "ADC_IN", "GND")])
        vds = detect_voltage_dividers(ctx)["voltage_dividers"]
        self.assertEqual(sorted(v["summary"] for v in vds),
                         ["Voltage divider R1/R2", "Voltage divider R3/R2"])
        self.assertEqual(detect_rc_filters(ctx, vds), [])

    def test_cap_on_the_resistors_other_node_is_not_merged_as_parallel(self):
        # C2 bridges R1's input node to the other leg of a differential pair; C1 filters its output
        ctx = _ctx([("R1", "resistor", "150", "IN_P", "OUT_P"),
                    ("C1", "capacitor", "120p", "OUT_P", "GND"),
                    ("C2", "capacitor", "1n", "IN_P", "IN_N")], _OPAMP)
        by_cap = {f["capacitor"]["ref"]: f for f in detect_rc_filters(ctx, [])
                  if f["resistor"]["ref"] == "R1"}
        self.assertEqual(sorted(by_cap), ["C1", "C2"])
        self.assertNotIn("parallel_caps", by_cap["C1"]["capacitor"])
        self.assertAlmostEqual(by_cap["C1"]["cutoff_hz"], 8841941.28, places=0)

    def test_feedback_divider_resistor_stays_out_of_rc_pairings(self):
        # Output -> R1 -> FB -> R2 -> GND with the output cap on the unnamed output node
        ctx = _ctx([("R1", "resistor", "100k", "VOUT_NODE", "FB"),
                    ("R2", "resistor", "22k", "FB", "GND"),
                    ("C1", "capacitor", "10u", "VOUT_NODE", "GND")],
                   [("U1", "4", "FB", "FB", "input"), ("U1", "5", "SW", "VOUT_NODE", "output")])
        vds = detect_voltage_dividers(ctx)["voltage_dividers"]
        self.assertEqual([v["summary"] for v in vds], ["Voltage divider R1/R2"])
        self.assertEqual(detect_rc_filters(ctx, vds), [])


if __name__ == "__main__":
    unittest.main()
