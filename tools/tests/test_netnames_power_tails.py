"""A rail name followed by a fault, monitor, feedback, sense or ADC-tap word, and a
power-LED node, names a signal about the rail, not the rail. Supply pins of an ADC or an
LED string, and a filtered supply, keep reading as rails."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT / "skills" / "emc" / "scripts"))

from kicad_core.netnames import is_power_net_name, is_rail_signal_name  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from emc_rules import _is_power_or_ground  # noqa: E402

RAILS = ["VDD_ADC", "AVDD_ADC", "+3V3_ADC", "+5V_ADC", "3V3_LED", "5V_LED", "VCC_LED",
         "PWR_LED_24V", "VCC_DIV", "5V_INT", "12V_SW", "V1P8", "V3P3D", "V18P",
         "VBAT_FLT", "5V_{FLT}", "VBUS_{FLT}"]
SIGNALS = ["PWR_OK2", "PWR_OK#", "5V_FAULT", "VBAT_ADC", "VBUS_ADC", "5V_ISENSE",
           "+3V3_iSense", "12V_{FBM}", "3V3_{FB}", "3V3_~{SHDN}", "PWR_EN1", "PWR_FAIL_DET2",
           "VBAT_MEAS", "VIN_Meas1", "VBUS_DIV", "12V_DIVIDED", "V12_Mesure", "VBAT_READ",
           "VIN_SENSED", "PWR_LED", "PWR_LED_K", "Power_LED_K", "/power/5V_PWRGOOD",
           "12V_FBM", "VSYS_ISNS"]


class SignalTails(unittest.TestCase):
    def test_tails_name_signals(self):
        for name in SIGNALS:
            with self.subTest(name=name):
                self.assertFalse(is_power_net_name(name))

    def test_supply_and_filtered_rails_stay_rails(self):
        for name in RAILS:
            with self.subTest(name=name):
                self.assertTrue(is_power_net_name(name))

    def test_predicate_reads_the_upper_cased_leaf(self):
        self.assertTrue(is_rail_signal_name("VBAT_ADC"))
        self.assertTrue(is_rail_signal_name("POWER_LED2_A"))
        self.assertFalse(is_rail_signal_name("VDD_ADC"))
        self.assertFalse(is_rail_signal_name("VCC_DIV"))
        self.assertFalse(is_rail_signal_name("VBAT_FLT"))
        self.assertFalse(is_rail_signal_name("FAULT"))


class VoltageChannelNames(unittest.TestCase):
    def test_v_n_p_channel_inputs_are_signals(self):
        for name in ["V1P", "V2P", "V3P", "V1P_IN", "V2P_SW", "V1N"]:
            with self.subTest(name=name):
                self.assertFalse(is_power_net_name(name))

    def test_voltage_in_p_notation_stays_a_rail(self):
        for name in ["V1P8", "V3P3", "V1P2", "V18P", "V12P0", "V3P3D", "V1P8_SW"]:
            with self.subTest(name=name):
                self.assertTrue(is_power_net_name(name))


class EmcSharesTheTailTest(unittest.TestCase):
    def test_tails_are_signals_for_emc(self):
        for name in ["PWR_LED", "PWR_LED_K", "VBAT_READ", "5V_FAULT", "12V_{FBM}", "PWR_OK2",
                     "/sub/VBAT_ADC", "5V FAULT"]:
            with self.subTest(name=name):
                self.assertFalse(_is_power_or_ground(name))

    def test_rails_stay_power_for_emc(self):
        for name in ["VDD_ADC", "+3V3_ADC", "3V3_LED", "VBAT_FLT", "VCC_DIV", "PWR", "5V PCIE"]:
            with self.subTest(name=name):
                self.assertTrue(_is_power_or_ground(name))


def _ctx(net_name):
    """U1 (an ADC or driver) whose VCC pin sits on *net_name*, with a 100 nF cap to GND."""
    comps = [{"reference": "U1", "type": "ic", "value": "AD7699", "lib_id": "Analog_ADC:AD7699"},
             {"reference": "C1", "type": "capacitor", "value": "100n", "lib_id": "Device:C"}]
    for c in comps:
        c.setdefault("pins", [])
        c.setdefault("footprint", "")
    pins = {net_name: [("U1", "1", "VDD", "power_in"), ("C1", "1", "~", "passive")],
            "GND": [("U1", "2", "GND", "power_in"), ("C1", "2", "~", "passive")]}
    nets = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in ps],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, ps in pins.items()}
    return build_analysis_context(comps, nets, {})


class SupplyPinNets(unittest.TestCase):
    def test_adc_supply_and_filtered_rail_with_a_power_pin_are_rails(self):
        for name in ["VDD_ADC", "3V3_LED", "VBAT_FLT", "5V_{FLT}"]:
            with self.subTest(name=name):
                self.assertTrue(_ctx(name).is_power_net(name))


if __name__ == "__main__":
    unittest.main()
