import os, sys, tempfile, unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_core.netnames import is_power_net_name  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from validation_detectors import _estimate_rail_voltage_for_ic, validate_voltage_levels  # noqa: E402
from schematic.pipeline import analyze_schematic  # noqa: E402
from pcb.routing import board_pin_signals  # noqa: E402


class NegativeDecimalPrefixedRails(unittest.TestCase):
    # Each name is a rail in a corpus design: a negative supply, a decimal voltage,
    # a conventional supply pin name, or a voltage behind a domain prefix.
    def test_negative_rails(self):
        for name in ["-12V", "-5V_F", "-114V", "-15V", "-BATT", "-BAT", "-VIN", "-2V5",
                     "/Analog/-12V"]:
            self.assertTrue(is_power_net_name(name), name)

    def test_decimal_rails(self):
        for name in ["3.3V", "5.5V", "2.5V", "3.3V_OUT", "1.25V_REF", "/Power/3.3V"]:
            self.assertTrue(is_power_net_name(name), name)

    def test_supply_pin_names(self):
        for name in ["VPP", "VM", "/Motors/Vm", "VEE", "VNEG"]:
            self.assertTrue(is_power_net_name(name), name)

    def test_prefixed_rails(self):
        for name in ["MCU3v3", "AVDD1V8_PLL", "D+5V", "CAN+5V"]:
            self.assertTrue(is_power_net_name(name), name)


class SignalsStaySignals(unittest.TestCase):
    def test_ground_and_control_lines(self):
        for name in ["0V", "0.0V", "5VEN", "12VPG", "PWM_5V", "EN_5V", "TX_3V3",
                     "3.3V_EN", "-12V_PG", "-5VEN", "3.3VPG"]:
            self.assertFalse(is_power_net_name(name), name)

    def test_active_low_and_control_prefixed_names(self):
        # A leading '-' is also an active-low mark (-RESET, -CS); a control prefix glued
        # to a voltage (PWM3V3, EN1V8) names a signal about the rail.
        for name in ["-RESET", "-CS", "-WR", "-IN", "PWM3V3", "EN1V8", "IO3V3", "TX+5V",
                     "PWRGD1V2", "PG3V3", "SWDIO1V8", "VSNS5V0_P"]:
            self.assertFalse(is_power_net_name(name), name)

    def test_logic_signals_named_after_their_level(self):
        # Level-shifted signals named <level>_<signal> (corpus: 3.3V_SDA, 3.3V_RC_DIR).
        for name in ["3.3V_SDA", "3.3V_SCL", "3.3V_TX", "1.8V_RC_DIR", "3.3VCTL"]:
            self.assertFalse(is_power_net_name(name), name)


def _ctx(components, nets):
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type=t)
                                    for r, p, pn, t in pins],
                "point_count": 0, "no_connect": False, "has_pwr_flag": False, "labels": []}
            for n, pins in nets.items()}
    return build_analysis_context(components, full, {}, known_power_rails=set())


class NegativeRailIsNotALogicDomain(unittest.TestCase):
    # An op-amp on +5 V / -12 V drives a 5 V MCU: its logic swing is set by the positive
    # supply, so its negative rail (now a power net) must not make it a 12 V IC.
    def test_split_supply_ic_takes_its_positive_rail(self):
        comps = [{"reference": "U1", "type": "ic", "value": "TL072"},
                 {"reference": "U2", "type": "ic", "value": "ATMEGA328P"}]
        nets = {"-12V": [("U1", "4", "V-", "power_in")],
                "+5V": [("U1", "8", "V+", "power_in"), ("U2", "7", "VCC", "power_in")],
                "GND": [("U2", "8", "GND", "power_in")],
                "SIG": [("U1", "1", "OUT", "output"), ("U2", "23", "PC0", "bidirectional")]}
        ctx = _ctx(comps, nets)
        self.assertEqual(_estimate_rail_voltage_for_ic(ctx, "U1"), 5.0)
        self.assertEqual([f for f in validate_voltage_levels(ctx) if f["rule_id"] == "VM-001"], [])

    def test_negative_only_ic_keeps_its_magnitude(self):
        comps = [{"reference": "U1", "type": "ic", "value": "MC10H116"}]
        nets = {"-5.2V": [("U1", "8", "VEE", "power_in")]}
        self.assertEqual(_estimate_rail_voltage_for_ic(_ctx(comps, nets), "U1"), 5.2)



def _pin(kind, name, num, x):
    return (f'(pin {kind} line (at {x} 0 0) (length 2.54) (name "{name}" (effects (font (size 1.27 1.27))))'
            f' (number "{num}" (effects (font (size 1.27 1.27)))))')


def _lib(lib_id, ref, pins):
    n = lib_id.split(":")[1]
    return (f'(symbol "{lib_id}" (in_bom yes) (on_board yes) (property "Reference" "{ref}" (at 0 0 0))'
            f' (property "Value" "{n}" (at 0 0 0)) (symbol "{n}_1_1" {" ".join(_pin(*p) for p in pins)}))')


class _Sheet:
    def __init__(self):
        self.libs, self.body = [], []

    def _uuid(self):
        return f"00000000-0000-0000-0000-{len(self.body) + 1:012d}"

    def place(self, lib, ref, value, x, y=100):
        if lib not in self.libs:
            self.libs.append(lib)
        lib_id = lib.split('"')[1]
        self.body.append(f'(symbol (lib_id "{lib_id}") (at {x} {y} 0) (unit 1) (in_bom yes) (on_board yes)'
                         f' (uuid "{self._uuid()}") (property "Reference" "{ref}" (at 0 0 0))'
                         f' (property "Value" "{value}" (at 0 0 0)))')

    def label(self, name, x, y=100):
        self.body.append(f'(label "{name}" (at {x} {y} 0) (effects (font (size 1.27 1.27)))'
                         f' (uuid "{self._uuid()}"))')

    def analyze(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.kicad_sch")
            with open(path, "w", encoding="utf-8") as f:
                f.write('(kicad_sch (version 20250114) (generator "eeschema")'
                        ' (uuid "00000000-0000-0000-0000-0000000000aa") (paper "A4")'
                        f' (lib_symbols {" ".join(self.libs)}) {" ".join(self.body)})')
            with redirect_stderr(StringIO()):
                return analyze_schematic(path)


CAP = _lib("t:C", "C", [("passive", "~", "1", -2.54), ("passive", "~", "2", 2.54)])
CONN = _lib("t:CONN", "J", [("passive", "Pin_1", "1", 0)])
RES = _lib("t:R", "R", [("passive", "~", "1", -2.54), ("passive", "~", "2", 2.54)])


def _rails(result):
    return {r["name"] for r in result["statistics"]["power_rails"]}


def _mentions(result, name):
    return sorted(f["rule_id"] + " " + f["summary"] for f in result["findings"]
                  if name in f.get("summary", ""))


class SupplyPinNamesFollowThePins(unittest.TestCase):
    # VPP and VM name supply pins (EPROM/OLED VPP, motor-driver VM) and also signals: a
    # PIC's ~MCLR/VPP line, an op-amp node called Vm. A net named so is power when a
    # power pin is on it or no IC pin is; an IC signal pin alone makes it a signal.
    def _decoupled(self, sheet, x):
        sheet.place(CAP, "C9", "100n", x)
        sheet.label("+5V", x - 2.54)
        sheet.label("GND", x + 2.54)

    def test_mclr_vpp_line_is_a_signal(self):
        s = _Sheet()
        s.place(_lib("t:PIC", "U", [("power_in", "VDD", "1", -5), ("input", "~{MCLR}/VPP", "4", 5),
                                    ("power_in", "VSS", "8", 10)]), "U1", "PIC16F1847", 100)
        s.label("+5V", 95)
        s.label("VPP", 105)
        s.label("GND", 110)
        s.place(CONN, "J1", "ICSP", 150)
        s.label("VPP", 150)
        self._decoupled(s, 200)
        r = s.analyze()
        self.assertNotIn("VPP", _rails(r))
        self.assertEqual(_mentions(r, "VPP"), [])

    def test_motor_driver_vm_is_power(self):
        s = _Sheet()
        s.place(_lib("t:DRV", "U", [("power_in", "VM", "1", -5), ("power_in", "GND", "2", 5)]),
                "U1", "DRV8837", 100)
        s.label("VM", 95)
        s.label("GND", 105)
        s.place(CAP, "C1", "10u", 150)
        s.label("VM", 147.46)
        s.label("GND", 152.54)
        self.assertIn("VM", _rails(s.analyze()))

    def test_vm_on_an_unspecified_driver_pin_is_power(self):
        # Corpus: DRV8231 symbols whose VM pin is typed unspecified; only a signal pin
        # type makes the net a signal.
        s = _Sheet()
        s.place(_lib("t:DRV2", "U", [("unspecified", "VM", "1", -5), ("power_in", "GND", "2", 5)]),
                "U1", "DRV8231", 100)
        s.label("VM", 95)
        s.label("GND", 105)
        s.place(CAP, "C1", "10u", 150)
        s.label("VM", 147.46)
        s.label("GND", 152.54)
        self.assertIn("VM", _rails(s.analyze()))

    def test_connector_and_cap_vpp_is_power(self):
        s = _Sheet()
        s.place(CONN, "J1", "FPC", 100)
        s.label("VPP", 100)
        s.place(CAP, "C1", "1u", 150)
        s.label("VPP", 147.46)
        s.label("GND", 152.54)
        self.assertIn("VPP", _rails(s.analyze()))

    def test_op_amp_vm_node_is_a_signal(self):
        s = _Sheet()
        s.place(_lib("t:OPA", "U", [("input", "-", "2", -5), ("output", "~", "1", 5),
                                    ("power_in", "V+", "8", -10), ("power_in", "V-", "4", 10)]),
                "U2", "MCP6004", 100)
        s.label("Vm", 95)
        s.label("Vm", 105)
        s.label("+5V", 90)
        s.label("GND", 110)
        s.place(RES, "R1", "100k", 150)
        s.label("Vm", 147.46)
        s.label("GND", 152.54)
        self._decoupled(s, 200)
        r = s.analyze()
        self.assertNotIn("Vm", _rails(r))
        self.assertEqual(_mentions(r, "Vm"), [])


class BoardSupplyPinNamesFollowThePads(unittest.TestCase):
    def _fp(self, *pads):
        return {"reference": "U1", "pads": [{"net_name": n, "pintype": t} for n, t in pads]}

    def test_pad_pin_types_decide(self):
        fps = [self._fp(("VPP", "input"), ("VM", "power_in"), ("/x/Vm", "bidirectional"), ("VPP2", "input"),
                        ("Vpp", "unspecified")),
               {"reference": "J1", "pads": [{"net_name": "VPP", "pintype": "passive"},
                                            {"net_name": "VM", "pintype": "passive"}]}]
        self.assertEqual(board_pin_signals(fps), frozenset({"VPP", "/x/Vm"}))
        self.assertEqual(board_pin_signals(fps, {"VPP"}), frozenset({"/x/Vm"}))

    def test_board_without_pin_types_keeps_the_name_rule(self):
        self.assertEqual(board_pin_signals([{"reference": "U1", "pads": [{"net_name": "VPP"}]}]),
                         frozenset())


if __name__ == "__main__":
    unittest.main()
