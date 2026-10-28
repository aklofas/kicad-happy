# tools/tests/test_rc_lc_filters_w4.py
"""RC/LC filters: parallel parts as one equivalent, high-pass input/output nets, a 3-pin
potentiometer is not a filter resistor; ADC anti-aliasing filters found by their R-C
junction; clock-distribution records carry the oscillator frequency; USB observations see
every net an ESD array protects.  Cutoffs are 1/(2*pi*R*C) by hand."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from kicad_types import build_analysis_context  # noqa: E402
import signal_detectors as sd  # noqa: E402
import domain_detectors as dd  # noqa: E402


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


def _r(ref, value, lib_id="Device:R"):
    return {"reference": ref, "type": "resistor", "value": value, "lib_id": lib_id}


def _c(ref, value):
    return {"reference": ref, "type": "capacitor", "value": value, "lib_id": "Device:C"}


def _p(ref, pin="1"):
    return (ref, pin, "~", "passive")


def _ic(ref, value, lib_id, pins):
    """``pins`` = [(number, name, net, pin_type)]."""
    return {"reference": ref, "type": "ic", "value": value, "lib_id": lib_id,
            "pins": [{"number": n, "name": nm} for n, nm, _, _ in pins]}


def _ic_net_pins(ref, pins):
    out = {}
    for n, nm, net, t in pins:
        out.setdefault(net, []).append((ref, n, nm, t))
    return out


def _merge(*maps):
    out = {}
    for m in maps:
        for k, v in m.items():
            out.setdefault(k, []).extend(v)
    return out


def _rc(ctx):
    return sd.detect_rc_filters(ctx, [], [], [])


class HighPass(unittest.TestCase):
    def test_input_is_the_capacitor_far_node(self):
        ctx = _ctx([_c("C1", "100n"), _r("R1", "10k")],
                   {"IN": [_p("C1", "1")], "OUT": [_p("C1", "2"), _p("R1", "1")],
                    "GND": [_p("R1", "2")]})
        got = [(f["type"], f["input_net"], f["output_net"], f["ground_net"], f["cutoff_hz"])
               for f in _rc(ctx)]
        self.assertEqual(got, [("high-pass", "IN", "OUT", "GND", 159.15)])

    def test_caps_from_two_sources_are_two_filters(self):
        # C1 from IN1 and C2 from IN2 onto one R-to-GND node: not parallel, two filters
        ctx = _ctx([_c("C1", "100n"), _c("C2", "100n"), _r("R1", "10k")],
                   {"IN1": [_p("C1", "1")], "IN2": [_p("C2", "1")],
                    "OUT": [_p("C1", "2"), _p("C2", "2"), _p("R1", "1")],
                    "GND": [_p("R1", "2")]})
        got = sorted((f["capacitor"]["ref"], f["input_net"], f["output_net"], f["cutoff_hz"])
                     for f in _rc(ctx))
        self.assertEqual(got, [("C1", "IN1", "OUT", 159.15), ("C2", "IN2", "OUT", 159.15)])
        self.assertFalse(any("parallel_caps" in f["capacitor"] for f in _rc(ctx)))


class ParallelParts(unittest.TestCase):
    def test_two_equal_parallel_resistors_double_the_cutoff(self):
        # R14 || R21 2k2 = 1k1 with 47 nF: 1539.22 Hz for one resistor, 3078.43 Hz for the pair
        ctx = _ctx([_r("R14", "2k2"), _r("R21", "2k2"), _c("C5", "47n")],
                   {"SIG": [_p("R14", "1"), _p("R21", "1")],
                    "FILT": [_p("R14", "2"), _p("R21", "2"), _p("C5", "1")],
                    "GND": [_p("C5", "2")]})
        rcs = _rc(ctx)
        self.assertEqual(len(rcs), 1)
        rc = rcs[0]
        self.assertEqual(rc["cutoff_hz"], 3078.43)
        self.assertEqual(rc["resistor"], {"ref": "R14", "value": "2 resistors parallel", "ohms": 1100.0,
                                          "parallel_refs": ["R14", "R21"]})
        self.assertEqual(rc["components"], ["R14", "R21", "C5"])
        self.assertIn("3078.43Hz", rc["summary"])

    def test_parallel_caps_keep_their_alias_and_merged_summary(self):
        # R1 10k with C1 || C2 100 nF = 200 nF: 79.58 Hz
        ctx = _ctx([_r("R1", "10k"), _c("C1", "100n"), _c("C2", "100n")],
                   {"SIG": [_p("R1", "1")],
                    "FILT": [_p("R1", "2"), _p("C1", "1"), _p("C2", "1")],
                    "GND": [_p("C1", "2"), _p("C2", "2")]})
        rcs = _rc(ctx)
        self.assertEqual(len(rcs), 1)
        self.assertEqual(rcs[0]["capacitor"]["value"], "2 caps parallel")
        self.assertEqual(rcs[0]["capacitor"]["parallel_caps"], ["C1", "C2"])
        self.assertEqual(rcs[0]["cutoff_hz"], 79.58)
        self.assertIn("79.58Hz", rcs[0]["summary"])
        self.assertEqual(rcs[0]["components"], ["R1", "C1", "C2"])

    def test_parallel_inductors_are_one_equivalent(self):
        # L1 || L2 10 uH = 5 uH with 1 uF: f0 = 1/(2*pi*sqrt(5e-6*1e-6)) = 71176.25 Hz
        ctx = _ctx([{"reference": "L1", "type": "inductor", "value": "10u", "lib_id": "Device:L"},
                    {"reference": "L2", "type": "inductor", "value": "10u", "lib_id": "Device:L"},
                    _c("C1", "1u")],
                   {"IN": [_p("L1", "1"), _p("L2", "1")],
                    "OUT": [_p("L1", "2"), _p("L2", "2"), _p("C1", "1")],
                    "GND": [_p("C1", "2")]})
        lcs = sd.detect_lc_filters(ctx)
        self.assertEqual(len(lcs), 1)
        ind = dict(lcs[0]["inductor"])
        self.assertAlmostEqual(ind.pop("henries"), 5e-06, delta=1e-18)
        self.assertEqual(ind, {"ref": "L1", "value": "2 inductors parallel", "parallel_refs": ["L1", "L2"]})
        self.assertEqual(lcs[0]["components"], ["L1", "L2", "C1"])
        self.assertEqual(lcs[0]["resonant_hz"], 71176.25)

    def test_three_pin_potentiometer_is_not_a_filter_resistor(self):
        # C10 DC block into node 8; R24 1k node 8 -> RIG_GND is the filter; RV1's pins 1-2
        # also touch node 8 but a 3-pin pot is not a two-terminal resistor
        pot = _r("RV1", "10k", lib_id="Device:R_Potentiometer_US")
        ctx = _ctx([_c("C10", "47u"), _r("R24", "1k"), pot],
                   {"RIG_AF_IN": [_p("C10", "1")],
                    "N8": [_p("C10", "2"), _p("R24", "1"), _p("RV1", "1")],
                    "RIG_GND": [_p("R24", "2")],
                    "WIPER": [_p("RV1", "2")], "TOP": [_p("RV1", "3")]},
                   rails=())
        got = [(f["resistor"]["ref"], f["capacitor"]["ref"]) for f in _rc(ctx)]
        self.assertNotIn("RV1", [r for r, _ in got])
        self.assertIn(("R24", "C10"), got)


_ADS1115_PINS = [("1", "ADDR", "GND", "input"), ("2", "ALERT/RDY", "ALRT", "output"),
                 ("3", "GND", "GND", "power_in"), ("4", "AIN0", "AIN0", "input"),
                 ("5", "AIN1", "AIN1", "input"), ("6", "AIN2", "AIN2", "input"),
                 ("7", "AIN3", "AIN3", "input"), ("8", "VDD", "+3V3", "power_in"),
                 ("9", "SDA", "SDA", "bidirectional"), ("10", "SCL", "SCL", "input")]


def _adc(extra_comps, extra_nets):
    u = _ic("U1", "ADS1115", "Analog_ADC:ADS1115IDGS", _ADS1115_PINS)
    ctx = _ctx([u] + extra_comps, _merge(_ic_net_pins("U1", _ADS1115_PINS), extra_nets))
    rcs = _rc(ctx)
    adcs = [a for a in dd.detect_adc_circuits(ctx, rcs, []) if a["ref"] == "U1"]
    return adcs[0]


class AntiAliasing(unittest.TestCase):
    def test_single_ended_low_pass(self):
        # SIG -> 1k -> AIN0, 100 nF AIN0 -> GND: 1591.55 Hz
        adc = _adc([_r("R1", "1k"), _c("C1", "100n")],
                   {"SIG": [_p("R1", "1")], "AIN0": [_p("R1", "2"), _p("C1", "1")],
                    "GND": [_p("C1", "2")]})
        self.assertEqual(adc["anti_aliasing"], [{"channel": "AIN0", "rc_ref_r": "R1", "rc_ref_c": "C1",
                                                 "cutoff_hz": 1591.55}])

    def test_differential_pair_each_channel_its_own_resistor(self):
        # R1 SIGP -> AIN0, R2 SIGN -> AIN1, C1 100 nF across AIN0/AIN1
        adc = _adc([_r("R1", "1k"), _r("R2", "1k"), _c("C1", "100n")],
                   {"SIGP": [_p("R1", "1")], "SIGN": [_p("R2", "1")],
                    "AIN0": [_p("R1", "2"), _p("C1", "1")], "AIN1": [_p("R2", "2"), _p("C1", "2")]})
        got = {a["channel"]: (a["rc_ref_r"], a["rc_ref_c"]) for a in adc["anti_aliasing"]}
        self.assertEqual(got, {"AIN0": ("R1", "C1"), "AIN1": ("R2", "C1")})

    def test_filter_of_another_channel_is_not_attached(self):
        # AIN0 sits directly on SIG; SIG -> R1 -> AIN1 with C1 AIN1 -> GND filters AIN1 only.
        # R1 touches SIG = AIN0's net, but its R-C junction is AIN1.
        adc = _adc([_r("R1", "1k"), _c("C1", "100n")],
                   {"AIN0": [_p("R1", "1")], "AIN1": [_p("R1", "2"), _p("C1", "1")],
                    "GND": [_p("C1", "2")]})
        self.assertEqual([(a["channel"], a["rc_ref_r"]) for a in adc["anti_aliasing"]],
                         [("AIN1", "R1")])


class ClockFrequency(unittest.TestCase):
    def test_oscillator_frequency_reaches_clock_distribution(self):
        osc_pins = [("1", "EN", "+3V3", "input"), ("2", "GND", "GND", "power_in"),
                    ("3", "OUT", "CLK", "output"), ("4", "VDD", "+3V3", "power_in")]
        mcu_pins = [("1", "OSC_IN", "CLK", "input"), ("2", "VDD", "+3V3", "power_in"),
                    ("3", "VSS", "GND", "power_in")]
        osc = {"reference": "X1", "type": "oscillator", "value": "16MHz",
               "lib_id": "Oscillator:ASE-xxxMHz",
               "pins": [{"number": n, "name": nm} for n, nm, _, _ in osc_pins]}
        mcu = _ic("U2", "STM32F103C8T6", "MCU_ST_STM32F1:STM32F103C8Tx", mcu_pins)
        ctx = _ctx([osc, mcu], _merge(_ic_net_pins("X1", osc_pins), _ic_net_pins("U2", mcu_pins)))
        xcs = sd.detect_crystal_circuits(ctx)
        cds = [c for c in dd.detect_clock_distribution(ctx, xcs) if c["ref"] == "X1"]
        self.assertEqual(len(cds), 1)
        self.assertEqual(cds[0]["frequency_hz"], 16e6)
        self.assertEqual(cds[0]["summary"], "Oscillator output X1 (16MHz) 16 MHz")


class EsdArray(unittest.TestCase):
    def test_every_net_of_an_esd_array_counts(self):
        esd_pins = [("1", "I/O1", "DP", "passive"), ("2", "GND", "GND", "power_in"),
                    ("3", "I/O2", "DM", "passive"), ("4", "I/O2", "DM", "passive"),
                    ("5", "VBUS", "+5V", "power_in"), ("6", "I/O1", "DP", "passive")]
        con_pins = [("1", "VBUS", "+5V", "power_out"), ("2", "D-", "DM", "bidirectional"),
                    ("3", "D+", "DP", "bidirectional"), ("4", "GND", "GND", "power_out")]
        esd = _ic("U3", "USBLC6-2SC6", "Power_Protection:USBLC6-2SC6", esd_pins)
        con = {"reference": "J1", "type": "connector", "value": "USB_B_Micro",
               "lib_id": "Connector:USB_B_Micro",
               "pins": [{"number": n, "name": nm} for n, nm, _, _ in con_pins]}
        ctx = _ctx([esd, con], _merge(_ic_net_pins("U3", esd_pins), _ic_net_pins("J1", con_pins)))
        pds = sd.detect_protection_devices(ctx)
        self.assertEqual([p["protected_nets"] for p in pds if p["ref"] == "U3"], [["DM", "DP"]])
        obs = sd.detect_design_observations(ctx, {"protection_devices": pds})
        usb = {o["net"]: o["has_esd_protection"] for o in obs if o.get("category") == "usb_data"}
        self.assertEqual(usb, {"DM": True, "DP": True})


if __name__ == "__main__":
    unittest.main()
