"""Text that reaches a SPICE netlist cannot start a simulator command line."""
import itertools
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for sub in ("skills/spice/scripts", "skills/kicad/scripts"):
    sys.path.insert(0, os.path.join(ROOT, sub))

import simulate_subcircuits  # noqa: E402
from spice_model_cache import ModelOptions  # noqa: E402
from spice_models import _sanitize_net, spice_ident, spice_text  # noqa: E402

PAYLOAD = "X\n.control\nshell echo pwned\n.endc"
MEAS = "<MEAS>"
# Fields that pick a branch of a template are left as they are.
VOCABULARY = {"configuration", "type", "high_side_type", "low_side_type"}


class _Backend:
    def format_measurement_block(self, *args, **kwargs):
        return MEAS


def _res(ref, ohms=10000):
    return {"ref": ref, "ohms": ohms}


DETECTIONS = {
    "rc_filters": [{"resistor": _res("R1"), "capacitor": {"ref": "C1", "farads": 1e-7},
                    "type": "low-pass", "cutoff_hz": 159.2, "input_net": "IN",
                    "output_net": "OUT", "ground_net": "GND"}],
    "lc_filters": [{"inductor": {"ref": "L1", "henries": 1e-6},
                    "capacitor": {"ref": "C1", "farads": 1e-7},
                    "resonant_hz": 1e6, "shared_net": "SW"}],
    "voltage_dividers": [{"r_top": _res("R2"), "r_bottom": _res("R3"), "ratio": 0.5,
                          "top_net": "+3V3", "mid_net": "MID", "bottom_net": "GND"}],
    "feedback_networks": [{"r_top": _res("R2"), "r_bottom": _res("R3"), "ratio": 0.5,
                           "top_net": "+3V3", "mid_net": "FB",
                           "mid_point_connections": [{"pin_name": "FB", "component": "U2"}]}],
    "opamp_circuits": [
        {"reference": "U1", "value": "LM358", "configuration": cfg, "output_net": "OUT",
         "inverting_input_net": "INN", "non_inverting_input_net": "INP", "gain": -10,
         "gain_dB": 20, "feedback_resistor": _res("R4"), "input_resistor": _res("R5"),
         "feedback_capacitor": {"ref": "C2", "farads": 1e-9}}
        for cfg in ("inverting", "non_inverting", "buffer", "transimpedance_or_buffer")],
    "crystal_circuits": [{"reference": "Y1", "value": "8MHz", "frequency": 8e6,
                          "type": "passive", "effective_load_pF": 12.0,
                          "load_caps": [{"ref": "C1", "farads": 2.2e-11, "net": "XIN"},
                                        {"ref": "C2", "farads": 2.2e-11, "net": "XOUT"}]}],
    "transistor_circuits": [
        {"type": "mosfet", "reference": "Q1", "value": "IRLZ44", "is_pchannel": p,
         "gate_net": "G", "drain_net": "D", "source_net": "S", "load_type": "resistive",
         "has_flyback_diode": True, "flyback_diode": "D1", "has_snubber": True}
        for p in (False, True)] + [
        {"type": "bjt", "reference": "Q2", "value": "BC547", "lib_id": lib,
         "base_net": "B", "collector_net": "C", "emitter_net": "E", "load_type": "led",
         "emitter_resistor": {"reference": "R9", "value": "100"}}
        for lib in ("Device:Q_NPN", "Device:Q_PNP")],
    "current_sense": [{"shunt": _res("R6", 0.01), "sense_ic": {"ref": "U4", "value": "INA219"},
                       "high_net": "VBUS", "low_net": "LOAD",
                       "max_current_50mV_A": 5, "max_current_100mV_A": 10}],
    "protection_devices": [{"ref": "D2", "value": "PESD", "type": "tvs",
                            "protected_net": "USB_D+", "clamp_net": "GND"}],
    "decoupling_analysis": [{"rail": "+3V3", "capacitors": [
        {"ref": "C3", "farads": 1e-7, "self_resonant_hz": 1e7},
        {"ref": "C4", "farads": 1e-5}]}],
    "power_regulators": [{"ref": "U5", "output_rail": "+5V", "assumed_vref": 0.8,
                          "estimated_vout": 5.0,
                          "feedback_divider": {"r_top": _res("R7"), "r_bottom": _res("R8"),
                                               "ratio": 0.16, "topology": "standard"}}],
    "rf_matching": [{"topology": "pi", "components": [
        {"ref": "C5", "type": "C", "farads": 1e-12},
        {"ref": "L2", "type": "L", "henries": 1e-9}]}],
    "bridge_circuits": [{"topology": "half", "half_bridges": [
        {"high_side": "Q3", "low_side": "Q4", "power_net": "VM", "ground_net": "GND",
         "high_side_type": "PMOS", "low_side_type": "NMOS"}]}],
    "bms_systems": [{"bms_reference": "U6", "bms_value": "BQ", "cell_count": 4,
                     "balance_resistors": [{"reference": "R10", "ohms": 100}]}],
    "rf_chains": [{"operating_frequency_hz": 2.4e9, "gain_budget_dB": 10.0,
                   "total_rf_components": 3, "frequency_band": "2.4G"}],
    "snubber_circuits": [{"reference": "Q5", "snubber_data": {
        "resistor_ref": "R11", "resistor_ohms": 10, "capacitor_ref": "C6",
        "capacitor_farads": 1e-9}}],
    "inrush_analysis": [{"regulator": "U7", "output_voltage": 3.3, "topology": "LDO",
                         "output_caps": [{"ref": "C7", "farads": 1e-5}],
                         "assumed_soft_start_ms": 0.5}],
}


def _poison(obj, key=None, counter=None):
    # A distinct suffix per string keeps nets that must differ distinct.
    counter = counter if counter is not None else itertools.count()
    if isinstance(obj, str):
        return obj if key in VOCABULARY else PAYLOAD + str(next(counter))
    if isinstance(obj, dict):
        return {k: _poison(v, k, counter) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_poison(v, key, counter) for v in obj]
    return obj


def _generators():
    table = dict(simulate_subcircuits.TEMPLATE_REGISTRY)
    table.update({k: gen for k, (_, gen) in simulate_subcircuits.TOPLEVEL_REGISTRY.items()})
    return table


def _render(gen, det, **extra):
    kwargs = dict(extra)
    if gen.__name__ == "generate_opamp_circuit":
        kwargs["model_options"] = ModelOptions(offline=True)
    tb = gen(det, "out.txt", **kwargs)
    return None if tb is None else tb.render(_Backend(), "out.txt")


class HelperTest(unittest.TestCase):
    def test_helpers(self):
        self.assertEqual(spice_text("10k 1%"), "10k 1%")
        self.assertEqual(spice_text("a\nb\r\nc\td"), "a b  c d")
        self.assertEqual(spice_text("\u00b5F"), "\u00b5F")
        self.assertEqual(spice_ident("U3"), "U3")
        self.assertEqual(spice_ident("U3\n.control"), "U3_.control")
        self.assertEqual(spice_ident("R1-A"), "R1-A")
        self.assertEqual(spice_ident("U1.2"), "U1.2")
        self.assertEqual(spice_ident("C+1"), "C+1")
        self.assertEqual(spice_ident("R1 A=1"), "R1_A_1")
        self.assertEqual(spice_ident("R(1),2;{3}"), "R_1__2__3_")
        self.assertEqual(_sanitize_net("VCC\n.control"), "VCC_.control")
        self.assertEqual(_sanitize_net("+3V3"), "_3V3")


class InjectionTest(unittest.TestCase):
    def test_every_dispatched_generator_has_a_detection(self):
        self.assertEqual(set(_generators()), set(DETECTIONS))

    def test_no_injected_line_in_any_template(self):
        for name, gen in _generators().items():
            for det in DETECTIONS[name]:
                clean = _render(gen, det)
                self.assertIsNotNone(clean, name)
                text = _render(gen, _poison(det))
                self.assertIsNotNone(text, name)
                for line in text.splitlines():
                    low = line.strip().lower()
                    for bad in (".control", "shell", ".endc"):
                        self.assertFalse(low.startswith(bad), (name, line))

    def test_free_text_ftype_and_context(self):
        det = dict(DETECTIONS["rc_filters"][0], type=PAYLOAD)
        text = _render(_generators()["rc_filters"], det)
        self.assertFalse([l for l in text.splitlines() if l.lower().startswith("shell")])


EXPECTED_RC = """\
* Auto-generated testbench for RC filter: R1/C1
* Type: low-pass, expected fc = 159.2 Hz
* Model: ideal passives (exact for RC)


R1 IN OUT 10k

C1 OUT 0 100n

* AC stimulus
VAC IN 0 DC 0 AC 1

<MEAS>

.end
"""

EXPECTED_VD = """\
* Auto-generated testbench for voltage divider: R2/R3
* Expected Vout = 3.3 * 0.500000 = 1.6500 V
* Model: ideal passives (exact, unloaded)

VIN _3V3 0 DC 3.3
R2 _3V3 MID 10k
R3 MID 0 10k

<MEAS>

.end
"""

EXPECTED_OP = """\
* Auto-generated testbench for opamp: U1 (LM358)
* Configuration: inverting
* Expected gain: -10.000 (20.0 dB)
* Model: LM358 behavioral (lookup:LM358, GBW=1.0MHz)

.subckt OPAMP_LM358 inp inn out vcc vee
* Behavioral model for LM358
* GBW=1.0MHz, SR=0.3V/us, Vos=2.0mV, Aol=100dB
* Source: kicad-happy part library (Phase 2)
*
* Input stage
Rin inp inn 2Meg
Vos inp inp_os DC 0.002
*
* Gain stage: Aol=100000, pole at 10.0Hz → GBW=1.0MHz
E1 int 0 inp_os inn 100000
R1 int out_int 1
C1 out_int 0 15.92m
*
* Output stage with rail clamping
* Output swing: 1.5V from rails
Dhigh out_int vcc_int DLIMIT
Dlow vee_int out_int DLIMIT
Vswh vcc vcc_int DC 1.5
Vswl vee_int vee DC 1.5
.model DLIMIT D(IS=1e-14 N=0.1)
Eout out 0 out_int 0 1
.ends OPAMP_LM358

* Generic semiconductor models for Phase 1 simulation
.model D_GENERIC D(IS=1e-14 N=1.05 BV=100 IBV=1e-10)
.model D_SCHOTTKY D(IS=1e-6 N=1.05 BV=40 IBV=1e-8 RS=0.5)
.model D_ZENER3V3 D(IS=1e-14 N=1.05 BV=3.3 IBV=5e-3)
.model D_ZENER5V1 D(IS=1e-14 N=1.05 BV=5.1 IBV=5e-3)
.model NPN_GENERIC NPN(IS=1e-14 BF=200 VAF=100 CJC=5p CJE=10p TF=0.3n)
.model PNP_GENERIC PNP(IS=1e-14 BF=200 VAF=100 CJC=5p CJE=10p TF=0.6n)
.model NMOS_GENERIC NMOS(VTO=1.5 KP=1e-2 LAMBDA=0.01)
.model PMOS_GENERIC PMOS(VTO=-1.5 KP=5e-3 LAMBDA=0.01)


* Power supplies
V_VCC VCC 0 DC 5
V_VEE VEE 0 DC -5

* Opamp instance
XU1 0 INN OUT VCC VEE OPAMP_LM358

* Feedback network
R4 OUT INN 100k
R5 sig_in INN 10k

* AC stimulus
VAC sig_in 0 DC 0 AC 1

<MEAS>

.end
"""


class CleanValuesTest(unittest.TestCase):
    def test_clean_values_byte_identical(self):
        gens = _generators()
        self.assertEqual(_render(gens["rc_filters"], DETECTIONS["rc_filters"][0]), EXPECTED_RC)
        det = dict(DETECTIONS["voltage_dividers"][0])
        self.assertEqual(_render(gens["voltage_dividers"], det), EXPECTED_VD)
        op = {"reference": "U1", "value": "LM358", "configuration": "inverting",
              "output_net": "OUT", "inverting_input_net": "INN",
              "non_inverting_input_net": "GND", "gain": -10, "gain_dB": 20,
              "feedback_resistor": _res("R4", 100000), "input_resistor": _res("R5")}
        self.assertEqual(_render(gens["opamp_circuits"], op), EXPECTED_OP)


if __name__ == "__main__":
    unittest.main()
