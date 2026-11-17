# tools/tests/test_led_driver_pullup.py
"""A transistor drives an LED through the LED's series resistor: the resistor's far end is
the LED. A resistor from the drain or collector to a supply rail (or to ground) is a pull-up
(pull-down); an LED elsewhere on that rail is not driven by the transistor."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
import signal_detectors as sd  # noqa: E402
import domain_detectors as dd  # noqa: E402
from kicad_core import parts  # noqa: E402

RAILS = ("VCC", "GND")


def _driver(nets, kind="mosfet", load_net="DRAIN", rails=RAILS, audit=False, pchannel=False,
            q1=None, emitter=None):
    """nets: {net: [(ref, pin, pin_name)]}; parts are typed by their reference letter, and
    q1 overrides Q1's part fields (lib_id, value, keywords, description). Returns the
    led_driver block the enrichment gives the transistor Q1, or None."""
    types = {"Q": "transistor", "R": "resistor", "D": "led", "C": "capacitor",
             "J": "connector"}
    refs = sorted({r for pins in nets.values() for r, _, _ in pins})
    comps = [{"reference": r, "type": types[r[0]], "value": "1k" if r[0] == "R" else "X",
              "lib_id": "", "pins": [], "footprint": ""} for r in refs]
    for c in comps:
        if c["reference"] == "Q1":
            c.update(q1 or {})
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn,
                                         pin_type="passive") for r, p, pn in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    ctx = build_analysis_context(comps, full, {}, known_power_rails=set(rails))
    tc = {"reference": "Q1", "type": kind,
          ("drain_net" if kind == "mosfet" else "collector_net"): load_net}
    if kind == "mosfet":
        tc["is_pchannel"] = pchannel
    elif emitter:
        tc["emitter_net"] = emitter
    sd.enrich_transistor_led_drivers(ctx, [tc])
    if audit:
        audited = {r["summary"].split()[1] for r in dd.audit_led_circuits(ctx, [tc])
                   if r.get("rule_id") == "LA-AUD"}
        return tc.get("led_driver"), audited
    return tc.get("led_driver")


class LedDriverThroughPullUp(unittest.TestCase):
    def test_pull_up_to_a_rail_with_an_unrelated_led_is_not_a_driver(self):
        nets = {"VCC": [("R1", "2", "~"), ("D9", "1", "A")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "LEDK": [("D9", "2", "K"), ("R9", "1", "~")],
                "GND": [("Q1", "2", "S"), ("R9", "2", "~")]}
        self.assertIsNone(_driver(nets))

    def test_bjt_collector_pull_up_to_a_rail_is_not_a_driver(self):
        nets = {"VCC": [("R1", "2", "~"), ("D9", "1", "A")],
                "COLL": [("Q1", "3", "C"), ("R1", "1", "~")],
                "LEDK": [("D9", "2", "K"), ("R9", "1", "~")],
                "GND": [("Q1", "2", "E"), ("R9", "2", "~")]}
        self.assertIsNone(_driver(nets, kind="bjt", load_net="COLL"))

    def test_pull_down_to_ground_with_an_led_on_ground_is_not_a_driver(self):
        nets = {"VCC": [("Q1", "2", "S"), ("R9", "1", "~")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "LEDA": [("R9", "2", "~"), ("D9", "1", "A")],
                "GND": [("R1", "2", "~"), ("D9", "2", "K")]}
        self.assertIsNone(_driver(nets))

    def test_pull_up_to_a_rail_named_only_by_its_label_is_not_a_driver(self):
        nets = {"3.3V": [("R1", "2", "~"), ("D9", "1", "A"), ("C1", "1", "~")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "LEDK": [("D9", "2", "K"), ("R9", "1", "~")],
                "GND": [("Q1", "2", "S"), ("R9", "2", "~"), ("C1", "2", "~")]}
        self.assertIsNone(_driver(nets))

    def test_led_node_whose_name_reads_as_a_rail_is_a_driver(self):
        nets = {"VCC": [("D1", "1", "A")],
                "PWR_LED_K": [("D1", "2", "K"), ("R1", "2", "~")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "GND": [("Q1", "2", "S")]}
        drv = _driver(nets)
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D1", "R1"))

    def test_led_node_brought_out_to_a_connector_is_a_driver(self):
        nets = {"VCC": [("Q1", "2", "S")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "PWR_LED": [("R1", "2", "~"), ("D1", "1", "A"), ("J1", "4", "Pin_4")],
                "GND": [("D1", "2", "K")]}
        drv = _driver(nets)
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D1", "R1"))

    def test_power_symbol_rail_holding_only_an_led_and_a_connector_is_not_a_driver(self):
        nets = {"VCC": [("R1", "2", "~"), ("D9", "1", "A"), ("J1", "1", "Pin_1")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "LEDK": [("D9", "2", "K"), ("R9", "1", "~")],
                "GND": [("Q1", "2", "S"), ("R9", "2", "~"), ("J1", "2", "Pin_2")]}
        self.assertIsNone(_driver(nets))

    def test_drain_on_a_rail_is_not_the_driver_of_that_rails_power_led(self):
        nets = {"VBUS": [("Q1", "3", "D"), ("R1", "1", "~"), ("R2", "1", "~")],
                "SENSE": [("R1", "2", "~")],
                "PWRLED": [("R2", "2", "~"), ("D5", "1", "A")],
                "VOUT": [("Q1", "2", "S")],
                "GND": [("D5", "2", "K")]}
        drv, audited = _driver(nets, load_net="VBUS", rails=("VBUS", "GND"), audit=True)
        self.assertIsNone(drv)
        self.assertIn("D5", audited)

    def test_drain_on_ground_is_not_an_led_driver(self):
        nets = {"GND": [("Q1", "3", "D"), ("R1", "1", "~")],
                "PWRKEY": [("Q1", "2", "S")],
                "PWR_LED_K": [("R1", "2", "~"), ("D6", "2", "K")],
                "+3.3V": [("D6", "1", "A")]}
        self.assertIsNone(_driver(nets, load_net="GND", rails=("+3.3V", "GND")))

    def test_collector_on_ground_is_not_an_led_driver(self):
        nets = {"GND": [("Q1", "3", "C"), ("R1", "1", "~")],
                "OUT": [("Q1", "2", "E")],
                "LEDK": [("R1", "2", "~"), ("D6", "2", "K")],
                "VCC": [("D6", "1", "A")]}
        self.assertIsNone(_driver(nets, kind="bjt", load_net="GND"))

    def test_p_channel_load_switch_drives_the_indicator_on_its_switched_rail(self):
        nets = {"+5V": [("Q1", "2", "S")],
                "VOUT": [("Q1", "3", "D"), ("R1", "1", "~")],
                "LEDA": [("R1", "2", "~"), ("D1", "1", "A")],
                "GND": [("D1", "2", "K")]}
        drv = _driver(nets, load_net="VOUT", rails=("+5V", "VOUT", "GND"), pchannel=True)
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D1", "R1"))

    def test_low_side_switch_with_led_and_series_resistor_is_a_driver(self):
        nets = {"VCC": [("D1", "1", "A")],
                "LEDK": [("D1", "2", "K"), ("R1", "2", "~")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "GND": [("Q1", "2", "S")]}
        drv = _driver(nets)
        self.assertEqual((drv["led_ref"], drv["current_resistor"], drv["power_rail"]),
                         ("D1", "R1", "VCC"))

    def test_high_side_switch_with_series_resistor_to_led_is_a_driver(self):
        nets = {"VCC": [("Q1", "2", "S")],
                "DRAIN": [("Q1", "3", "D"), ("R1", "1", "~")],
                "LEDA": [("R1", "2", "~"), ("D1", "1", "A")],
                "GND": [("D1", "2", "K")]}
        drv = _driver(nets)
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D1", "R1"))

    def test_bjt_collector_with_led_and_series_resistor_is_a_driver(self):
        nets = {"VCC": [("D1", "1", "A")],
                "LEDK": [("D1", "2", "K"), ("R1", "2", "~")],
                "COLL": [("Q1", "3", "C"), ("R1", "1", "~")],
                "GND": [("Q1", "2", "E")]}
        drv = _driver(nets, kind="bjt", load_net="COLL")
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D1", "R1"))


# An NPN emitter follower with its collector on +5V; HL1 is that rail's power LED,
# fed through its own resistor.
FOLLOWER = {"+5V": [("Q1", "3", "C"), ("R1", "1", "~")],
            "LEDA": [("R1", "2", "~"), ("D1", "1", "A")],
            "OUT": [("Q1", "2", "E")],
            "GND": [("D1", "2", "K")]}
FOLLOWER_RAILS = ("+5V", "GND")


class NpnCollectorOnARail(unittest.TestCase):
    def _follower(self, **q1):
        return _driver(FOLLOWER, kind="bjt", load_net="+5V", rails=FOLLOWER_RAILS, q1=q1,
                       emitter="OUT")

    def test_npn_by_symbol_is_not_the_driver_of_its_collector_rails_led(self):
        self.assertIsNone(self._follower(lib_id="gost_common:VT_NPN_EBC", value="KT315"))
        self.assertIsNone(self._follower(lib_id="Device:Q_NPN_BEC", value="Q"))

    def test_npn_by_keywords_or_description_is_not_the_driver(self):
        self.assertIsNone(self._follower(lib_id="my:T1", value="T1", keywords="BJT NPN"))
        self.assertIsNone(self._follower(lib_id="my:T1", value="T1",
                                         description="Small Signal NPN Transistor"))

    def test_npn_by_part_number_is_not_the_driver(self):
        for value in ("2N3904", "BC847BLT1G", "MMBT3904LT1G", "S8050", "BC547B"):
            with self.subTest(value=value):
                self.assertIsNone(self._follower(lib_id="my:Q", value=value))

    def test_pnp_or_unread_polarity_keeps_todays_reading(self):
        for q1 in ({"lib_id": "Device:Q_PNP_BEC", "value": "BC857"},
                   {"lib_id": "my:Q", "value": "Q"},
                   {"lib_id": "my:Q", "value": "BC847BPN"},
                   {"lib_id": "my:Q", "value": "T1", "description": "NPN/PNP pair"}):
            with self.subTest(q1=q1):
                drv = self._follower(**q1)
                self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D1", "R1"))

    def test_npn_follower_keeps_the_led_on_its_emitter(self):
        nets = {"+5V": [("Q1", "3", "C"), ("R1", "1", "~")],
                "LEDA": [("R1", "2", "~"), ("D1", "1", "A"), ("Q1", "2", "E")],
                "GND": [("D1", "2", "K")]}
        npn = {"lib_id": "Device:Q_NPN_BCE", "value": "Q"}
        drv = _driver(nets, kind="bjt", load_net="+5V", rails=FOLLOWER_RAILS, q1=npn,
                      emitter="LEDA")
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D1", "R1"))
        nets["GND"].append(("Q1", "2", "E"))
        nets["LEDA"].remove(("Q1", "2", "E"))
        self.assertIsNone(_driver(nets, kind="bjt", load_net="+5V", rails=FOLLOWER_RAILS,
                                  q1=npn, emitter="GND"))

    def test_npn_switch_on_its_own_collector_node_is_still_a_driver(self):
        nets = {"VCC": [("D1", "1", "A")],
                "LEDK": [("D1", "2", "K"), ("R1", "2", "~")],
                "COLL": [("Q1", "3", "C"), ("R1", "1", "~")],
                "GND": [("Q1", "2", "E")]}
        drv = _driver(nets, kind="bjt", load_net="COLL",
                      q1={"lib_id": "Transistor_BJT:MMBT3904", "value": "MMBT3904"})
        self.assertEqual((drv["led_ref"], drv["current_resistor"]), ("D1", "R1"))


# Entry -> Description of the symbol in KiCad 9.0 Transistor_BJT.kicad_sym (the symbol of
# the same name, or the one in brackets).
KICAD_NPN_SYMBOLS = {
    "2N2219": "800mA Ic, 50V Vce, NPN Transistor, TO-39",
    "2N3055": "15A Ic, 60V Vce, Power NPN Transistor, TO-3",
    "2N3904": "0.2A Ic, 40V Vce, Small Signal NPN Transistor, TO-92",
    "2SC1815": "0.15A Ic, 50V Vce, Low Noise Audio NPN Transistor, TO-92",
    "BC107": "0.1A Ic, 50V Vce, Low Noise General Purpose NPN Transistor, TO-18",
    "BC108": "0.1A Ic, 30V Vce, Low Noise General Purpose NPN Transistor, TO-18",
    "BC109": "0.2A Ic, 25V Vce, Low Noise General Purpose NPN Transistor, TO-18",
    "BC237": "100mA Ic, 50V Vce, Epitaxial Silicon NPN Transistor, TO-92",
    "BC337": "0.8A Ic, 45V Vce, NPN Transistor, TO-92",
    "BC338": "0.8A Ic, 25V Vce, NPN Transistor, TO-92",
    "BC546": "0.1A Ic, 65V Vce, Small Signal NPN Transistor, TO-92",
    "BC547": "0.1A Ic, 45V Vce, Small Signal NPN Transistor, TO-92",
    "BC548": "0.1A Ic, 30V Vce, Small Signal NPN Transistor, TO-92",
    "BC549": "0.1A Ic, 30V Vce, Small Signal NPN Transistor, TO-92",
    "BC550": "0.1A Ic, 45V Vce, Small Signal NPN Transistor, TO-92",
    "BC817": "0.8A Ic, 45V Vce, NPN Transistor, SOT-23",
    "BC818": "0.8A Ic, 25V Vce, NPN Transistor, SOT-23",
    "BC846": "0.1A Ic, 65V Vce, NPN Transistor, SOT-23",
    "BC847": "0.1A Ic, 45V Vce, NPN Transistor, SOT-23",
    "BC848": "0.1A Ic, 30V Vce, NPN Transistor, SOT-23",
    "BC849": "0.1A Ic, 30V Vce, NPN Transistor, SOT-23",
    "BC850": "0.1A Ic, 45V Vce, NPN Transistor, SOT-23",
    "BCP56": "1A Ic, 80V Vce, NPN Medium Power Transistor, SOT-223",
    "BCX56": "1A Ic, 80V Vce, NPN Medium Power Transistor, SOT-89",
    "BD433": "4A Ic, 22V Vce, Power NPN Transistor, TO-126",
    "BD435": "4A Ic, 32V Vce, Power NPN Transistor, TO-126",
    "BD437": "4A Ic, 45V Vce, Power NPN Transistor, TO-126",
    "BD441": "4A Ic, 80V Vce, Power NPN Transistor, TO-126",
    "DTC114E": "Digital NPN Transistor, 10k/10k, SOT-23",
    "DTC143Z": "Digital NPN Transistor, 4k7/47k, SOT-23",
    "DTC144E": "Digital NPN Transistor, 47k/47k, SOT-23",
    "MJE13003": "1.5A Ic, 400V Vce, Silicon Switching Power NPN Transistor, TO-225",
    "MMBT2222": "(MMBT2222A) 600mA Ic, 40V Vce, NPN Transistor, SOT-23",
    "MMBT3904": "0.2A Ic, 40V Vce, Small Signal NPN Transistor, SOT-23",
    "MMBT5550": "(MMBT5550L) 0.6A Ic, 140V Vce, NPN Transistor, SOT-23",
    "MMBT5551": "(MMBT5551L) 0.6A Ic, 160V Vce, NPN Transistor, SOT-23",
    "MMBTA06": "0.5A Ic, 80V Vce, general purpose NPN",
    "MMBTA42": "0.5A Ic, 300V Vce, NPN High Voltage Transistor, SOT-23",
    "MPSA42": "0.5A Ic, 300V Vce, NPN High Voltage Transistor, TO-92",
    "PMBT2222": "(PMBT2222A) 600mA Ic, 40V Vce, NPN Transistor, SOT-23",
    "PN2222": "(PN2222A) 1A Ic, 40V Vce, NPN Transistor, General Purpose Transistor, TO-92",
    "PZT2222": "(PZT2222A) 1A Ic, 40V Vce, NPN Transistor, General Purpose Transistor, SOT-223",
    "PZT3904": "0.2A Ic, 40V Vce, Small Signal NPN Transistor, SOT-223",
    "S8050": "0.7A Ic, 20V Vce, Low Voltage High Current NPN Transistor, TO-92",
    "SS8050": "General Purpose NPN Transistor, 1.5A Ic, 25V Vce, SOT-23",
    "TIP120": "5A Ic, 60V Vce, Silicon Darlington Power NPN Transistor, TO-220",
    "TIP121": "5A Ic, 80V Vce, Silicon Darlington Power NPN Transistor, TO-220",
    "TIP122": "5A Ic, 100V Vce, Silicon Darlington Power NPN Transistor, TO-220",
    "TIP3055": "15A Ic, 60V Vce, Power NPN Transistor, TO-218",
    "TIP41": "6A Ic, 40V Vce, Power NPN Transistor, TO-220",
}


class NpnPartNumbers(unittest.TestCase):
    def test_every_entry_is_cited_as_npn(self):
        self.assertEqual(set(parts._NPN_BJT_PARTS), set(KICAD_NPN_SYMBOLS))
        for entry, desc in KICAD_NPN_SYMBOLS.items():
            self.assertIn("NPN", desc, entry)

    def test_part_numbers_with_packing_suffixes_read_npn(self):
        for name in ("2N3904BU", "BC847BLT1G", "MMBT3904LT1G", "BC817-40", "MMBT2222A",
                     "S8050", "dtc114eka"):
            with self.subTest(name=name):
                self.assertTrue(parts.names_npn_bjt(name))

    def test_pnp_parts_and_complementary_pairs_do_not_read_npn(self):
        for name in ("BC857", "BC807", "MMBT3906", "DTA144W", "BC847BPN", "BC846BPDW1",
                     "BC5470", "2N39045", ""):
            with self.subTest(name=name):
                self.assertFalse(parts.names_npn_bjt(name))


if __name__ == "__main__":
    unittest.main()
