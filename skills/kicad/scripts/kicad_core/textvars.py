"""KiCad text variable expansion (``${NAME}``), as KiCad 10 expands field text.

A port of ``ExpandTextVars`` / ``ResolveTextVars`` (common/common.cpp): nested ``${}`` expand
innermost first; ``\\${…}`` and ``\\@{…}`` are escapes, kept literal and shown as ``${…}`` /
``@{…}``; a token the resolver does not know stays ``${TOKEN}``; ``${}`` is dropped;
``ERC_*`` / ``DRC_*`` tokens are dropped outside ERC/DRC; ``@{…}`` math has its variables
expanded but is not evaluated.  Expansion repeats while text variables remain, up to KiCad's
default recursion depth of 6.
"""
from __future__ import annotations

from typing import Callable

MAX_DEPTH = 6

_ESC_DOLLAR = "<<<ESC_DOLLAR:"
_ESC_AT = "<<<ESC_AT:"
_ERC_DRC = ("ERC_WARNING", "ERC_ERROR", "DRC_WARNING", "DRC_ERROR")


def _copy_marker(src: str, i: int, marker: str, out: list) -> int:
    """Copy an escape marker and its contents up to the matching ``}``; return the next index."""
    out.append(marker)
    i += len(marker)
    count = 1
    while i < len(src) and count > 0:
        c = src[i]
        if c == "{":
            count += 1
        elif c == "}":
            count -= 1
        out.append(c)
        i += 1
    return i


def _has_vars(text: str) -> bool:
    return "${" in text or "@{" in text


def _expand_once(src: str, resolve: Callable[[str], str | None], depth: int = 0) -> str:
    """One pass of KiCad's ExpandTextVars."""
    out: list = []
    n = len(src)
    i = 0
    while i < n:
        if src.startswith(_ESC_DOLLAR, i):
            i = _copy_marker(src, i, _ESC_DOLLAR, out)
            continue
        if src.startswith(_ESC_AT, i):
            i = _copy_marker(src, i, _ESC_AT, out)
            continue
        c = src[i]
        if c == "\\" and i + 2 < n and src[i + 1] in "$@" and src[i + 2] == "{":
            out.append(_ESC_DOLLAR if src[i + 1] == "$" else _ESC_AT)
            j = i + 3
            count = 1
            while j < n and count > 0:
                if src[j] == "{":
                    count += 1
                elif src[j] == "}":
                    count -= 1
                out.append(src[j])
                j += 1
            i = j
            continue
        if c in "$@" and i + 1 < n and src[i + 1] == "{":
            is_math = c == "@"
            token: list = []
            count = 1
            j = i + 2
            while j < n:
                if src.startswith(_ESC_DOLLAR, j):
                    j = _copy_marker(src, j, _ESC_DOLLAR, token)
                    continue
                if src.startswith(_ESC_AT, j):
                    j = _copy_marker(src, j, _ESC_AT, token)
                    continue
                ch = src[j]
                if ch == "{":
                    count += 1
                elif ch == "}":
                    count -= 1
                    if count == 0:
                        break
                token.append(ch)
                j += 1
            i = j + 1
            tok = "".join(token)
            if not tok:
                continue
            if _has_vars(tok) and depth < MAX_DEPTH:
                tok = _expand_once(tok, resolve, depth + 1)
            if is_math:
                out.append("@{" + tok + "}")
            elif tok.startswith(_ERC_DRC):
                pass
            else:
                value = resolve(tok)
                out.append(value if value is not None else "${" + tok + "}")
            continue
        out.append(c)
        i += 1
    return "".join(out)


def resolve_text_vars(text: str, resolve_at: Callable[[str, int], str | None],
                      depth: int = 0) -> str:
    """KiCad's multi-pass ResolveTextVars.  *resolve_at(token, depth)* receives the pass's
    depth so a resolver that expands further text can carry it on; the result keeps the
    escape markers (see unescape_text_vars)."""
    while _has_vars(text):
        depth += 1
        if depth > MAX_DEPTH:
            break
        d = depth
        text = _expand_once(text, lambda tok: resolve_at(tok, d))
    return text


def unescape_text_vars(text: str) -> str:
    """Turn escape markers back into literal ``${`` / ``@{`` (done once, on the shown text)."""
    return text.replace(_ESC_DOLLAR, "${").replace(_ESC_AT, "@{")


def expand_text_vars(text: str, resolve: Callable[[str], str | None]) -> str:
    """*text* with every ``${TOKEN}`` that *resolve* knows replaced; unknown tokens stay as
    written and ``\\${`` is a literal ``${``."""
    if _has_vars(text):
        text = resolve_text_vars(text, lambda tok, _depth: resolve(tok))
    return unescape_text_vars(text)
