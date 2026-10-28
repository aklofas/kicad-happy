"""analysis.power_rails.voltage_overrides and ignore reach the detectors, not only the summary.

Expected values are arithmetic on the parts and the VM-001 threshold table
(validation_detectors._VOLTAGE_THRESHOLDS: a 1.8 V-class input has a 2.0 V absolute maximum).
"""
import io, json, os, sys, tempfile, unittest
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "datasheets"))

import analyze_schematic as cli  # noqa: E402
import lookup_detectors  # noqa: E402
from datasheet_types import Evidence, SpecValue  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from schematic.pipeline import analyze_schematic, detect_topologies  # noqa: E402

_n = [0]


def _uuid():
    _n[0] += 1
    return f"00000000-0000-0000-0000-{_n[0]:012d}"


def _lib(lib_id, ref, pins):
    """Pins on the x axis, 2.54 mm apart, connection point at the pin's own position."""
    short = lib_id.split(":")[-1]
    body = " ".join(f'(pin {kind} line (at {i * 2.54} 0 0) (length 0) (name "{name}") (number "{num}"))'
                    for i, (num, name, kind) in enumerate(pins))
    return (f'(symbol "{lib_id}" (in_bom yes) (on_board yes)'
            f' (property "Reference" "{ref}" (at 0 0 0)) (property "Value" "{short}" (at 0 0 0))'
            f' (symbol "{short}_1_1" {body}))')


IC = [("1", "VDD", "power_in"), ("2", "GND", "power_in"), ("3", "IO", "bidirectional")]
REG = [("1", "GND", "power_in"), ("2", "VO", "power_out"), ("3", "VI", "power_in")]
TWO = [("1", "~", "passive"), ("2", "~", "passive")]
LED = [("1", "K", "passive"), ("2", "A", "passive")]

# ref, lib_id, value, pins, net per pin
PARTS = [
    ("U1", "t:MCU_CORE", "MCU_CORE", IC, ["VDD_CORE", "GND", "SIG"]),
    ("U2", "t:MCU_IO", "MCU_IO", IC, ["+3V3", "GND", "SIG"]),
    ("U5", "Regulator_Linear:AMS1117-3.3", "AMS1117-3.3", REG, ["GND", "+3V3", "+5V"]),
    ("U3", "t:FAKE-LOAD", "FAKE-LOAD", [("1", "VIN", "power_in"), ("2", "GND", "power_in")],
     ["+5V", "GND"]),
    ("R1", "Device:R", "100", TWO, ["+12V", "LED_A"]),
    ("D1", "Device:LED", "LED", LED, ["GND", "LED_A"]),
    ("R2", "Device:R", "10k", TWO, ["+12V", "GND"]),
]


def write_project(tmp):
    _n[0] = 0
    libs, items = {}, []
    for k, (ref, lib_id, value, pins, nets) in enumerate(PARTS):
        libs[lib_id] = _lib(lib_id, ref.rstrip("0123456789"), pins)
        x, y = 50.8, 25.4 * (k + 1)
        pl = " ".join(f'(pin "{num}" (uuid "{_uuid()}"))' for num, _, _ in pins)
        items.append(f'(symbol (lib_id "{lib_id}") (at {x} {y} 0) (unit 1) (in_bom yes) (on_board yes)'
                     f' (uuid "{_uuid()}") (property "Reference" "{ref}" (at {x} {y} 0))'
                     f' (property "Value" "{value}" (at {x} {y} 0)) {pl}'
                     f' (instances (project "t" (path "/00000000-0000-0000-0000-0000000000aa"'
                     f' (reference "{ref}") (unit 1)))))')
        for i, net in enumerate(nets):
            items.append(f'(label "{net}" (at {round(x + i * 2.54, 2)} {y} 0) (uuid "{_uuid()}"))')
    path = os.path.join(tmp, "t.kicad_sch")
    with open(path, "w", encoding="utf-8") as f:
        f.write('(kicad_sch (version 20231120) (generator "eeschema")'
                ' (uuid "00000000-0000-0000-0000-0000000000aa") (paper "A4")'
                f' (lib_symbols {" ".join(libs.values())}) {" ".join(items)}'
                ' (sheet_instances (path "/" (page "1"))))\n')
    with open(os.path.join(tmp, "t.kicad_pro"), "w", encoding="utf-8") as f:
        f.write('{"meta":{"filename":"t.kicad_pro","version":1}}')
    return path


def _load_facts(mpn, **_kw):
    # FAKE-LOAD: VIN pin rated 3.6 V absolute maximum.
    if mpn != "FAKE-LOAD":
        return None
    vin_max = SpecValue(unit="V", evidence=Evidence(page=1, confidence="high", method="table"), max=3.6)
    pin = SimpleNamespace(numbers=["1"], name="VIN", power_domain="VIN", absolute_max=None,
                          is_5v_tolerant=None)
    return SimpleNamespace(base=SimpleNamespace(absolute_max={"VIN_max": [vin_max]}, pinout=[pin],
                                                recommended_operating=None))


def run(power_rails_config=None):
    with tempfile.TemporaryDirectory() as tmp:
        path = write_project(tmp)
        with redirect_stderr(io.StringIO()), \
                patch.object(lookup_detectors, "get_facts", side_effect=_load_facts):
            return analyze_schematic(path, power_rails_config=power_rails_config)


def rule(result, rule_id):
    return [f for f in result["findings"] if f.get("rule_id") == rule_id]


class Fixture(unittest.TestCase):
    """The schematic is wired as PARTS says (a broken fixture would make every test vacuous)."""

    def test_nets(self):
        nets = run()["nets"]
        self.assertEqual(sorted(f'{p["component"]}.{p["pin_number"]}' for p in nets["SIG"]["pins"]),
                         ["U1.3", "U2.3"])
        self.assertEqual(sorted(f'{p["component"]}.{p["pin_number"]}' for p in nets["+12V"]["pins"]),
                         ["R1.1", "R2.1"])


class VoltageOverride(unittest.TestCase):
    def test_override_adds_a_rail_and_vm001_sees_it(self):
        base = run()
        self.assertNotIn("VDD_CORE", base["rail_voltages"])
        self.assertEqual(rule(base, "VM-001"), [])
        got = run({"voltage_overrides": {"VDD_CORE": 1.2}})
        self.assertEqual(got["rail_voltages"]["VDD_CORE"], 1.2)
        (vm,) = rule(got, "VM-001")
        # U2 at 3.3 V drives U1 at 1.2 V; a 1.8 V-class input's absolute max is 2.0 V < 3.3 V.
        self.assertEqual((vm["nets"], vm["severity"], vm["components"]), (["SIG"], "error", ["U1", "U2"]))
        self.assertIn("3.3V / 1.2V", vm["summary"])
        self.assertEqual(vm["rail_voltage_source"], "config")

    def test_am001_reads_the_override(self):
        base = run()
        (am,) = rule(base, "AM-001")
        # +5V by name: 5.0 V > 3.6 V.
        self.assertEqual((am["rail_voltage"], "rail_voltage_source" in am), (5.0, False))
        self.assertEqual(rule(run({"voltage_overrides": {"+5V": 3.3}}), "AM-001"), [])  # 3.3 <= 3.6
        (am,) = rule(run({"voltage_overrides": {"+5V": 4.0}}), "AM-001")             # 4.0 > 3.6
        self.assertEqual((am["rail_voltage"], am["rail_voltage_source"]), (4.0, "config"))

    def test_override_does_not_rewrite_the_regulator_estimate(self):
        got = run({"voltage_overrides": {"+3V3": 3.0}})
        (reg,) = [f for f in rule(got, "PR-DET") if f["ref"] == "U5"]
        self.assertEqual(reg["estimated_vout"], 3.3)
        self.assertEqual(got["rail_voltages"]["+3V3"], 3.0)
        self.assertNotIn("vout_net_mismatch", json.dumps(got["findings"]))

    def test_bare_name_override_applies_to_a_sheet_instance_net(self):
        net = "/0b1e6a52-3c1d-4e0f-9a8b-1c2d3e4f5a61/+3V3"
        pins = [dict(component="R1", pin_number="1", pin_name="~", pin_type="passive")]
        nets = {net: {"name": net, "pins": pins, "point_count": 0, "no_connect": False,
                      "has_pwr_flag": False, "labels": []}}
        ctx = build_analysis_context([{"reference": "R1", "type": "resistor", "value": "10k"}], nets, {},
                                     known_power_rails=set(), source="test",
                                     power_rails_config={"voltage_overrides": {"+3V3": 3.0}})
        topo = detect_topologies(ctx)
        self.assertEqual(ctx.rail_voltage(net), 3.0)
        self.assertEqual(topo["rail_voltages"], {"+3V3": 3.0})


class IgnoredRail(unittest.TestCase):
    def test_ignored_rail_leaves_map_sleep_audit_and_lr001(self):
        base = run()
        self.assertEqual(base["rail_voltages"]["+12V"], 12.0)
        self.assertIn("+12V", base["sleep_current_audit"]["rails"])
        # (12 V - 2 V) / 100 ohm = 100 mA > 2 x 20 mA, and 0.1 A^2 x 100 ohm = 1 W > 250 mW.
        self.assertEqual(len(rule(base, "LR-001")), 2)
        got = run({"ignore": ["+12V"]})
        self.assertNotIn("+12V", got["rail_voltages"])
        self.assertNotIn("+12V", got["sleep_current_audit"].get("rails", {}))
        self.assertEqual(rule(got, "LR-001"), [])

    def test_ignored_regulator_output_leaves_sleep_audit_and_power_budget(self):
        base = run()
        self.assertEqual([p["type"] for p in base["sleep_current_audit"]["rails"]["+3V3"]["current_paths"]],
                         ["regulator_iq"])
        self.assertIn("+3V3", base["power_budget"]["rails"])
        got = run({"ignore": ["+3V3"]})
        self.assertNotIn("+3V3", got["sleep_current_audit"]["rails"])
        self.assertNotIn("+3V3", got["power_budget"]["rails"])


class NoConfig(unittest.TestCase):
    def test_empty_config_is_byte_identical(self):
        base = json.dumps(run(), sort_keys=False)
        for cfg in ({}, {"voltage_overrides": {}, "ignore": []}):
            self.assertEqual(json.dumps(run(cfg), sort_keys=False), base)


class Cli(unittest.TestCase):
    def test_config_file_reaches_detection_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_project(tmp)
            cfg = os.path.join(tmp, "cfg.json")
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump({"analysis": {"power_rails": {"voltage_overrides": {"VDD_CORE": 1.2},
                                                        "ignore": ["+12V"]}}}, f)
            out = os.path.join(tmp, "out.json")
            with redirect_stderr(io.StringIO()), \
                    patch.object(lookup_detectors, "get_facts", side_effect=_load_facts):
                self.assertEqual(cli.main([path, "--config", cfg, "--output", out]), 0)
            with open(out, encoding="utf-8") as f:
                got = json.load(f)
        self.assertEqual(got["rail_voltages"]["VDD_CORE"], 1.2)
        self.assertNotIn("+12V", got["rail_voltages"])
        rails = {r["name"]: r for r in got["statistics"]["power_rails"]}
        self.assertEqual(rails["VDD_CORE"], {"name": "VDD_CORE", "voltage": 1.2, "source": "config"})
        self.assertNotIn("source", rails["+5V"])
        self.assertNotIn("+12V", rails)
        self.assertEqual([f["rail_voltage_source"] for f in rule(got, "VM-001")], ["config"])
        self.assertEqual(rule(got, "LR-001"), [])


if __name__ == "__main__":
    unittest.main()
