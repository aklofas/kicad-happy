# tools/tests/test_topology_rails.py
"""A named net is a power rail by its pins: every IC pin on it is a supply input or a power
output, and a capacitor goes to ground. A reference node, a divider midpoint, a crystal
pin, a bootstrap node, a flying cap and a motor-driver output stay signals. VM-001 keeps reading an IC's I/O level from its
named rails, and CS-DET keeps a shunt whose sense side is such a rail."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
import signal_detectors as sd  # noqa: E402
import validation_detectors as vd  # noqa: E402


def _ctx(components, nets, rails=("+3V3", "GND")):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    for c in components:
        c.setdefault("lib_id", "")
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
    return build_analysis_context(components, full, {}, known_power_rails=set(rails))


def _ic(ref, value="IC"):
    return {"reference": ref, "type": "ic", "value": value}


def _r(ref, value):
    return {"reference": ref, "type": "resistor", "value": value}


def _c(ref, value="100n"):
    return {"reference": ref, "type": "capacitor", "value": value}


def _p(ref, pin):
    return (ref, pin, "~", "passive")


class TopologyRails(unittest.TestCase):
    def test_passive_vcc_pins_with_a_pull_up_make_a_rail(self):
        # Two transceivers' VCC pins (typed passive), a cap to GND and a FAULT pull-up
        ctx = _ctx([_ic("U1"), _ic("U2"), _c("C1"), _r("R1", "10k")],
                   {"CAN_VCC_PROTECTED": [("U1", "1", "VCC", "passive"),
                                          ("U2", "1", "VCC", "passive"),
                                          _p("C1", "1"), _p("R1", "1")],
                    "CAN_FAULT": [_p("R1", "2"), ("U1", "2", "FAULT", "open_collector")],
                    "GND": [_p("C1", "2"), ("U1", "3", "GND", "power_in"),
                            ("U2", "3", "GND", "power_in")]})
        self.assertIn("CAN_VCC_PROTECTED", ctx.topology_rails)
        self.assertTrue(ctx.is_power_net("CAN_VCC_PROTECTED"))
        self.assertFalse(ctx.is_power_net("CAN_VCC_PROTECTED", by_pins=False))
        self.assertEqual(sd.detect_rc_filters(ctx, [], [], []), [])
        self.assertEqual([d["rail"] for d in sd.detect_decoupling(ctx)],
                         ["CAN_VCC_PROTECTED"])

    def test_fet_drawn_as_an_ic_beside_power_inputs_makes_a_rail(self):
        ctx = _ctx([_ic("U1", "P-FET"), _ic("U2"), _c("C1", "10u")],
                   {"4.5V-28V IN": [("U1", "1", "S", "passive"),
                                    ("U2", "1", "VSYS", "power_in"),
                                    _p("C1", "1")],
                    "GND": [_p("C1", "2"), ("U2", "2", "GND", "power_in")]})
        self.assertIn("4.5V-28V IN", ctx.topology_rails)

    def test_passive_pins_alone_need_a_supply_name(self):
        # A crystal pin with its load cap: OSC_IN is no supply, though it ends in IN
        ctx = _ctx([_ic("U1"), _c("C1", "18p")],
                   {"OSC_IN": [("U1", "1", "OSC_IN", "passive"), _p("C1", "1")],
                    "GND": [_p("C1", "2")]})
        self.assertEqual(ctx.topology_rails, frozenset())

    def test_reference_node_stays_a_signal(self):
        ctx = _ctx([_ic("U1"), _c("C1")],
                   {"VREF_OUT": [("U1", "1", "OUT", "power_out"), _p("C1", "1")],
                    "GND": [_p("C1", "2")]})
        self.assertEqual(ctx.topology_rails, frozenset())

    def test_divider_midpoint_stays_a_signal(self):
        ctx = _ctx([_ic("U1"), _c("C1"), _r("R1", "100k"), _r("R2", "10k")],
                   {"VBAT_SENSE": [("U1", "1", "VIN", "power_in"), _p("C1", "1"),
                                   _p("R1", "2"), _p("R2", "1")],
                    "+3V3": [_p("R1", "1")],
                    "GND": [_p("C1", "2"), _p("R2", "2")]})
        self.assertEqual(ctx.topology_rails, frozenset())

    def test_bootstrap_and_switch_nodes_stay_signals(self):
        # A high-side driver's VS (the IC has a VB pin) and a BST node capped to SW
        ctx = _ctx([_ic("U1"), _c("C1"), _c("C2")],
                   {"HS": [("U1", "1", "VS", "power_in"), _p("C1", "1")],
                    "HB": [("U1", "2", "VB", "power_in"), _p("C2", "1")],
                    "SW_BOOT": [("U1", "3", "BST", "power_in"), _p("C2", "2")],
                    "GND": [_p("C1", "2")]})
        self.assertEqual(ctx.topology_rails, frozenset())

    def test_flying_cap_stays_a_signal(self):
        # A charge pump's flying cap joins C1+ and C1-, not ground
        ctx = _ctx([_ic("U1", "MAX232"), _c("C1", "1u")],
                   {"C1P": [("U1", "1", "C1+", "passive"), _p("C1", "1")],
                    "C1N": [("U1", "3", "C1-", "passive"), _p("C1", "2")]})
        self.assertEqual(ctx.topology_rails, frozenset())

    def test_motor_driver_outputs_stay_signals(self):
        # DRV8833 bridge outputs are typed power_out; EMI caps to GND do not make them rails
        comps = [_ic("U1", "DRV8833PWP"), _c("C1", "10n"), _c("C2", "10n")]
        comps[0]["lib_id"] = "Driver_Motor:DRV8833PWP"
        ctx = _ctx(comps, {"MOTOR_A": [("U1", "2", "AOUT1", "power_out"), _p("C1", "1")],
                           "MOTOR_B": [("U1", "4", "AOUT2", "power_out"), _p("C2", "1")],
                           "GND": [_p("C1", "2"), _p("C2", "2")]})
        self.assertEqual(ctx.topology_rails, frozenset())
        # A part the classifier names a motor driver: any power_out pin, whatever its name
        ctx = _ctx(comps[:2], {"PHASE": [("U1", "2", "MOT", "power_out"), _p("C1", "1")],
                               "GND": [_p("C1", "2")]})
        self.assertEqual(ctx.topology_rails, frozenset())

    def test_bridge_outputs_of_an_unclassified_part_stay_signals(self):
        # A custom-library H-bridge (OUT1/OUT2 power_out) makes no rail; a dual-output
        # regulator's OUT1/OUT2 do, and so does an unclassified PMIC output that feeds
        # a supply input
        comps = [_ic("U1", "TLE9201SG"), _ic("U2", "LP3996"), _ic("U3", "ACT8945A"),
                 _ic("U4", "SOC"), _c("C1", "10n"), _c("C2", "10n"), _c("C3", "1u"),
                 _c("C4", "1u"), _c("C5", "1u"), _c("C6", "1u")]
        comps[1]["lib_id"] = "Regulator_Linear:LP3996SD"
        ctx = _ctx(comps, {"ETB_P": [("U1", "1", "OUT1", "power_out"), _p("C1", "1")],
                           "ETB_N": [("U1", "2", "OUT2", "power_out"), _p("C2", "1")],
                           "LDO_A": [("U2", "1", "OUT1", "power_out"), _p("C3", "1")],
                           "LDO_B": [("U2", "2", "OUT2", "power_out"), _p("C4", "1")],
                           "VDDCORE": [("U3", "1", "OUT1", "power_out"),
                                       ("U4", "1", "VDDCORE", "power_in"), _p("C5", "1")],
                           "PMIC_SPARE": [("U3", "2", "OUT2", "power_out"), _p("C6", "1")],
                           "GND": [_p(f"C{i}", "2") for i in range(1, 7)]})
        self.assertEqual(ctx.topology_rails, frozenset({"LDO_A", "LDO_B", "VDDCORE"}))


class Containment(unittest.TestCase):
    def test_vm001_reads_the_io_level_from_the_named_rail(self):
        # U1's first supply by pin order is a 1.2 V core rail known only by its pins
        comps = [_ic("U1", "MCU"), _ic("U2", "MCU"), _c("C1")]
        nets = {"D1V2": [("U1", "1", "VDDCORE", "power_in"), _p("C1", "1")],
                "+3V3": [("U1", "2", "VDDIO", "power_in"), ("U2", "1", "VDD", "power_in")],
                "GND": [_p("C1", "2"), ("U1", "3", "GND", "power_in"),
                        ("U2", "2", "GND", "power_in")],
                "SIG": [("U1", "4", "PA0", "output"), ("U2", "3", "PB0", "input")]}
        ctx = _ctx(comps, nets)
        self.assertIn("D1V2", ctx.topology_rails)
        with patch.object(vd, "get_regulator_features", return_value=None):
            found = vd.validate_voltage_levels(ctx)
        self.assertEqual([f for f in found if f["rule_id"] == "VM-001"], [])

    def test_shunt_onto_a_rail_known_by_pins_is_still_a_shunt(self):
        # SRP beside a power input makes SENSE_HI a rail; the gauge still senses the shunt
        comps = [_ic("U1", "BQ27441"), _ic("U2"), _r("R1", "0.01"), _c("C1")]
        nets = {"SENSE_HI": [_p("R1", "1"), ("U1", "1", "SRP", "passive"),
                             ("U2", "1", "VIN", "power_in"), _p("C1", "1")],
                "SENSE_LO": [_p("R1", "2"), ("U1", "2", "SRN", "passive")],
                "GND": [_p("C1", "2"), ("U2", "2", "GND", "power_in")]}
        ctx = _ctx(comps, nets)
        self.assertIn("SENSE_HI", ctx.topology_rails)
        self.assertEqual([(c["shunt"]["ref"], c["sense_ic"]["ref"])
                          for c in sd.detect_current_sense(ctx)], [("R1", "U1")])


if __name__ == "__main__":
    unittest.main()
