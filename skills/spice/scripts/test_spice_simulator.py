#!/usr/bin/env python3
"""Unit tests for SPICE simulator selection and external-deck execution."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import call, patch

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import spice_simulator
import run_external_deck


class TestExternalDeckCliSurface(unittest.TestCase):
    """Exercise the standalone script as a user invokes it."""

    def test_help_lists_only_explicit_external_deck_choices(self):
        script = SCRIPT_DIR / "run_external_deck.py"
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("{pspice,ngspice,ltspice,xyce}", result.stdout)
        self.assertIn("--timeout", result.stdout)
        self.assertIn("--output", result.stdout)
        self.assertNotIn("{auto,", result.stdout)

    def test_backend_selector_is_available(self):
        self.assertTrue(
            hasattr(run_external_deck, "select_backend"),
            "external-deck CLI should expose select_backend",
        )

    def test_missing_deck_is_rejected_before_simulator_discovery(self):
        script = SCRIPT_DIR / "run_external_deck.py"
        missing = SCRIPT_DIR / "missing-external-deck.cir"
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                str(missing),
                "--simulator",
                "pspice",
            ],
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertIn("deck is not a file", result.stderr)

    def test_nonpositive_timeout_is_rejected(self):
        script = SCRIPT_DIR / "run_external_deck.py"
        with tempfile.TemporaryDirectory() as tmp:
            deck = Path(tmp) / "synthetic.cir"
            deck.write_text("* synthetic\n.end\n", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    str(deck),
                    "--simulator",
                    "pspice",
                    "--timeout",
                    "0",
                ],
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("--timeout must be greater than zero", result.stderr)


class TestExternalDeckSelection(unittest.TestCase):
    """Keep PSpice selection outside the generated-backend registry."""

    def test_pspice_is_constructed_only_for_explicit_request(self):
        with (
            patch("run_external_deck.PspiceBackend") as pspice_class,
            patch("run_external_deck.detect_simulator") as detect,
        ):
            pspice_class.return_value.find.return_value = "pspice.exe"
            selected = run_external_deck.select_backend("pspice")

        self.assertIs(selected, pspice_class.return_value)
        detect.assert_not_called()

    def test_existing_backend_requests_use_existing_detector(self):
        expected = object()
        with (
            patch("run_external_deck.PspiceBackend") as pspice_class,
            patch(
                "run_external_deck.detect_simulator",
                return_value=expected,
            ) as detect,
        ):
            selected = run_external_deck.select_backend("ngspice")

        self.assertIs(selected, expected)
        detect.assert_called_once_with("ngspice")
        pspice_class.assert_not_called()


class TestExternalDeckCli(unittest.TestCase):
    """Verify the standalone JSON and process-exit contract."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.deck = Path(self.tempdir.name) / "example deck.cir"
        self.deck.write_text("* synthetic deck\n.end\n", encoding="utf-8")

    @staticmethod
    def _backend(name, result):
        calls = []

        def run(deck, timeout):
            calls.append((deck, timeout))
            return result

        return SimpleNamespace(name=name, run=run, calls=calls)

    def _run(self, arguments, backend):
        stdout = io.StringIO()
        stderr = io.StringIO()
        ticks = iter([10.0, 11.2344])
        fake_time = SimpleNamespace(perf_counter=lambda: next(ticks))
        with (
            patch(
                "run_external_deck.select_backend",
                return_value=backend,
            ),
            patch.object(
                run_external_deck,
                "time",
                fake_time,
                create=True,
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            code = run_external_deck.main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def _json_stdout(self, stdout):
        self.assertNotEqual(stdout, "", "CLI should emit result JSON")
        return json.loads(stdout)

    def test_success_emits_stable_json_and_zero_exit(self):
        backend = self._backend("pspice", (True, "", ""))
        code, stdout, stderr = self._run(
            [
                str(self.deck),
                "--simulator",
                "pspice",
                "--timeout",
                "120",
            ],
            backend,
        )

        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(
            self._json_stdout(stdout),
            {
                "simulator": "pspice",
                "success": True,
                "deck": str(self.deck.resolve()),
                "native_output": str(
                    self.deck.resolve().with_suffix(".out")
                ),
                "elapsed_s": 1.234,
                "note": "PSpice reported JOB CONCLUDED",
            },
        )
        self.assertEqual(
            backend.calls,
            [(str(self.deck.resolve()), 120)],
        )

    def test_existing_backend_reports_no_invented_native_output(self):
        backend = self._backend("ngspice", (True, "", ""))
        code, stdout, _ = self._run(
            [str(self.deck), "--simulator", "ngspice"],
            backend,
        )

        self.assertEqual(code, 0)
        self.assertIsNone(self._json_stdout(stdout)["native_output"])

    def test_backend_failure_emits_json_stderr_and_nonzero_exit(self):
        backend = self._backend(
            "pspice",
            (
                False,
                "",
                "PSpice completion marker missing: JOB CONCLUDED",
            ),
        )
        code, stdout, stderr = self._run(
            [str(self.deck), "--simulator", "pspice"],
            backend,
        )

        self.assertEqual(code, 1)
        self.assertFalse(self._json_stdout(stdout)["success"])
        self.assertIn("completion marker missing", stderr.lower())

    def test_missing_simulator_returns_actionable_failure(self):
        code, stdout, stderr = self._run(
            [str(self.deck), "--simulator", "pspice"],
            None,
        )

        self.assertEqual(code, 1)
        self.assertFalse(self._json_stdout(stdout)["success"])
        self.assertIn("set PSPICE_PATH", stderr)

    def test_output_option_writes_json_file_instead_of_stdout(self):
        result_path = Path(self.tempdir.name) / "result.json"
        backend = self._backend("pspice", (True, "", ""))
        code, stdout, stderr = self._run(
            [
                str(self.deck),
                "--simulator",
                "pspice",
                "--output",
                str(result_path),
            ],
            backend,
        )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        self.assertTrue(result_path.is_file())
        self.assertTrue(
            json.loads(result_path.read_text(encoding="utf-8"))["success"]
        )
        self.assertTrue(result_path.read_text(encoding="utf-8").endswith("\n"))


class TestPspiceBackendSurface(unittest.TestCase):
    """Require an explicit backend class without registering it."""

    def test_pspice_backend_is_available_for_direct_import(self):
        self.assertTrue(
            hasattr(spice_simulator, "PspiceBackend"),
            "PspiceBackend should be available for the external-deck runner",
        )


class TestPspiceDiscovery(unittest.TestCase):
    """Exercise the documented PSPICE_PATH then PATH lookup order."""

    def test_pspice_path_existing_file_takes_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "PSpice executable.exe"
            executable.touch()
            with (
                patch.dict(
                    os.environ,
                    {"PSPICE_PATH": str(executable)},
                    clear=False,
                ),
                patch("spice_simulator.shutil.which") as which,
            ):
                found = spice_simulator.PspiceBackend().find()

        self.assertEqual(found, str(executable))
        which.assert_not_called()

    def test_invalid_pspice_path_falls_back_to_path_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.exe"
            with (
                patch.dict(
                    os.environ,
                    {"PSPICE_PATH": str(missing)},
                    clear=False,
                ),
                patch(
                    "spice_simulator.shutil.which",
                    side_effect=[None, "/tools/pspice.exe"],
                ) as which,
            ):
                found = spice_simulator.PspiceBackend().find()

        self.assertEqual(found, "/tools/pspice.exe")
        self.assertEqual(
            which.call_args_list,
            [call("pspice"), call("pspice.exe")],
        )


class TestPspiceRun(unittest.TestCase):
    """Classify native PSpice batch outcomes, not just process exits."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.deck = Path(self.tempdir.name) / "deck with spaces.cir"
        self.deck.write_text(
            "* synthetic passive deck\n.end\n",
            encoding="utf-8",
        )
        self.output = self.deck.with_suffix(".out")
        self.backend = spice_simulator.PspiceBackend()

    def _run_with_output(self, native_text, returncode=0):
        def fake_run(command, **kwargs):
            if native_text is not None:
                self.output.write_text(native_text, encoding="utf-8")
            return subprocess.CompletedProcess(
                command,
                returncode,
                "process stdout",
                "process stderr",
            )

        with (
            patch.object(
                self.backend,
                "find",
                return_value="C:/Program Files/PSpice/pspice.exe",
            ),
            patch(
                "spice_simulator.subprocess.run",
                side_effect=fake_run,
            ) as run,
        ):
            result = self.backend.run(self.deck, timeout=120)
        return result, run

    def test_command_keeps_space_containing_paths_as_single_arguments(self):
        (success, _, _), run = self._run_with_output("JOB CONCLUDED\n")

        self.assertTrue(success)
        run.assert_called_once_with(
            [
                "C:/Program Files/PSpice/pspice.exe",
                "-r",
                "-e",
                self.deck.name,
                "-o",
                self.output.name,
            ],
            cwd=str(self.deck.resolve().parent),
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_exit_zero_with_completion_marker_succeeds(self):
        result, _ = self._run_with_output(
            "PSpice batch output\nJOB CONCLUDED\n"
        )
        self.assertEqual(
            result,
            (True, "process stdout", "process stderr"),
        )

    def test_exit_zero_without_completion_marker_fails(self):
        (success, _, diagnostic), _ = self._run_with_output(
            "analysis stopped\n"
        )
        self.assertFalse(success)
        self.assertIn("completion marker missing", diagnostic.lower())

    def test_abort_marker_fails_even_with_zero_exit(self):
        (success, _, diagnostic), _ = self._run_with_output(
            "JOB ABORTED\nJOB CONCLUDED\n"
        )
        self.assertFalse(success)
        self.assertIn("abort marker", diagnostic.lower())

    def test_fatal_error_line_fails(self):
        (success, _, diagnostic), _ = self._run_with_output(
            "ERROR -- invalid model\nJOB CONCLUDED\n"
        )
        self.assertFalse(success)
        self.assertIn("fatal error", diagnostic.lower())

    def test_zero_error_summary_is_not_fatal(self):
        (success, _, _), _ = self._run_with_output(
            "ERROR COUNT = 0\nJOB CONCLUDED\n"
        )
        self.assertTrue(success)

    def test_nonzero_process_exit_fails(self):
        (success, _, diagnostic), _ = self._run_with_output(
            "JOB CONCLUDED\n",
            returncode=7,
        )
        self.assertFalse(success)
        self.assertIn("exit code 7", diagnostic.lower())

    def test_missing_and_empty_native_outputs_fail(self):
        for native_text, expected in ((None, "missing"), ("", "empty")):
            with self.subTest(native_text=native_text):
                self.output.unlink(missing_ok=True)
                (success, _, diagnostic), _ = self._run_with_output(
                    native_text
                )
                self.assertFalse(success)
                self.assertIn(expected, diagnostic.lower())

    def test_timeout_returns_failure_without_deleting_native_output(self):
        self.output.write_text(
            "partial native output\n",
            encoding="utf-8",
        )
        with (
            patch.object(self.backend, "find", return_value="pspice.exe"),
            patch(
                "spice_simulator.subprocess.run",
                side_effect=subprocess.TimeoutExpired("pspice", 9),
            ),
        ):
            success, _, diagnostic = self.backend.run(self.deck, timeout=9)

        self.assertFalse(success)
        self.assertEqual(diagnostic, "Simulation timed out after 9s")
        self.assertEqual(
            self.output.read_text(encoding="utf-8"),
            "partial native output\n",
        )

    def test_missing_executable_returns_actionable_failure(self):
        with patch.object(self.backend, "find", return_value=None):
            success, stdout, diagnostic = self.backend.run(
                self.deck,
                timeout=120,
            )

        self.assertFalse(success)
        self.assertEqual(stdout, "")
        self.assertIn("set PSPICE_PATH", diagnostic)

    def test_launch_error_returns_actionable_failure(self):
        with (
            patch.object(self.backend, "find", return_value="pspice.exe"),
            patch(
                "spice_simulator.subprocess.run",
                side_effect=OSError("launch blocked"),
            ),
        ):
            success, _, diagnostic = self.backend.run(
                self.deck,
                timeout=120,
            )

        self.assertFalse(success)
        self.assertIn("Could not launch PSpice", diagnostic)
        self.assertIn("launch blocked", diagnostic)

    def test_unreadable_native_output_returns_actionable_failure(self):
        def fake_run(command, **kwargs):
            self.output.write_text("JOB CONCLUDED\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, "", "")

        with (
            patch.object(self.backend, "find", return_value="pspice.exe"),
            patch("spice_simulator.subprocess.run", side_effect=fake_run),
            patch.object(
                spice_simulator.Path,
                "read_text",
                side_effect=OSError("read blocked"),
            ),
        ):
            success, _, diagnostic = self.backend.run(
                self.deck,
                timeout=120,
            )

        self.assertFalse(success)
        self.assertIn("Could not read PSpice native output", diagnostic)
        self.assertIn("read blocked", diagnostic)

    def test_unsupported_generated_measurement_methods_are_actionable(self):
        message = "use run_external_deck.py"
        with self.assertRaisesRegex(NotImplementedError, message):
            self.backend.format_measurement_block(
                [],
                [],
                "measurements.out",
            )
        with self.assertRaisesRegex(NotImplementedError, message):
            self.backend.parse_results("measurements.out", "", "")


class TestExistingBackendSelection(unittest.TestCase):
    """Guard the generated-testbench simulator selection contract."""

    def test_registry_excludes_pspice(self):
        self.assertEqual(
            list(spice_simulator.BACKENDS),
            ["ngspice", "ltspice", "xyce"],
        )
        self.assertNotIn("pspice", spice_simulator.BACKENDS)

    def test_explicit_pspice_is_not_available_through_existing_detector(self):
        with patch.dict(os.environ, {"PSPICE_PATH": __file__}, clear=False):
            self.assertIsNone(spice_simulator.detect_simulator("pspice"))

    def test_auto_detection_order_is_unchanged(self):
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(
                spice_simulator.NgspiceBackend,
                "find",
                return_value=None,
            ) as ng_find,
            patch.object(
                spice_simulator.LtspiceBackend,
                "find",
                return_value=None,
            ) as lt_find,
            patch.object(
                spice_simulator.XyceBackend,
                "find",
                return_value="/bin/Xyce",
            ) as xyce_find,
        ):
            backend = spice_simulator.detect_simulator("auto")

        self.assertIsInstance(backend, spice_simulator.XyceBackend)
        ng_find.assert_called_once_with()
        lt_find.assert_called_once_with()
        xyce_find.assert_called_once_with()


if __name__ == "__main__":
    unittest.main(verbosity=2)
