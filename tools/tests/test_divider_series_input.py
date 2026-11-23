# tools/tests/test_divider_series_input.py
"""A resistor in series with an IC input, whose signal enters at the other end, is not the
top of a voltage divider; its resistor stays out of the RC pairing all the same."""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402
from schematic.pipeline import detect_topologies  # noqa: E402

_LIB = {"resistor": "Device:R", "capacitor": "Device:C", "diode": "Device:D_Zener",
        "inductor": "Device:L"}
_TYPES = {"R": "resistor", "C": "capacitor", "D": "diode", "L": "inductor"}


def _two_pin(ref, value, n1, n2):
    return (ref, value, n1, n2)


def _topo(two_pins, ics=(), labels=None, rails=("GND", "+3V3", "+5V", "VIN")):
    """Phase-1 records of a design: two-pin parts ``(ref, value, n1, n2)``, IC pins
    ``(ref, value, pin, name, net, pin_type)`` and extra net labels ``{net: [label]}``."""
    comps, nets = [], {}

    def _pin(net, ref, num, name, kind):
        nets.setdefault(net, []).append(
            {"component": ref, "pin_number": num, "pin_name": name, "pin_type": kind})

    for ref, value, n1, n2 in two_pins:
        typ = _TYPES[ref.rstrip("0123456789")]
        comps.append({"reference": ref, "type": typ, "value": value, "lib_id": _LIB[typ],
                      "footprint": "", "properties": {},
                      "pins": [{"number": "1", "name": ""}, {"number": "2", "name": ""}]})
        # A diode's pin 1 is its cathode
        _pin(n1, ref, "1", "K" if typ == "diode" else "", "passive")
        _pin(n2, ref, "2", "A" if typ == "diode" else "", "passive")
    for ref in sorted({i[0] for i in ics}):
        pins = [i for i in ics if i[0] == ref]
        comps.append({"reference": ref, "type": "ic", "value": pins[0][1], "lib_id": "", "footprint": "",
                      "properties": {}, "pins": [{"number": p[2], "name": p[3]} for p in pins]})
        for _, _, num, name, net, kind in pins:
            _pin(net, ref, num, name, kind)
    full = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False, "has_pwr_flag": False,
                "labels": (labels or {}).get(n, [])} for n, ps in nets.items()}
    ctx = build_analysis_context(comps, full, {}, known_power_rails=set(rails), source="test")
    return detect_topologies(ctx)


def _dividers(topo):
    return sorted(v["summary"] for v in topo["voltage_dividers"])


# A current-sense channel: three diode cathodes on VOUT_ISENSE, R41 develops the voltage,
# R38 limits the current into the ADC input and its clamp zener
_SENSE = [_two_pin("R38", "1k", "A5", "VOUT_ISENSE"),
          _two_pin("R41", "330", "VOUT_ISENSE", "GND"),
          _two_pin("D7", "3V3", "A5", "GND"),
          _two_pin("D1", "BAT54", "VOUT_ISENSE", "SENSE_1"),
          _two_pin("D2", "BAT54", "VOUT_ISENSE", "SENSE_2"),
          _two_pin("D3", "BAT54", "VOUT_ISENSE", "SENSE_3")]
_ADC = [("U3", "ADS1115", "4", "AIN0", "A5", "input"),
        ("U3", "ADS1115", "8", "VDD", "+3V3", "power_in"),
        ("U3", "ADS1115", "3", "GND", "GND", "power_in")]


class SeriesResistorIntoAnInput(unittest.TestCase):
    def test_series_resistor_into_a_clamped_adc_input_is_not_a_divider(self):
        topo = _topo(_SENSE, _ADC)
        self.assertNotIn("Voltage divider R38/R41", _dividers(topo))
        self.assertEqual(topo["feedback_networks"], [])

    def test_series_resistor_forms_no_rc_filter(self):
        self.assertEqual(_topo(_SENSE, _ADC)["rc_filters"], [])

    def test_series_resistor_stays_out_of_rc_pairing_with_a_cap_on_the_input(self):
        topo = _topo(_SENSE + [_two_pin("C9", "100n", "A5", "GND")], _ADC)
        self.assertNotIn("Voltage divider R38/R41", _dividers(topo))
        self.assertEqual([(f["resistor"]["ref"], f["capacitor"]["ref"]) for f in topo["rc_filters"]], [])

    def test_no_kept_record_carries_a_private_key(self):
        topo = _topo(_SENSE, _ADC)
        for vd in topo["voltage_dividers"] + topo["feedback_networks"]:
            self.assertFalse([k for k in vd if k.startswith("_")], vd["summary"])


# A charger's FB pin on the mid-point of R2 / R3 (R2 from its +5V output); R1 carries the
# same node into a second controller's FB input
_FEEDBACK = [_two_pin("R1", "20k", "U1_FB", "FB"),
             _two_pin("R2", "4.64k", "+5V", "FB"),
             _two_pin("R3", "1k", "FB", "GND")]
_CONVERTERS = [("U2", "TPS54331", "1", "VIN", "VIN", "power_in"),
               ("U2", "TPS54331", "2", "FB", "FB", "input"),
               ("U2", "TPS54331", "3", "GND", "GND", "power_in"),
               ("U1", "TPS54331", "4", "FB", "U1_FB", "input"),
               ("U1", "TPS54331", "5", "GND", "GND", "power_in")]


class FeedbackThroughASeriesResistor(unittest.TestCase):
    def test_regulator_reads_its_output_from_the_real_divider(self):
        topo = _topo(_FEEDBACK, _CONVERTERS)
        (reg,) = [r for r in topo["power_regulators"] if r["ref"] == "U2"]
        fd = reg["feedback_divider"]
        self.assertEqual((fd["r_top"]["ref"], fd["r_bottom"]["ref"]), ("R2", "R3"))
        self.assertEqual(_dividers(topo), ["Voltage divider R2/R3"])
        self.assertEqual(sorted(f["summary"] for f in topo["feedback_networks"]),
                         ["Voltage divider R2/R3"])


class RealDividersStay(unittest.TestCase):
    def _sense_with_top(self, top_pins, labels=None):
        """R1 from the top net to MID, R2 from MID to GND, an IC output driving MID."""
        parts = [_two_pin("R1", "10k", "TOP", "MID"), _two_pin("R2", "10k", "MID", "GND")]
        ics = [("U9", "LM358", "1", "OUT", "MID", "output")] + list(top_pins)
        return _dividers(_topo(parts, ics, labels))

    def test_rail_on_top_stays(self):
        parts = [_two_pin("R1", "10k", "+5V", "MID"), _two_pin("R2", "10k", "MID", "GND")]
        ics = [("U1", "MCU", "1", "PA0", "MID", "input"), ("U1", "MCU", "2", "VDD", "+5V", "power_in")]
        self.assertEqual(_dividers(_topo(parts, ics)), ["Voltage divider R1/R2"])

    def test_hierarchical_label_on_top_stays(self):
        top = [("U1", "MCU", "1", "PA0", "TOP", "input")]
        labels = {"TOP": [{"name": "TOP", "type": "hierarchical_label"}]}
        self.assertEqual(self._sense_with_top(top, labels), ["Voltage divider R1/R2"])

    def test_input_pins_named_like_sources_stay(self):
        for name in ("MICBIAS", "VREF"):
            with self.subTest(pin=name):
                top = [("U1", "CODEC", "1", name, "TOP", "input")]
                self.assertEqual(self._sense_with_top(top), ["Voltage divider R1/R2"])

    def test_opamp_output_on_top_stays(self):
        top = [("U1", "LM358", "1", "OUT", "TOP", "output")]
        self.assertEqual(self._sense_with_top(top), ["Voltage divider R1/R2"])

    def test_no_source_on_either_end_stays(self):
        parts = [_two_pin("R1", "10k", "TOP", "MID"), _two_pin("R2", "10k", "MID", "GND")]
        ics = [("U1", "MCU", "1", "PA0", "TOP", "input"), ("U1", "MCU", "2", "PA1", "MID", "input")]
        self.assertEqual(_dividers(_topo(parts, ics)), ["Voltage divider R1/R2"])


if __name__ == "__main__":
    unittest.main()
