"""Re-exporting the tracking CSV binds hand-kept columns to the part, keeps manual `--` rows and
distributor columns filled on any row, and never lets a different part inherit Validated or
stock. Expected values are the hand-derived contents of the CSV the user edited."""
import csv, os, stat, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "bom" / "scripts"))

import bom_manager
from kicad_core import fileio

COLS = ["Reference", "Qty", "Value", "Footprint", "MPN", "Manufacturer", "Datasheet", "DNP",
        "Chosen_Distributor", "Validated", "Notes", "DigiKey", "DK_Stock", "Mouser", "MO_Stock"]


def line(refs, mpn, value="1k", dnp=False):
    return {"type": "resistor", "references": refs, "quantity": len(refs), "value": value,
            "footprint": "Resistor_SMD:R_0402_1005Metric", "mpn": mpn, "manufacturer": "",
            "datasheet": "~", "dnp": dnp, "bom_comments": []}


def report(*lines):
    return {"bom": list(lines), "convention": {"field_mapping": {}}, "stats": {}}


def write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in COLS})


def read(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


class TrackingCsvMergeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.csv = Path(self._tmp.name) / "bom.csv"

    def tearDown(self):
        self._tmp.cleanup()

    def test_dnp_twin_keeps_its_own_notes_and_validated(self):
        write(self.csv, [
            {"Reference": "R18", "Qty": "1", "Value": "1k", "Footprint": "0402", "MPN": "RC0402",
             "DNP": "yes", "Notes": "spare pad", "Validated": ""},
            {"Reference": "R19", "Qty": "1", "Value": "1k", "Footprint": "0402", "MPN": "RC0402",
             "Notes": "pull-up", "Validated": "yes"},
        ])
        bom_manager.export_csv(report(line(["R18"], "RC0402", dnp=True), line(["R19"], "RC0402")),
                               self.csv)
        rows = {r["Reference"]: r for r in read(self.csv)}
        self.assertEqual((rows["R18"]["Notes"], rows["R18"]["Validated"]), ("spare pad", ""))
        self.assertEqual((rows["R19"]["Notes"], rows["R19"]["Validated"]), ("pull-up", "yes"))

    def test_manual_rows_survive_after_the_schematic_rows(self):
        write(self.csv, [
            {"Reference": "R1", "Qty": "1", "Value": "1k", "MPN": "A"},
            {"Reference": "--", "Qty": "1", "Value": "cable", "MPN": "CABLE-1", "Notes": "buy",
             "DigiKey": "CAB-ND"},
            {"Reference": "--", "Qty": "2", "Value": "screws", "MPN": "", "Notes": "M3"},
        ])
        bom_manager.export_csv(report(line(["R1"], "A"), line(["R2"], "B")), self.csv)
        rows = read(self.csv)
        self.assertEqual([r["Reference"] for r in rows], ["R1", "R2", "--", "--"])
        self.assertEqual((rows[2]["MPN"], rows[2]["Notes"], rows[2]["DigiKey"]),
                         ("CABLE-1", "buy", "CAB-ND"))
        self.assertEqual((rows[3]["Value"], rows[3]["Qty"], rows[3]["Notes"]), ("screws", "2", "M3"))

    def test_changed_part_keeps_only_notes_and_distributor_choice(self):
        write(self.csv, [{"Reference": "R1", "Qty": "1", "Value": "1k", "Footprint": "0402",
                          "MPN": "OLD-X", "Chosen_Distributor": "Mouser", "Validated": "yes",
                          "Notes": "tight", "DigiKey": "OLD-ND", "DK_Stock": "500"}])
        bom_manager.export_csv(report(line(["R1"], "X")), self.csv)
        row = read(self.csv)[0]
        self.assertEqual(row["MPN"], "X")
        self.assertEqual(row["Validated"], "")
        self.assertEqual(row["DigiKey"], "")
        self.assertEqual(row["DK_Stock"], "")
        self.assertEqual((row["Notes"], row["Chosen_Distributor"]), ("tight", "Mouser"))

    def test_distributor_columns_filled_on_a_later_row_are_kept(self):
        write(self.csv, [
            {"Reference": "R1", "Qty": "1", "MPN": "A"},
            {"Reference": "R2", "Qty": "1", "MPN": "B", "Mouser": "595-B", "MO_Stock": "7"},
        ])
        bom_manager.export_csv(report(line(["R1"], "A"), line(["R2"], "B")), self.csv)
        rows = read(self.csv)
        self.assertEqual((rows[1]["Mouser"], rows[1]["MO_Stock"]), ("595-B", "7"))

    def test_mpnless_line_matches_by_value_and_footprint_not_by_another_part(self):
        write(self.csv, [{"Reference": "R1", "Qty": "1", "Value": "10k", "Footprint": "0402",
                          "Validated": "yes", "Notes": "n"}])
        bom_manager.export_csv(report(line(["R1"], "", value="1k")), self.csv)
        row = read(self.csv)[0]
        self.assertEqual((row["Validated"], row["Notes"]), ("", "n"))

    def test_csv_keeps_crlf(self):
        write(self.csv, [{"Reference": "R1", "Qty": "1", "MPN": "A", "Notes": "keep"}])
        bom_manager.export_csv(report(line(["R1"], "A")), self.csv)
        self.assertIn(b"\r\n", self.csv.read_bytes())

    def test_failed_write_keeps_the_old_file_and_leaves_no_temp(self):
        write(self.csv, [{"Reference": "R1", "Qty": "1", "MPN": "A", "Notes": "keep"}])
        before = self.csv.read_bytes()
        real = os.replace

        def boom(src, dst):
            raise OSError("disk full")
        os.replace = boom
        try:
            with self.assertRaises(OSError):
                bom_manager.export_csv(report(line(["R1"], "A")), self.csv)
        finally:
            os.replace = real
        self.assertEqual(self.csv.read_bytes(), before)
        self.assertEqual(os.listdir(self.csv.parent), ["bom.csv"])

    def test_new_csv_takes_the_umask_mode_and_an_existing_one_keeps_its_mode(self):
        old = os.umask(0o022)
        try:
            bom_manager.export_csv(report(line(["R1"], "A")), self.csv)
        finally:
            os.umask(old)
        self.assertEqual(stat.S_IMODE(self.csv.stat().st_mode), 0o644)
        os.chmod(self.csv, 0o640)
        bom_manager.export_csv(report(line(["R1"], "A")), self.csv)
        self.assertEqual(stat.S_IMODE(self.csv.stat().st_mode), 0o640)

    def _temp_open_modes(self):
        real, modes = os.open, []

        def spy(path, flags, mode=0o777, *a, **kw):
            if str(path).endswith(".tmp"):
                modes.append(mode)
            return real(path, flags, mode, *a, **kw)
        return spy, modes

    def test_temp_is_private_for_an_existing_file_and_umask_governed_for_a_new_one(self):
        for existing, expected in ((True, [0o600]), (False, [0o666])):
            with self.subTest(existing=existing):
                if existing:
                    write(self.csv, [{"Reference": "R1", "Qty": "1", "MPN": "A"}])
                elif self.csv.exists():
                    self.csv.unlink()
                spy, modes = self._temp_open_modes()
                real = fileio.os.open
                fileio.os.open = spy
                try:
                    bom_manager.export_csv(report(line(["R1"], "A")), self.csv)
                finally:
                    fileio.os.open = real
                self.assertEqual(modes, expected)

    def test_empty_known_distributor_column_is_not_moved_to_the_end(self):
        write(self.csv, [{"Reference": "R1", "Qty": "1", "MPN": "A"}])
        bom_manager.export_csv(report(line(["R1"], "A")), self.csv)
        with open(self.csv, newline="", encoding="utf-8") as f:
            head = next(csv.reader(f))
        self.assertEqual(head, bom_manager._build_csv_columns([]))

    def test_user_added_columns_and_awkward_manual_rows_round_trip(self):
        with open(self.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLS + ["Link"])
            w.writeheader()
            w.writerow({"Reference": "R1", "Qty": "1", "MPN": "A", "Link": "http://a"})
            w.writerow({"Reference": "--", "Qty": "1", "Value": 'cable, 1m "x"',
                        "Notes": "multi\nline", "Link": "http://x"})
        bom_manager.export_csv(report(line(["R1"], "A")), self.csv)
        rows = read(self.csv)
        self.assertEqual(rows[0]["Link"], "http://a")
        self.assertEqual((rows[1]["Value"], rows[1]["Notes"], rows[1]["Link"]),
                         ('cable, 1m "x"', "multi\nline", "http://x"))

    def test_dnp_twin_match_ignores_dnp_spelling(self):
        write(self.csv, [
            {"Reference": "R1", "Qty": "1", "Value": "1k", "Footprint": "0402", "MPN": "M",
             "Notes": "fitted"},
            {"Reference": "R1", "Qty": "1", "Value": "1k", "Footprint": "0402", "MPN": "M",
             "DNP": "DNP", "Notes": "unfitted"},
        ])
        bom_manager.export_csv(report(line(["R1"], "M", dnp=True)), self.csv)
        self.assertEqual(read(self.csv)[0]["Notes"], "unfitted")


if __name__ == "__main__":
    unittest.main()
