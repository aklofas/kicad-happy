"""LC filters: the capacitor is the shunt element, so a pair is listed only when the
capacitor's far end returns to ground, a supply rail, earth or a return net. A capacitor
that leaves the inductor's node for another signal (DC block, coupling, bootstrap) is a
series element. f0 = 1/(2*pi*sqrt(L*C)) by hand."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
import signal_detectors as sd  # noqa: E402


def _ctx(components, nets, rails=("+5V", "+3V3")):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    for c in components:
        c.setdefault("lib_id", "")
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
    return build_analysis_context(components, full, {}, known_power_rails=set(rails))


def _l(ref, value):
    return {"reference": ref, "type": "inductor", "value": value, "lib_id": "Device:L"}


def _c(ref, value):
    return {"reference": ref, "type": "capacitor", "value": value, "lib_id": "Device:C"}


def _d(ref, value="1N4148"):
    return {"reference": ref, "type": "diode", "value": value, "lib_id": "Device:D"}


def _ic(ref, value):
    return {"reference": ref, "type": "ic", "value": value, "lib_id": "Custom:" + value}


def _j(ref):
    return {"reference": ref, "type": "connector", "value": "Conn_01x02", "lib_id": "Connector:Conn_01x02"}


def _p(ref, pin="1"):
    return (ref, pin, "~", "passive")


def _pairs(ctx):
    return sorted((f["inductor"]["ref"], f["capacitor"]["ref"], f["shared_net"], f["resonant_hz"])
                  for f in sd.detect_lc_filters(ctx))


class SeriesCapacitorIsNotAFilter(unittest.TestCase):
    def test_coupling_capacitor_to_a_connector_is_dropped(self):
        # L1 10 uH IN -> NODE, C1 100 nF NODE -> GND: 1/(2*pi*sqrt(10e-6*100e-9)) = 159154.94 Hz.
        # C2 220 uF NODE -> OUT is the output coupling capacitor
        ctx = _ctx([_l("L1", "10u"), _c("C1", "100n"), _c("C2", "220u"), _j("J1")],
                   {"IN": [_p("L1", "1")],
                    "NODE": [_p("L1", "2"), _p("C1", "1"), _p("C2", "1")],
                    "GND": [_p("C1", "2"), _p("J1", "2")],
                    "OUT": [_p("C2", "2"), _p("J1", "1")]})
        self.assertEqual(_pairs(ctx), [("L1", "C1", "NODE", 159154.94)])

    def test_bias_feed_from_a_rail_with_a_dc_block_is_not_a_filter(self):
        # L3 68 nH from the RF supply to the antenna node, C31 100 pF on to the IC input
        ctx = _ctx([_l("L3", "68n"), _c("C31", "100p"), _ic("U1", "MAX2659"), _j("J1")],
                   {"+3V3": [_p("L3", "1")],
                    "ANT": [_p("L3", "2"), _p("C31", "1"), _p("J1", "1")],
                    "RF_IN": [_p("C31", "2"), ("U1", "3", "RFIN", "input")],
                    "GND": [_p("J1", "2")]})
        self.assertEqual(_pairs(ctx), [])

    def test_bootstrap_capacitor_to_a_boot_net_not_named_as_a_rail_is_not_a_filter(self):
        # SW -> L1 -> +5V; C5 from SW to the converter's BTST pin
        ctx = _ctx([_l("L1", "2.2u"), _c("C5", "47n"), _ic("U1", "BQ25798")],
                   {"SW": [_p("L1", "1"), _p("C5", "1"), ("U1", "1", "SW1", "power_out")],
                    "+5V": [_p("L1", "2")],
                    "VBOOT_5V": [_p("C5", "2"), ("U1", "2", "BTST1", "power_in")]})
        self.assertEqual(_pairs(ctx), [])

    def test_bootstrap_capacitor_on_a_rail_named_boot_net_is_not_a_filter(self):
        # The boot net is named like a rail, so only the pin name tells the capacitor apart
        ctx = _ctx([_l("L1", "2.2u"), _c("C5", "47n"), _ic("U1", "BQ25798")],
                   {"SW": [_p("L1", "1"), _p("C5", "1"), ("U1", "1", "SW1", "power_out")],
                    "+5V": [_p("L1", "2")],
                    "+5V_BST": [_p("C5", "2"), ("U1", "2", "BTST1", "power_in")]})
        self.assertEqual(_pairs(ctx), [])

    def test_band_switched_tank_capacitor_is_dropped(self):
        # Known loss: the tank capacitor C1 reaches ground through the switching diode D1,
        # so its far net is not an AC ground by name and the tank L1 + C1 is not listed
        ctx = _ctx([_l("L1", "1u"), _c("C1", "270p"), _d("D1", "BAR64")],
                   {"TANK": [_p("L1", "1"), _p("C1", "1")],
                    "GND": [_p("L1", "2"), ("D1", "1", "K", "passive")],
                    "SWITCHED": [_p("C1", "2"), ("D1", "2", "A", "passive")]})
        self.assertEqual(_pairs(ctx), [])


class ShuntCapacitorStays(unittest.TestCase):
    def _one(self, far_net, rails=("+5V", "+3V3")):
        ctx = _ctx([_l("L1", "10u"), _c("C1", "100n")],
                   {"IN": [_p("L1", "1")],
                    "NODE": [_p("L1", "2"), _p("C1", "1")],
                    far_net: [_p("C1", "2")]}, rails=rails)
        return _pairs(ctx)

    def test_capacitor_to_ground_rail_earth_or_return_is_one_filter(self):
        for far in ("GND", "+5V", "Earth", "POE_RTN", "/power/AD_RETURN"):
            self.assertEqual(self._one(far), [("L1", "C1", "NODE", 159154.94)], far)

    def test_pi_filter_keeps_both_sections(self):
        # C1 - L1 - C2, both caps 10 uF to GND, L1 4.7 uH: f0 = 1/(2*pi*sqrt(4.7e-6*10e-6))
        ctx = _ctx([_l("L1", "4.7u"), _c("C1", "10u"), _c("C2", "10u")],
                   {"IN": [_p("L1", "1"), _p("C1", "1")],
                    "OUT": [_p("L1", "2"), _p("C2", "1")],
                    "GND": [_p("C1", "2"), _p("C2", "2")]})
        self.assertEqual(_pairs(ctx), [("L1", "C1", "IN", 23215.13), ("L1", "C2", "OUT", 23215.13)])

    def test_shunt_capacitor_is_not_hidden_by_a_larger_series_capacitor(self):
        # L1 18 nH between two 10 pF shunt caps; C3 100 nF DC block leaves the OUT node for
        # RF_OUT. Keeping the largest capacitor per node used to list L1 + C3 instead of C2
        ctx = _ctx([_l("L1", "18n"), _c("C1", "10p"), _c("C2", "10p"), _c("C3", "100n"), _j("J1")],
                   {"IN": [_p("L1", "1"), _p("C1", "1")],
                    "OUT": [_p("L1", "2"), _p("C2", "1"), _p("C3", "1")],
                    "RF_OUT": [_p("C3", "2"), _p("J1", "1")],
                    "GND": [_p("C1", "2"), _p("C2", "2"), _p("J1", "2")]})
        self.assertEqual([p[:3] for p in _pairs(ctx)], [("L1", "C1", "IN"), ("L1", "C2", "OUT")])

    def test_boot_mode_pin_on_ground_does_not_hide_filters(self):
        # The MCU's BOOT0 is strapped to GND; L1 + C1 to GND is a filter on the audio node
        ctx = _ctx([_l("L1", "10u"), _c("C1", "100n"), _ic("U1", "STM32F103C8T6")],
                   {"+3V3": [("U1", "1", "VDD", "power_in")],
                    "DAC_OUT": [_p("L1", "1"), ("U1", "14", "PA4", "bidirectional")],
                    "AUDIO_F": [_p("L1", "2"), _p("C1", "1")],
                    "GND": [_p("C1", "2"), ("U1", "44", "BOOT0", "input"),
                            ("U1", "47", "VSS", "power_in")]},
                   rails=("+3V3",))
        self.assertEqual(_pairs(ctx), [("L1", "C1", "AUDIO_F", 159154.94)])


if __name__ == "__main__":
    unittest.main()
