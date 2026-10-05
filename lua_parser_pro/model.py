"""Shared, immutable source locations and diagnostics (Python 3.10+)."""
from __future__ import annotations

import gc
import re
from typing import Any, NamedTuple

_NEWLINES = re.compile(r"\r\n|\n\r|\r|\n")


class gc_paused:
    """Suspend the cyclic garbage collector while building tokens or trees.

    Analysis allocates millions of small immutable objects and no reference
    cycle; the collector would only rescan them. Its previous state is restored
    on exit, including when a diagnostic is raised.
    """

    __slots__ = ("_was_enabled",)

    def __enter__(self) -> None:
        self._was_enabled = gc.isenabled()
        gc.disable()

    def __exit__(self, *exc_info: object) -> None:
        if self._was_enabled:
            gc.enable()


class Position(NamedTuple):
    """A place in the source: zero-based code-point offset, one-based line and column."""

    offset: int
    line: int
    column: int


class Span(NamedTuple):
    """A half-open source range: ``source[start.offset:end.offset]``."""

    start: Position
    end: Position


class Token(NamedTuple):
    """A lexeme. ``value`` is ``bytes`` for strings and ``str`` otherwise."""

    kind: str
    value: str | bytes
    raw: str
    span: Span


class LuaSyntaxError(Exception):
    """A machine-readable diagnostic plus a human-readable source excerpt."""

    def __init__(self, message: str, span: Span, source: str = "",
                 filename: str = "<input>", code: str = "SYNTAX_ERROR") -> None:
        self.message = message
        self.span = span
        self.source = source
        self.filename = filename
        self.code = code
        super().__init__(message)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "filename": self.filename,
                "line": self.span.start.line, "column": self.span.start.column,
                "offset": self.span.start.offset,
                "end_offset": self.span.end.offset}

    def __str__(self) -> str:
        p = self.span.start
        heading = f"{self.filename}:{p.line}:{p.column}: {self.code}: {self.message}"
        # Lua treats CRLF and LFCR as one newline, and lone CR/LF as newlines.
        lines = _NEWLINES.split(self.source)
        if not (0 < p.line <= len(lines)):
            return heading
        line = lines[p.line - 1]
        left = max(0, p.column - 1 - 80)
        excerpt = line[left:left + 160].expandtabs(4)
        prefix = line[left:p.column - 1].expandtabs(4)
        return f"{heading}\n  {excerpt}\n  {' ' * len(prefix)}^"
