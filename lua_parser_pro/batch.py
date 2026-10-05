"""Read Lua files from disk and check many of them at once.

Lua source is bytes. ``read_source`` decodes it as UTF-8 by default; with
``encoding="auto"`` a file that is not valid UTF-8 is decoded as Latin-1, which
maps every byte to one character and lets the lexer return the exact bytes of
each string literal.
"""
from __future__ import annotations

import gc
import os
import re
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .model import LuaSyntaxError
from .parser import Parser

AUTO = "auto"
_FALLBACK = "latin-1"
_NEWLINES = re.compile(r"\r\n|\n\r|\r|\n")


def count_lines(text: str) -> int:
    """Lines of ``text`` as Lua counts them; a final newline does not start another line."""
    lines = sum(1 for _ in _NEWLINES.finditer(text))
    return lines if not text or text[-1] in "\r\n" else lines + 1


def read_source(path: str | os.PathLike[str], encoding: str = "utf-8", *,
                limit: int | None = None) -> tuple[str, str]:
    """Return ``(text, encoding_used)``, keeping the original line endings.

    ``limit`` bounds the number of code points read; one more is read so that
    the caller can detect an oversized source.
    """
    count = -1 if limit is None else limit + 1
    first = "utf-8" if encoding == AUTO else encoding
    try:
        with open(path, "r", encoding=first, newline="") as stream:
            return stream.read(count), first
    except UnicodeDecodeError:
        if encoding != AUTO:
            raise
    with open(path, "r", encoding=_FALLBACK, newline="") as stream:
        return stream.read(count), _FALLBACK


def decode_source(data: bytes, encoding: str = "utf-8") -> tuple[str, str]:
    """Decode bytes already in memory with the same rules as :func:`read_source`."""
    if encoding != AUTO:
        return data.decode(encoding), encoding
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode(_FALLBACK), _FALLBACK


@dataclass(frozen=True, slots=True)
class FileReport:
    """Outcome of checking one file. ``error`` is ``None`` when the syntax is valid."""

    path: str
    ok: bool
    size: int = 0
    lines: int = 0          # Lines of the file; a final newline does not start another one.
    tokens: int = 0         # Tokens without comments; 0 when the syntax is invalid.
    seconds: float = 0.0
    encoding: str = "utf-8"
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def find_lua_files(root: str | os.PathLike[str]) -> list[Path]:
    """Every ``*.lua`` file under ``root`` (case-insensitive), sorted by path."""
    found: list[Path] = []
    for directory, names, files in os.walk(root):
        names.sort(key=str.lower)
        for name in files:
            if name.lower().endswith(".lua"):
                found.append(Path(directory, name))
    found.sort(key=lambda path: str(path).lower())
    return found


def check_file(path: str | os.PathLike[str], *, encoding: str = AUTO, max_depth: int = 150,
               max_tokens: int = 1_000_000, max_source_length: int = 10_000_000) -> FileReport:
    """Parse one file and report the result instead of raising."""
    name = os.fspath(path)
    started = time.perf_counter()
    size = 0
    used = encoding
    try:
        size = os.path.getsize(name)
        text, used = read_source(name, encoding, limit=max_source_length)
    except (OSError, UnicodeError, LookupError) as error:
        return FileReport(name, False, size, seconds=time.perf_counter() - started, encoding=used,
                          error={"code": "UNREADABLE", "message": str(error), "filename": name,
                                 "line": 0, "column": 0, "offset": 0, "end_offset": 0,
                                 "text": f"{name}: {error}"})
    try:
        parser = Parser(text, filename=name, comments=False, max_depth=max_depth,
                        max_tokens=max_tokens, max_source_length=max_source_length,
                        encoding=used)
        parser.parse()
    except LuaSyntaxError as error:
        report = dict(error.to_dict(), text=str(error))
        return FileReport(name, False, size, count_lines(text), 0,
                          time.perf_counter() - started, used, report)
    end = parser.tokens[-1].span.end
    return FileReport(name, True, size, end.line if end.column > 1 else end.line - 1,
                      len(parser.tokens) - 1, time.perf_counter() - started, used)


def _check_chunk(paths: Sequence[str], options: dict[str, Any]) -> list[FileReport]:
    reports = [check_file(path, **options) for path in paths]
    gc.collect()  # Diagnostics hold tracebacks; workers run with the collector off.
    return reports


def _start_worker() -> None:
    gc.disable()


def default_jobs() -> int:
    return max(1, min(os.cpu_count() or 1, 16))


def check_files(paths: Iterable[str | os.PathLike[str]], *, jobs: int | None = None,
                on_result: Callable[[FileReport], None] | None = None,
                should_stop: Callable[[], bool] | None = None,
                **options: Any) -> list[FileReport]:
    """Check many files, in parallel when it pays off; reports come back sorted by path.

    ``on_result`` is called in the calling thread as each report arrives.
    ``should_stop`` is polled between files; remaining files are skipped once
    it returns true. ``options`` are passed to :func:`check_file`.
    """
    names = [os.fspath(path) for path in paths]
    reports: list[FileReport] = []

    def deliver(batch: Iterable[FileReport]) -> None:
        for report in batch:
            reports.append(report)
            if on_result is not None:
                on_result(report)

    workers = default_jobs() if jobs is None else max(1, jobs)
    workers = min(workers, max(1, len(names) // 4))
    remaining = names
    if workers > 1:
        remaining = _check_in_processes(names, workers, options, deliver, should_stop)
    for name in remaining:
        if should_stop is not None and should_stop():
            break
        deliver([check_file(name, **options)])
    reports.sort(key=lambda report: report.path.lower())
    return reports


def _check_in_processes(names: list[str], workers: int, options: dict[str, Any],
                        deliver: Callable[[Iterable[FileReport]], None],
                        should_stop: Callable[[], bool] | None) -> list[str]:
    """Run chunks in worker processes; return the files that still need checking."""
    try:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        from concurrent.futures.process import BrokenProcessPool
    except ImportError:  # pragma: no cover - platforms without multiprocessing
        return names
    size = max(1, min(16, len(names) // (workers * 4) or 1))
    chunks = [names[index:index + size] for index in range(0, len(names), size)]
    done: set[int] = set()
    try:
        with ProcessPoolExecutor(max_workers=workers, initializer=_start_worker) as pool:
            futures = {pool.submit(_check_chunk, chunk, options): index
                       for index, chunk in enumerate(chunks)}
            for future in as_completed(futures):
                deliver(future.result())
                done.add(futures[future])
                if should_stop is not None and should_stop():
                    for pending in futures:
                        pending.cancel()
                    return []
    except (OSError, BrokenProcessPool, RuntimeError, ImportError):
        # No process pool here (restricted environment): finish in this process.
        pass
    return [name for index, chunk in enumerate(chunks) if index not in done for name in chunk]
