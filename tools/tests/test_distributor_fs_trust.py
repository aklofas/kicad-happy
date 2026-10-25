"""Datasheet sync temp files and manifest file names stay inside the datasheets directory.
No network: every transport is a local fake."""
import io, json, os, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "skills" / "datasheets"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_distributor_sync_driver import fake_provider  # noqa: E402


def _fake_urllib(url, path):
    with open(path, "wb") as f:
        f.write(b"%PDF-1.4 test")
    return True


class FsTrust(unittest.TestCase):
    def setUp(self):
        from distributor_core import download
        p = mock.patch.object(download, "_resolve", return_value=["93.184.216.34"])
        p.start()
        self.addCleanup(p.stop)

    def test_part_symlink_not_followed(self):
        from distributor_core import download
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            outside = d / "outside.txt"
            outside.write_bytes(b"SENTINEL")
            out = d / "out"
            out.mkdir()
            (out / "x.pdf.part").symlink_to(outside)
            with mock.patch.object(download, "_requests", None), \
                 mock.patch.object(download, "_sync_playwright", None), \
                 mock.patch.object(download, "_download_urllib", _fake_urllib), \
                 redirect_stdout(io.StringIO()):
                ok = download.download_pdf("https://example.com/x.pdf", str(out / "x.pdf"))
            self.assertTrue(ok)
            self.assertEqual(outside.read_bytes(), b"SENTINEL")
            self.assertEqual((out / "x.pdf").read_bytes(), b"%PDF-1.4 test")
            self.assertTrue((out / "x.pdf.part").is_symlink())

    def test_umask_untouched_and_import_time_mode_used(self):
        from distributor_core import download, manifest
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            old = os.umask(0o027)
            try:
                with mock.patch.object(manifest, "DEFAULT_FILE_MODE", 0o640), \
                     mock.patch.object(download, "DEFAULT_FILE_MODE", 0o640), \
                     mock.patch.object(download, "_requests", None), \
                     mock.patch.object(download, "_sync_playwright", None), \
                     mock.patch.object(download, "_download_urllib", _fake_urllib), \
                     redirect_stdout(io.StringIO()):
                    download.download_pdf("https://example.com/x.pdf", str(out / "x.pdf"))
                    manifest.save_index(out / "manifest.json", {"parts": {}})
                    after = os.umask(0o027)
            finally:
                os.umask(old)
            self.assertEqual(after, 0o027)
            self.assertEqual((out / "x.pdf").stat().st_mode & 0o777, 0o640)
            self.assertEqual((out / "manifest.json").stat().st_mode & 0o777, 0o640)

    def test_part_removed_on_interrupt_and_on_missing(self):
        from distributor_core import download

        def interrupt(url, path):
            raise KeyboardInterrupt

        def vanish(url, path):
            os.remove(path)
            return False
        for fn, exc in ((interrupt, KeyboardInterrupt), (vanish, None)):
            with tempfile.TemporaryDirectory() as d, \
                 mock.patch.object(download, "_requests", None), \
                 mock.patch.object(download, "_sync_playwright", None), \
                 mock.patch.object(download, "_download_urllib", fn):
                target = str(Path(d) / "x.pdf")
                if exc:
                    with self.assertRaises(exc):
                        download.download_pdf("https://example.com/x.pdf", target)
                else:
                    self.assertFalse(download.download_pdf("https://example.com/x.pdf", target))
                self.assertEqual(os.listdir(d), [])

    def test_manifest_tmp_symlink_not_followed(self):
        from distributor_core.manifest import save_index
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            outside = d / "outside.txt"
            outside.write_bytes(b"SENTINEL")
            out = d / "out"
            out.mkdir()
            (out / "manifest.tmp").symlink_to(outside)
            save_index(out / "manifest.json", {"parts": {}})
            self.assertEqual(outside.read_bytes(), b"SENTINEL")
            m = out / "manifest.json"
            self.assertFalse(m.is_symlink())
            self.assertEqual(json.loads(m.read_text(encoding="utf-8")), {"parts": {}})

    def test_manifest_file_path(self):
        from distributor_core.manifest import manifest_file_path
        with tempfile.TemporaryDirectory() as d:
            out = Path(d)
            (out / "target").write_bytes(b"x")
            (out / "link.pdf").symlink_to(out / "target")
            self.assertEqual(manifest_file_path(out, "a.pdf"), out / "a.pdf")
            for bad in ("../a.pdf", "/etc/passwd", "sub/a.pdf", "a\\b.pdf", "..", ".", "", 5, None, "link.pdf"):
                self.assertIsNone(manifest_file_path(out, bad), bad)

    def test_rename_refuses_outside_file(self):
        from distributor_core.sync import sync_datasheets
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            out = d / "out"
            out.mkdir()
            victim = d / "victim.pdf"
            victim.write_bytes(b"%PDF victim")
            (out / "manifest.json").write_text(json.dumps({"parts": {"LM358DR": {
                "status": "ok", "file": "../victim.pdf", "description": "Op Amp", "manufacturer": "TI"}}}),
                encoding="utf-8")
            mpns = d / "mpns.txt"
            mpns.write_text("LM358DR\n", encoding="utf-8")
            prov = fake_provider(RENAME_PRESENT=True)
            err = io.StringIO()
            with redirect_stderr(err), redirect_stdout(io.StringIO()):
                sync_datasheets(prov, mpn_list=str(mpns), output_dir=str(out))
            self.assertTrue(victim.read_bytes() == b"%PDF victim")
            self.assertEqual([p.name for p in out.iterdir() if p.suffix == ".pdf"], [])
            self.assertIn("names a file outside", err.getvalue())

    def test_derived_datasheets_symlink_refused(self):
        from distributor_core.sync import sync_datasheets
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            outside = d / "outside"
            outside.mkdir()
            project = d / "project"
            project.mkdir()
            bom = project / "bom.json"
            bom.write_text(json.dumps({"bom": [{"mpn": "LM358DR", "references": ["U1"],
                                                "value": "LM358DR", "type": "ic"}]}),
                           encoding="utf-8")
            (project / "datasheets").symlink_to(outside, target_is_directory=True)
            mpns = project / "mpns.txt"
            mpns.write_text("LM358DR\n", encoding="utf-8")
            cwd = os.getcwd()
            os.chdir(project)
            try:
                for kw in ({"input_path": str(bom)}, {"mpn_list": str(mpns)}):
                    with self.subTest(**kw), redirect_stderr(io.StringIO()), \
                         redirect_stdout(io.StringIO()):
                        r = sync_datasheets(fake_provider(), **kw)
                    self.assertEqual(set(r), {"error"})
                    self.assertIn("symlink", r["error"])
                    self.assertEqual(os.listdir(outside), [])
            finally:
                os.chdir(cwd)

    def test_explicit_output_symlink_allowed(self):
        from distributor_core.sync import sync_datasheets
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            outside = d / "outside"
            outside.mkdir()
            (d / "link").symlink_to(outside, target_is_directory=True)
            mpns = d / "mpns.txt"
            mpns.write_text("LM358DR\n", encoding="utf-8")
            with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                r = sync_datasheets(fake_provider(), mpn_list=str(mpns), output_dir=str(d / "link"))
            self.assertNotIn("error", r)
            self.assertEqual(os.listdir(outside), ["manifest.json"])

    def test_parallel_worker_exception_propagates(self):
        from distributor_core.sync import sync_datasheets

        def boom(part, out_dir, index, delay, ctx):
            raise RuntimeError("boom")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            mpns = d / "mpns.txt"
            mpns.write_text("LM358DR\nNE555P\n", encoding="utf-8")
            for par in (1, 2):
                with self.subTest(parallel=par), redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                    with self.assertRaises(RuntimeError):
                        sync_datasheets(fake_provider(sync_one_part=boom), mpn_list=str(mpns),
                                        output_dir=str(d / "out"), parallel=par)


if __name__ == "__main__":
    unittest.main()
