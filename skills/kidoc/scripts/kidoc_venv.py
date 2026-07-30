"""Virtual environment manager for kidoc report generation.

Creates and manages a project-local venv at ``reports/.venv/`` with the
dependencies needed for PDF/DOCX generation.  Never touches the user's
global or user Python environment.

Zero external dependencies — Python stdlib only.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys


REQUIREMENTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 'requirements.txt')


def venv_dir(project_dir: str) -> str:
    """Return the path to the venv directory."""
    return os.path.join(project_dir, 'reports', '.venv')


def venv_python(project_dir: str) -> str:
    """Return the path to the venv Python executable."""
    vd = venv_dir(project_dir)
    if platform.system() == 'Windows':
        return os.path.join(vd, 'Scripts', 'python.exe')
    return os.path.join(vd, 'bin', 'python')


def venv_pip(project_dir: str) -> str:
    """Return the path to the venv pip executable."""
    vd = venv_dir(project_dir)
    if platform.system() == 'Windows':
        return os.path.join(vd, 'Scripts', 'pip.exe')
    return os.path.join(vd, 'bin', 'pip')


def is_venv_ready(project_dir: str) -> bool:
    """Check if the venv exists and has required packages."""
    py = venv_python(project_dir)
    if not os.path.isfile(py):
        return False
    # Quick check: try importing the key packages
    try:
        result = subprocess.run(
            [py, '-c', 'import reportlab; import docx; import odf; import PIL'],
            capture_output=True, timeout=10)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def ensure_venv(project_dir: str, quiet: bool = False) -> str:
    """Ensure the venv exists and has required packages.

    Creates the venv and installs dependencies if needed.
    Returns the path to the venv Python executable.
    """
    py = venv_python(project_dir)

    if is_venv_ready(project_dir):
        return py

    vd = venv_dir(project_dir)
    _log = (lambda msg: None) if quiet else (lambda msg: print(msg, file=sys.stderr))

    # Create venv if it doesn't exist
    if not os.path.isfile(py):
        _log(f"Creating venv at {vd}")
        os.makedirs(os.path.dirname(vd), exist_ok=True)
        subprocess.run([sys.executable, '-m', 'venv', vd], check=True)

    # Install/upgrade dependencies
    pip = venv_pip(project_dir)
    if not os.path.isfile(pip):
        # Fallback: use venv python -m pip
        pip_cmd = [py, '-m', 'pip']
    else:
        pip_cmd = [pip]

    _log("Installing report generation dependencies...")
    cmd = pip_cmd + ['install', '-q', '-r', REQUIREMENTS_FILE]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        _log(f"pip install failed: {result.stderr}")
        raise RuntimeError(f"Failed to install dependencies: {result.stderr}")

    _log("Venv ready.")
    return py
