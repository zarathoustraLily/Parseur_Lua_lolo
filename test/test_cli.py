"""CLI regressions through the public module entry point."""
from __future__ import annotations

import http.client
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def invoke(self, *arguments: str, source: str | bytes = "") -> subprocess.CompletedProcess:
        payload = source.encode("utf-8") if isinstance(source, str) else source
        return subprocess.run(
            [sys.executable, "-m", "lua_parser_pro", *arguments], input=payload,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT, timeout=15,
        )

    def test_stdin_ast_preserves_bytes_and_exact_numeric_lexeme(self):
        process = self.invoke("-", source='return "\\255\\0", 0x1.fp+3')
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["type"], "Chunk")
        arguments = result["body"][0]["arguments"]
        self.assertEqual(arguments[0]["value"], [255, 0])
        self.assertEqual(arguments[1]["raw"], "0x1.fp+3")

    def test_check_reads_utf8_file_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "exemple.lua"
            path.write_bytes('return "été"\r\n'.encode("utf-8"))
            process = self.invoke(str(path), "--check")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout, b"")
        self.assertEqual(process.stderr, b"")

    def test_tokens_allow_lexically_valid_non_program(self):
        process = self.invoke("-", "--tokens", source='-- note\n+ "\\255"')
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(len(result["comments"]), 1)
        string_token = next(t for t in result["tokens"] if t["raw"] == '"\\255"')
        self.assertEqual(string_token["value"], [255])

    def test_no_comments_in_both_modes(self):
        for options in [("--no-comments",), ("--tokens", "--no-comments")]:
            with self.subTest(options=options):
                process = self.invoke("-", *options, source="-- note\nreturn 1")
                self.assertEqual(process.returncode, 0, process.stderr)
                self.assertEqual(json.loads(process.stdout)["comments"], [])

    def test_compact_is_single_line_json(self):
        process = self.invoke("-", "--compact", source="return 1")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(len(process.stdout.splitlines()), 1)
        self.assertEqual(json.loads(process.stdout)["type"], "Chunk")

    def test_syntax_error_has_diagnostic_and_exit_one(self):
        process = self.invoke("-", "--check", source="local x = 1\r\nreturn )")
        self.assertEqual(process.returncode, 1)
        self.assertEqual(process.stdout, b"")
        self.assertIn(b"<stdin>:2:", process.stderr)
        self.assertIn(b"^", process.stderr)
        self.assertNotIn(b"Traceback", process.stderr)

    def test_missing_file_returns_exit_two(self):
        with tempfile.TemporaryDirectory() as directory:
            process = self.invoke(str(Path(directory) / "missing.lua"))
        self.assertEqual(process.returncode, 2)
        self.assertEqual(process.stdout, b"")
        self.assertNotIn(b"Traceback", process.stderr)

    def test_invalid_utf8_returns_exit_two(self):
        process = self.invoke("-", source=b'return "\xff"')
        self.assertEqual(process.returncode, 2)
        self.assertNotIn(b"Traceback", process.stderr)

    def test_bad_options_return_exit_two(self):
        for options in [("--tokens", "--check"), ("--max-depth", "0"),
                        ("--max-tokens", "-1"), ("--max-source-length", "text")]:
            with self.subTest(options=options):
                process = self.invoke("-", *options)
                self.assertEqual(process.returncode, 2)
                self.assertNotIn(b"Traceback", process.stderr)

    def test_configured_source_token_and_depth_limits(self):
        cases = [
            (("--max-source-length", "5"), "return 123456789"),
            (("--max-tokens", "2"), "return 1 + 2"),
            (("--max-depth", "5"), "return " + "(" * 20 + "1" + ")" * 20),
        ]
        for options, source in cases:
            with self.subTest(options=options):
                process = self.invoke("-", "--check", *options, source=source)
                self.assertEqual(process.returncode, 1, process.stderr)
                self.assertNotIn(b"Traceback", process.stderr)

    def test_text_only_stdin_is_supported_and_left_open(self):
        from lua_parser_pro.cli import main
        source = io.StringIO("return 1")
        with patch("sys.stdin", source), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["-", "--check"])
        self.assertEqual(code, 0)
        self.assertFalse(source.closed)

    def test_version_does_not_require_file(self):
        from lua_parser_pro import __version__
        process = self.invoke("--version")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn(__version__.encode(), process.stdout)

    def test_file_is_required_except_for_the_studio(self):
        process = self.invoke()
        self.assertEqual(process.returncode, 2)
        self.assertNotIn(b"Traceback", process.stderr)
        with tempfile.TemporaryDirectory() as directory:
            missing = self.invoke("--gui", "--no-browser", str(Path(directory) / "absent"))
        self.assertEqual(missing.returncode, 2)
        self.assertNotIn(b"Traceback", missing.stderr)

    def test_first_line_starting_with_hash_is_skipped(self):
        process = self.invoke("-", "--tokens", source="# usage: lua script.lua\nreturn 1")
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual(result["comments"][0]["raw"], "# usage: lua script.lua")
        self.assertEqual(result["tokens"][0]["span"]["start"]["line"], 2)
        self.assertEqual(self.invoke("-", "--check", source="x = 1\n#! later").returncode, 1)

    def test_encoding_option(self):
        source = b'return "\xe9"'
        process = self.invoke("-", "--compact", "--encoding", "latin-1", source=source)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["body"][0]["arguments"][0]["value"], [233])
        self.assertEqual(self.invoke("-", "--check", "--encoding", "auto", source=source).returncode, 0)
        utf8 = self.invoke("-", "--compact", "--encoding", "auto", source='return "\u00e9"')
        self.assertEqual(json.loads(utf8.stdout)["body"][0]["arguments"][0]["value"], [195, 169])
        unknown = self.invoke("-", "--check", "--encoding", "no-such-encoding", source="return 1")
        self.assertEqual(unknown.returncode, 2)
        self.assertNotIn(b"Traceback", unknown.stderr)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ancien.lua"
            path.write_bytes(source)
            self.assertEqual(self.invoke(str(path), "--check").returncode, 2)
            self.assertEqual(self.invoke(str(path), "--check", "--encoding", "auto").returncode, 0)
            self.assertEqual(self.invoke(str(path), "--check", "--encoding", "cp1252").returncode, 0)

    def test_check_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ok.lua").write_text("return 1\n", encoding="utf-8")
            (root / "sub").mkdir()
            (root / "sub" / "ancien.LUA").write_bytes(b'return "\xe9"\n')
            (root / "notes.txt").write_text("return )", encoding="utf-8")
            clean = self.invoke(str(root), "--check")
            self.assertEqual(clean.returncode, 0, clean.stderr)
            self.assertEqual(clean.stdout, b"")
            self.assertIn(b"2 .lua file(s) checked", clean.stderr)
            self.assertIn(b"2 valid, 0 with errors", clean.stderr)
            strict = self.invoke(str(root), "--check", "--encoding", "utf-8")
            self.assertEqual(strict.returncode, 2)
            self.assertIn(b"1 valid, 1 with errors", strict.stderr)
            (root / "sub" / "bad.lua").write_text("x = 1\nreturn )\n", encoding="utf-8")
            failing = self.invoke(str(root), "--check", "--jobs", "1")
            self.assertEqual(failing.returncode, 1)
            self.assertEqual(failing.stdout, b"")
            self.assertIn(b"bad.lua:2:8: SYNTAX_ERROR", failing.stderr)
            self.assertIn(b"2 valid, 1 with errors", failing.stderr)
            self.assertNotIn(b"Traceback", failing.stderr)
            without_mode = self.invoke(str(root))
            self.assertEqual(without_mode.returncode, 2)
            self.assertIn(b"--check", without_mode.stderr)
            (root / "vide").mkdir()
            self.assertEqual(self.invoke(str(root / "vide"), "--check").returncode, 0)

    def test_outline_and_stats(self):
        source = "local function f(a) return a end\nreturn { f = f }\n"
        outline = self.invoke("-", "--outline", source=source)
        self.assertEqual(outline.returncode, 0, outline.stderr)
        self.assertEqual([(symbol["name"], symbol["kind"]) for symbol in json.loads(outline.stdout)],
                         [("f", "function"), ("return", "table")])
        stats = self.invoke("-", "--stats", "--compact", source=source)
        self.assertEqual(len(stats.stdout.splitlines()), 1)
        counts = json.loads(stats.stdout)
        self.assertEqual((counts["lines"]["total"], counts["functions"]["total"], counts["tokens"]["total"]),
                         (2, 1, 15))
        self.assertEqual(self.invoke("-", "--outline", source="return )").returncode, 1)
        self.assertEqual(self.invoke("-", "--stats", "--tokens").returncode, 2)

    def test_deep_tree_is_exported(self):
        depth = 300
        source = "return " + "(" * depth + "1" + ")" * depth
        for options in (("--compact",), ()):
            with self.subTest(options=options):
                process = self.invoke("-", "--max-depth", "5000", *options, source=source)
                self.assertEqual(process.returncode, 0, process.stderr[-300:])
                self.assertEqual(process.stdout.count(b'"ParenthesizedExpression"'), depth)
        too_deep = "return " + "(" * 3000 + "1" + ")" * 3000
        process = self.invoke("-", "--check", "--max-depth", "5000", source=too_deep)
        self.assertEqual(process.returncode, 1)
        self.assertIn(b"DEPTH_LIMIT", process.stderr)
        self.assertNotIn(b"Traceback", process.stderr)

    def test_studio_serves_its_page_until_stopped(self):
        from lua_parser_pro.studio.server import free_port
        port = free_port()
        process = subprocess.Popen(
            [sys.executable, "-m", "lua_parser_pro", "--gui", "--no-browser", "--port", str(port)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT)
        try:
            deadline = time.monotonic() + 30
            while True:
                try:
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
                    connection.request("GET", "/")
                    response = connection.getresponse()
                    body = response.read()
                    connection.close()
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise
                    time.sleep(0.05)
            self.assertEqual(response.status, 200)
            self.assertIn(b"Studio du parseur Lua", body)
        finally:
            process.terminate()
            output, errors = process.communicate(timeout=15)
        self.assertIn(f"127.0.0.1:{port}".encode(), output)
        self.assertNotIn(b"Traceback", errors)

    def test_studio_reports_a_busy_port(self):
        with socket.socket() as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen(1)
            port = busy.getsockname()[1]
            process = self.invoke("--gui", "--no-browser", "--port", str(port))
        self.assertEqual(process.returncode, 2)
        self.assertIn(str(port).encode(), process.stderr)
        self.assertNotIn(b"Traceback", process.stderr)


if __name__ == "__main__":
    unittest.main()
