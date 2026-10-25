"""PCB facts → checks phases: no analysis mutates the board, checks do not perturb facts, and
run_analyses is exactly run_facts + run_checks (the precondition for hoisting the late checks)."""
import dataclasses, json, os, sys, tempfile, unittest
from pathlib import Path
from tools.tests._fixtures import fixture_path, have
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "skills" / "kicad" / "scripts"))

from tools.check_refactor import KICAD10_BOARD_A, KICAD10_BOARD_B

FX = fixture_path()
KW = dict(return_path_radius_mm=2.0, gp001_debug=False, resolved_power_rails=None)


def _default(o):
    from pcb.geometry import ZoneFills
    if isinstance(o, ZoneFills):
        # the fill data; `_grids` is a lazily built memo of `_fills` (KH-420), not state
        return {"fills": o._fills, "next_fill_id": o._next_fill_id}
    if dataclasses.is_dataclass(o):
        return dataclasses.asdict(o)
    if isinstance(o, (set, frozenset)):
        return sorted(o, key=repr)
    return str(o)


def _dump(obj):
    return json.dumps(obj, default=_default, sort_keys=True)


def _freeze(board):
    return _dump({f.name: getattr(board, f.name) for f in dataclasses.fields(board)})


def _fields(obj):
    return {f.name: _dump(getattr(obj, f.name)) for f in dataclasses.fields(obj)}


class PhasePurity(unittest.TestCase):
    def _boards(self):
        paths = sorted(p for p in FX.rglob("*.kicad_pcb") if p.is_file()) if FX.is_dir() else []
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        for name, text in (("k10_a", KICAD10_BOARD_A), ("k10_b", KICAD10_BOARD_B)):
            p = Path(td.name) / f"{name}.kicad_pcb"
            p.write_text(text, encoding="utf-8")
            paths.append(p)
        return paths

    def test_facts_and_checks_are_pure(self):
        from pcb.pipeline import read_board, run_facts, run_checks
        boards = self._boards()
        if not have(FX):
            self.skipTest(f"fixture tree absent: {FX}")
        for path in boards:
            for full in (False, True):
                with self.subTest(board=path.name, full=full):
                    board = read_board(str(path))
                    snap = _freeze(board)
                    f1 = run_facts(board, include_trace_segments=full, **KW)
                    f1_snap = _fields(f1)
                    c1 = run_checks(board, f1, include_trace_segments=full)
                    self.assertEqual(_fields(f1), f1_snap)          # checks do not perturb facts
                    f2 = run_facts(board, include_trace_segments=full, **KW)
                    c2 = run_checks(board, f2, include_trace_segments=full)
                    self.assertEqual(_freeze(board), snap)          # no analysis mutates the board
                    self.assertEqual(_fields(f1), _fields(f2))
                    self.assertEqual(_fields(c1), _fields(c2))
                    if not full:
                        self.assertIsNone(c1.via_in_pad)
                        self.assertIsNone(c1.edge_via)

    def test_run_analyses_equals_facts_plus_checks(self):
        from pcb.pipeline import read_board, run_facts, run_checks, run_analyses
        for path in self._boards():
            for full in (False, True):
                with self.subTest(board=path.name, full=full):
                    a = run_analyses(read_board(str(path)), include_trace_segments=full, **KW)
                    board = read_board(str(path))
                    facts = run_facts(board, include_trace_segments=full, **KW)
                    checks = run_checks(board, facts, include_trace_segments=full)
                    composed = {**_fields(facts), **_fields(checks)}
                    self.assertEqual(set(_fields(a)), set(composed))
                    for name, val in composed.items():
                        self.assertEqual(_fields(a)[name], val, name)

    def test_assemble_result_leaves_board_and_analyses_unchanged(self):
        from pcb.pipeline import read_board, run_analyses, assemble_result
        boards = self._boards()
        if not have(FX):
            self.skipTest(f"fixture tree absent: {FX}")
        for path in boards:
            for full in (False, True):
                with self.subTest(board=path.name, full=full):
                    board = read_board(str(path))
                    analyses = run_analyses(board, include_trace_segments=full, **KW)
                    snap = _freeze(board)
                    # the one documented write: assemble_result pops connectivity["unrouted"]
                    expected = {f.name: getattr(analyses, f.name) for f in dataclasses.fields(analyses)}
                    expected["connectivity"] = {k: v for k, v in expected["connectivity"].items() if k != "unrouted"}
                    expected = {k: _dump(v) for k, v in expected.items()}
                    assemble_result(board, analyses, proximity=False, include_trace_segments=full,
                                    schematic_data=None, resolved_power_rails=None, power_rails_source="heuristic")
                    self.assertEqual(_freeze(board), snap)
                    self.assertEqual(_fields(analyses), expected)


if __name__ == "__main__":
    unittest.main()
