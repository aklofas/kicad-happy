"""A regulator enable pin held on ground is reported as tied to ground, not as always enabled.

An overbar (active-low) enable on ground is enabled by it and stays always on; any other
enable's polarity is not known from its name.
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from domain_detectors import build_power_sequencing_graph  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from schematic.system_analyses import analyze_power_sequencing  # noqa: E402

# ref -> (enable pin name, enable net)
ENABLES = {"U1": ("EN", "GND"), "U2": ("~{EN}", "GND"), "U3": ("~{SHDN}", "GND"),
           "U4": ("EN", "+5V"), "U5": ("EN", "EN_FLOAT"), "U6": ("~{ON}/OFF", "GND"),
           "U7": ("EN", "VSS_SW_EN"), "U8": ("EN", "VSS_DRV")}


def _ctx():
    comps, nets = [], {"+5V": [], "GND": [], "EN_FLOAT": [], "VSS_SW_EN": [], "VSS_DRV": []}
    for ref, (en_name, en_net) in ENABLES.items():
        comps.append({"reference": ref, "type": "ic", "value": "REG", "lib_id": "Regulator:REG",
                      "footprint": "", "properties": {},
                      "pins": [{"number": "1", "name": "VIN"}, {"number": "2", "name": "GND"},
                               {"number": "3", "name": en_name}, {"number": "4", "name": "VOUT"}]})
        nets["+5V"].append(dict(component=ref, pin_number="1", pin_name="VIN", pin_type="power_in"))
        nets["GND"].append(dict(component=ref, pin_number="2", pin_name="GND", pin_type="power_in"))
        nets[en_net].append(dict(component=ref, pin_number="3", pin_name=en_name, pin_type="input"))
        nets["OUT_" + ref] = [dict(component=ref, pin_number="4", pin_name="VOUT", pin_type="power_out")]
    # U8's enable net has a driver: a connector pin
    comps.append({"reference": "J1", "type": "connector", "value": "CONN", "lib_id": "Connector:C",
                  "footprint": "", "properties": {}, "pins": [{"number": "1", "name": "1"}]})
    nets["VSS_DRV"].append(dict(component="J1", pin_number="1", pin_name="1", pin_type="passive"))
    full = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False, "has_pwr_flag": False,
                "labels": []} for n, ps in nets.items()}
    return build_analysis_context(comps, full, {}, known_power_rails={"+5V", "GND"}, source="test")


def _regs():
    return [{"ref": ref, "output_rail": "OUT_" + ref} for ref in ENABLES]


class DependencyEnSource(unittest.TestCase):
    def setUp(self):
        self.out = analyze_power_sequencing(_ctx(), {"power_regulators": _regs()})
        self.deps = {d["regulator"]: d for d in self.out["dependencies"]}

    def test_plain_enable_on_ground_is_tied_to_ground(self):
        self.assertEqual(self.deps["U1"]["en_source"], "tied_to_ground")
        self.assertEqual(self.deps["U1"]["en_driven_by"], "GND")

    def test_overbar_enable_on_ground_stays_always_on(self):
        self.assertEqual(self.deps["U2"]["en_source"], "always_on")

    def test_overbar_shutdown_on_ground_is_tied_to_ground(self):
        self.assertEqual(self.deps["U3"]["en_source"], "tied_to_ground")

    def test_enable_on_a_rail_is_always_on(self):
        self.assertEqual(self.deps["U4"]["en_source"], "always_on")
        self.assertEqual(self.deps["U4"]["en_driven_by"], "+5V")

    def test_floating_enable_is_floating(self):
        self.assertEqual(self.deps["U5"]["en_source"], "floating")

    def test_enable_on_a_vss_named_net_is_not_tied_to_ground(self):
        # VSS can be a negative supply: the enable keeps its pre-ground-test reading
        for ref in ("U7", "U8"):
            self.assertEqual(self.deps[ref]["en_source"], "disabled", ref)
            self.assertEqual(self.deps[ref]["en_net"], ENABLES[ref][1], ref)

    def test_observation_lists_only_the_always_on_regulators(self):
        self.assertIn("2 regulator(s) always enabled: U2, U4", self.out["observations"])


class PowerTreeEnableType(unittest.TestCase):
    def setUp(self):
        out = build_power_sequencing_graph(_ctx(), _regs(), [], [])
        self.tree = {e["source"]: e for e in out["power_tree"]}

    def test_enable_on_ground_is_tied_to_ground_with_no_sequence_order(self):
        for ref in ("U1", "U3"):
            self.assertEqual(self.tree[ref]["enable_type"], "tied_to_ground", ref)
            self.assertEqual(self.tree[ref]["enabled_by"], "GND", ref)
            self.assertNotIn("sequence_order", self.tree[ref], ref)

    def test_overbar_enable_on_ground_is_always_on_and_starts_the_sequence(self):
        for ref in ("U2", "U6"):
            self.assertEqual(self.tree[ref]["enable_type"], "always_on", ref)
            self.assertEqual(self.tree[ref]["enabled_by"], "GND", ref)
            self.assertEqual(self.tree[ref]["sequence_order"], 0, ref)

    def test_enable_on_a_rail_starts_the_sequence(self):
        self.assertEqual(self.tree["U4"]["enable_type"], "tied_to_rail")
        self.assertEqual(self.tree["U4"]["sequence_order"], 0)

    def test_floating_enable_is_floating(self):
        self.assertEqual(self.tree["U5"]["enable_type"], "floating")

    def test_enable_on_a_vss_named_net_is_not_tied_to_ground(self):
        self.assertEqual(self.tree["U7"]["enable_type"], "floating")
        self.assertEqual(self.tree["U8"]["enable_type"], "gpio_controlled")
        self.assertEqual(self.tree["U8"]["enabled_by"], "J1")


if __name__ == "__main__":
    unittest.main()
