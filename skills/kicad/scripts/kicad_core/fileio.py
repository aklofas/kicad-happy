"""Atomic text writes shared by the scripts that rewrite user files."""

from __future__ import annotations

import os
import secrets
import shutil
from pathlib import Path


def atomic_write_text(path, text: str, newline: str | None = None, *,
                      follow_symlinks: bool = True) -> None:
    """Write UTF-8 text to path via a temp file and os.replace.

    A symlink at *path* is resolved and its target rewritten, unless *follow_symlinks* is
    false: then the link itself is replaced by a regular file and its target is never touched.
    *newline* is passed to the file object ("" keeps the text's line endings as given)."""
    target = Path(path).resolve() if follow_symlinks else Path(os.path.abspath(path))
    existing = target.exists()
    if not follow_symlinks:
        if existing and not target.resolve().is_file():
            # /dev/stdout, /dev/null, a FIFO: replacing it would be wrong, so write into it
            with open(target, "w", encoding="utf-8", newline=newline) as f:
                f.write(text)
            return
        if target.is_symlink():
            existing = False    # the link's mode and target are not the new file's
    # A new target gets 0o666 so the kernel applies the umask; an existing one is rewritten
    # through a private temp until copymode gives it the old mode
    flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
             | getattr(os, "O_BINARY", 0))
    mode = 0o600 if existing else 0o666
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
        if existing:
            shutil.copymode(target, tmp)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
