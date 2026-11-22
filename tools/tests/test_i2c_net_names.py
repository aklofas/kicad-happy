# tools/tests/test_i2c_net_names.py
"""I2C bus observations read SDA / SCL as a word of the net name, with a bus number or a
prefix (SDA2, SCL_2, OLED_SDA). A display's 3-wire SPI lines named like I2C (LCD_SDA beside
LCD_CS) and a numbered address bus (SDA12) are not I2C."""
import sys, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))
from finding_schema import make_provenance  # noqa: E402
from kicad_types import build_analysis_context  # noqa: E402
from schematic.net_analysis import _detect_i2c_buses  # noqa: E402
from signal_detectors import detect_design_observations  # noqa: E402


def _comp(ref, ctype, value, lib_id, pins=()):
    return {"reference": ref, "type": ctype, "value": value, "lib_id": lib_id,
            "pins": [{"number": n, "name": nm, "type": t} for n, nm, t in pins]}


def _res(ref, value="4.7k"):
    return _comp(ref, "resistor", value, "Device:R", [("1", "~", "passive"), ("2", "~", "passive")])


MCU = _comp("U1", "ic", "STM32F103C8Tx", "MCU_ST_STM32F1:STM32F103C8Tx",
            [(str(i), f"PB{i}", "bidirectional") for i in range(1, 9)])
SENSOR = _comp("U2", "ic", "BME280", "Sensor:BME280",
               [("1", "SDI", "bidirectional"), ("2", "SCK", "input"), ("3", "CSB", "input"),
                ("4", "SDO", "output")])
DISPLAY = _comp("U3", "ic", "GC9A01", "Display:GC9A01",
                [("1", "SDA", "bidirectional"), ("2", "SCL", "input"), ("3", "CS", "input"),
                 ("4", "DC", "input")])


def _ctx(nets, components=(MCU, SENSOR), pullups=(), value="4.7k", rail="+3V3"):
    """``nets`` maps a net name to (ref, pin, pin name) rows; each net in ``pullups``
    gets a resistor of ``value`` to ``rail``."""
    comps = list(components)
    rows = {n: [(r, p, pn) for r, p, pn in pins] for n, pins in nets.items()}
    rows.setdefault("+3V3", [])
    rows.setdefault(rail, [])
    for i, net in enumerate(pullups, start=1):
        ref = f"R{i}"
        comps.append(_res(ref, value))
        rows[net].append((ref, "1", "~"))
        rows[rail].append((ref, "2", "~"))
    full = {n: {"name": n, "pins": [dict(component=r, pin_number=p, pin_name=pn, pin_type="bidirectional")
                                    for r, p, pn in pins],
                "point_count": 0, "no_connect": False, "labels": []}
            for n, pins in rows.items()}
    return build_analysis_context(comps, full, {}, known_power_rails={"+3V3", "GND"})


def _i2c_obs(ctx):
    obs = detect_design_observations(ctx, {"decoupling_analysis": [], "power_regulators": []})
    return {o["net"]: o for o in obs if o["category"] == "i2c_bus"}


def _i2c_bus_entries(ctx):
    return {e["net"]: e for e in _detect_i2c_buses(ctx)}


def _bus(sda, scl, sda_pin="SDI", scl_pin="SCK"):
    return {sda: [("U1", "7", "PB7"), ("U2", "1", sda_pin)],
            scl: [("U1", "6", "PB6"), ("U2", "2", scl_pin)]}


class I2cWordInNetName(unittest.TestCase):
    def test_numbered_and_prefixed_names_are_i2c_lines(self):
        for sda, scl in (("SDA0", "SCL2"), ("SDA_2", "SCL_2"), ("/X/SDA2", "/X/SCL2"),
                         ("OLED_SDA", "OLED_SCL"), ("SDA_3V3", "SCL_3V3")):
            with self.subTest(sda=sda):
                obs = _i2c_obs(_ctx(_bus(sda, scl), pullups=(sda, scl)))
                self.assertEqual(sorted(obs), sorted((sda, scl)))
                self.assertEqual(obs[sda]["line"], "SDA")
                self.assertEqual(obs[scl]["line"], "SCL")
                self.assertTrue(obs[sda]["has_pullup"])

    def test_prefixed_line_without_a_pull_up_is_still_listed(self):
        obs = _i2c_obs(_ctx(_bus("OLED_SDA", "OLED_SCL")))
        self.assertEqual(sorted(obs), ["OLED_SCL", "OLED_SDA"])
        self.assertFalse(obs["OLED_SDA"]["has_pullup"])

    def test_other_signals_that_contain_the_letters_are_not_i2c(self):
        for name in ("SDATA", "ESDA", "SCLK", "I2S_SDA", "SAI2_SDA"):
            with self.subTest(name=name):
                obs = _i2c_obs(_ctx({name: [("U1", "7", "PB7"), ("U2", "1", "SDI")]}))
                self.assertEqual(obs, {})


def _display_nets(prefix, sep="_"):
    return {f"{prefix}{sep}SDA": [("U1", "1", "PB1"), ("U3", "1", "SDA")],
            f"{prefix}{sep}SCL": [("U1", "2", "PB2"), ("U3", "2", "SCL")],
            f"{prefix}{sep}CS": [("U1", "3", "PB3"), ("U3", "3", "CS")],
            f"{prefix}{sep}DC": [("U1", "4", "PB4"), ("U3", "4", "DC")]}


class DisplaySpiLinesNamedLikeI2c(unittest.TestCase):
    def test_display_lines_beside_a_chip_select_are_not_i2c(self):
        obs = _i2c_obs(_ctx(_display_nets("LCD"), components=(MCU, DISPLAY)))
        self.assertEqual(obs, {})

    def test_kicad5_root_labels_with_a_slash_are_guarded_like_an_underscore(self):
        for prefix in ("LCD", "/54E8D6A6/LCD"):
            with self.subTest(prefix=prefix):
                obs = _i2c_obs(_ctx(_display_nets(prefix, sep="/"), components=(MCU, DISPLAY)))
                self.assertEqual(obs, {})

    def test_display_family_across_sheet_paths_is_guarded(self):
        nets = {"/LCD_SDA": [("U1", "1", "PB1"), ("U3", "1", "SDA")],
                "/LCD_SCL": [("U1", "2", "PB2"), ("U3", "2", "SCL")],
                "/display/LCD_CS": [("U1", "3", "PB3"), ("U3", "3", "CS")]}
        self.assertEqual(_i2c_obs(_ctx(nets, components=(MCU, DISPLAY))), {})
        nets = {"/55E94587/LCD_SDA": [("U1", "1", "PB1"), ("U3", "1", "SDA")],
                "/55E94587/LCD_SCL": [("U1", "2", "PB2"), ("U3", "2", "SCL")],
                "/55E94588/LCD_DC": [("U1", "4", "PB4"), ("U3", "4", "DC")]}
        self.assertEqual(_i2c_obs(_ctx(nets, components=(MCU, DISPLAY))), {})

    def test_display_lines_with_a_pull_up_are_i2c(self):
        obs = _i2c_obs(_ctx(_display_nets("LCD"), components=(MCU, DISPLAY),
                            pullups=("LCD_SDA", "LCD_SCL")))
        self.assertEqual(sorted(obs), ["LCD_SCL", "LCD_SDA"])

    def test_sensor_with_a_strapped_chip_select_keeps_its_i2c_lines(self):
        nets = {"IMU_SDA": [("U1", "7", "PB7"), ("U2", "1", "SDA/SDI")],
                "IMU_CS": [("U1", "5", "PB5"), ("U2", "3", "CSB")]}
        self.assertEqual(sorted(_i2c_obs(_ctx(nets))), ["IMU_SDA"])

    def test_sheet_name_does_not_make_a_sensor_family_a_display(self):
        for sheet in ("/Display/", "/Sensors/"):
            with self.subTest(sheet=sheet):
                nets = {f"{sheet}IMU_SDA": [("U1", "7", "PB7"), ("U2", "1", "SDA/SDI")],
                        f"{sheet}IMU_CS": [("U1", "5", "PB5"), ("U2", "3", "CSB")]}
                ctx = _ctx(nets)
                self.assertEqual(sorted(_i2c_obs(ctx)), [f"{sheet}IMU_SDA"])
                self.assertEqual(sorted(_i2c_bus_entries(ctx)), [f"{sheet}IMU_SDA"])

    def test_numbered_bus_beside_a_chip_select_is_i2c(self):
        nets = {"MCU_SCL2": [("U1", "6", "PB6"), ("U2", "2", "SCK")],
                "MCU_SDA2": [("U1", "7", "PB7"), ("U2", "1", "SDI")],
                "MCU_CS": [("U1", "5", "PB5"), ("U2", "3", "CSB")]}
        self.assertEqual(sorted(_i2c_obs(_ctx(nets))), ["MCU_SCL2", "MCU_SDA2"])

    def test_numbered_line_with_no_partner_and_no_i2c_pin_is_an_address_bus(self):
        z80 = _comp("U4", "ic", "Z80", "CPU:Z80CPU", [("1", "A12", "output")])
        nets = {"SDA12": [("U1", "1", "PB1"), ("U4", "1", "A12")]}
        self.assertEqual(_i2c_obs(_ctx(nets, components=(MCU, z80))), {})


def _expected_obs(net, line, devices, pullup=None):
    return {"category": "i2c_bus", "net": net, "line": line, "devices": devices,
            "has_pullup": pullup is not None, "pullup_resistor": pullup,
            "pullup_rail": "+3V3" if pullup else None,
            "detector": "detect_design_observations", "rule_id": "DO-DET", "severity": "info",
            "confidence": "heuristic", "evidence_source": "topology",
            "summary": f"I2C {line} bus on {net}",
            "description": f"I2C {line} bus detected with {len(devices)} device(s)",
            "components": devices, "nets": [], "pins": [], "recommendation": "",
            "report_context": {"section": "Design Observations", "impact": "", "standard_ref": ""},
            "provenance": make_provenance("obs_topology", "heuristic", devices)}


class BareNamesUnchanged(unittest.TestCase):
    def test_bare_and_i2c_prefixed_names_keep_their_records(self):
        nets = {"SDA": [("U1", "7", "PB7"), ("U2", "1", "SDI")],
                "SCL": [("U1", "6", "PB6"), ("U2", "2", "SCK")],
                "I2C1_SDA": [("U1", "5", "PB5")]}
        obs = _i2c_obs(_ctx(nets, pullups=("SDA",)))
        self.assertEqual(obs, {"SDA": _expected_obs("SDA", "SDA", ["U1", "U2"], "R1"),
                               "SCL": _expected_obs("SCL", "SCL", ["U1", "U2"]),
                               "I2C1_SDA": _expected_obs("I2C1_SDA", "SDA", ["U1"])})


class BusAnalysisLeavesOutTheSameNets(unittest.TestCase):
    def test_display_family_has_no_observation_and_no_bus_entry(self):
        ctx = _ctx(_display_nets("LCD"), components=(MCU, DISPLAY))
        self.assertEqual(_i2c_obs(ctx), {})
        self.assertEqual(_i2c_bus_entries(ctx), {})

    def test_display_family_across_sheet_paths_has_no_bus_entry(self):
        nets = {"/LCD_SDA": [("U1", "1", "PB1"), ("U3", "1", "SDA")],
                "/LCD_SCL": [("U1", "2", "PB2"), ("U3", "2", "SCL")],
                "/display/LCD_CS": [("U1", "3", "PB3"), ("U3", "3", "CS")]}
        self.assertEqual(_i2c_bus_entries(_ctx(nets, components=(MCU, DISPLAY))), {})
        nets = {"/55E94587/LCD_SDA": [("U1", "1", "PB1"), ("U3", "1", "SDA")],
                "/55E94587/LCD_SCL": [("U1", "2", "PB2"), ("U3", "2", "SCL")],
                "/55E94588/LCD_DC": [("U1", "4", "PB4"), ("U3", "4", "DC")]}
        self.assertEqual(_i2c_bus_entries(_ctx(nets, components=(MCU, DISPLAY))), {})

    def test_address_line_has_no_bus_entry(self):
        z80 = _comp("U4", "ic", "Z80", "CPU:Z80CPU", [("1", "A12", "output")])
        nets = {"SDA12": [("U1", "1", "PB1"), ("U4", "1", "A12")]}
        self.assertEqual(_i2c_bus_entries(_ctx(nets, components=(MCU, z80))), {})

    def test_display_lines_with_a_pull_up_keep_their_bus_entries(self):
        ctx = _ctx(_display_nets("LCD"), components=(MCU, DISPLAY), pullups=("LCD_SDA", "LCD_SCL"))
        self.assertEqual(sorted(_i2c_bus_entries(ctx)), ["LCD_SCL", "LCD_SDA"])

    def test_observation_and_bus_entry_agree_on_a_pull_up_with_no_value(self):
        ctx = _ctx(_display_nets("LCD"), components=(MCU, DISPLAY),
                   pullups=("LCD_SDA", "LCD_SCL"), value="R")
        self.assertEqual(sorted(_i2c_obs(ctx)), ["LCD_SCL", "LCD_SDA"])
        self.assertEqual(sorted(_i2c_bus_entries(ctx)), ["LCD_SCL", "LCD_SDA"])

    def test_a_resistor_to_ground_is_not_a_pull_up_for_either(self):
        ctx = _ctx(_display_nets("LCD"), components=(MCU, DISPLAY),
                   pullups=("LCD_SDA", "LCD_SCL"), rail="GND")
        self.assertEqual(_i2c_obs(ctx), {})
        self.assertEqual(_i2c_bus_entries(ctx), {})

    def test_bare_and_i2c_prefixed_names_keep_their_bus_entries(self):
        nets = {"SDA": [("U1", "7", "PB7"), ("U2", "1", "SDI")],
                "SCL": [("U1", "6", "PB6"), ("U2", "2", "SCK")],
                "I2C1_SDA": [("U1", "5", "PB5")]}
        entries = _i2c_bus_entries(_ctx(nets, pullups=("SDA",)))

        def entry(net, line, refs, pull_ups):
            devices = [{"ref": r, "value": v, "lib_id": lib}
                       for r, v, lib in ((c["reference"], c["value"], c["lib_id"])
                                         for c in (MCU, SENSOR)) if r in refs]
            ohms = pull_ups[0]["ohms"] if pull_ups else None
            return {"net": net, "line": line, "devices": devices, "load_count": len(devices),
                    "estimated_bus_capacitance_pF": 5 * len(devices), "pull_ups": pull_ups,
                    "has_pull_up": bool(pull_ups), "speed_mode": "fast" if pull_ups else None,
                    "voltage_level_V": 3.3 if pull_ups else None, "pull_up_ohms": ohms,
                    "controller": None}
        r1 = [{"ref": "R1", "value": "4.7k", "ohms": 4700.0, "to_rail": "+3V3"}]
        self.assertEqual(entries, {"SDA": entry("SDA", "SDA", ("U1", "U2"), r1),
                                   "SCL": entry("SCL", "SCL", ("U1", "U2"), []),
                                   "I2C1_SDA": entry("I2C1_SDA", "SDA", ("U1",), [])})


if __name__ == "__main__":
    unittest.main()
