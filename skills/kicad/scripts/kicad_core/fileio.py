"""Atomic text writes shared by the scripts that rewrite user files."""

from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path


def atomic_write_text(path, text: str, newline: str | None = None) -> None:
    """Write UTF-8 text to path (symlinks resolved) via a temp file and os.replace.

    *newline* is passed to the file object ("" keeps the text's line endings as given)."""
    target = Path(path).resolve()
    # A new target gets 0o666 so the kernel applies the umask; an existing one is rewritten
    # through a private temp until copymode gives it the old mode
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_BINARY", 0))
    mode = 0o600 if target.exists() else 0o666
    while True:
        tmp = str(target.parent / f"{target.name}.{secrets.token_hex(6)}.tmp")
        try:
            fd = os.open(tmp, flags, mode)
            break
        except FileExistsError:
            continue
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
            f.write(text)
        if target.exists():
            shutil.copymode(target, tmp)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
