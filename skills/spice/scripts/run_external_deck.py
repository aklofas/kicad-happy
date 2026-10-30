#!/usr/bin/env python3
"""Run a complete external SPICE deck with an explicitly selected simulator."""

import argparse
import json
from pathlib import Path
import sys
import time

from spice_simulator import PspiceBackend, detect_simulator


SIMULATORS = ("pspice", "ngspice", "ltspice", "xyce")


def select_backend(simulator: str):
    if simulator == "pspice":
        backend = PspiceBackend()
        return backend if backend.find() else None
    return detect_simulator(simulator)


def native_output_for(deck: Path, simulator: str) -> Path | None:
    if simulator == "pspice":
        return deck.with_suffix(".out")
    return None


def _build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Run a complete external SPICE deck without generating "
            "measurements"
        )
    )
    parser.add_argument("deck", type=Path, help="Existing external .cir deck")
    parser.add_argument(
        "--simulator",
        required=True,
        choices=SIMULATORS,
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        help="Timeout in seconds (default: 5)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write result JSON to this path",
    )
    return parser


def _result(simulator, success, deck, native_output, elapsed_s, note):
    return {
        "simulator": simulator,
        "success": success,
        "deck": str(deck),
        "native_output": (
            str(native_output) if native_output is not None else None
        ),
        "elapsed_s": round(elapsed_s, 3),
        "note": note,
    }


def _write_json(payload, output_path):
    if output_path:
        with Path(output_path).open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        return
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    deck = args.deck.resolve()
    if not deck.is_file():
        parser.error(f"deck is not a file: {deck}")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")

    native_output = native_output_for(deck, args.simulator)
    backend = select_backend(args.simulator)
    if backend is None:
        if args.simulator == "pspice":
            diagnostic = (
                "PSpice executable not found; set PSPICE_PATH or add "
                "pspice to PATH"
            )
        else:
            diagnostic = f"{args.simulator} executable not found"
        payload = _result(
            args.simulator,
            False,
            deck,
            native_output,
            0.0,
            diagnostic,
        )
        _write_json(payload, args.output)
        print(diagnostic, file=sys.stderr)
        return 1

    started = time.perf_counter()
    success, _stdout, diagnostic = backend.run(
        str(deck),
        timeout=args.timeout,
    )
    elapsed_s = time.perf_counter() - started
    if success and args.simulator == "pspice":
        note = "PSpice reported JOB CONCLUDED"
    elif success:
        note = f"{backend.name} exited successfully"
    else:
        note = (
            diagnostic
            or f"{backend.name} did not report successful completion"
        )

    payload = _result(
        args.simulator,
        success,
        deck,
        native_output,
        elapsed_s,
        note,
    )
    _write_json(payload, args.output)
    if not success:
        print(note, file=sys.stderr)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
