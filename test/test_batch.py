"""Reading Lua files from disk and checking a whole folder."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from lua_parser_pro import FileReport, check_file, check_files, find_lua_files, read_source
from lua_parser_pro.batch import AUTO, count_lines, decode_source, default_jobs


class FolderCase(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def write(self, name: str, data: bytes | str) -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)
        return path


class ReadingTests(FolderCase):
    def test_utf8_keeps_line_endings(self):
        path = self.write("a.lua", 'return "été"\r\nx = 1\r')
        self.assertEqual(read_source(path), ('return "été"\r\nx = 1\r', "utf-8"))

    def test_auto_falls_back_to_latin_1_byte_for_byte(self):
        path = self.write("b.lua", b'return "\xe9\xff"\n')
        text, encoding = read_source(path, AUTO)
        self.assertEqual((text, encoding), ('return "éÿ"\n', "latin-1"))
        with self.assertRaises(UnicodeDecodeError):
            read_source(path)
        self.assertEqual(read_source(self.write("c.lua", "return 1"), AUTO)[1], "utf-8")

    def test_limit_reads_one_code_point_more(self):
        path = self.write("d.lua", "0123456789")
        self.assertEqual(read_source(path, limit=4)[0], "01234")
        self.assertEqual(read_source(path, limit=50)[0], "0123456789")

    def test_decode_source_follows_the_same_rules(self):
        self.assertEqual(decode_source(b"x = 1"), ("x = 1", "utf-8"))
        self.assertEqual(decode_source(b"\xe9", AUTO), ("é", "latin-1"))
        with self.assertRaises(UnicodeDecodeError):
            decode_source(b"\xe9")

    def test_count_lines(self):
        for text, expected in (("", 0), ("a", 1), ("a\n", 1), ("a\nb", 2), ("a\r\nb\r\n", 2),
                               ("\n", 1), ("a\rb\n\rc", 3)):
            with self.subTest(text=text):
                self.assertEqual(count_lines(text), expected)


class CheckFileTests(FolderCase):
    def test_valid_file(self):
        report = check_file(self.write("ok.lua", "local a = 1\nreturn a\n"))
        self.assertIsInstance(report, FileReport)
        self.assertTrue(report.ok)
        self.assertIsNone(report.error)
        self.assertEqual((report.size, report.lines, report.tokens, report.encoding), (21, 2, 6, "utf-8"))
        self.assertGreaterEqual(report.seconds, 0)

    def test_syntax_error_is_reported_not_raised(self):
        path = self.write("bad.lua", "x = 1\nreturn )\n")
        report = check_file(path)
        self.assertFalse(report.ok)
        self.assertEqual((report.error["code"], report.error["line"], report.error["column"]),
                         ("SYNTAX_ERROR", 2, 8))
        self.assertIn(f"{path}:2:8:", report.error["text"])
        self.assertEqual(report.lines, 2)
        self.assertEqual(report.to_dict()["error"], report.error)

    def test_encodings(self):
        path = self.write("latin.lua", b'return "\xe9"\n')
        self.assertEqual((check_file(path).ok, check_file(path).encoding), (True, "latin-1"))
        strict = check_file(path, encoding="utf-8")
        self.assertEqual((strict.ok, strict.error["code"]), (False, "UNREADABLE"))
        self.assertEqual(check_file(path, encoding="no-such-encoding").error["code"], "UNREADABLE")

    def test_missing_file_and_limits(self):
        missing = check_file(self.root / "missing.lua")
        self.assertEqual((missing.ok, missing.error["code"], missing.error["line"]), (False, "UNREADABLE", 0))
        path = self.write("deep.lua", "return " + "(" * 30 + "1" + ")" * 30)
        self.assertTrue(check_file(path).ok)
        self.assertEqual(check_file(path, max_depth=10).error["code"], "DEPTH_LIMIT")
        self.assertEqual(check_file(path, max_tokens=5).error["code"], "TOKEN_LIMIT")
        self.assertEqual(check_file(path, max_source_length=10).error["code"], "SOURCE_LIMIT")

    def test_first_line_starting_with_hash_is_skipped(self):
        self.assertTrue(check_file(self.write("script.lua", "# not Lua\nreturn 1\n")).ok)


class FolderTests(FolderCase):
    def populate(self, count: int = 3) -> None:
        self.write("b.lua", "return 2")
        self.write("A.LUA", "return 1")
        self.write("sub/c.lua", "return )")
        self.write("sub/notes.txt", "not lua")
        self.write("sub/deeper/d.lua.bak", "return 4")
        for index in range(count - 3):
            self.write(f"many/f{index:03}.lua", f"return {index}" if index % 7 else "return (")

    def test_find_lua_files_is_sorted_and_recursive(self):
        self.populate()
        names = [path.relative_to(self.root).as_posix() for path in find_lua_files(self.root)]
        self.assertEqual(names, ["A.LUA", "b.lua", "sub/c.lua"])
        self.assertEqual(find_lua_files(self.root / "sub" / "deeper"), [])

    def test_reports_come_back_sorted_with_callbacks(self):
        self.populate()
        seen: list[str] = []
        reports = check_files(find_lua_files(self.root), on_result=lambda report: seen.append(report.path))
        self.assertEqual([Path(report.path).name for report in reports], ["A.LUA", "b.lua", "c.lua"])
        self.assertEqual([report.ok for report in reports], [True, True, False])
        self.assertEqual(sorted(seen), sorted(report.path for report in reports))

    def test_should_stop_skips_the_remaining_files(self):
        self.populate()
        done: list[FileReport] = []
        reports = check_files(find_lua_files(self.root), jobs=1, on_result=done.append,
                              should_stop=lambda: len(done) >= 2)
        self.assertEqual(len(reports), 2)

    def test_worker_processes_give_the_same_reports(self):
        self.populate(60)
        files = find_lua_files(self.root)
        self.assertEqual(len(files), 60)

        def summary(reports: list[FileReport]) -> list[tuple]:
            return [(report.path, report.ok, report.size, report.lines, report.tokens, report.encoding,
                     report.error and report.error["code"]) for report in reports]

        alone = check_files(files, jobs=1)
        together = check_files(files, jobs=4)
        self.assertEqual(summary(alone), summary(together))
        self.assertEqual(sum(not report.ok for report in alone), 1 + len(range(0, 57, 7)))

    def test_options_reach_every_file(self):
        self.populate()
        reports = check_files(find_lua_files(self.root), max_tokens=1)
        self.assertEqual([report.error["code"] for report in reports], ["TOKEN_LIMIT"] * 3)

    def test_default_jobs_is_bounded(self):
        self.assertTrue(1 <= default_jobs() <= 16)
        self.assertLessEqual(default_jobs(), max(1, os.cpu_count() or 1))


if __name__ == "__main__":
    unittest.main()
