"""Programs launched for PDF text and GitHub are absolute PATH entries on Windows,
never a copy in the current directory."""
import os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for p in (ROOT / "skills" / "kicad" / "scripts", ROOT / "skills" / "datasheets",
          ROOT / "skills" / "datasheets" / "scripts", ROOT / "skills" / "spice" / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from kicad_core import executables  # noqa: E402
from distributor_core import verify  # noqa: E402
import datasheet_page_selector as dps  # noqa: E402
import spice_spec_fetcher as ssf  # noqa: E402
import export_issues  # noqa: E402

MPN = "POPAMP1"


class WindowsLookupBase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.cwd = self.tmp / "cwd"
        self.bin = self.tmp / "bin"
        self.cwd.mkdir()
        self.bin.mkdir()
        old = os.getcwd()
        self.addCleanup(os.chdir, old)
        os.chdir(self.cwd)
        self.pdf = self.tmp / "a.pdf"
        self.pdf.write_bytes(b"%PDF-1.4 plain readable text in the raw scan")
        p = mock.patch.object(executables, "_on_windows", return_value=True)
        p.start()
        self.addCleanup(p.stop)

    def tools(self, where, *names):
        for n in names:
            (where / f"{n}.exe").write_bytes(b"")

    def path(self, *dirs):
        return mock.patch.dict(os.environ, {"PATH": os.pathsep.join(dirs)})


class VerifyExtractTest(WindowsLookupBase):
    def test_cwd_copy_is_not_launched(self):
        self.tools(self.cwd, "pdftotext")
        with self.path("."), mock.patch("subprocess.run") as run:
            text = verify._extract_pdf_text(str(self.pdf))
        run.assert_not_called()
        self.assertIn("plain readable text", text)

    def test_absolute_path_entry_is_launched_by_full_path(self):
        self.tools(self.bin, "pdftotext")
        done = subprocess.CompletedProcess([], 0, "page text", "")
        with self.path(".", str(self.bin)), mock.patch("subprocess.run", return_value=done) as run:
            verify._extract_pdf_text(str(self.pdf))
        self.assertEqual(run.call_args.args[0][0], str(self.bin / "pdftotext.exe"))


class PageSelectorTest(WindowsLookupBase):
    def test_absolute_tools_are_launched_by_full_path(self):
        self.tools(self.bin, "pdfinfo", "pdftotext")
        outs = [subprocess.CompletedProcess([], 0, "Pages: 2\n", ""),
                subprocess.CompletedProcess([], 0, "a\fb", "")]
        with self.path(".", str(self.bin)), mock.patch("subprocess.run", side_effect=outs) as run:
            dps._extract_pages_text(str(self.pdf))
        self.assertEqual([c.args[0][0] for c in run.call_args_list],
                         [str(self.bin / "pdfinfo.exe"), str(self.bin / "pdftotext.exe")])

    def test_cwd_copies_are_not_launched(self):
        self.tools(self.cwd, "pdfinfo", "pdftotext")
        with self.path("."), mock.patch("subprocess.run") as run:
            self.assertEqual(dps._extract_pages_text(str(self.pdf)), {})
        run.assert_not_called()


class SpecFetcherTest(WindowsLookupBase):
    def _project(self):
        proj = self.tmp / "proj"
        (proj / "datasheets").mkdir(parents=True)
        (proj / "datasheets" / "manifest.json").write_text(
            '{"parts": {"%s": {"status": "ok", "file": "%s.pdf"}}}' % (MPN, MPN), encoding="utf-8")
        (proj / "datasheets" / f"{MPN}.pdf").write_bytes(b"%PDF-1.4")
        return proj

    def test_absolute_pdftotext_is_launched_by_full_path(self):
        self.tools(self.bin, "pdftotext")
        done = subprocess.CompletedProcess([], 0, "", "")
        with self.path(".", str(self.bin)), mock.patch("subprocess.run", return_value=done) as run:
            ssf.fetch_specs_from_datasheet(MPN, self._project())
        self.assertEqual(run.call_args.args[0][0], str(self.bin / "pdftotext.exe"))

    def test_cwd_pdftotext_is_not_launched(self):
        self.tools(self.cwd, "pdftotext")
        with self.path("."), mock.patch("subprocess.run") as run:
            self.assertIsNone(ssf.fetch_specs_from_datasheet(MPN, self._project()))
        run.assert_not_called()


class GhTest(WindowsLookupBase):
    def test_cwd_gh_is_not_available(self):
        self.tools(self.cwd, "gh")
        with self.path("."), mock.patch("subprocess.run") as run:
            self.assertFalse(export_issues.check_gh_available())
        run.assert_not_called()

    def test_absolute_gh_is_launched_by_full_path(self):
        self.tools(self.bin, "gh")
        done = subprocess.CompletedProcess([], 0, b"", b"")
        with self.path(".", str(self.bin)), mock.patch("subprocess.run", return_value=done) as run:
            self.assertTrue(export_issues.check_gh_available())
        self.assertEqual(run.call_args.args[0][0], str(self.bin / "gh.exe"))


if __name__ == "__main__":
    unittest.main()
