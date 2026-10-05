"""Command-line syntax validation, JSON and HTML export, and launcher of the Studio."""
from __future__ import annotations

import argparse
import gc
import io
import os
import sys
import time
from collections.abc import Sequence
from typing import Any

from . import __version__
from .analysis import outline, statistics
from .ast import iter_json, to_dict
from .batch import AUTO, check_files, decode_source, find_lua_files, read_source
from .lexer import Lexer
from .model import LuaSyntaxError
from .parser import Parser, parse


def _positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a positive integer") from None
    if not 0 < number < sys.maxsize:
        raise argparse.ArgumentTypeError(f"expected an integer between 1 and {sys.maxsize - 1}")
    return number


def _port(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected a port number") from None
    if not 0 <= number <= 65535:
        raise argparse.ArgumentTypeError("expected a port between 0 and 65535")
    return number


def _arguments() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lua-parser",
        description="Parse Lua 5.4 source into JSON without executing it.",
    )
    parser.add_argument("file", nargs="?",
                        help="Lua source file; - for standard input; a folder with --check or --gui")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--check", action="store_true",
                        help="check syntax; write no JSON (a folder checks every .lua file in it)")
    output.add_argument("--tokens", action="store_true", help="export lexical tokens and comments")
    output.add_argument("--outline", action="store_true",
                        help="export the functions, tables and module-level variables")
    output.add_argument("--stats", action="store_true", help="export counts describing the source")
    output.add_argument("--html", action="store_true",
                        help="export the decision diagrams of every function as one standalone "
                             "HTML page (redirect it to a .html file)")
    output.add_argument("--gui", "--studio", dest="gui", action="store_true",
                        help="open the Studio, a local interface in the web browser")
    parser.add_argument("--compact", action="store_true", help="write compact JSON")
    parser.add_argument("--no-comments", action="store_true", help="omit collected comments")
    parser.add_argument("--max-depth", type=_positive_integer, default=150,
                        help="maximum parsing/tree depth (default: 150)")
    parser.add_argument("--max-tokens", type=_positive_integer, default=1_000_000,
                        help="maximum tokens and comments (default: 1000000)")
    parser.add_argument("--max-source-length", type=_positive_integer, default=10_000_000,
                        help="maximum source length in code points (default: 10000000)")
    parser.add_argument("--encoding", default=None, metavar="NAME",
                        help="source encoding, or 'auto' for UTF-8 with a Latin-1 fallback "
                             "(default: utf-8 for a file, auto for a folder)")
    parser.add_argument("--jobs", type=_positive_integer, default=None, metavar="N",
                        help="worker processes used to check a folder (default: one per core, at most 16)")
    parser.add_argument("--port", type=_port, default=None,
                        help="port of the Studio (default: 8642, or the next free one)")
    parser.add_argument("--no-browser", action="store_true",
                        help="start the Studio without opening the web browser")
    return parser


def _read_source(filename: str, limit: int, encoding: str = "utf-8") -> tuple[str, str]:
    """Bound decoding before parsing, preserving Lua's original line endings."""
    if filename != "-":
        return read_source(filename, encoding, limit=limit)
    buffer = getattr(sys.stdin, "buffer", None)
    if buffer is None:
        # Support embedders/tests whose stdin is a StringIO or other text stream.
        return sys.stdin.read(limit + 1), "utf-8"
    if encoding == AUTO:
        # A code point is at most four bytes long.
        return decode_source(buffer.read(4 * limit + 4), AUTO)
    stream = io.TextIOWrapper(buffer, encoding=encoding, newline="")
    try:
        return stream.read(limit + 1), encoding
    finally:
        stream.detach()  # Do not close the process's standard input.


def _write_json(data: Any, compact: bool) -> None:
    write = sys.stdout.write
    for chunk in iter_json(data, indent=None if compact else 2):
        write(chunk)
    write("\n")


def _check_folder(args: argparse.Namespace) -> int:
    if not args.check:
        print(f"lua-parser: {args.file}: is a folder; use --check to check its .lua files "
              "or --gui to browse it", file=sys.stderr)
        return 2
    started = time.perf_counter()
    files = find_lua_files(args.file)
    reports = check_files(files, jobs=args.jobs, encoding=args.encoding or AUTO,
                          max_depth=args.max_depth, max_tokens=args.max_tokens,
                          max_source_length=args.max_source_length)
    failures = [report for report in reports if not report.ok]
    for report in failures:
        assert report.error is not None
        print(report.error["text"], file=sys.stderr)
    elapsed = time.perf_counter() - started
    print(f"lua-parser: {len(reports)} .lua file(s) checked in {elapsed:.1f} s: "
          f"{len(reports) - len(failures)} valid, {len(failures)} with errors", file=sys.stderr)
    codes = {report.error["code"] for report in failures if report.error is not None}
    if codes - {"UNREADABLE"}:
        return 1
    return 2 if codes else 0


def _run(args: argparse.Namespace) -> int:
    filename = "<stdin>" if args.file == "-" else args.file
    try:
        if args.file != "-" and os.path.isdir(args.file):
            return _check_folder(args)
        source, encoding = _read_source(args.file, args.max_source_length,
                                        args.encoding or "utf-8")
        limits = {"filename": filename, "comments": not args.no_comments,
                  "max_tokens": args.max_tokens, "max_source_length": args.max_source_length,
                  "encoding": encoding}
        if args.tokens:
            lexer = Lexer(source, **limits)
            tokens = lexer.tokenize()
            result: Any = {"tokens": to_dict(tokens), "comments": to_dict(lexer.comments)}
        elif args.html:
            from .studio.report import build_report  # Imported on demand, like the Studio.
            page = build_report(source, filename, max_depth=args.max_depth,
                                max_tokens=args.max_tokens,
                                max_source_length=args.max_source_length, encoding=encoding)
            sys.stdout.write(page)
            return 0
        elif args.outline or args.stats:
            parser = Parser(source, max_depth=args.max_depth, **limits)
            tree = parser.parse()
            if args.outline:
                result = [symbol.to_dict() for symbol in outline(tree)]
            else:
                result = statistics(tree, parser.tokens)
        else:
            tree = parse(source, max_depth=args.max_depth, **limits)
            if args.check:
                return 0
            result = tree.to_dict()
        _write_json(result, args.compact)
        return 0
    except LuaSyntaxError as error:
        print(str(error), file=sys.stderr)
        return 1
    except BrokenPipeError:
        # The reader went away (for instance `| head`): not an error of the analysis.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError, AttributeError):
            pass
        return 0
    except (OSError, UnicodeError, LookupError) as error:
        print(f"lua-parser: {filename}: {error}", file=sys.stderr)
        return 2


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _arguments()
    args = arguments.parse_args(argv)
    if args.gui:
        from .studio import serve  # Imported on demand: the Studio is optional.
        return serve(args.file, port=args.port, open_browser=not args.no_browser)
    if args.file is None:
        arguments.error("the following arguments are required: file")
    # A command runs once and builds no reference cycle worth collecting.
    collecting = gc.isenabled()
    gc.disable()
    try:
        return _run(args)
    finally:
        if collecting:
            gc.enable()


if __name__ == "__main__":
    raise SystemExit(main())
