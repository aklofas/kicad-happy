# tools/tests/test_extraction_filenames.py
import contextlib, io, json, os, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

DS = Path(__file__).resolve().parents[2] / "skills" / "datasheets"
sys.path.insert(0, str(DS))
sys.path.insert(0, str(DS / "scripts"))


def _tree(root):
    return sorted(str(p.relative_to(root)) for p in Path(root).rglob("*"))


def _scout(cache, stem):
    (cache / f"{stem}.scout.json").write_text(json.dumps({
        "categories": [],
        "extraction_pages": {"base": [1], "pinout": [1]},
        "quality_verdict": {"verdict": "ok"},
    }), encoding="utf-8")


class PlanExtraction(unittest.TestCase):
    def _run(self, mpn, cache, pdf):
        import plan_extraction
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return plan_extraction.main([mpn, str(pdf), "--cache-dir", str(cache), "--use-cached-scout"])

    def test_slash_mpn_uses_the_readers_filename(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            pdf = root / "x.pdf"; pdf.write_bytes(b"%PDF-1.4")
            cache = root / "cache"; cache.mkdir()
            _scout(cache, "LM317_NOPB")
            self.assertEqual(self._run("LM317/NOPB", cache, pdf), 0)
            plan = json.loads((cache / "LM317_NOPB.plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["mpn"], "LM317/NOPB")
            self.assertEqual(plan["scout_ref"], "LM317_NOPB.scout.json")

    def test_traversal_mpn_writes_only_inside_the_cache(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            pdf = root / "x.pdf"; pdf.write_bytes(b"%PDF-1.4")
            cache = root / "a" / "b" / "cache"; cache.mkdir(parents=True)
            # ".." and "/" each become "_": ".._.._escape"
            _scout(cache, ".._.._escape")
            before = _tree(root)
            self._run("../../escape", cache, pdf)
            new = set(_tree(root)) - set(before)
            self.assertEqual(new, {os.path.join("a", "b", "cache", ".._.._escape.plan.json")})


class MergeResults(unittest.TestCase):
    def _plan(self, cache, stem, tid):
        (cache / f"{stem}.plan.json").write_text(json.dumps({
            "mpn": "LM317/NOPB", "pdf_path": "x.pdf", "pdf_sha256": "sha256:0",
            "tasks": [{"task_id": tid, "subagent_role": "base", "tier": "B",
                       "schema": "skills/datasheets/schemas/base.schema.json",
                       "pages": [1], "status": "pending", "result_ref": None}],
            "execution": {"started_at": None, "completed_at": None, "outcomes": []},
        }), encoding="utf-8")

    def _merge(self, cache, mpn):
        import merge_results
        with mock.patch.object(merge_results, "validate_against_schema", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return merge_results.merge(cache, mpn)

    def test_slash_mpn_merges_to_the_name_the_reader_finds(self):
        from datasheet_types.cache_reader import cache_path_for
        with tempfile.TemporaryDirectory() as d:
            cache = Path(d)
            self._plan(cache, "LM317_NOPB", "base")
            (cache / "LM317_NOPB.base.result.json").write_text(json.dumps(
                {"task_id": "base", "status": "complete", "pdf_sha256": "sha256:0",
                 "data": {"family": "LM317"}}), encoding="utf-8")
            self.assertEqual(self._merge(cache, "LM317/NOPB"), 0)
            out = json.loads((cache / "LM317_NOPB.json").read_text(encoding="utf-8"))
            self.assertEqual(out["source"]["mpn"], "LM317/NOPB")
            self.assertEqual(out["extraction"]["plan_ref"], "LM317_NOPB.plan.json")
            self.assertEqual(cache_path_for("LM317/NOPB", cache), cache / "LM317_NOPB.json")

    def test_task_id_outside_the_cache_is_a_failed_task(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cache = root / "cache"; cache.mkdir()
            self._plan(cache, "LM317_NOPB", "../x")
            # would be read if the task id were joined into the path
            (root / "x.result.json").write_text("{}", encoding="utf-8")
            rc = self._merge(cache, "LM317/NOPB")
            self.assertEqual(rc, 1)
            plan = json.loads((cache / "LM317_NOPB.plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["tasks"][0]["status"], "failed")
            self.assertEqual(plan["execution"]["outcomes"][0]["final_status"], "failed")
            self.assertFalse((cache / "LM317_NOPB.json").exists())


if __name__ == "__main__":
    unittest.main()
