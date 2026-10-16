# tools/tests/test_pcb_facade.py
import json, sys, unittest
from pathlib import Path
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parents[1] / "skills" / "kicad" / "scripts"))


class Facades(unittest.TestCase):
    def test_analyze_pcb_binds_every_round4_name(self):
        import analyze_pcb as ap
        names = json.loads((TESTS / "analyze_pcb_names_round4.json").read_text(encoding="utf-8"))
        missing = [n for n in names if n != "main" and not hasattr(ap, n)]
        self.assertEqual(missing, [])

    def test_analyze_pcb_binds_the_two_imported_names_the_harness_uses(self):
        import analyze_pcb as ap, kicad_core.sexp as sexp, pcb.connectivity as conn
        self.assertIs(ap.parse_file, sexp.parse_file)
        self.assertIs(ap.build_connectivity_graph, conn.build_connectivity_graph)

    def test_pcb_connectivity_facade_binds_every_round4_name(self):
        import pcb_connectivity, pcb.connectivity as conn
        for n in json.loads((TESTS / "pcb_connectivity_names_round4.json").read_text(encoding="utf-8")):
            self.assertIs(getattr(pcb_connectivity, n), getattr(conn, n), n)

    def test_pipeline_names_are_the_same_objects(self):
        import analyze_pcb as ap, pcb.pipeline as pl, pcb.presentation as pr
        for n in ("analyze_pcb", "MAX_TESTED_FORMAT_VERSION", "ANALYZER_SOURCE", "_power_rails_from_schematic"):
            self.assertIs(getattr(ap, n), getattr(pl, n), n)
        for n in ("group_components", "compute_statistics"):
            self.assertIs(getattr(ap, n), getattr(pr, n), n)

    def test_read_board_uses_the_reader_module_attribute(self):
        import inspect, pcb.pipeline as pl
        src = inspect.getsource(pl.read_board)
        self.assertIn("reader.extract_footprints(", src)
        self.assertIn("reader._build_net_mapping(", src)


if __name__ == "__main__":
    unittest.main()
