import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_core.netnames import net_leaf, parse_voltage_from_net_name  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from schematic.net_analysis import _estimate_rail_voltage  # noqa: E402
from schematic.pipeline import detect_topologies  # noqa: E402
from signal_detectors import _infer_rail_voltage  # noqa: E402


def _ctx(nets, rails=()):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name="", pin_type=t) for r, p, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    comps = sorted({r for pins in nets.values() for r, _, _ in pins})
    return build_analysis_context([{"reference": r, "type": "resistor", "value": "10k"} for r in comps],
                                  full, {}, known_power_rails=set(rails))


class NetLeaf(unittest.TestCase):
    # A KiCad net name is <sheet path>/<label>; the sheet path names the sheet, not the net.
    def test_leaf(self):
        self.assertEqual(net_leaf("/3v3_buck/PGND"), "PGND")
        self.assertEqual(net_leaf("/a/b{slash}3V3"), "b{slash}3V3")
        self.assertEqual(net_leaf("1V/Oct"), "1V/Oct")
        self.assertEqual(net_leaf("+3V3"), "+3V3")


class VoltageFromTheNetsOwnName(unittest.TestCase):
    def test_parse(self):
        for name, want in [("/3v3_buck/PGND", None), ("/5v_buck/SW", None), ("/Analog/-5V", -5.0),
                           ("/think/-114V", -114.0), ("1V/Oct", 1.0), ("VCC_3V3", 3.3),
                           ("/a/b{slash}3V3", 3.3), ("SX1250.VREG", None)]:
            self.assertEqual(parse_voltage_from_net_name(name), want, name)

    def test_estimate(self):
        self.assertIsNone(_estimate_rail_voltage("/usb3_hub/ILIM"))
        self.assertEqual(_estimate_rail_voltage("/USB/VBUS"), 5.0)
        self.assertEqual(_estimate_rail_voltage("/x/GND"), 0)

    def test_infer(self):
        self.assertIsNone(_infer_rail_voltage("/5v_buck/FB"))
        self.assertEqual(_infer_rail_voltage("/Power/+3V3"), 3.3)


class RailMapOnlyOnPowerAndGround(unittest.TestCase):
    def _rails(self, names, rails=()):
        nets = {n: [(f"R{i}", "1", "passive")] for i, n in enumerate(names, 1)}
        return detect_topologies(_ctx(nets, rails))["rail_voltages"]

    def test_sheet_name_puts_no_voltage_on_its_nets(self):
        self.assertEqual(self._rails(["/3v3_buck/SW", "/3v3_buck/PGND"]), {})

    def test_signals_named_after_a_rail_are_not_rails(self):
        self.assertEqual(self._rails(["USB_FS_DM", "EN_5V", "SX1250.VREG"]), {})

    def test_rails_keep_their_name_voltage(self):
        # -12V is a power net by name (negative rail), so it keeps its map entry.
        self.assertEqual(self._rails(["-12V", "+3V3", "/x/GND", "/USB/VBUS"], {"+3V3"}),
                         {"-12V": -12.0, "+3V3": 3.3, "/x/GND": 0, "/USB/VBUS": 5.0})

    def test_sheet_output_loses_the_sheet_name_hint(self):
        # A sheet "3v3_filter" with output VOUT: the leaf carries no voltage.
        self.assertEqual(self._rails(["/3v3_filter/VOUT"]), {})


if __name__ == "__main__":
    unittest.main()
