"""cross_verify compares parts the way KiCad's schematic parity check and the analyzers see them.

KiCad 10 pcbnew/drc/drc_test_provider_schematic_parity.cpp skips board-only footprints, and
the board netlist (eeschema/netlist_exporters/netlist_exporter_xml.cpp) omits symbols
excluded from the board, so neither is an orphan or missing. The parity check compares the
symbol's DNP with the footprint's DNP attribute, which boards write from file version
20230410 (KiCad 8). Decoupling capacitors are read per rail as DA-001 reads them: a rail's
fitted ICs are those with a pin on it. Only the PCB analysis's pad distance can say a cap
sits too far from its IC; a footprint-centre distance may be to a load the cap does not serve.
"""
import sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "kicad" / "scripts"))

import cross_verify as cv  # noqa: E402


def _c(ref, path=None, value="10k", ctype="resistor", dnp=False, on_board=True, pin_nets=None):
    c = {"reference": ref, "value": value, "type": ctype, "instance_path": path or f"/{ref}",
         "pin_nets": pin_nets or {}, "on_board": on_board}
    if dnp:
        c["dnp"] = True
    return c


def _fp(ref, path=None, value="10k", dnp=False, board_only=False, pad_count=2, x=0, y=0):
    fp = {"reference": ref, "value": value, "pad_count": pad_count, "x": x, "y": y}
    if path is not None:
        fp["sch_path"] = path
    if dnp:
        fp["dnp"] = True
    if board_only:
        fp["board_only"] = True
    return fp


def _pcb(fps, file_version="20240108", **extra):
    return {"file_version": file_version, "footprints": fps, **extra}


def _match(sch_comps, fps, file_version="20240108"):
    return cv.check_component_matching({"components": sch_comps}, _pcb(fps, file_version))


class ComponentParityTest(unittest.TestCase):
    def test_board_only_footprint_is_not_an_orphan(self):
        res = _match([_c("R1", "/U1")],
                     [_fp("R1", "/U1"), _fp("G***", board_only=True, pad_count=0)])
        self.assertEqual(res["orphans"], [])

    def test_stale_footprint_still_an_orphan(self):
        res = _match([_c("R1", "/U1")],
                     [_fp("R1", "/U1"), _fp("G***", board_only=True, pad_count=0), _fp("R9")])
        self.assertEqual([(o["ref"], o["status"]) for o in res["orphans"]], [("R9", "fail")])

    def test_graphic_footprint_without_board_only_still_an_orphan(self):
        res = _match([_c("R1", "/U1")], [_fp("R1", "/U1"), _fp("LOGO1", pad_count=0)])
        self.assertEqual([o["ref"] for o in res["orphans"]], ["LOGO1"])

    def test_reference_shared_with_a_placed_footprint_still_an_orphan(self):
        res = _match([_c("R1", "/U1")],
                     [_fp("R1", "/U1"), _fp("G1", board_only=True), _fp("G1")])
        self.assertEqual([o["ref"] for o in res["orphans"]], ["G1"])

    def test_excluded_from_board_symbol_not_missing(self):
        res = _match([_c("R1", "/U1"), _c("G1", on_board=False)], [_fp("R1", "/U1")])
        self.assertEqual(res["missing"], [])

    def test_fitted_symbol_without_footprint_still_missing(self):
        res = _match([_c("R1", "/U1"), _c("R2", on_board=True)], [_fp("R1", "/U1")])
        self.assertEqual([m["ref"] for m in res["missing"]], ["R2"])

    def test_unit_on_the_board_keeps_the_part_missing(self):
        res = _match([_c("U2", "/a", on_board=False), _c("U2", "/b", on_board=True)], [])
        self.assertEqual([m["ref"] for m in res["missing"]], ["U2"])

    def test_dnp_symbol_without_footprint_still_not_missing(self):
        res = _match([_c("R1", "/U1"), _c("R3", dnp=True)], [_fp("R1", "/U1")])
        self.assertEqual(res["missing"], [])

    def test_dnp_in_sync_is_not_a_conflict(self):
        res = _match([_c("U1", "/U1", dnp=True)], [_fp("U1", "/U1", dnp=True)])
        self.assertEqual(res["dnp_conflicts"], [])

    def test_dnp_schematic_only_is_a_conflict(self):
        res = _match([_c("U1", "/U1", dnp=True)], [_fp("U1", "/U1")])
        self.assertEqual([(d["ref"], d["status"]) for d in res["dnp_conflicts"]], [("U1", "warning")])
        self.assertIn("not on the PCB footprint", res["dnp_conflicts"][0]["message"])

    def test_dnp_pcb_only_is_a_conflict(self):
        res = _match([_c("U1", "/U1")], [_fp("U1", "/U1", dnp=True)])
        self.assertEqual([(d["ref"], d["status"]) for d in res["dnp_conflicts"]], [("U1", "warning")])
        self.assertIn("DNP on the PCB", res["dnp_conflicts"][0]["message"])

    def test_board_without_dnp_attribute_not_compared(self):
        for fv in ("20221018", "unknown", None):
            res = _match([_c("U1", "/U1", dnp=True)], [_fp("U1", "/U1")], file_version=fv)
            self.assertEqual(res["dnp_conflicts"], [], fv)

    def test_first_board_version_with_the_attribute_is_compared(self):
        res = _match([_c("U1", "/U1", dnp=True)], [_fp("U1", "/U1")], file_version="20230410")
        self.assertEqual([d["ref"] for d in res["dnp_conflicts"]], ["U1"])


def _decoupling_sch(u1_dnp=False, caps=(("C1", "100n", 1e-7), ("C2", "100n", 1e-7), ("C3", "100n", 1e-7)),
                    unfit=("C2",)):
    comps = [_c("U1", "/U1", value="MCU", ctype="ic", dnp=u1_dnp, pin_nets={"1": "+3V3", "2": "GND"})]
    for ref, value, _ in caps:
        comps.append(_c(ref, value=value, ctype="capacitor", dnp=ref in unfit,
                        pin_nets={"1": "+3V3", "2": "GND"}))
    finding = {"detector": "detect_decoupling", "rail": "+3V3",
               "capacitors": [{"ref": r, "value": v, "farads": f} for r, v, f in caps]}
    return {"components": comps, "findings": [finding]}


def _rows(res):
    return [(r["ic_ref"], r["cap_ref"], r["status"]) for r in res]


class DecouplingPlacementTest(unittest.TestCase):
    FPS = [_fp("U1", "/U1", x=0, y=0), _fp("C1", x=2, y=0), _fp("C2", x=1, y=0), _fp("C3", x=12, y=0)]

    def test_decoupling_measures_nearest_rail_ic(self):
        res = cv.check_decoupling_placement(_decoupling_sch(), _pcb(self.FPS))
        self.assertEqual([r["cap_ref"] for r in res], ["C1", "C3"])
        self.assertEqual([r["ic_ref"] for r in res], ["U1", "U1"])
        self.assertEqual((res[0]["status"], res[1]["distance_mm"]), ("pass", 12.0))

    def test_far_small_cap_by_centre_distance_is_info(self):
        res = cv.check_decoupling_placement(_decoupling_sch(), _pcb(self.FPS))
        self.assertEqual(_rows(res), [("U1", "C1", "pass"), ("U1", "C3", "info")])
        self.assertIn("footprint centres", res[1]["message"])
        self.assertNotIn("should be within", res[1]["message"])

    def test_far_small_cap_by_pad_distance_warns(self):
        pcb = _pcb(self.FPS, decoupling_placement=[
            {"ic": "U1", "nearby_caps": [{"cap": "C3", "distance_mm": 7.0}]}])
        res = cv.check_decoupling_placement(_decoupling_sch(), pcb)
        self.assertEqual(_rows(res), [("U1", "C1", "pass"), ("U1", "C3", "warning")])
        self.assertEqual(res[1]["distance_mm"], 7.0)
        self.assertIn("should be within 5mm", res[1]["message"])

    def test_far_bulk_cap_by_pad_distance_is_info(self):
        sch = _decoupling_sch(caps=(("C3", "10u", 1e-5),), unfit=())
        pcb = _pcb(self.FPS, decoupling_placement=[
            {"ic": "U1", "nearby_caps": [{"cap": "C3", "distance_mm": 7.0}]}])
        res = cv.check_decoupling_placement(sch, pcb)
        self.assertEqual(_rows(res), [("U1", "C3", "info")])
        self.assertIn("bulk", res[0]["message"])

    def test_regulator_far_from_rail_caps_reports_info(self):
        # A 3.3 V rail whose only fitted IC is its regulator; the small caps serve loads
        # elsewhere on the rail, so their centre distance to the regulator is not a fault.
        caps = (("C3", "1.0uF", 1e-6), ("C6", "0.1uF", 1e-7), ("C7", "0.1uF", 1e-7),
                ("C10", "0.1uF", 1e-7), ("C13", "0.1uF", 1e-7))
        sch = {"components": [_c("U2", "/U2", value="AP7361C-3.3V", ctype="ic",
                                 pin_nets={"1": "GND", "2": "3.3V", "3": "5V"})]
               + [_c(r, value=v, ctype="capacitor", pin_nets={"1": "3.3V", "2": "GND"}) for r, v, _ in caps],
               "findings": [{"detector": "detect_decoupling", "rail": "3.3V",
                             "capacitors": [{"ref": r, "value": v, "farads": f} for r, v, f in caps]}]}
        fps = [_fp("U2", "/U2", x=141.57, y=92.46), _fp("C3", x=140.0, y=93.3),
               _fp("C6", x=166.624, y=85.09), _fp("C7", x=168.275, y=107.696),
               _fp("C10", x=153.67, y=117.367), _fp("C13", x=153.67, y=85.598)]
        pcb = _pcb(fps, decoupling_placement=[
            {"ic": "U2", "nearby_caps": [{"cap": "C3", "distance_mm": 1.78}]}])
        res = cv.check_decoupling_placement(sch, pcb)
        self.assertEqual([(r["cap_ref"], r["status"]) for r in res],
                         [("C3", "pass"), ("C6", "info"), ("C7", "info"), ("C10", "info"), ("C13", "info")])

    def test_cap_beside_an_ic_without_pad_distance_does_not_warn(self):
        # FLASH1 is fitted on the rail but not a U/IC ref, so the PCB analysis gives it no
        # pad distance; the cap sits beside it, so U1's 7 mm pad distance is not its fault.
        sch = _decoupling_sch()
        sch["components"].append(_c("FLASH1", "/F1", value="W25Q16", ctype="ic", pin_nets={"8": "+3V3"}))
        fps = self.FPS + [_fp("FLASH1", "/F1", x=14, y=0)]
        pcb = _pcb(fps, decoupling_placement=[
            {"ic": "U1", "nearby_caps": [{"cap": "C3", "distance_mm": 7.0}]}])
        res = cv.check_decoupling_placement(sch, pcb)
        c3 = [r for r in res if r["cap_ref"] == "C3"][0]
        self.assertEqual((c3["ic_ref"], c3["status"], c3["distance_mm"]), ("FLASH1", "pass", 2.0))

    def test_rail_without_fitted_ic_gives_no_rows(self):
        res = cv.check_decoupling_placement(_decoupling_sch(u1_dnp=True), _pcb(self.FPS))
        self.assertEqual(res, [])

    def test_ic_excluded_from_board_gives_no_rows(self):
        sch = _decoupling_sch()
        sch["components"][0]["on_board"] = False
        self.assertEqual(cv.check_decoupling_placement(sch, _pcb(self.FPS)), [])

    def test_bulk_capacitor_far_from_ic_is_info(self):
        sch = _decoupling_sch(caps=(("C1", "100n", 1e-7), ("C3", "1u", 1e-6)), unfit=())
        res = cv.check_decoupling_placement(sch, _pcb(self.FPS))
        self.assertEqual(_rows(res), [("U1", "C1", "pass"), ("U1", "C3", "info")])
        self.assertEqual(res[1]["distance_mm"], 12.0)
        self.assertIn("bulk", res[1]["message"])

    def test_bulk_capacitor_near_ic_passes(self):
        sch = _decoupling_sch(caps=(("C1", "10u", 1e-5),), unfit=())
        res = cv.check_decoupling_placement(sch, _pcb(self.FPS))
        self.assertEqual(_rows(res), [("U1", "C1", "pass")])

    def test_capacitor_not_on_the_pcb_is_info(self):
        sch = _decoupling_sch(caps=(("C1", "100n", 1e-7), ("C9", "100n", 1e-7)), unfit=())
        res = cv.check_decoupling_placement(sch, _pcb(self.FPS))
        self.assertEqual(_rows(res), [("U1", "C1", "pass"), ("U1", "C9", "info")])
        self.assertIn("not found in PCB placement", res[1]["message"])

    def test_report_carries_the_decoupling_rows(self):
        res = cv.cross_verify(_decoupling_sch(), _pcb(self.FPS))
        self.assertEqual(_rows(res["decoupling_placement"]), [("U1", "C1", "pass"), ("U1", "C3", "info")])


if __name__ == "__main__":
    unittest.main()
