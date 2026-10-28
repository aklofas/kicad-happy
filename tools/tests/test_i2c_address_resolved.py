# tools/tests/test_i2c_address_resolved.py
"""IA-001 compares resolved 7-bit I2C addresses across part models (datasheet address tables);
devices whose address pins cannot be resolved give one info per bus, never an error."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from domain_detectors import detect_i2c_address_conflicts  # noqa: E402


def _ia(devices, rails=("+3V3",)):
    """IA-001 findings for ``[(ref, value, {pin_name: net})]``; every device also gets SDA/SCL/GND/VS."""
    comps, nets = [], {}
    for ref, value, straps in devices:
        pins = {"SDA": "SDA", "SCL": "SCL", "GND": "GND", "VS": "+3V3", **straps}
        comp = {"reference": ref, "type": "ic", "value": value, "lib_id": f"Lib:{value}", "pins": []}
        for i, (name, net) in enumerate(pins.items(), 1):
            comp["pins"].append({"number": str(i), "name": name, "type": "passive"})
            nets.setdefault(net, []).append(
                {"component": ref, "pin_number": str(i), "pin_name": name, "pin_type": "passive"})
        comps.append(comp)
    full = {n: {"name": n, "pins": p, "point_count": 0, "no_connect": False, "labels": []}
            for n, p in nets.items()}
    ctx = build_analysis_context(comps, full, {}, known_power_rails=set(rails))
    return [f for f in detect_i2c_address_conflicts(ctx) if f["rule_id"] == "IA-001"]


class ResolvedAddressConflicts(unittest.TestCase):
    def test_cross_model_conflict_at_resolved_address(self):
        # INA219 Table 2 / INA226 Table 2: A1=GND, A0=SDA -> 1000010 = 0x42.
        out = _ia([("U1", "INA219", {"A1": "GND", "A0": "SDA"}),
                   ("U2", "INA226", {"A1": "GND", "A0": "SDA"})])
        self.assertEqual(len(out), 1)
        f = out[0]
        self.assertEqual(f["severity"], "error")
        self.assertEqual(f["confidence"], "deterministic")
        self.assertEqual(f["components"], ["U1", "U2"])
        self.assertEqual(f["fix_params"]["basis"], "0x42")

    def test_same_model_same_straps(self):
        out = _ia([("U1", "INA219", {"A1": "GND", "A0": "GND"}),
                   ("U2", "INA219", {"A1": "GND", "A0": "GND"})])
        self.assertEqual([(f["severity"], f["fix_params"]["basis"]) for f in out], [("error", "0x40")])

    def test_same_model_distinct_straps(self):
        out = _ia([("U1", "INA219", {"A1": "GND", "A0": "GND"}),
                   ("U2", "INA219", {"A1": "GND", "A0": "+3V3"})])  # 0x40 vs 0x41
        self.assertEqual(out, [])

    def test_fixed_address_rtcs_collide(self):
        # DS3231 datasheet: slave address 1101000 = 0x68; DS1307 shares it.
        out = _ia([("U1", "DS1307", {}), ("U2", "DS3231", {})])
        self.assertEqual([(f["severity"], f["fix_params"]["basis"]) for f in out], [("error", "0x68")])

    def test_pcf8574a_is_not_pcf8574(self):
        # NXP PCF8574/74A Table 4 / Table 5: A2..A0 = VSS -> 0x20 / 0x38.
        low = {"A0": "GND", "A1": "GND", "A2": "GND"}
        self.assertEqual(_ia([("U1", "PCF8574A", low), ("U2", "PCF8574", low)]), [])

    def test_mcp4725_address_option_is_in_the_part_number(self):
        # MCP4725 section 7.2: A2:A1 by ordering code (A1 option = 01), A0 from the pin.
        self.assertEqual(_ia([("U1", "MCP4725A1T-E/CH", {"A0": "GND"}),
                              ("U2", "MCP4725A0T-E/CH", {"A0": "GND"})]), [])
        out = _ia([("U1", "MCP4725", {"A0": "GND"}), ("U2", "MCP4725", {"A0": "GND"})])
        self.assertEqual([f["fix_params"]["basis"] for f in out], ["0x60"])

    def test_unresolved_straps_give_one_info_without_a_fix(self):
        # ADDR on two distinct non-rail nets: the addresses differ or not, nothing proves a conflict.
        out = _ia([("U1", "ADS1115", {"ADDR": "ADDR1"}), ("U2", "ADS1115", {"ADDR": "ADDR2"})])
        self.assertEqual(len(out), 1)
        f = out[0]
        self.assertEqual(f["severity"], "info")
        self.assertEqual(f["components"], ["U1", "U2"])
        self.assertFalse(f.get("fix_params"))

    def test_strap_to_another_bus_data_line_is_unresolved(self):
        # SDA of this bus is "SDA"; "SDA2" is some other line, not a datasheet strap state.
        out = _ia([("U1", "INA219", {"A1": "GND", "A0": "SDA2"}),
                   ("U2", "INA219", {"A1": "GND", "A0": "SDA2"})])
        self.assertEqual([f["severity"] for f in out], ["info"])

    def test_single_table_device_on_bus_gives_nothing(self):
        self.assertEqual(_ia([("U1", "ADS1115", {"ADDR": "ADDR1"})]), [])


if __name__ == "__main__":
    unittest.main()
