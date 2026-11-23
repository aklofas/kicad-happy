# tools/tests/test_pullup_bridged_jumper.py
"""A pull-up resistor whose far side reaches its rail through a solder jumper that is
bridged as built (SparkFun's cuttable I2C pull-up jumper) is a pull-up. Only the pads the
jumper joins are followed, only to a supply that is not ground, and an open jumper, an
open footprint or a jumper marked DNP joins nothing."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from detector_helpers import (  # noqa: E402
    bridged_jumper_pads, not_i2c_despite_name, rail_behind_bridged_jumper,
)
from kicad_types import build_analysis_context  # noqa: E402
from schematic.net_analysis import _detect_i2c_buses  # noqa: E402
from signal_detectors import detect_design_observations  # noqa: E402
from validation_detectors import validate_i2c_bus, validate_pullups  # noqa: E402


def _comp(ref, ctype, value, lib_id, pins, footprint="", dnp=False):
    return {"reference": ref, "type": ctype, "value": value, "lib_id": lib_id,
            "footprint": footprint, "dnp": dnp,
            "pins": [{"number": n, "name": nm, "type": t} for n, nm, t in pins]}


def _res(ref, value="4.7k"):
    return _comp(ref, "resistor", value, "Device:R", [("1", "~", "passive"), ("2", "~", "passive")])


def _jumper(lib_id, footprint="", pads=3, dnp=False):
    return _comp("JP1", "jumper", "I2C", lib_id,
                 [(str(i), "~", "passive") for i in range(1, pads + 1)], footprint, dnp)


SENSOR = _comp("U1", "ic", "LIS3DH", "Sensor_Motion:LIS3DH",
               [("1", "SDA", "bidirectional"), ("2", "SCL", "input"), ("3", "VDD", "power_in")])
REGULATOR = _comp("U2", "ic", "AP2112K-3.3", "Regulator_Linear:AP2112K-3.3",
                  [("1", "VIN", "power_in"), ("3", "EN", "input"), ("5", "VOUT", "power_out")])


def _ctx(components, nets):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type="passive")
                                    for r, p, pn in pins],
                "point_count": 0, "no_connect": False, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(list(components), full, {},
                                  known_power_rails={"+3V3", "VCC", "GND"})


def _sparkfun_board(jumper, sda_pad="1", scl_pad="3", rail_pad="2", rail="+3V3",
                    sda="SDA", scl="SCL"):
    """SDA - R1 - jumper pad, SCL - R2 - jumper pad, the rail on another pad."""
    nets = {sda: [("U1", "1", "SDA"), ("R1", "1", "~")],
            scl: [("U1", "2", "SCL"), ("R2", "1", "~")],
            "PU_A": [("R1", "2", "~"), ("JP1", sda_pad, "~")],
            "PU_C": [("R2", "2", "~"), ("JP1", scl_pad, "~")],
            rail: [("U1", "3", "VDD"), ("JP1", rail_pad, "~")],
            "GND": []}
    return _ctx((SENSOR, _res("R1"), _res("R2"), jumper), nets)


BRIDGED_123 = _jumper("SparkFun:SolderJumper_3_Bridged123", "SparkFun:Jumper_3_NC-2_Trace")


def _bus(ctx):
    return {e["net"]: e for e in _detect_i2c_buses(ctx)}


def _obs(ctx):
    obs = detect_design_observations(ctx, {"decoupling_analysis": [], "power_regulators": []})
    return {o["net"]: o for o in obs if o["category"] == "i2c_bus"}


def _pr001(ctx):
    return [f["summary"] for f in validate_i2c_bus(ctx) if f["rule_id"] == "PR-001"]


def _pu001(ctx):
    return [(f["severity"], f["summary"]) for f in validate_pullups(ctx)]


class BridgedJumperPads(unittest.TestCase):
    def test_pads_named_by_the_footprint_then_the_symbol(self):
        cases = (
            (_jumper("Jumper:SolderJumper_3_Bridged12",
                     "Jumper:SolderJumper-3_P1.3mm_Bridged12_RoundedPad1.0x1.5mm"), 3, {"1", "2"}),
            (_jumper("Jumper:SolderJumper_3_Bridged12",
                     "Jumper:SolderJumper-3_P1.3mm_Bridged2Bar12_Pad1.0x1.5mm"), 3, {"1", "2"}),
            (_jumper("Jumper:SolderJumper_3_Bridged123", "SparkFun:Jumper_3_NC-2_Trace"),
             3, {"1", "2", "3"}),
            (_jumper("Jumper:SolderJumper_2_Bridged", "", pads=2), 2, {"1", "2"}),
            (_jumper("Jumper:Jumper_2_Open",
                     "Jumper:SolderJumper-2_P1.3mm_Bridged_RoundedPad1.0x1.5mm", pads=2), 2, {"1", "2"}),
        )
        for comp, n, want in cases:
            with self.subTest(lib=comp["lib_id"], fp=comp["footprint"]):
                self.assertEqual(bridged_jumper_pads(comp, n), frozenset(want))

    def test_open_or_unknown_pads_join_nothing(self):
        cases = (
            (_jumper("Jumper:SolderJumper_3_Open"), 3),
            (_jumper("Jumper:SolderJumper_2_Bridged",
                     "Jumper:SolderJumper-2_P1.3mm_Open_RoundedPad1.0x1.5mm", pads=2), 2),
            (_jumper("Jumper:SolderJumper_3_Bridged", "", pads=3), 3),
            (_jumper("Jumper:SolderJumper_3_Bridged123", dnp=True), 3),
            (_res("R9"), 2),
        )
        for comp, n in cases:
            with self.subTest(lib=comp["lib_id"], fp=comp["footprint"], dnp=comp["dnp"]):
                self.assertEqual(bridged_jumper_pads(comp, n), frozenset())


class PullUpThroughBridgedJumper(unittest.TestCase):
    def test_pull_up_is_found_in_every_check(self):
        ctx = _sparkfun_board(BRIDGED_123)
        self.assertEqual(rail_behind_bridged_jumper(ctx, "PU_A"), ("+3V3", "JP1"))
        bus = _bus(ctx)
        for net, ref in (("SDA", "R1"), ("SCL", "R2")):
            with self.subTest(net=net):
                self.assertTrue(bus[net]["has_pull_up"])
                self.assertEqual(bus[net]["pull_ups"],
                                 [{"ref": ref, "value": "4.7k", "ohms": 4700.0, "to_rail": "+3V3"}])
                obs = _obs(ctx)[net]
                self.assertTrue(obs["has_pullup"])
                self.assertEqual((obs["pullup_resistor"], obs["pullup_rail"]), (ref, "+3V3"))
        self.assertEqual(_pr001(ctx), [])
        self.assertEqual([s for s in _pu001(ctx) if "missing pull-up" in s[1]], [])

    def test_pin_named_bus_line_finds_it_too(self):
        ctx = _sparkfun_board(BRIDGED_123, sda="/X/DATA", scl="/X/CLOCK")
        bus = _bus(ctx)
        self.assertEqual(bus["/X/DATA"]["pull_ups"][0]["to_rail"], "+3V3")
        self.assertTrue(bus["/X/CLOCK"]["has_pull_up"])

    def test_without_the_jumper_rail_the_lines_still_lack_pull_ups(self):
        ctx = _sparkfun_board(_jumper("Jumper:SolderJumper_3_Open"))
        self.assertFalse(_bus(ctx)["SDA"]["has_pull_up"])
        self.assertFalse(_obs(ctx)["SDA"]["has_pullup"])
        self.assertEqual(sorted(_pr001(ctx)), ["I2C bus SDA/SCL: SCL missing pull-up",
                                               "I2C bus SDA/SCL: SDA missing pull-up"])
        self.assertIn(("warning", "U1 pin SDA (SDA) missing pull-up resistor"), _pu001(ctx))

    def test_only_the_bridged_pads_are_followed(self):
        # Bridged12 select jumper: pad 1 VCC, pad 2 the resistor, pad 3 GND -> VCC
        jp = _jumper("Jumper:SolderJumper_3_Bridged12",
                     "Jumper:SolderJumper-3_P1.3mm_Bridged12_RoundedPad1.0x1.5mm")
        nets = {"SDA": [("U1", "1", "SDA"), ("R1", "1", "~")],
                "SCL": [("U1", "2", "SCL")],
                "PU_A": [("R1", "2", "~"), ("JP1", "2", "~")],
                "VCC": [("U1", "3", "VDD"), ("JP1", "1", "~")],
                "GND": [("JP1", "3", "~")]}
        ctx = _ctx((SENSOR, _res("R1"), jp), nets)
        self.assertEqual(_bus(ctx)["SDA"]["pull_ups"][0]["to_rail"], "VCC")
        # the resistor on pad 3, which the jumper leaves open: no pull-up
        nets = {"SDA": [("U1", "1", "SDA"), ("R1", "1", "~")],
                "SCL": [("U1", "2", "SCL")],
                "PU_A": [("R1", "2", "~"), ("JP1", "3", "~")],
                "VCC": [("U1", "3", "VDD"), ("JP1", "1", "~")],
                "GND": [("JP1", "2", "~")]}
        ctx = _ctx((SENSOR, _res("R1"), jp), nets)
        self.assertFalse(_bus(ctx)["SDA"]["has_pull_up"])
        self.assertIsNone(rail_behind_bridged_jumper(ctx, "PU_A"))

    def test_a_jumper_bridged_to_ground_is_not_a_pull_up(self):
        ctx = _sparkfun_board(BRIDGED_123, rail="GND")
        self.assertIsNone(rail_behind_bridged_jumper(ctx, "PU_A"))
        self.assertFalse(_bus(ctx)["SDA"]["has_pull_up"])
        self.assertFalse(_obs(ctx)["SDA"]["has_pullup"])

    def test_open_footprint_and_dnp_jumper_join_nothing(self):
        for jp in (_jumper("Jumper:SolderJumper_3_Bridged123",
                           "Jumper:SolderJumper-3_P1.3mm_Open_RoundedPad1.0x1.5mm"),
                   _jumper("Jumper:SolderJumper_3_Bridged123", dnp=True)):
            with self.subTest(fp=jp["footprint"], dnp=jp["dnp"]):
                ctx = _sparkfun_board(jp)
                self.assertFalse(_bus(ctx)["SDA"]["has_pull_up"])
                self.assertFalse(_obs(ctx)["SCL"]["has_pullup"])
                self.assertEqual(len(_pr001(ctx)), 2)

    def test_enable_pin_pulled_up_through_a_jumper(self):
        jp = _jumper("Jumper:SolderJumper_2_Bridged",
                     "Jumper:SolderJumper-2_P1.3mm_Bridged_RoundedPad1.0x1.5mm", pads=2)
        nets = {"EN": [("U2", "3", "EN"), ("R1", "1", "~")],
                "PU_EN": [("R1", "2", "~"), ("JP1", "1", "~")],
                "VCC": [("U2", "1", "VIN"), ("JP1", "2", "~")],
                "+3V3": [("U2", "5", "VOUT")], "GND": []}
        found = _pu001(_ctx((REGULATOR, _res("R1", "100k"), jp), nets))
        self.assertNotIn(("warning", "U2 pin EN (EN) missing pull-up resistor"), found)
        jp_open = _jumper("Jumper:SolderJumper_2_Open", pads=2)
        found = _pu001(_ctx((REGULATOR, _res("R1", "100k"), jp_open), nets))
        self.assertIn(("warning", "U2 pin EN (EN) missing pull-up resistor"), found)

    def test_plain_pull_up_keeps_its_rail_and_value(self):
        nets = {"SDA": [("U1", "1", "SDA"), ("R1", "1", "~")],
                "SCL": [("U1", "2", "SCL"), ("R2", "1", "~")],
                "+3V3": [("U1", "3", "VDD"), ("R1", "2", "~"), ("R2", "2", "~")],
                "GND": []}
        ctx = _ctx((SENSOR, _res("R1", "2.2k"), _res("R2", "2.2k")), nets)
        bus = _bus(ctx)
        self.assertEqual(bus["SDA"]["pull_ups"],
                         [{"ref": "R1", "value": "2.2k", "ohms": 2200.0, "to_rail": "+3V3"}])
        self.assertEqual(bus["SDA"]["pull_up_ohms"], 2200.0)
        self.assertEqual(_obs(ctx)["SCL"]["pullup_rail"], "+3V3")


class DisplayGuardSeesJumperPullUps(unittest.TestCase):
    def test_display_named_lines_pulled_up_through_a_jumper_are_i2c(self):
        display = _comp("U3", "ic", "SSD1306", "Display:SSD1306",
                        [("1", "SDA", "bidirectional"), ("2", "SCL", "input"),
                         ("3", "CS", "input"), ("4", "VDD", "power_in")])
        nets = {"LCD_SDA": [("U3", "1", "SDA"), ("R1", "1", "~")],
                "LCD_SCL": [("U3", "2", "SCL"), ("R2", "1", "~")],
                "LCD_CS": [("U3", "3", "CS")],
                "PU_A": [("R1", "2", "~"), ("JP1", "1", "~")],
                "PU_C": [("R2", "2", "~"), ("JP1", "3", "~")],
                "+3V3": [("U3", "4", "VDD"), ("JP1", "2", "~")], "GND": []}
        ctx = _ctx((display, _res("R1"), _res("R2"), BRIDGED_123), nets)
        self.assertFalse(not_i2c_despite_name(ctx, "LCD_SDA"))
        self.assertEqual(sorted(_obs(ctx)), ["LCD_SCL", "LCD_SDA"])
        self.assertEqual(sorted(_bus(ctx)), ["LCD_SCL", "LCD_SDA"])
        open_ctx = _ctx((display, _res("R1"), _res("R2"),
                         _jumper("Jumper:SolderJumper_3_Open")), nets)
        self.assertTrue(not_i2c_despite_name(open_ctx, "LCD_SDA"))
        self.assertEqual(_obs(open_ctx), {})


if __name__ == "__main__":
    unittest.main()
