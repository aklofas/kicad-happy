#!/usr/bin/env python3
"""Unit tests for SPICE simulator selection and external-deck execution."""

import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import call, patch

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import spice_simulator  # noqa: E402
import run_external_deck  # noqa: E402


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

    def _usage_error(self, arguments):
        backend = self._backend("pspice", (True, "", ""))
        stderr = io.StringIO()
        with (
            patch("run_external_deck.select_backend", return_value=backend),
            redirect_stderr(stderr),
            self.assertRaises(SystemExit) as raised,
        ):
            run_external_deck.main(arguments)
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(backend.calls, [], "simulator must not be launched")
        return stderr.getvalue()

    def test_output_may_not_overwrite_deck_native_output_or_sidecar(self):
        native = self.deck.with_suffix(".out")
        for victim in (self.deck, native, native.with_suffix(".json")):
            with self.subTest(victim=victim.name):
                message = self._usage_error(
                    [
                        str(self.deck),
                        "--simulator",
                        "pspice",
                        "--output",
                        str(victim),
                    ]
                )
                self.assertIn("would overwrite", message)
        self.assertEqual(
            self.deck.read_text(encoding="utf-8"),
            "* synthetic deck\n.end\n",
        )

    @unittest.skipUnless(os.name == "nt", "case-insensitive file system")
    def test_output_collision_check_ignores_case_on_windows(self):
        message = self._usage_error(
            [
                str(self.deck),
                "--simulator",
                "pspice",
                "--output",
                str(self.deck).upper(),
            ]
        )
        self.assertIn("would overwrite", message)

    def test_sidecar_name_is_only_reserved_for_pspice(self):
        sidecar = self.deck.with_suffix(".json")
        backend = self._backend("ngspice", (True, "", ""))
        code, _, _ = self._run(
            [
                str(self.deck),
                "--simulator",
                "ngspice",
                "--output",
                str(sidecar),
            ],
            backend,
        )
        self.assertEqual(code, 0)
        self.assertTrue(sidecar.is_file())

    def test_output_directory_and_missing_directory_are_usage_errors(self):
        missing = Path(self.tempdir.name) / "missing" / "result.json"
        for destination, expected in (
            (Path(self.tempdir.name), "is a directory"),
            (missing, "directory does not exist"),
        ):
            with self.subTest(destination=destination.name):
                message = self._usage_error(
                    [
                        str(self.deck),
                        "--simulator",
                        "pspice",
                        "--output",
                        str(destination),
                    ]
                )
                self.assertIn(expected, message)
                self.assertNotIn("Traceback", message)

    def test_pspice_deck_with_out_suffix_is_rejected(self):
        clashing = Path(self.tempdir.name) / "clash.OUT"
        clashing.write_text("* synthetic deck\n.end\n", encoding="utf-8")
        message = self._usage_error(
            [str(clashing), "--simulator", "pspice"]
        )
        self.assertIn(".out suffix", message)

    def test_default_timeout_is_ten_minutes(self):
        backend = self._backend("pspice", (True, "", ""))
        self._run([str(self.deck), "--simulator", "pspice"], backend)
        self.assertEqual(backend.calls, [(str(self.deck.resolve()), 600)])

    def test_result_json_is_replaced_atomically(self):
        result_path = Path(self.tempdir.name) / "result.json"
        result_path.write_text("previous result\n", encoding="utf-8")
        backend = self._backend("pspice", (True, "", ""))
        with patch(
            "run_external_deck.os.replace",
            side_effect=OSError("replace blocked"),
        ):
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

        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn(f"could not write {result_path}", stderr)
        self.assertIn("replace blocked", stderr)

        self.assertEqual(
            result_path.read_text(encoding="utf-8"),
            "previous result\n",
        )
        self.assertEqual(
            sorted(p.name for p in result_path.parent.iterdir()),
            ["example deck.cir", "result.json"],
        )

    def test_result_creation_failure_is_a_clean_error(self):
        result_path = Path(self.tempdir.name) / "result.json"
        for backend in (None, self._backend("pspice", (True, "", ""))):
            with self.subTest(simulator_available=backend is not None):
                with patch(
                    "run_external_deck.tempfile.mkstemp",
                    side_effect=PermissionError("access denied"),
                ):
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
                self.assertEqual(code, 1)
                self.assertEqual(stdout, "")
                self.assertIn(f"could not write {result_path}", stderr)
                self.assertIn("access denied", stderr)
                self.assertFalse(result_path.exists())


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


STUB_SOURCE = '''\
import json
import os
import subprocess
import sys
import time
from pathlib import Path

here = Path(__file__).resolve().parent
config = json.loads((here / "stub.json").read_text(encoding="utf-8"))
args = sys.argv[1:]
(here / "record.json").write_text(
    json.dumps({"argv": args, "cwd": os.getcwd()}),
    encoding="utf-8",
)
if config.get("out_hex") is not None:
    Path(args[args.index("-o") + 1]).write_bytes(
        bytes.fromhex(config["out_hex"])
    )
if config.get("stdout_hex"):
    sys.stdout.buffer.write(bytes.fromhex(config["stdout_hex"]))
    sys.stdout.flush()
if config.get("heartbeat"):
    child = (
        "import time\\n"
        "from pathlib import Path\\n"
        "for _ in range(600):\\n"
        f"    Path({config['heartbeat']!r}).write_text('alive')\\n"
        "    time.sleep(0.05)\\n"
    )
    subprocess.Popen([sys.executable, "-c", child])
time.sleep(config.get("sleep", 0))
sys.exit(config.get("exit_code", 0))
'''


class StubPspice(spice_simulator.PspiceBackend):
    """Real PspiceBackend launch path with a Python script as the program."""

    def __init__(self, stub):
        self.stub = stub

    def find(self):
        return sys.executable

    def _command(self, binary, deck_name, output_name):
        command = super()._command(binary, deck_name, output_name)
        return [command[0], str(self.stub), *command[1:]]


class TestPspiceRun(unittest.TestCase):
    """Classify native PSpice batch outcomes of a real child process."""

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        root = Path(self.tempdir.name)
        self.stub_dir = root / "stub"
        self.stub_dir.mkdir()
        self.stub = self.stub_dir / "stub_pspice.py"
        self.stub.write_text(STUB_SOURCE, encoding="utf-8")
        self.deck_dir = root / "deck dir"
        self.deck_dir.mkdir()
        self.deck = self.deck_dir / "deck with spaces.cir"
        self.deck.write_text(
            "* synthetic passive deck\n.end\n",
            encoding="utf-8",
        )
        self.output = self.deck.with_suffix(".out")
        self.backend = StubPspice(self.stub)

    def _run(self, native=None, timeout=60, **config):
        if isinstance(native, str):
            native = native.encode("utf-8")
        if native is not None:
            config["out_hex"] = native.hex()
        (self.stub_dir / "stub.json").write_text(
            json.dumps(config),
            encoding="utf-8",
        )
        return self.backend.run(self.deck, timeout=timeout)

    def _record(self):
        return json.loads(
            (self.stub_dir / "record.json").read_text(encoding="utf-8")
        )

    def test_process_runs_in_deck_directory_with_expected_arguments(self):
        success, _, _ = self._run("JOB CONCLUDED\n")

        self.assertTrue(success)
        record = self._record()
        self.assertEqual(
            record["argv"],
            ["-r", "-e", self.deck.name, "-o", self.output.name],
        )
        self.assertTrue(os.path.samefile(record["cwd"], self.deck_dir))

    def test_exit_zero_with_completion_marker_succeeds(self):
        result = self._run("PSpice batch output\n   JOB CONCLUDED  \r\n")
        self.assertEqual(result, (True, "", ""))

    def test_marker_must_be_a_whole_line(self):
        for text in (
            "JOB CONCLUDED early\n",
            "* JOB CONCLUDED\n",
            "echo JOB CONCLUDEDX\n",
        ):
            with self.subTest(text=text):
                (success, _, diagnostic) = self._run(text)
                self.assertFalse(success)
                self.assertIn("completion marker missing", diagnostic)

    def test_abort_marker_must_be_a_whole_line(self):
        (success, _, diagnostic) = self._run(
            "JOB ABORTED later\nJOB CONCLUDED\n"
        )
        self.assertTrue(success, diagnostic)

    def test_stale_native_output_is_not_success(self):
        self.output.write_text("JOB CONCLUDED\n", encoding="utf-8")

        success, _, diagnostic = self._run(None)

        self.assertFalse(success)
        self.assertIn("did not update native output", diagnostic)
        self.assertEqual(
            self.output.read_text(encoding="utf-8"),
            "JOB CONCLUDED\n",
        )

    def test_rewritten_native_output_replaces_stale_content(self):
        self.output.write_text("stale\n", encoding="utf-8")

        success, _, diagnostic = self._run("fresh\n JOB CONCLUDED\n")

        self.assertTrue(success, diagnostic)

    def test_missing_native_output_fails(self):
        success, _, diagnostic = self._run(None)
        self.assertFalse(success)
        self.assertIn("did not write native output", diagnostic)
        self.assertIn(str(self.output.resolve()), diagnostic)

    def test_empty_native_output_fails(self):
        success, _, diagnostic = self._run("")
        self.assertFalse(success)
        self.assertIn("empty", diagnostic.lower())

    def test_exit_zero_without_completion_marker_fails(self):
        (success, _, diagnostic) = self._run("analysis stopped\n")
        self.assertFalse(success)
        self.assertIn("completion marker missing", diagnostic.lower())

    def test_abort_marker_fails_even_with_zero_exit(self):
        (success, _, diagnostic) = self._run(
            "JOB ABORTED\nJOB CONCLUDED\n"
        )
        self.assertFalse(success)
        self.assertIn("abort marker", diagnostic.lower())

    def test_fatal_error_line_fails(self):
        (success, _, diagnostic) = self._run(
            "ERROR -- invalid model\nJOB CONCLUDED\n"
        )
        self.assertFalse(success)
        self.assertIn("fatal error", diagnostic.lower())

    def test_orpsim_error_is_fatal_and_reported_without_completion(self):
        (success, _, diagnostic) = self._run(
            "WARNING(ORPSIM-0001): harmless\n"
            "ERROR(ORPSIM-9999): Synthetic library not found\n"
            "ERROR(ORPSIM-9998): second problem\n"
        )
        self.assertFalse(success)
        self.assertIn("fatal error", diagnostic.lower())
        self.assertIn("Synthetic library not found", diagnostic)
        self.assertNotIn("second problem", diagnostic)
        self.assertNotIn("completion marker missing", diagnostic)

    def test_long_fatal_error_line_is_truncated(self):
        (success, _, diagnostic) = self._run(
            "ERROR(ORPSIM-9999): " + "x" * 1000 + "\n"
        )
        self.assertFalse(success)
        self.assertLess(len(diagnostic), 300)

    def test_warning_and_zero_error_summary_are_not_fatal(self):
        (success, _, diagnostic) = self._run(
            "WARNING(ORPSIM-0001): synthetic warning\n"
            "ERROR COUNT = 0\nJOB CONCLUDED\n"
        )
        self.assertTrue(success, diagnostic)

    def test_nonzero_process_exit_fails(self):
        (success, _, diagnostic) = self._run(
            "JOB CONCLUDED\n",
            exit_code=7,
        )
        self.assertFalse(success)
        self.assertIn("exit code 7", diagnostic.lower())

    def test_utf16_native_output_is_decoded_by_byte_order_mark(self):
        for encoding in ("utf-16", "utf-16-be", "utf-8-sig"):
            with self.subTest(encoding=encoding):
                raw = "synthetic\nJOB CONCLUDED\n".encode(encoding)
                if encoding == "utf-16-be":
                    raw = b"\xfe\xff" + raw
                (success, _, diagnostic) = self._run(raw)
                self.assertTrue(success, diagnostic)

    def test_undecodable_native_output_is_reported_distinctly(self):
        (success, _, diagnostic) = self._run(b"\xff\xfe\x41")
        self.assertFalse(success)
        self.assertIn("Could not decode", diagnostic)
        self.assertNotIn("marker missing", diagnostic)

    def test_invalid_utf8_stdout_does_not_break_a_successful_run(self):
        result = self._run("JOB CONCLUDED\n", stdout_hex="ff")
        self.assertEqual(result, (True, "", ""))

    def test_timeout_returns_failure_without_deleting_native_output(self):
        self.output.write_text(
            "partial native output\n",
            encoding="utf-8",
        )

        success, _, diagnostic = self._run(timeout=1, sleep=60)

        self.assertFalse(success)
        self.assertEqual(diagnostic, "Simulation timed out after 1s")
        self.assertEqual(
            self.output.read_text(encoding="utf-8"),
            "partial native output\n",
        )

    def test_timeout_kills_the_whole_process_tree_promptly(self):
        heartbeat = self.stub_dir / "heartbeat.txt"
        timeout = 3

        started = time.perf_counter()
        success, _, diagnostic = self._run(
            timeout=timeout,
            sleep=60,
            heartbeat=str(heartbeat),
        )
        elapsed = time.perf_counter() - started

        self.assertFalse(success)
        self.assertIn("timed out", diagnostic)
        self.assertLess(elapsed, timeout + 5)
        self.assertTrue(heartbeat.exists(), "grandchild never started")
        time.sleep(0.3)
        last_beat = heartbeat.stat().st_mtime_ns
        time.sleep(0.5)
        self.assertEqual(
            heartbeat.stat().st_mtime_ns,
            last_beat,
            "grandchild survived the timeout",
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
        with patch(
            "spice_simulator.subprocess.Popen",
            side_effect=OSError("launch blocked"),
        ):
            success, _, diagnostic = self.backend.run(
                self.deck,
                timeout=120,
            )

        self.assertFalse(success)
        self.assertIn("Could not launch PSpice", diagnostic)
        self.assertIn("launch blocked", diagnostic)

    def test_native_output_stat_errors_produce_cli_failure_json(self):
        (self.stub_dir / "stub.json").write_text(
            json.dumps({"out_hex": b"JOB CONCLUDED\n".hex()}),
            encoding="utf-8",
        )
        for stage in ("before", "after"):
            with self.subTest(stage=stage):
                error = PermissionError(13, "Access denied", str(self.output))
                signatures = [error] if stage == "before" else [None, error]
                stdout = io.StringIO()
                stderr = io.StringIO()
                with (
                    patch(
                        "spice_simulator._file_signature",
                        side_effect=signatures,
                    ),
                    patch(
                        "run_external_deck.select_backend",
                        return_value=self.backend,
                    ),
                    redirect_stdout(stdout),
                    redirect_stderr(stderr),
                ):
                    code = run_external_deck.main([
                        str(self.deck), "--simulator", "pspice",
                    ])

                self.assertEqual(code, 1)
                result = json.loads(stdout.getvalue())
                self.assertFalse(result["success"])
                self.assertIn(str(self.output.resolve()), result["note"])
                self.assertIn("Access denied", result["note"])
                self.assertIn(result["note"], stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())

    def test_unreadable_native_output_returns_actionable_failure(self):
        with patch.object(
            spice_simulator.Path,
            "read_bytes",
            side_effect=OSError("read blocked"),
        ):
            success, _, diagnostic = self._run("JOB CONCLUDED\n")

        self.assertFalse(success)
        self.assertIn("Could not read PSpice native output", diagnostic)
        self.assertIn("read blocked", diagnostic)

    def test_windows_batch_script_executable_is_rejected(self):
        for name in ("pspice.bat", "PSPICE.CMD"):
            with self.subTest(name=name):
                with (
                    patch.object(
                        self.backend,
                        "find",
                        return_value=f"C:/tools/{name}",
                    ),
                    patch("spice_simulator._on_windows", return_value=True),
                    patch("spice_simulator.subprocess.Popen") as popen,
                ):
                    success, _, diagnostic = self.backend.run(
                        self.deck,
                        timeout=120,
                    )

                self.assertFalse(success)
                self.assertIn("native program", diagnostic)
                self.assertIn(".bat/.cmd", diagnostic)
                popen.assert_not_called()

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
