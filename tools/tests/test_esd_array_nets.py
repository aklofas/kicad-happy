"""ESD arrays (multi-pin TVS diode arrays and ESD ICs) report the ground they clamp to, list the
supply rails a diode array's cathodes sit on, and leave out pins that reach nothing. An array whose
only return is protective earth or chassis clamps to it; Earth stays out of ground everywhere else."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from kicad_types import build_analysis_context  # noqa: E402

RAILS = {"GND", "3.3V", "V_BCKP", "+5V", "Earth", "AGND", "DGND"}


def _part(ref, ctype, value, lib_id, pins):
    return {"reference": ref, "type": ctype, "value": value, "lib_id": lib_id,
            "description": "", "keywords": "", "mpn": "", "footprint": "",
            "pins": [{"number": n, "name": nm} for n, nm in pins]}


def _ctx(components, nets, rails=RAILS):
    """nets: name -> (pins [(ref, pin)], labelled, no_connect). ``rails=None`` reads the power
    symbols and the ground evidence on the nets, as a real schematic does."""
    full = {}
    for name, (pins, labelled, nc) in nets.items():
        full[name] = {"name": name, "point_count": 0, "no_connect": nc,
                      "labels": [{"name": name, "type": "global_label"}] if labelled else [],
                      "pins": [dict(component=r, pin_number=p, pin_name="", pin_type="passive")
                               for r, p in pins]}
    return build_analysis_context(components, full, {}, known_power_rails=rails)


def _record(ctx, ref):
    from signal_detectors import detect_protection_devices
    recs = [r for r in detect_protection_devices(ctx) if r["ref"] == ref]
    if not recs:
        return None
    r = recs[0]
    return r["type"], r["protected_nets"], r["protected_net"], r["clamp_net"]


def _pesd_array(nc_pins_alone=True):
    """PESD3V3L4UG: common anode on GND, cathodes on 3.3V and V_BCKP, two cathodes unused."""
    d7 = _part("D7", "diode", "PESD3V3L4UG", "SparkFun-DiscreteSemi:D_TVS_ESD_4_3.3V",
               [("1", "K1"), ("2", "A"), ("3", "K2"), ("4", "K3"), ("5", "K4")])
    u1 = _part("U1", "ic", "SAM-M8Q", "GNSS:SAM-M8Q", [("3", "V_BCKP"), ("17", "VCC"), ("8", "GND")])
    nets = {"GND": ([("D7", "2"), ("U1", "8")], False, False),
            "3.3V": ([("D7", "3"), ("U1", "17")], False, False),
            "V_BCKP": ([("D7", "5"), ("U1", "3")], True, False),
            "__unnamed_17": ([("D7", "1")], False, True),
            "__unnamed_18": ([("D7", "4")], False, True)}
    return _ctx([d7, u1], nets)


def _usblc6(vbus="+5V", gnd="GND", lines=("USB_DP", "USB_DM"), wired=True):
    u = _part("U5", "ic", "USBLC6-2SC6", "Power_Protection:USBLC6-2SC6",
              [("1", "I/O1"), ("2", "GND"), ("3", "I/O2"), ("4", "I/O2"), ("5", "VBUS"), ("6", "I/O1")])
    j = _part("J1", "connector", "USB_C", "Connector:USB_C_Receptacle",
              [("A6", "D+"), ("A7", "D-"), ("A4", "VBUS"), ("A1", "GND")])
    if not wired:
        nets = {f"__unnamed_{i}": ([("U5", p)], False, False) for i, p in enumerate("13456")}
        nets[gnd] = ([("U5", "2")], False, False)
        return _ctx([u], nets)
    dp, dm = lines
    nets = {dp: ([("U5", "1"), ("U5", "6"), ("J1", "A6")], False, False),
            dm: ([("U5", "3"), ("U5", "4"), ("J1", "A7")], False, False),
            vbus: ([("U5", "5"), ("J1", "A4")], False, False),
            gnd: ([("U5", "2"), ("J1", "A1")], False, False)}
    return _ctx([u, j], nets)


class DiodeArray(unittest.TestCase):
    def test_rails_a_diode_array_clamps_are_protected_and_unused_pins_are_not(self):
        self.assertEqual(_record(_pesd_array(), "D7"),
                         ("esd_ic", ["3.3V", "V_BCKP"], "3.3V", "GND"))

    def test_pin_alone_on_a_labelled_net_stays_protected(self):
        d1 = _part("D1", "diode", "PRTR5V0U2X", "Power_Protection:PRTR5V0U2X",
                   [("1", "GND"), ("2", "IO1"), ("3", "IO2"), ("4", "VCC")])
        u2 = _part("U2", "ic", "MCU", "MCU:Generic", [("1", "PA0"), ("2", "VDD"), ("3", "GND")])
        ctx = _ctx([d1, u2], {"GND": ([("D1", "1"), ("U2", "3")], False, False),
                              "SENSE": ([("D1", "2")], True, False),
                              "PA0": ([("D1", "3"), ("U2", "1")], False, False),
                              "+5V": ([("D1", "4"), ("U2", "2")], False, False)})
        self.assertEqual(_record(ctx, "D1"), ("esd_ic", ["+5V", "PA0", "SENSE"], "PA0", "GND"))

    def test_line_shared_with_a_no_connect_pin_of_another_part_stays_protected(self):
        d1 = _part("D1", "diode", "PRTR5V0U2X", "Power_Protection:PRTR5V0U2X",
                   [("1", "GND"), ("2", "IO1"), ("3", "IO2"), ("4", "VCC")])
        u2 = _part("U2", "ic", "MCU", "MCU:Generic", [("1", "PA0"), ("2", "NC"), ("3", "GND")])
        ctx = _ctx([d1, u2], {"GND": ([("D1", "1"), ("U2", "3")], False, False),
                              "PA0": ([("D1", "2"), ("U2", "1")], False, False),
                              "PA1": ([("D1", "3"), ("U2", "2")], False, True),
                              "+5V": ([("D1", "4")], False, False)})
        self.assertEqual(_record(ctx, "D1"), ("esd_ic", ["PA0", "PA1"], "PA0", "GND"))

    def test_array_whose_only_return_is_earth_clamps_to_earth(self):
        d1 = _part("D1", "diode", "PESD1CAN", "Diode:PESD1CAN", [("1", "K"), ("2", "K"), ("3", "O")])
        u2 = _part("U2", "ic", "TJA1051", "Interface_CAN_LIN:TJA1051T-3", [("6", "CANL"), ("7", "CANH")])
        j1 = _part("J1", "connector", "CAN", "Connector:Conn_01x03", [("1", "1"), ("2", "2"), ("3", "3")])
        ctx = _ctx([d1, u2, j1], {"CANL": ([("D1", "1"), ("U2", "6"), ("J1", "1")], False, False),
                                  "CANH": ([("D1", "2"), ("U2", "7"), ("J1", "2")], False, False),
                                  "Earth": ([("D1", "3"), ("J1", "3")], False, False)})
        self.assertEqual(_record(ctx, "D1"), ("esd_ic", ["CANH", "CANL"], "CANH", "Earth"))
        self.assertFalse(ctx.is_ground("Earth"))

    def test_array_without_any_return_has_no_clamp_net(self):
        d1 = _part("D1", "diode", "PESD1CAN", "Diode:PESD1CAN", [("1", "K"), ("2", "K"), ("3", "O")])
        u2 = _part("U2", "ic", "TJA1051", "Interface_CAN_LIN:TJA1051T-3",
                   [("6", "CANL"), ("7", "CANH"), ("3", "VCC")])
        ctx = _ctx([d1, u2], {"CANL": ([("D1", "1"), ("U2", "6")], False, False),
                              "CANH": ([("D1", "2"), ("U2", "7")], False, False),
                              "+5V": ([("D1", "3"), ("U2", "3")], False, False)})
        self.assertEqual(_record(ctx, "D1"), ("esd_ic", ["CANH", "CANL"], "CANH", None))

    def test_ground_beats_earth(self):
        d1 = _part("D1", "diode", "SRV05-4", "Power_Protection:SRV05-4",
                   [("1", "IO1"), ("2", "GND"), ("3", "IO2"), ("4", "IO3"), ("5", "VP"), ("6", "IO4")])
        u2 = _part("U2", "ic", "MCU", "MCU:Generic", [("1", "PA0"), ("2", "PA1"), ("3", "GND")])
        j1 = _part("J1", "connector", "Conn", "Connector:Conn_01x02", [("1", "1"), ("2", "2")])
        ctx = _ctx([d1, u2, j1], {"PA0": ([("D1", "1"), ("U2", "1")], False, False),
                                  "PA1": ([("D1", "3"), ("U2", "2")], False, False),
                                  "GND": ([("D1", "2"), ("U2", "3")], False, False),
                                  "Earth": ([("D1", "4"), ("J1", "2")], False, False),
                                  "+5V": ([("D1", "5"), ("J1", "1")], False, False),
                                  "__unnamed_6": ([("D1", "6")], False, True)})
        self.assertEqual(_record(ctx, "D1"), ("esd_ic", ["+5V", "PA0", "PA1"], "PA0", "GND"))

    def test_earth_that_carries_a_ground_symbol_is_a_ground_like_any_other(self):
        # A board whose ground KiCad names Earth_Protective (a GND symbol sits on it) and a
        # signal that happens to be named like a ground: the array clamps to the board ground.
        d1 = _part("D1", "diode", "ESDA5V3L", "Power_Protection:ESDA5V3L",
                   [("1", "K"), ("2", "K"), ("3", "A")])
        gnd = _part("#PWR01", "power_symbol", "GND", "power:GND", [("1", "~")])
        u2 = _part("U2", "ic", "ULN2002A", "Transistor_Array:ULN2002A",
                   [("1", "I1"), ("2", "I2"), ("8", "GND")])
        nets = {"FHGND": ([("D1", "1"), ("U2", "1")], True, False),
                "IN2": ([("D1", "2"), ("U2", "2")], False, False),
                "Earth_Protective": ([("D1", "3"), ("U2", "8"), ("#PWR01", "1")], False, False)}
        ctx = _ctx([d1, gnd, u2], nets, rails=None)
        self.assertTrue(ctx.is_ground("Earth_Protective"))
        self.assertEqual(_record(ctx, "D1")[3], "Earth_Protective")

    def test_capacitor_to_earth_is_still_not_decoupling(self):
        from signal_detectors import detect_decoupling
        d1 = _part("D1", "diode", "PESD1CAN", "Diode:PESD1CAN", [("1", "K"), ("2", "K"), ("3", "O")])
        c1 = _part("C1", "capacitor", "4.7n", "Device:C", [("1", "~"), ("2", "~")])
        u2 = _part("U2", "ic", "TJA1051", "Interface_CAN_LIN:TJA1051T-3",
                   [("6", "CANL"), ("7", "CANH"), ("3", "VCC")])
        ctx = _ctx([d1, c1, u2], {"CANL": ([("D1", "1"), ("U2", "6")], False, False),
                                  "CANH": ([("D1", "2"), ("U2", "7")], False, False),
                                  "Earth": ([("D1", "3"), ("C1", "2")], False, False),
                                  "+5V": ([("C1", "1"), ("U2", "3")], False, False)})
        self.assertEqual(_record(ctx, "D1")[3], "Earth")
        self.assertFalse(ctx.is_ground("Earth"))
        self.assertEqual([d["rail"] for d in detect_decoupling(ctx)], [])


class EsdIc(unittest.TestCase):
    def test_usblc6_lists_its_io_lines_and_clamps_to_ground(self):
        self.assertEqual(_record(_usblc6(), "U5"),
                         ("esd_ic", ["USB_DM", "USB_DP"], "USB_DM", "GND"))

    def test_an_ic_supply_pin_is_not_a_protected_line(self):
        rec = _record(_usblc6(vbus="+5V"), "U5")
        self.assertNotIn("+5V", rec[1])
        self.assertEqual(rec[3], "GND")

    def test_unused_pins_of_an_ic_are_not_protected(self):
        u = _part("U3", "ic", "ECMF02-2AMX6", "Power_Protection:ECMF02",
                  [("1", "D+in"), ("2", "GND"), ("3", "D-in"), ("4", "NC"), ("5", "D-out"), ("6", "D+out")])
        ctx = _ctx([u], {"DP_C": ([("U3", "1")], True, False), "DM_C": ([("U3", "3")], True, False),
                         "GND": ([("U3", "2")], False, False),
                         "__unnamed_4": ([("U3", "4")], False, True),
                         "DP": ([("U3", "6")], True, False), "DM": ([("U3", "5")], True, False)})
        self.assertEqual(_record(ctx, "U3"), ("esd_ic", ["DM", "DM_C", "DP", "DP_C"], "DM", "GND"))


    def test_clamp_is_chosen_the_same_way_among_several_grounds(self):
        u = _part("U4", "ic", "TPD2E2U06", "Power_Protection:TPD2E2U06",
                  [("1", "IO1"), ("2", "GND"), ("3", "IO2"), ("4", "GND")])
        ctx = _ctx([u], {"IO_A": ([("U4", "1")], True, False), "IO_B": ([("U4", "3")], True, False),
                         "DGND": ([("U4", "2")], False, False), "AGND": ([("U4", "4")], False, False)})
        self.assertEqual(_record(ctx, "U4"), ("esd_ic", ["IO_A", "IO_B"], "IO_A", "AGND"))

class UnwiredArray(unittest.TestCase):
    def test_unwired_array_keeps_its_record_and_clamps_only_to_a_ground(self):
        rec = _record(_usblc6(wired=False), "U5")
        self.assertIsNotNone(rec)
        self.assertEqual(rec[1], ["__unnamed_0", "__unnamed_1", "__unnamed_2", "__unnamed_3",
                                  "__unnamed_4"])
        self.assertEqual(rec[3], "GND")
        rec = _record(_usblc6(wired=False, gnd="__unnamed_9"), "U5")
        self.assertIsNotNone(rec)
        self.assertEqual(len(rec[1]), 6)
        self.assertIsNone(rec[3])


if __name__ == "__main__":
    unittest.main()
