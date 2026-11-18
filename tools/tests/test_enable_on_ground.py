"""A regulator enable pin held on ground is reported as tied to ground, not as always enabled.

An overbar (active-low) enable on ground is enabled by it and stays always on; any other
enable's polarity is not known from its name. A VSS net that no regulator drives is ground
like GND. An enable held only by pull-ups to a supply (a UVLO divider, a delay capacitor
beside it) is always on too; a pull-down is not a pull-up.
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from domain_detectors import build_power_sequencing_graph  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from schematic.system_analyses import analyze_power_sequencing, analyze_sleep_current  # noqa: E402

# ref -> (enable pin name, enable net)
ENABLES = {"U1": ("EN", "GND"), "U2": ("~{EN}", "GND"), "U3": ("~{SHDN}", "GND"),
           "U4": ("EN", "+5V"), "U5": ("EN", "EN_FLOAT"), "U6": ("~{ON}/OFF", "GND"),
           "U7": ("EN", "VSS_AUX"), "U8": ("EN", "VSS_DRV")}


def _ctx():
    comps, nets = [], {"+5V": [], "GND": [], "EN_FLOAT": [], "VSS_AUX": [], "VSS_DRV": []}
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

    def test_enable_on_a_vss_ground_is_tied_to_ground(self):
        for ref in ("U7", "U8"):
            self.assertEqual(self.deps[ref]["en_source"], "tied_to_ground", ref)
            self.assertEqual(self.deps[ref]["en_driven_by"], ENABLES[ref][1], ref)

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

    def test_enable_on_a_vss_ground_is_tied_to_ground(self):
        for ref in ("U7", "U8"):
            self.assertEqual(self.tree[ref]["enable_type"], "tied_to_ground", ref)
            self.assertEqual(self.tree[ref]["enabled_by"], ENABLES[ref][1], ref)


def _pull_ctx(extra_regs=None, extra_parts=None):
    """Enables held by resistors and capacitors. Pin 1 of each two-pin part sits on the EN net."""
    regs = {"U1": ("+12V", "EN1"), "U2": ("+12V", "EN2"), "U3": ("+12V", "EN3"),
            "U4": ("+48V", "EN4"), "U5": ("+5V", "EN5"), "U6": ("+5V", "EN6"),
            "U7": ("__unnamed_7", "EN7")}
    # ref -> (type, value, far-end net); the near end (pin 1) is the EN net named alongside
    parts = {"R1": ("resistor", "100k", "EN1", "+12V"),
             "R2": ("resistor", "10k", "EN2", "GND"),
             "R3": ("resistor", "10k", "EN3", "GND"),
             "R4": ("resistor", "560k", "EN4", "+48V"), "R5": ("resistor", "33k", "EN4", "GND"),
             "R6": ("resistor", "10k", "EN5", "+5V"), "C1": ("capacitor", "1u", "EN5", "GND"),
             "R7": ("resistor", "10k", "EN6", "+5V"),
             "R8": ("resistor", "100k", "EN7", "__unnamed_7")}
    regs.update(extra_regs or {})
    parts.update(extra_parts or {})
    comps, nets = [], {}

    def add(net, ref, num, name, ptype):
        nets.setdefault(net, []).append(dict(component=ref, pin_number=num, pin_name=name,
                                             pin_type=ptype))

    for ref, (vin, en) in regs.items():
        comps.append({"reference": ref, "type": "ic", "value": "REG", "lib_id": "Regulator:REG",
                      "footprint": "", "properties": {},
                      "pins": [{"number": "1", "name": "VIN"}, {"number": "2", "name": "GND"},
                               {"number": "3", "name": "EN"}, {"number": "4", "name": "VOUT"}]})
        add(vin, ref, "1", "VIN", "power_in")
        add("GND", ref, "2", "GND", "power_in")
        add(en, ref, "3", "EN", "input")
        add("OUT_" + ref, ref, "4", "VOUT", "power_out")
    for ref, (kind, value, near, far) in parts.items():
        comps.append({"reference": ref, "type": kind, "value": value, "lib_id": "Device:" + ref[0],
                      "footprint": "", "properties": {},
                      "pins": [{"number": "1", "name": "~"}, {"number": "2", "name": "~"}]})
        add(near, ref, "1", "~", "passive")
        add(far, ref, "2", "~", "passive")
    # U2's enable is also driven by a microcontroller GPIO
    comps.append({"reference": "U9", "type": "ic", "value": "MCU", "lib_id": "MCU:MCU",
                  "footprint": "", "properties": {}, "pins": [{"number": "7", "name": "PA7"}]})
    add("EN2", "U9", "7", "PA7", "bidirectional")
    full = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False, "has_pwr_flag": False,
                "labels": []} for n, ps in nets.items()}
    # U6's enable net leaves the sheet through a global label
    full["EN6"]["labels"] = [{"name": "EN6", "type": "global_label"}]
    ctx = build_analysis_context(comps, full, {}, known_power_rails={"+12V", "+48V", "+5V", "GND"},
                                 source="test")
    return ctx, [{"ref": ref, "input_rail": vin, "output_rail": "OUT_" + ref}
                 for ref, (vin, _) in regs.items()]


class EnableHeldByResistors(unittest.TestCase):
    def setUp(self):
        ctx, regs = _pull_ctx()
        out = analyze_power_sequencing(ctx, {"power_regulators": regs})
        self.deps = {d["regulator"]: d for d in out["dependencies"]}

    def test_pull_up_to_the_input_alone_is_always_on(self):
        self.assertEqual(self.deps["U1"]["en_source"], "always_on")
        self.assertTrue(self.deps["U1"].get("has_pull_up"))
        self.assertEqual(self.deps["U1"]["en_driven_by"], ["R1"])

    def test_pull_down_beside_a_gpio_is_controlled_and_not_a_pull_up(self):
        self.assertEqual(self.deps["U2"]["en_source"], "controlled")
        self.assertNotIn("has_pull_up", self.deps["U2"])

    def test_pull_down_alone_stays_controlled(self):
        # an enable named without an overbar may still be active low
        self.assertEqual(self.deps["U3"]["en_source"], "controlled")
        self.assertNotIn("has_pull_up", self.deps["U3"])

    def test_uvlo_divider_from_the_input_is_always_on(self):
        self.assertEqual(self.deps["U4"]["en_source"], "always_on")
        self.assertTrue(self.deps["U4"].get("has_pull_up"))

    def test_pull_up_with_a_delay_capacitor_is_always_on(self):
        self.assertEqual(self.deps["U5"]["en_source"], "always_on")
        self.assertTrue(self.deps["U5"].get("has_pull_up"))

    def test_labelled_enable_net_stays_controlled(self):
        # a global or hierarchical label may bring a driver from another sheet
        self.assertEqual(self.deps["U6"]["en_source"], "controlled")
        self.assertTrue(self.deps["U6"].get("has_pull_up"))

    def test_pull_up_to_an_unnamed_net_carrying_the_input_is_a_pull_up(self):
        self.assertTrue(self.deps["U7"].get("has_pull_up"))
        self.assertEqual(self.deps["U7"]["en_source"], "always_on")


class EnableHeldToAVssGround(unittest.TestCase):
    """A VSS net that no regulator drives is ground: a resistor to it is a pull-down."""

    def _deps(self, parts):
        ctx, regs = _pull_ctx({"U10": ("+12V", "EN10")}, parts)
        out = analyze_power_sequencing(ctx, {"power_regulators": regs})
        return {d["regulator"]: d for d in out["dependencies"]}["U10"]

    def test_uvlo_divider_to_vss_is_always_on(self):
        dep = self._deps({"R10": ("resistor", "560k", "EN10", "+12V"),
                          "R11": ("resistor", "33k", "EN10", "VSS")})
        self.assertEqual(dep["en_source"], "always_on")
        self.assertTrue(dep.get("has_pull_up"))

    def test_pull_down_to_vss_alone_stays_controlled(self):
        dep = self._deps({"R11": ("resistor", "10k", "EN10", "VSS")})
        self.assertEqual(dep["en_source"], "controlled")
        self.assertNotIn("has_pull_up", dep)


class SleepNoteForAnEnableThatIsNotSwitched(unittest.TestCase):
    def _iq(self):
        ctx, regs = _pull_ctx()
        for r in regs:
            r.update(value="AP2112K-3.3", topology="LDO")
        seq = analyze_power_sequencing(ctx, {"power_regulators": regs})
        rails = analyze_sleep_current(ctx, {"power_regulators": regs}, seq)["rails"]
        return {p["ref"]: p for r in rails.values() for p in r["current_paths"]
                if p["type"] == "regulator_iq"}

    def test_always_on_regulator_with_an_enable_pin_says_its_enable_is_not_switched(self):
        iq = self._iq()["U1"]
        self.assertEqual(iq["likely_state"], "always-on")
        self.assertEqual(iq["note"], "estimated Iq (always-on, EN not switched)")
        self.assertEqual(iq["realistic_uA"], iq["current_uA"])

    def test_enable_tied_to_the_input_says_its_enable_is_not_switched(self):
        regs = [dict(r, value="AP2112K-3.3", topology="LDO") for r in _regs()]
        ctx = _ctx()
        seq = analyze_power_sequencing(ctx, {"power_regulators": regs})
        rails = analyze_sleep_current(ctx, {"power_regulators": regs}, seq)["rails"]
        iq = next(p for p in rails["OUT_U4"]["current_paths"] if p["type"] == "regulator_iq")
        self.assertEqual(iq["likely_state"], "always-on")
        self.assertEqual(iq["note"], "estimated Iq (always-on, EN not switched)")
        self.assertEqual(iq["realistic_uA"], 55)

    def test_controlled_regulator_keeps_the_disable_note(self):
        iq = self._iq()["U2"]
        self.assertEqual(iq["likely_state"], "can be disabled via EN")
        self.assertEqual(iq["note"], "estimated Iq (can be disabled via EN)")
        self.assertEqual(iq["realistic_uA"], 0.0)


if __name__ == "__main__":
    unittest.main()
