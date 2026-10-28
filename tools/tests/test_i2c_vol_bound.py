# tools/tests/test_i2c_vol_bound.py
"""The I2C VOL check flags a pull-up below UM10204's lower bound Rp(min) = (VDD - 0.4 V) / 3 mA,
with the line's fitted pull-ups combined in parallel and VDD read from the rail map."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
from schematic.net_analysis import _detect_i2c_buses, _estimate_rail_voltage  # noqa: E402
from schematic.pipeline import build_rail_map  # noqa: E402
from schematic.system_analyses import analyze_protocol_compliance  # noqa: E402

SENSOR = {"reference": "U1", "type": "ic", "value": "BME280", "lib_id": "Sensor:BME280",
          "pins": [{"number": "1", "name": "SDA", "type": "bidirectional"},
                   {"number": "2", "name": "SCL", "type": "input"}]}


def _res(ref, value, dnp=False):
    comp = {"reference": ref, "type": "resistor", "value": value, "lib_id": "Device:R",
            "pins": [{"number": "1", "name": "~", "type": "passive"},
                     {"number": "2", "name": "~", "type": "passive"}]}
    if dnp:
        comp["dnp"] = True
    return comp


def _vol(sda_pullups, scl_rail="+3V3", power_rails_config=None, regulators=()):
    """VOL record for a sensor whose SDA pull-ups are ``[(value, rail[, dnp])]`` (SCL: 4.7k)."""
    comps = [SENSOR, _res("R9", "4.7k")]
    nets = {"SDA": [("U1", "1", "SDA", "bidirectional")],
            "SCL": [("U1", "2", "SCL", "input"), ("R9", "1", "~", "passive")],
            scl_rail: [("R9", "2", "~", "passive")]}
    for i, (value, rail, *dnp) in enumerate(sda_pullups, 1):
        comps.append(_res(f"R{i}", value, dnp=bool(dnp and dnp[0])))
        nets["SDA"].append((f"R{i}", "1", "~", "passive"))
        nets.setdefault(rail, []).append((f"R{i}", "2", "~", "passive"))
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "labels": []}
            for n, pins in nets.items()}
    rails = {r for _, r, *_ in sda_pullups} | {scl_rail}
    ctx = build_analysis_context(comps, full, {}, known_power_rails=rails,
                                 power_rails_config=power_rails_config)
    ctx.rail_by_net = build_rail_map(ctx, list(regulators))
    design = {"bus_analysis": {"i2c": _detect_i2c_buses(ctx)}}
    out = analyze_protocol_compliance(comps, ctx.nets, design, {}, ctx.pin_net, ctx=ctx)
    i2c = [f for f in out.get("findings", []) if f["protocol"] == "i2c"]
    return i2c[0]["checks"].get("vol_compatibility") if i2c else None


class I2cVolLowerBound(unittest.TestCase):
    def test_standard_pull_up_meets_vol(self):
        self.assertIsNone(_vol([("4.7k", "+3V3")]))

    def test_strong_pull_up_on_3v3_is_flagged(self):
        vc = _vol([("820", "+3V3")])
        self.assertEqual(vc["status"], "warning")
        self.assertEqual(vc["pull_up_ohms"], 820)
        self.assertEqual(vc["min_for_vol"], 967)  # (3.3 - 0.4) / 3 mA
        self.assertEqual(vc["pull_up_voltage"], 3.3)
        self.assertEqual(vc["iol_ma"], 3)
        self.assertNotIn("max_for_vol", vc)

    def test_parallel_pull_ups_are_combined(self):
        vc = _vol([("2.2k", "+3V3"), ("1k", "+3V3")])
        self.assertEqual(vc["pull_up_ohms"], 688)  # 2.2k || 1k
        self.assertEqual(vc["min_for_vol"], 967)

    def test_1k_on_5v_is_flagged(self):
        vc = _vol([("1k", "+5V")])
        self.assertEqual(vc["min_for_vol"], 1533)  # (5 - 0.4) / 3 mA
        self.assertEqual(vc["pull_up_voltage"], 5.0)

    def test_unknown_rail_voltage_gives_no_record(self):
        self.assertIsNone(_vol([("820", "VDD_IO")]))

    def test_two_standard_pull_ups_in_parallel_meet_vol(self):
        self.assertIsNone(_vol([("4.7k", "+3V3"), ("4.7k", "+3V3")]))  # 2.35k > 967

    def test_unfitted_pull_up_is_not_in_parallel(self):
        self.assertIsNone(_vol([("1.5k", "+3V3"), ("1.5k", "+3V3", True)]))  # 750 if both fitted

    def test_rail_voltage_override_reaches_the_check(self):
        cfg = {"voltage_overrides": {"VDD_IO": 1.8}}
        self.assertIsNone(_vol([("820", "VDD_IO")], power_rails_config=cfg))  # (1.8-0.4)/3mA = 467
        vc = _vol([("390", "VDD_IO")], power_rails_config=cfg)
        self.assertEqual(vc["min_for_vol"], 467)

    def test_rail_estimate_beyond_the_i2c_range_is_not_checked(self):
        reg = {"output_rail": "VDD", "estimated_vout": 49.4}
        self.assertIsNone(_vol([("5.1k", "VDD")], regulators=[reg]))
        reg = {"output_rail": "VDD", "estimated_vout": 5.0}
        self.assertEqual(_vol([("1k", "VDD")], regulators=[reg])["min_for_vol"], 1533)

    def test_usb_data_line_is_not_a_5v_pull_up_rail(self):
        self.assertEqual(_estimate_rail_voltage("USB_FS_DM"), 5.0)  # the name parse alone would say 5 V
        comps = [SENSOR, _res("R1", "820")]
        nets = {n: {"name": n, "pins": [], "point_count": 0, "no_connect": False, "labels": []}
                for n in ("SDA", "USB_FS_DM")}
        ctx = build_analysis_context(comps, nets, {}, known_power_rails=set())
        ctx.rail_by_net = build_rail_map(ctx, [])
        self.assertNotIn("USB_FS_DM", ctx.rail_by_net)
        pu = {"ref": "R1", "value": "820", "ohms": 820.0, "to_rail": "USB_FS_DM"}
        design = {"bus_analysis": {"i2c": [{"line": "SDA", "net": "SDA", "devices": ["U1"],
                                            "pull_ups": [pu]}]}}
        out = analyze_protocol_compliance(comps, nets, design, {}, {}, ctx=ctx)
        self.assertNotIn("vol_compatibility", out["findings"][0]["checks"])


if __name__ == "__main__":
    unittest.main()
