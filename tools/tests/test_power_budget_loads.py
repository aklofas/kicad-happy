"""The power budget counts each die of a multi-pin LED through its own resistor, an
addressable LED as a flat 5 mA from any pin, and loads behind a fuse on the fused rail."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from schematic.system_analyses import analyze_power_budget  # noqa: E402


def _ctx(comps, nets, rails):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=nm, pin_type=t)
                                    for r, p, nm, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(comps, full, {}, known_power_rails=set(rails))


def _part(ref, kind, value, lib="Device:X", n=2, **extra):
    d = {"reference": ref, "type": kind, "value": value, "lib_id": lib, "footprint": "",
         "properties": {}, "pins": [{"number": str(i + 1), "name": "~"} for i in range(n)]}
    d.update(extra)
    return d


def _rgb_board(**r3_extra):
    comps = [_part("D1", "led", "LED_RABG", "Device:LED_RABG", n=4),
             _part("R3", "resistor", "150", **r3_extra),
             _part("R4", "resistor", "110"), _part("R5", "resistor", "110")]
    nets = {"+5V": [("D1", "2", "A", "passive")],
            "NR": [("D1", "1", "RK", "passive"), ("R3", "1", "~", "passive")],
            "NG": [("D1", "3", "GK", "passive"), ("R4", "1", "~", "passive")],
            "NB": [("D1", "4", "BK", "passive"), ("R5", "1", "~", "passive")],
            "GND": [("R3", "2", "~", "passive"), ("R4", "2", "~", "passive"),
                    ("R5", "2", "~", "passive")]}
    return comps, nets


def _loads(comps, nets, rails=("+5V", "GND")):
    out = analyze_power_budget(_ctx(comps, nets, rails), {})
    return out.get("rails", {})


class LedLoads(unittest.TestCase):
    def test_rgb_led_sums_each_die_through_its_resistor(self):
        comps, nets = _rgb_board()
        led = _loads(comps, nets)["+5V"]["other_loads"][0]
        # (5-2.0)/150 + 2 x (5-3.2)/110, each die at its own colour's forward voltage
        self.assertEqual(led["ref"], "D1")
        self.assertAlmostEqual(led["estimated_mA"], 52.7, delta=0.5)

    def test_unfitted_channel_resistor_is_not_a_channel(self):
        comps, nets = _rgb_board(dnp=True)
        led = _loads(comps, nets)["+5V"]["other_loads"][0]
        self.assertAlmostEqual(led["estimated_mA"], 5 + 2 * (5 - 3.2) / 110 * 1000, delta=0.5)

    def test_addressable_led_is_five_milliamps_from_any_pin(self):
        comps = [_part("D2", "led", "WS2812B", "LED:WS2812B", n=4), _part("R1", "resistor", "330")]
        nets = {"DIN": [("D2", "4", "DIN", "input"), ("R1", "1", "~", "passive")],
                "+5V": [("D2", "1", "VDD", "power_in")],
                "GND": [("D2", "3", "VSS", "power_in"), ("R1", "2", "~", "passive")]}
        loads = _loads(comps, nets)["+5V"]["other_loads"]
        self.assertEqual([(o["ref"], o["estimated_mA"]) for o in loads], [("D2", 5)])

    def test_two_pin_led_stays_five_milliamps(self):
        comps = [_part("D3", "led", "LED"), _part("R1", "resistor", "330")]
        nets = {"+5V": [("R1", "1", "~", "passive")],
                "N1": [("R1", "2", "~", "passive"), ("D3", "1", "A", "passive")],
                "GND": [("D3", "2", "K", "passive")]}
        loads = _loads(comps, nets)["+5V"]["other_loads"]
        self.assertEqual([(o["ref"], o["estimated_mA"]) for o in loads], [("D3", 5)])

    def test_mounting_pin_is_not_a_second_die(self):
        comps = [_part("D3", "led", "IR LED", n=3), _part("R1", "resistor", "330")]
        nets = {"+3V3": [("D3", "2", "A", "passive")],
                "N1": [("D3", "1", "K", "passive"), ("R1", "1", "~", "passive")],
                "GND": [("R1", "2", "~", "passive")],
                "MNT": [("D3", "3", "MNT", "passive")]}
        loads = _loads(comps, nets, rails=("+3V3", "GND"))["+3V3"]["other_loads"]
        self.assertEqual([(o["ref"], o["estimated_mA"]) for o in loads], [("D3", 5)])

    def test_unfitted_and_off_board_leds_add_no_load(self):
        for extra in ({"dnp": True}, {"on_board": False}):
            comps = [_part("D3", "led", "LED", **extra)]
            nets = {"+5V": [("D3", "1", "A", "passive")], "GND": [("D3", "2", "K", "passive")]}
            self.assertNotIn("+5V", _loads(comps, nets), extra)

    def test_led_behind_an_unfitted_resistor_is_not_counted(self):
        comps = [_part("D3", "led", "LED"), _part("R1", "resistor", "330", dnp=True)]
        nets = {"+5V": [("R1", "1", "~", "passive")],
                "N1": [("R1", "2", "~", "passive"), ("D3", "1", "A", "passive")],
                "GND": [("D3", "2", "K", "passive")]}
        self.assertNotIn("+5V", _loads(comps, nets))


class LedFalseLoads(unittest.TestCase):
    def _led(self, pins, nets_extra, value="LED", lib="Device:LED", resistors=()):
        comps = [_part("D3", "led", value, lib, n=len(pins))] + [_part(r, "resistor", v) for r, v in resistors]
        nets = {"+5V": [("D3", "1", pins[0], "passive")]}
        nets.update(nets_extra)
        return comps, nets

    def test_thermal_pad_is_not_a_die(self):
        for pad in ("PAD", "HEAT"):
            comps = [_part("D3", "led", "LED_1W", n=3), _part("R1", "resistor", "0.1")]
            nets = {"+5V": [("D3", "1", "A", "passive"), ("R1", "1", "~", "passive")],
                    "N1": [("D3", "2", "K", "passive"), ("R1", "2", "~", "passive")],
                    "GND": [("D3", "3", pad, "passive")]}
            loads = _loads(comps, nets)["+5V"]["other_loads"]
            self.assertEqual([(o["ref"], o["estimated_mA"]) for o in loads], [("D3", 5)], pad)

    def test_pad_net_does_not_become_the_leds_rail(self):
        comps = [_part("D3", "led", "LED_Pad", n=3), _part("R1", "resistor", "330")]
        nets = {"+5V": [("R1", "1", "~", "passive")],
                "N1": [("R1", "2", "~", "passive"), ("D3", "1", "A", "passive")],
                "N2": [("D3", "2", "K", "passive")],
                "Earth": [("D3", "3", "PAD", "passive")]}
        rails = _loads(comps, nets, rails=("+5V", "Earth", "GND"))
        self.assertEqual([(o["ref"], o["estimated_mA"]) for o in rails["+5V"]["other_loads"]], [("D3", 5)])
        self.assertNotIn("Earth", rails)

    def test_resistor_pack_counts_once_per_die(self):
        # a multi-unit pack arrives as one component entry per unit under the same reference
        def board(units):
            comps = [_part("D1", "led", "LED_RGB", "Device:LED_RGB", n=4)]
            comps += [_part("R27", "resistor", "33", "Device:R_Pack04_Split") for _ in range(units)]
            nets = {"+3V3": [("D1", "1", "A", "passive")],
                    "N1": [("D1", "2", "RK", "passive"), ("R27", "1", "~", "passive")],
                    "N2": [("D1", "3", "GK", "passive")], "N3": [("D1", "4", "BK", "passive")],
                    "GND": [("R27", "2", "~", "passive")]}
            return _loads(comps, nets, rails=("+3V3", "GND"))["+3V3"]["other_loads"][0]["estimated_mA"]
        self.assertEqual(board(3), board(1))

    def test_part_typed_led_without_diode_pins_keeps_the_flat_load(self):
        comps = [_part("RGB0", "led", "Conn_01x04", "Connector_Generic:Conn_01x04", n=4)]
        nets = {"+5V": [("RGB0", "1", "Pin_1", "passive")], "N1": [("RGB0", "2", "Pin_2", "passive")],
                "N2": [("RGB0", "3", "Pin_3", "passive")], "N3": [("RGB0", "4", "Pin_4", "passive")]}
        loads = _loads(comps, nets)["+5V"]["other_loads"]
        self.assertEqual([o["estimated_mA"] for o in loads], [5])

    def test_milliohm_shunt_is_not_a_series_resistor(self):
        comps, nets = _rgb_board()
        comps[1]["value"] = "0.1"
        led = _loads(comps, nets)["+5V"]["other_loads"][0]
        self.assertAlmostEqual(led["estimated_mA"], 5 + 2 * (5 - 3.2) / 110 * 1000, delta=0.5)


class FusePassThrough(unittest.TestCase):
    def _fused(self, far):
        comps = [_part("F1", "fuse", "500mA"),
                 _part("U1", "ic", "USBLC6-2SC6", "Power_Protection:USBLC6", n=2)]
        nets = {"VBUS": [("F1", "1", "~", "passive")],
                far: [("F1", "2", "~", "passive"), ("U1", "1", "VCC", "power_in")],
                "GND": [("U1", "2", "GND", "power_in")]}
        return _loads(comps, nets, rails=("VBUS", "GND"))

    def test_ic_behind_a_fuse_loads_the_fused_rail(self):
        rails = self._fused("N$1")
        self.assertEqual([i["ref"] for i in rails["VBUS"]["ics"]], ["U1"])

    def test_fuse_to_a_named_rail_does_not_alias_it(self):
        comps = [_part("F1", "fuse", "500mA"), _part("U1", "ic", "XYZ", n=2)]
        nets = {"VBUS": [("F1", "1", "~", "passive")],
                "+5V": [("F1", "2", "~", "passive"), ("U1", "1", "VCC", "power_in")],
                "GND": [("U1", "2", "GND", "power_in")]}
        rails = _loads(comps, nets, rails=("VBUS", "+5V", "GND"))
        self.assertEqual(rails["+5V"]["ic_count"], 1)
        self.assertNotIn("VBUS", rails)


if __name__ == "__main__":
    unittest.main()
