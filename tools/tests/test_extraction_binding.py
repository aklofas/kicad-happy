# tools/tests/test_extraction_binding.py
import contextlib, io, json, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

DS = Path(__file__).resolve().parents[2] / "skills" / "datasheets"
sys.path.insert(0, str(DS))
sys.path.insert(0, str(DS / "scripts"))

SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64


def _plan(cache, sha, tids=("base", "pinout")):
    (cache / "X1.plan.json").write_text(json.dumps({
        "mpn": "X1", "pdf_path": "x.pdf", "pdf_sha256": sha,
        "tasks": [{"task_id": t, "subagent_role": t, "tier": "B",
                   "schema": "skills/datasheets/schemas/base.schema.json",
                   "pages": [1], "status": "pending", "result_ref": None} for t in tids],
        "execution": {"started_at": None, "completed_at": None, "outcomes": []},
    }), encoding="utf-8")


def _result(cache, tid, **extra):
    w = {"task_id": tid, "status": "complete", "data": {"family": "X"}}
    w.update(extra)
    (cache / f"X1.{tid}.result.json").write_text(json.dumps(w), encoding="utf-8")


def _merge(cache):
    import merge_results
    err = io.StringIO()
    with mock.patch.object(merge_results, "validate_against_schema", return_value=None), \
            contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        rc = merge_results.merge(cache, "X1")
    return rc, err.getvalue()


class MergeBinding(unittest.TestCase):
    def test_bound_result_on_the_planned_pdf_still_merges(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d)
            _plan(cache, SHA_A, ("base",))
            _result(cache, "base", pdf_sha256=SHA_A)
            self.assertEqual(_merge(cache)[0], 0)
            out = json.loads((cache / "X1.json").read_text(encoding="utf-8"))
            self.assertEqual(out["source"]["sha256"], SHA_A)

    def test_unbound_result_is_rejected_with_a_message(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d)
            _plan(cache, SHA_A, ("base",))
            _result(cache, "base")
            rc, err = _merge(cache)
            self.assertNotEqual(rc, 0)
            self.assertIn("pdf_sha256", err)
            plan = json.loads((cache / "X1.plan.json").read_text(encoding="utf-8"))
            self.assertIn("pdf_sha256", plan["execution"]["outcomes"][0]["last_error"])

    def test_result_from_another_pdf_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d)
            _plan(cache, SHA_B, ("base",))
            _result(cache, "base", pdf_sha256=SHA_A)
            rc, err = _merge(cache)
            self.assertNotEqual(rc, 0)
            self.assertIn(SHA_A, err)


class ReplanDropsStaleResults(unittest.TestCase):
    def _replan(self, cache, pdf):
        import plan_extraction
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return plan_extraction.main(["X1", str(pdf), "--cache-dir", str(cache), "--use-cached-scout"])

    def test_new_pdf_deletes_the_old_plans_results_only(self):
        import plan_extraction
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            pdf = root / "x.pdf"; pdf.write_bytes(b"%PDF-1.4 rev2")
            cache = root / "cache"; cache.mkdir()
            (cache / "X1.scout.json").write_text(json.dumps({
                "categories": [], "extraction_pages": {"base": [1], "pinout": [1]},
                "quality_verdict": {"verdict": "ok"}}), encoding="utf-8")
            _plan(cache, SHA_A, ("base", "pinout", "../escape"))
            _result(cache, "base", pdf_sha256=SHA_A)
            _result(cache, "pinout", pdf_sha256=SHA_A)
            (root / "escape.result.json").write_text("{}", encoding="utf-8")
            (cache / "X1.regulator.result.json").write_text("{}", encoding="utf-8")
            self.assertEqual(self._replan(cache, pdf), 0)
            self.assertFalse((cache / "X1.base.result.json").exists())
            self.assertFalse((cache / "X1.pinout.result.json").exists())
            self.assertTrue((root / "escape.result.json").exists())
            self.assertTrue((cache / "X1.regulator.result.json").exists())
            new = json.loads((cache / "X1.plan.json").read_text(encoding="utf-8"))
            self.assertEqual(new["pdf_sha256"], plan_extraction._sha256(pdf))

    def test_same_pdf_replan_keeps_results(self):
        import plan_extraction
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            pdf = root / "x.pdf"; pdf.write_bytes(b"%PDF-1.4")
            cache = root / "cache"; cache.mkdir()
            (cache / "X1.scout.json").write_text(json.dumps({
                "categories": [], "extraction_pages": {"base": [1], "pinout": [1]},
                "quality_verdict": {"verdict": "ok"}}), encoding="utf-8")
            sha = plan_extraction._sha256(pdf)
            _plan(cache, sha)
            _result(cache, "base", pdf_sha256=sha)
            self.assertEqual(self._replan(cache, pdf), 0)
            self.assertTrue((cache / "X1.base.result.json").exists())


class PageSelectorKeepsLastPage(unittest.TestCase):
    def test_fallback_keeps_front_and_last_page(self):
        from datasheet_page_selector import _fallback_page_selection as f
        self.assertEqual(f(40, 4), [1, 2, 3, 40])
        self.assertEqual(f(40, 5), [1, 2, 3, 4, 40])
        self.assertEqual(f(40, 1), [1])
        self.assertEqual(f(3, 10), [1, 2, 3])

    def test_cap_keeps_front_and_last_page(self):
        from datasheet_page_selector import _cap_pages
        self.assertEqual(_cap_pages([1, 5, 6, 7, 8, 40], 4, 40), [1, 5, 6, 40])


class ValidateSanityVectorHelp(unittest.TestCase):
    def test_help_does_not_need_yaml(self):
        code = ("import sys; sys.modules['yaml']=None; sys.argv=['v','--help']; "
                "import runpy; runpy.run_path(%r, run_name='__main__')"
                % str(DS / "scripts" / "validate_sanity_vector.py"))
        r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("usage", r.stdout)


if __name__ == "__main__":
    unittest.main()
