"""The sleep audit reads a battery rail's voltage from its battery symbols, and counts an
indicator LED wired straight to ground while a GPIO-driven LED stays off during sleep."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from schematic.system_analyses import analyze_sleep_current  # noqa: E402


def _ctx(comps, nets, rails):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name="", pin_type=t)
                                    for r, p, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(comps, full, {}, known_power_rails=set(rails))


def _part(ref, kind, value, lib="Device:X", n=2):
    return {"reference": ref, "type": kind, "value": value, "lib_id": lib, "footprint": "",
            "properties": {}, "pins": [{"number": str(i + 1), "name": "~"} for i in range(n)]}


def _bleeder_voltage(batteries, nets):
    """Rail voltage the audit reads on VBAT, loaded by a 10k bleeder to ground."""
    comps = [_part("R1", "resistor", "10k")] + batteries
    base = {"VBAT": [("R1", "1", "passive")], "GND": [("R1", "2", "passive")]}
    for k, v in nets.items():
        base.setdefault(k, []).extend(v)
    out = analyze_sleep_current(_ctx(comps, base, {"VBAT", "GND"}), {})
    return out["rails"]["VBAT"]["current_paths"][0]["rail_voltage"]


class BatteryVoltage(unittest.TestCase):
    def test_two_aa_value_is_three_volts(self):
        b = _part("BT1", "battery", "2xAA", "Device:Battery")
        self.assertEqual(_bleeder_voltage([b], {"VBAT": [("BT1", "1", "passive")],
                                                "GND": [("BT1", "2", "passive")]}), 3.0)

    def test_dual_cell_symbol_reads_two_cells(self):
        b = _part("BT1", "battery", "AA", "Device:Battery_Dual")
        self.assertEqual(_bleeder_voltage([b], {"VBAT": [("BT1", "1", "passive")],
                                                "GND": [("BT1", "2", "passive")]}), 3.0)

    def test_coin_cell_is_three_volts(self):
        b = _part("BT1", "battery", "CR2032", "Device:Battery_Cell")
        self.assertEqual(_bleeder_voltage([b], {"VBAT": [("BT1", "1", "passive")],
                                                "GND": [("BT1", "2", "passive")]}), 3.0)

    def test_stated_voltage_is_used(self):
        b = _part("BT1", "battery", "4.5v", "Device:Battery")
        self.assertEqual(_bleeder_voltage([b], {"VBAT": [("BT1", "1", "passive")],
                                                "GND": [("BT1", "2", "passive")]}), 4.5)

    def test_two_coin_cells_in_series_add(self):
        bs = [_part("BT1", "battery", "CR2032", "Device:Battery_Cell"),
              _part("BT2", "battery", "CR2032", "Device:Battery_Cell")]
        nets = {"VBAT": [("BT1", "1", "passive")], "MID": [("BT1", "2", "passive"), ("BT2", "1", "passive")],
                "GND": [("BT2", "2", "passive")]}
        self.assertEqual(_bleeder_voltage(bs, nets), 6.0)

    def test_battery_behind_a_p_fet_keeps_its_value(self):
        b = _part("BT1", "battery", "CR2032", "Device:Battery_Cell")
        q = _part("Q1", "transistor", "PFET", "Device:Q_PMOS_GSD", 3)
        nets = {"VBAT": [("Q1", "3", "passive")], "BATT_RAW": [("Q1", "2", "passive"), ("BT1", "1", "passive")],
                "GND": [("BT1", "2", "passive"), ("Q1", "1", "passive")]}
        self.assertEqual(_bleeder_voltage([b, q], nets), 3.0)

    def test_battery_without_a_readable_value_stays_li_ion(self):
        b = _part("BT1", "battery", "Battery", "Device:Battery")
        self.assertEqual(_bleeder_voltage([b], {"VBAT": [("BT1", "1", "passive")],
                                                "GND": [("BT1", "2", "passive")]}), 3.7)

    def test_symbol_with_more_than_two_terminals_stays_li_ion(self):
        b = _part("BT1", "battery", "NiCd 1.2V", "Device:Battery", 3)
        nets = {"VBAT": [("BT1", "1", "passive")], "GND": [("BT1", "2", "passive")],
                "TAP": [("BT1", "3", "passive"), ("R2", "1", "passive")]}
        self.assertEqual(_bleeder_voltage([b, _part("R2", "resistor", "1k")], nets), 3.7)


def _led_rail(cathode_net, seq=None):
    comps = [_part("R1", "resistor", "330"), _part("D1", "led", "LED", "Device:LED"),
             _part("U1", "ic", "MCU", "MCU:X", 3)]
    nets = {"+3V3": [("R1", "1", "passive")], "N1": [("R1", "2", "passive"), ("D1", "2", "passive")],
            "GND": [("U1", "2", "power_in")]}
    nets.setdefault(cathode_net, []).append(("D1", "1", "passive"))
    if cathode_net != "GND":
        nets[cathode_net].append(("U1", "1", "output"))
    out = analyze_sleep_current(_ctx(comps, nets, {"+3V3", "GND"}), {}, seq)
    return [p for p in out["rails"]["+3V3"]["current_paths"] if p["type"] == "led_indicator"][0]


class IndicatorLeds(unittest.TestCase):
    def test_led_to_ground_conducts_through_sleep(self):
        p = _led_rail("GND")
        self.assertEqual(p["likely_state"], "always conducting")
        self.assertEqual(p["realistic_uA"], p["current_uA"])
        self.assertGreater(p["realistic_uA"], 0)

    def test_led_driven_by_a_gpio_is_off_during_sleep(self):
        p = _led_rail("GPIO_LED")
        self.assertEqual(p["likely_state"], "GPIO off during sleep")
        self.assertEqual(p["realistic_uA"], 0.0)

    def test_led_to_ground_on_a_controlled_rail_is_off(self):
        seq = {"dependencies": [{"en_source": "controlled", "output_rail": "+3V3", "regulator": "U9"}]}
        p = _led_rail("GND", seq)
        self.assertEqual(p["likely_state"], "rail disabled during sleep")
        self.assertEqual(p["realistic_uA"], 0.0)

    def test_working_flag_is_not_exposed(self):
        self.assertNotIn("_hardwired", _led_rail("GND"))


if __name__ == "__main__":
    unittest.main()
