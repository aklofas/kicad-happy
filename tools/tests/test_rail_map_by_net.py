import sys, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "datasheets"))

import lookup_detectors  # noqa: E402
from datasheet_types import Evidence, SpecValue  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from schematic.pipeline import detect_topologies, run_domain_detectors  # noqa: E402
from schematic.system_analyses import analyze_sleep_current  # noqa: E402

# Two instances of one sheet; each gets its VOUT from a regulator in the root.
VOUT1 = "/0b1e6a52-3c1d-4e0f-9a8b-1c2d3e4f5a61/VOUT"
VOUT2 = "/7d2f8c93-4a5b-4c6d-8e7f-9a0b1c2d3e4f/VOUT"
NEG5 = "/0b1e6a52-3c1d-4e0f-9a8b-1c2d3e4f5a61/-5V"


def _pin(ref, num, name, ptype):
    return dict(component=ref, pin_number=num, pin_name=name, pin_type=ptype)


def _ic(ref, value, pins):
    return {"reference": ref, "type": "ic", "value": value, "lib_id": "Regulator_Linear:" + value,
            "footprint": "", "properties": {}, "pins": [{"number": n, "name": nm} for n, nm in pins]}


def _ctx():
    comps = [_ic("U1", "AMS1117-5.0", [("1", "GND"), ("2", "VO"), ("3", "VI")]),
             _ic("U2", "AMS1117-3.3", [("1", "GND"), ("2", "VO"), ("3", "VI")]),
             _ic("U3", "FAKE-LOAD", [("1", "VIN"), ("2", "GND")]),
             _ic("U4", "FAKE-LOAD", [("1", "VIN"), ("2", "GND")]),
             {"reference": "R1", "type": "resistor", "value": "10k"},
             {"reference": "R2", "type": "resistor", "value": "10k"},
             {"reference": "R3", "type": "resistor", "value": "10k"}]
    nets = {
        "+12V": [_pin("U1", "3", "VI", "power_in"), _pin("U2", "3", "VI", "power_in")],
        "GND": [_pin(r, "1", "GND", "power_in") for r in ("U1", "U2")]
               + [_pin(r, "2", "GND", "power_in") for r in ("U3", "U4")]
               + [_pin(r, "2", "", "passive") for r in ("R1", "R2", "R3")],
        VOUT1: [_pin("U1", "2", "VO", "power_out"), _pin("U3", "1", "VIN", "power_in"),
                _pin("R1", "1", "", "passive")],
        VOUT2: [_pin("U2", "2", "VO", "power_out"), _pin("U4", "1", "VIN", "power_in"),
                _pin("R2", "1", "", "passive")],
        NEG5: [_pin("R3", "1", "", "passive")],
    }
    full = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False, "has_pwr_flag": False,
                "labels": []} for n, ps in nets.items()}
    return build_analysis_context(comps, full, {}, known_power_rails={"+12V", "GND"}, source="test")


def _load_facts(mpn, **_kw):
    # FAKE-LOAD: VIN pin rated 4.0 V absolute maximum.
    if mpn != "FAKE-LOAD":
        return None
    vin_max = SpecValue(unit="V", evidence=Evidence(page=1, confidence="high", method="table"), max=4.0)
    pin = SimpleNamespace(numbers=["1"], name="VIN", power_domain="VIN", absolute_max=None)
    return SimpleNamespace(base=SimpleNamespace(absolute_max={"VIN_max": [vin_max]}, pinout=[pin]))


class RailMapByNet(unittest.TestCase):
    def test_each_instance_keeps_its_regulator_voltage(self):
        ctx = _ctx()
        detect_topologies(ctx)
        self.assertEqual(ctx.rail_voltage(VOUT1), 5.0)
        self.assertEqual(ctx.rail_voltage(VOUT2), 3.3)

    def test_negative_rail_keeps_its_sign(self):
        ctx = _ctx()
        topo = detect_topologies(ctx)
        self.assertEqual(ctx.rail_voltage(NEG5), -5.0)
        self.assertEqual(topo["rail_voltages"]["-5V"], -5.0)

    def test_public_map_keeps_stripped_keys(self):
        topo = detect_topologies(_ctx())
        self.assertEqual(topo["rail_voltages"], {"VOUT": 3.3, "+12V": 12.0, "GND": 0, "-5V": -5.0})

    def test_am001_fires_only_on_the_5v_instance(self):
        ctx = _ctx()
        topo = detect_topologies(ctx)
        with patch.object(lookup_detectors, "get_facts", side_effect=_load_facts):
            found = run_domain_detectors(ctx, topo)["am_001_findings"]
        # 5.0 V > 4.0 V on U3; 3.3 V <= 4.0 V on U4.
        self.assertEqual([(f["components"], f["nets"], f["rail_voltage"]) for f in found],
                         [(["U3"], [VOUT1], 5.0)])

    def test_sleep_audit_reads_each_instance(self):
        ctx = _ctx()
        topo = detect_topologies(ctx)
        rails = analyze_sleep_current(ctx, {"rail_voltages": topo["rail_voltages"],
                                            "power_regulators": topo["power_regulators"]})["rails"]
        draw = {p["ref"]: p["current_uA"] for r in (VOUT1, VOUT2) for p in rails[r]["current_paths"]
                if p["type"] == "resistor_to_gnd"}
        # 10 kOhm to ground: 5.0 V / 10 kOhm = 500 uA, 3.3 V / 10 kOhm = 330 uA.
        self.assertEqual(draw, {"R1": 500.0, "R2": 330.0})


if __name__ == "__main__":
    unittest.main()
