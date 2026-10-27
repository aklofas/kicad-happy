"""A power symbol names and joins a net only through a power-input pin, as KiCad 10 does (a pin
drives a net name only when it is a power input): a PWR_FLAG, whose pin is a power output, never
joins nets by name whatever its Value, while power-input symbols with an empty Value still join
one another.  Expected values are kicad-cli 10.0.6 netlist exports of the same files."""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
sys.path.insert(0, str(ROOT))

from tools.tests.test_same_sheet_power_names import R_LIB, Sheet, members, power_lib, run  # noqa: E402

FLAG_LIB = ('(symbol "power:PWR_FLAG" (power) (pin_numbers hide) (pin_names (offset 0) hide)'
            ' (in_bom yes) (on_board yes)'
            ' (property "Reference" "#FLG" (at 0 0 0)) (property "Value" "PWR_FLAG" (at 0 0 0))'
            ' (symbol "PWR_FLAG_0_1" (pin power_out line (at 0 0 90) (length 0)'
            ' (name "pwr") (number "1"))))')


def flag_files(version):
    """R1 pin 1 and R2 pin 1 each on their own wire to a PWR_FLAG whose placed Value is ""."""
    s = Sheet(version)
    for ref, flag, x in (("R1", "#FLG01", 50), ("R2", "#FLG02", 80)):
        s.r(ref, x, 50); s.wire(x, 50, x, 40)
        s.symbol("power:PWR_FLAG", flag, "", x, 40, ("1",))
    return {"t.kicad_sch": s.text([R_LIB, FLAG_LIB])}


def gnd_files(version, inst_value):
    """R1 pin 1 and R2 pin 1 each on a power:GND (visible power-in pin XX, so no legacy rename)
    whose placed Value is ""; a KiCad 6 root gives each the symbol_instances value
    `inst_value`."""
    s = Sheet(version, path="")
    for ref, pwr, x in (("R1", "#PWR01", 50), ("R2", "#PWR02", 80)):
        s.r(ref, x, 50); s.wire(x, 50, x, 40)
        s.symbol("power:GND", pwr, "", x, 40, ("1",))
        if s.instances:
            s.instances[-1] = s.instances[-1].replace('(value "")', f'(value "{inst_value}")')
    return {"t.kicad_sch": s.text([R_LIB, power_lib("power:GND", "XX", hidden=False)])}


def flag_named_gnd_files():
    """R1 pin 1 on a PWR_FLAG whose Value is "GND"; R2 pin 1 on a power:GND."""
    s = Sheet(20250114)
    s.r("R1", 50, 50); s.wire(50, 50, 50, 40)
    s.symbol("power:PWR_FLAG", "#FLG01", "GND", 50, 40, ("1",))
    s.r("R2", 80, 50); s.wire(80, 50, 80, 40)
    s.symbol("power:GND", "#PWR01", "GND", 80, 40, ("1",))
    return {"t.kicad_sch": s.text([R_LIB, FLAG_LIB, power_lib("power:GND", "GND")])}


def net_with(result, member):
    return [n for n, net in result["nets"].items()
            if any(f'{p["component"]}.{p["pin_number"]}' == member for p in net["pins"])]


class PowerSymbolDrivesTest(unittest.TestCase):
    def test_empty_value_pwr_flags_stay_apart(self):
        # kicad-cli (20250114 and 20211123): Net-(R1-Pad1) = R1.1; Net-(R2-Pad1) = R2.1
        for version in (20250114, 20211123):
            with self.subTest(version=version):
                r = run(flag_files(version))
                n1, n2 = net_with(r, "R1.1"), net_with(r, "R2.1")
                self.assertEqual(len(n1), 1)
                self.assertNotEqual(n1, n2)
                self.assertEqual(members(r, n1[0]), ["R1.1"])
                self.assertTrue(r["nets"][n1[0]]["has_pwr_flag"])

    def test_power_symbols_still_lists_the_flags(self):
        r = run(flag_files(20250114))
        flags = [p for p in r["power_symbols"] if p["lib_id"] == "power:PWR_FLAG"]
        self.assertEqual(len(flags), 2)
        self.assertFalse(any("_drives" in p for p in r["power_symbols"]))

    def test_flag_valued_like_a_rail_does_not_join_it(self):
        # kicad-cli: GND = R2.1; Net-(R1-Pad1) = R1.1
        r = run(flag_named_gnd_files())
        self.assertEqual(members(r, "GND"), ["R2.1"])

    def test_k6_instance_value_names_the_power_net(self):
        # kicad-cli: GND = R1.1 R2.1
        r = run(gnd_files(20211123, "GND"))
        self.assertEqual(members(r, "GND"), ["R1.1", "R2.1"])

    def test_empty_value_power_inputs_still_join(self):
        # kicad-cli (20211123 and 20250114): one net "<NO NET>" = R1.1 R2.1
        for version in (20211123, 20250114):
            with self.subTest(version=version):
                r = run(gnd_files(version, ""))
                self.assertEqual(net_with(r, "R1.1"), net_with(r, "R2.1"))

    def test_drives_rule(self):
        from schematic.reader import power_symbol_drives
        pin_in = [{"type": "power_in"}]
        self.assertTrue(power_symbol_drives({"value": "GND", "pins": pin_in}))
        self.assertTrue(power_symbol_drives({"value": "GND", "pins": []}))
        self.assertTrue(power_symbol_drives({"value": "", "pins": pin_in}))
        self.assertFalse(power_symbol_drives({"value": "PWR_FLAG", "pins": [{"type": "power_out"}]}))


if __name__ == "__main__":
    unittest.main()
