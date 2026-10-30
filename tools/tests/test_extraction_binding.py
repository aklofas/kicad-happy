# tools/tests/test_extraction_binding.py
import contextlib, io, json, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

from tools.tests._fixtures import fixture

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


def _scout(cache, pdf):
    import plan_extraction
    (cache / "X1.scout.json").write_text(json.dumps({
        "pdf_sha256": plan_extraction._sha256(pdf),
        "categories": [], "extraction_pages": {"base": [1], "pinout": [1]},
        "quality_verdict": {"verdict": "ok"}}), encoding="utf-8")


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
            _scout(cache, pdf)
            _plan(cache, SHA_A, ("base", "pinout", "../../../escape", "link"))
            _result(cache, "base", pdf_sha256=SHA_A)
            _result(cache, "pinout", pdf_sha256=SHA_A)
            # an unguarded "<cache>/X1.<tid>.result.json" would resolve here
            (cache / "X1...").mkdir()
            decoy = root / "escape.result.json"
            decoy.write_text("{}", encoding="utf-8")
            target = root / "outside.txt"; target.write_text("keep", encoding="utf-8")
            try:
                (cache / "X1.link.result.json").symlink_to(target)
            except OSError:
                pass
            (cache / "X1.regulator.result.json").write_text("{}", encoding="utf-8")
            self.assertEqual(self._replan(cache, pdf), 0)
            self.assertFalse((cache / "X1.base.result.json").exists())
            self.assertFalse((cache / "X1.pinout.result.json").exists())
            self.assertTrue(decoy.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "keep")
            self.assertTrue((cache / "X1.regulator.result.json").exists())
            new = json.loads((cache / "X1.plan.json").read_text(encoding="utf-8"))
            self.assertEqual(new["pdf_sha256"], plan_extraction._sha256(pdf))

    def test_same_pdf_replan_keeps_results(self):
        import plan_extraction
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            pdf = root / "x.pdf"; pdf.write_bytes(b"%PDF-1.4")
            cache = root / "cache"; cache.mkdir()
            _scout(cache, pdf)
            sha = plan_extraction._sha256(pdf)
            _plan(cache, sha)
            _result(cache, "base", pdf_sha256=sha)
            self.assertEqual(self._replan(cache, pdf), 0)
            self.assertTrue((cache / "X1.base.result.json").exists())


class ReplanNeedsAScoutFromThisPdf(unittest.TestCase):
    def _run(self, cache, pdf):
        import plan_extraction
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            rc = plan_extraction.main(["X1", str(pdf), "--cache-dir", str(cache), "--use-cached-scout"])
        return rc, err.getvalue()

    def test_scout_from_another_pdf_is_refused_and_nothing_is_written(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            old = root / "old.pdf"; old.write_bytes(b"%PDF-1.4 old")
            new = root / "new.pdf"; new.write_bytes(b"%PDF-1.4 new")
            cache = root / "cache"; cache.mkdir()
            _scout(cache, old)
            _plan(cache, SHA_A, ("base",))
            _result(cache, "base", pdf_sha256=SHA_A)
            before = (cache / "X1.plan.json").read_text(encoding="utf-8")
            rc, err = self._run(cache, new)
            self.assertEqual(rc, 2)
            self.assertIn("re-run the scout", err)
            self.assertEqual((cache / "X1.plan.json").read_text(encoding="utf-8"), before)
            self.assertTrue((cache / "X1.base.result.json").exists())

    def test_scout_without_a_sha_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            pdf = root / "x.pdf"; pdf.write_bytes(b"%PDF-1.4")
            cache = root / "cache"; cache.mkdir()
            (cache / "X1.scout.json").write_text(json.dumps({
                "categories": [], "extraction_pages": {"base": [1], "pinout": [1]},
                "quality_verdict": {"verdict": "ok"}}), encoding="utf-8")
            self.assertEqual(self._run(cache, pdf)[0], 2)
            self.assertFalse((cache / "X1.plan.json").exists())

    def test_scout_from_this_pdf_plans_as_before(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            pdf = root / "x.pdf"; pdf.write_bytes(b"%PDF-1.4")
            cache = root / "cache"; cache.mkdir()
            _scout(cache, pdf)
            self.assertEqual(self._run(cache, pdf)[0], 0)
            self.assertTrue((cache / "X1.plan.json").exists())


def _have_jsonschema():
    try:
        import jsonschema, referencing  # noqa: F401
        return True
    except ImportError:
        return False


class PdfSwapEndToEnd(unittest.TestCase):
    @unittest.skipUnless(_have_jsonschema(), "jsonschema/referencing not installed")
    def test_extraction_goes_stale_after_the_pdf_changes(self):
        import shutil
        import plan_extraction, merge_results
        from datasheet_types.cache_reader import lookup
        pdfs = fixture("datasheets-pdfs")
        ext = fixture("datasheets-extracted")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cache = root / "datasheets" / "extracted"; cache.mkdir(parents=True)
            pdf = root / "datasheets" / "LM2596-ADJ.pdf"
            shutil.copy(pdfs / "LM2596-ADJ.pdf", pdf)
            scout = json.loads((ext / "LM2596-ADJ.scout.json").read_text(encoding="utf-8"))

            def put_scout():
                scout["pdf_sha256"] = plan_extraction._sha256(pdf)
                (cache / "LM2596-ADJ.scout.json").write_text(json.dumps(scout), encoding="utf-8")

            def run(fn, *a, **k):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    return fn(*a, **k)

            put_scout()
            argv = ["LM2596-ADJ", str(pdf), "--cache-dir", str(cache), "--use-cached-scout"]
            self.assertEqual(run(plan_extraction.main, argv), 0)
            for tid in ("base", "pinout", "regulator"):
                w = json.loads((ext / f"LM2596-ADJ.{tid}.result.json").read_text(encoding="utf-8"))
                w["pdf_sha256"] = plan_extraction._sha256(pdf)
                (cache / f"LM2596-ADJ.{tid}.result.json").write_text(json.dumps(w), encoding="utf-8")
            self.assertEqual(run(merge_results.merge, cache, "LM2596-ADJ"), 0)
            self.assertFalse(lookup("LM2596-ADJ", cache_dir=cache).stale)

            shutil.copy(pdfs / "LM358.pdf", pdf)
            put_scout()
            self.assertEqual(run(plan_extraction.main, argv), 0)
            self.assertNotEqual(run(merge_results.merge, cache, "LM2596-ADJ"), 0)
            self.assertTrue(lookup("LM2596-ADJ", cache_dir=cache).stale)


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
