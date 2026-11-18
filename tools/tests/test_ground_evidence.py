"""A net is ground by what sits on it, whatever label names it.

A one-pin ground symbol (``power:GND``, the SPICE ground ``0``) on a net that another label
names makes that net ground: KiCad connects them, so the net is the ground. A ``COM`` net is
ground when a ground label or an IC ground pin is on it, or when it is the common return of an
isolated converter. A relay, multiplexer or switch ``COM`` stays a common, and protective
earth stays out.
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402


def _pin(ref, num, name, pin_type="passive"):
    return dict(component=ref, pin_number=num, pin_name=name, pin_type=pin_type)


def _part(ref, typ, value, lib_id, pin_names):
    return {"reference": ref, "type": typ, "value": value, "lib_id": lib_id, "footprint": "",
            "properties": {}, "pins": [{"number": n, "name": nm} for n, nm in pin_names]}


def _symbol(ref, value, lib_id, pins=(("1", "~"),)):
    return _part(ref, "power_symbol", value, lib_id, list(pins))


def _cap(ref):
    return _part(ref, "capacitor", "100n", "Device:C", [("1", "~"), ("2", "~")])


def _ctx(comps, nets, labels=None):
    """Context built the production way: power rails come from the ``#PWR`` / ``#FLG`` scan."""
    labels = labels or {}
    full = {n: {"name": n, "pins": ps, "point_count": 0, "no_connect": False,
                "has_pwr_flag": False, "labels": [{"name": lb} for lb in labels.get(n, ())]}
            for n, ps in nets.items()}
    return build_analysis_context(comps, full, {}, source="test")


def _sym_pin(ref):
    return _pin(ref, "1", "~", "power_in")


class GroundSymbolEvidence(unittest.TestCase):
    def test_spice_ground_symbol_makes_net_0_ground(self):
        for lib_id in ("Simulation_SPICE:0", "pspice:0"):
            with self.subTest(lib_id=lib_id):
                ctx = _ctx([_symbol("#GND01", "0", lib_id), _cap("C1")],
                           {"0": [_sym_pin("#GND01"), _pin("C1", "2", "~")],
                            "OUT": [_pin("C1", "1", "~")]})
                self.assertTrue(ctx.is_ground("0"))
                self.assertIn("0", ctx.ground_evidence)

    def test_connector_pin_labelled_0_is_a_signal(self):
        ctx = _ctx([_part("J1", "connector", "Conn_01x02", "Connector:Conn_01x02",
                          [("1", "0"), ("2", "1")])],
                   {"0": [_pin("J1", "1", "0")], "1": [_pin("J1", "2", "1")]},
                   labels={"0": ["0"]})
        self.assertFalse(ctx.is_ground("0"))

    def test_global_label_on_a_ground_symbol_net_is_ground(self):
        ctx = _ctx([_symbol("#PWR01", "GND", "power:GND"),
                    _part("U1", "ic", "LM1117-3.3", "Regulator_Linear:LM1117-3.3",
                          [("1", "GND"), ("2", "VO"), ("3", "VI")])],
                   {"THERMISTOR_B": [_sym_pin("#PWR01"), _pin("U1", "1", "GND", "power_in")]},
                   labels={"THERMISTOR_B": ["THERMISTOR_B"]})
        self.assertTrue(ctx.is_ground("THERMISTOR_B"))

    def test_ground_symbol_with_a_ground_named_pin_counts(self):
        ctx = _ctx([_symbol("#PWR01", "GNDREF", "power:GNDREF", [("1", "GNDREF")]), _cap("C1")],
                   {"AIN1": [_pin("#PWR01", "1", "GNDREF", "power_in"), _pin("C1", "2", "~")]})
        self.assertTrue(ctx.is_ground("AIN1"))

    def test_supply_named_net_with_a_stray_ground_symbol_stays_power(self):
        ctx = _ctx([_symbol("#PWR01", "+5V", "power:+5V"), _symbol("#PWR02", "GND", "power:GND"),
                    _part("U1", "ic", "74HC00", "74xx:74HC00", [("14", "VCC")])],
                   {"+5V": [_sym_pin("#PWR01"), _sym_pin("#PWR02"),
                            _pin("U1", "14", "VCC", "power_in")]})
        self.assertFalse(ctx.is_ground("+5V"))
        self.assertTrue(ctx.is_power_net("+5V"))

    def test_zero_ohm_resistor_typed_as_a_power_symbol_is_no_evidence(self):
        ctx = _ctx([_symbol("#R42", "0", "Device:R", [("1", "~"), ("2", "~")]),
                    _part("U1", "ic", "ATmega328P", "MCU:ATmega328P", [("5", "PD3")])],
                   {"SIG": [_pin("#R42", "1", "~"), _pin("U1", "5", "PD3", "bidirectional")],
                    "SIG2": [_pin("#R42", "2", "~")]})
        self.assertFalse(ctx.is_ground("SIG"))

    def test_two_pin_power_symbol_is_no_evidence(self):
        ctx = _ctx([_symbol("#PWR0104", "GND", "power:GND", [("1", "~"), ("2", "~")]), _cap("C1")],
                   {"SENSE": [_pin("#PWR0104", "1", "~", "power_in"), _pin("C1", "1", "~")]})
        self.assertFalse(ctx.is_ground("SENSE"))

    def test_shared_unannotated_reference_is_no_evidence(self):
        # Two unannotated power ports share #PWR?: the lookup by reference cannot tell which
        # one sits on the net.
        ctx = _ctx([_symbol("#PWR?", "USB_DM", "power:USB_DM"),
                    _symbol("#PWR?", "GND", "power:GND"),
                    _part("U1", "ic", "STM32F103", "MCU:STM32F103", [("32", "PA11")])],
                   {"USB_DM": [_sym_pin("#PWR?"), _pin("U1", "32", "PA11", "bidirectional")]})
        self.assertFalse(ctx.is_ground("USB_DM"))

    def test_renamed_ground_symbol_is_no_evidence(self):
        # A power:GND symbol whose value was edited to another name names that net, not ground.
        ctx = _ctx([_symbol("#PWR01", "VREF", "power:GND"), _cap("C1")],
                   {"VREF": [_sym_pin("#PWR01"), _pin("C1", "1", "~")]})
        self.assertFalse(ctx.is_ground("VREF"))

    def test_net_with_only_power_symbols_is_no_evidence(self):
        ctx = _ctx([_symbol("#PWR01", "GND", "power:GND")],
                   {"N1": [_sym_pin("#PWR01")]})
        self.assertFalse(ctx.is_ground("N1"))

    def test_earth_named_net_with_a_ground_symbol_stays_earth(self):
        # Protective earth stays out of the signal ground even when a GND symbol is drawn on it.
        for name in ("Earth", "Earth_Protective", "PE", "/power/CHASSIS"):
            with self.subTest(name=name):
                ctx = _ctx([_symbol("#PWR01", "Earth", "power:Earth"),
                            _symbol("#PWR02", "GND", "power:GND"),
                            _part("U1", "ic", "STM32F103", "MCU:STM32F103", [("1", "VSS")])],
                           {name: [_sym_pin("#PWR01"), _sym_pin("#PWR02"),
                                   _pin("U1", "1", "VSS", "power_in")]})
                self.assertFalse(ctx.is_ground(name))

    def test_earth_symbol_is_no_evidence(self):
        ctx = _ctx([_symbol("#PWR01", "Earth", "power:Earth"), _cap("C1")],
                   {"Earth": [_sym_pin("#PWR01"), _pin("C1", "1", "~")]})
        self.assertFalse(ctx.is_ground("Earth"))


class ComEvidence(unittest.TestCase):
    """A relay, multiplexer or switch COM pin is a common, not a return."""

    def _com_ctx(self, part, com_pin, labels=None):
        num, name = com_pin
        return _ctx([part, _cap("C1"), _symbol("#PWR01", "GND", "power:GND")],
                    {"COM": [_pin(part["reference"], num, name), _pin("C1", "1", "~")],
                     "GND": [_sym_pin("#PWR01"), _pin("C1", "2", "~")]},
                    labels=labels)

    def test_relay_com_is_a_common(self):
        relay = _part("K1", "relay", "G5LE-1", "Relay:G5LE-1",
                      [("1", "COM"), ("2", "NO"), ("3", "NC")])
        self.assertFalse(self._com_ctx(relay, ("1", "COM")).is_ground("COM"))

    def test_multiplexer_com_is_a_common(self):
        for value, pins in (("CD74HC4067", [("1", "COM"), ("12", "GND"), ("24", "VCC")]),
                            ("DG449", [("1", "COM"), ("2", "NO"), ("4", "GND"), ("5", "V+")])):
            with self.subTest(value=value):
                mux = _part("U1", "ic", value, "Analog_Switch:" + value, pins)
                self.assertFalse(self._com_ctx(mux, ("1", "COM")).is_ground("COM"))

    def test_part_with_an_unsigned_vout_and_a_com_is_not_a_return(self):
        part = _part("U1", "ic", "SENSOR", "Sensor:SENSOR", [("1", "VOUT"), ("2", "COM")])
        self.assertFalse(self._com_ctx(part, ("2", "COM")).is_ground("COM"))

    def test_isolated_converter_com_is_ground(self):
        mgj2 = _part("U3", "ic", "MGJ2", "Converter_DCDC:MGJ2",
                     [("1", "VIN+"), ("2", "VIN-"), ("5", "VOUT-"), ("6", "COM"), ("7", "VOUT+")])
        ctx = self._com_ctx(mgj2, ("6", "COM"))
        self.assertTrue(ctx.is_ground("COM"))
        self.assertIn("COM", ctx.ground_evidence)

    def test_com_net_with_a_ground_label_is_ground(self):
        relay = _part("K1", "relay", "G5LE-1", "Relay:G5LE-1", [("1", "COM")])
        self.assertTrue(self._com_ctx(relay, ("1", "COM"),
                                      labels={"COM": ["COM", "GND_ISO"]}).is_ground("COM"))

    def test_com_net_with_ic_ground_pins_is_ground(self):
        ft232 = _part("IC1", "ic", "FT232RL", "Interface_USB:FT232RL",
                      [("7", "GND"), ("18", "GND1"), ("25", "AGND")])
        ctx = _ctx([ft232, _cap("C1")],
                   {"COM": [_pin("IC1", "7", "GND", "power_in"), _pin("IC1", "18", "GND1", "power_in"),
                            _pin("IC1", "25", "AGND", "power_in"), _pin("C1", "2", "~")]})
        self.assertTrue(ctx.is_ground("COM"))

    def test_sheet_com_net_with_an_isolated_ground_pin_is_ground(self):
        amc = _part("U8", "ic", "AMC1301", "Amplifier_Instrumentation:AMC1301",
                    [("3", "VINN"), ("4", "GND1")])
        ctx = _ctx([amc], {"/V_PHASE/COM": [_pin("U8", "3", "VINN", "input"),
                                            _pin("U8", "4", "GND1", "power_in")]})
        self.assertTrue(ctx.is_ground("/V_PHASE/COM"))


if __name__ == "__main__":
    unittest.main()
