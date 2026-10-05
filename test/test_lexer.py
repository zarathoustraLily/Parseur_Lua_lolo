"""Lexical regression tests for Lua 5.4's byte and newline semantics."""
import unittest

from lua_parser_pro.lexer import KEYWORDS, Lexer, tokenize
from lua_parser_pro.model import LuaSyntaxError, Position


class LexerTests(unittest.TestCase):
    def tokens(self, source):
        return tokenize(source)[:-1]

    def string(self, source):
        tokens = self.tokens(source)
        self.assertEqual(len(tokens), 1)
        self.assertEqual(tokens[0].kind, "string")
        return tokens[0].value

    def error(self, source, code):
        with self.assertRaises(LuaSyntaxError) as caught:
            tokenize(source)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_keywords_and_identifier_boundaries(self):
        for word in KEYWORDS:
            with self.subTest(word=word):
                self.assertEqual(self.tokens(word)[0].kind, "keyword")
                self.assertEqual(self.tokens(word + "_")[0].kind, "identifier")
        self.assertEqual([t.value for t in self.tokens("_G abc_9 X")], ["_G", "abc_9", "X"])

    def test_symbols_use_longest_match(self):
        symbols = "+ - * / // % ^ # & ~ | << >> == ~= <= >= < > = ( ) { } [ ] ; : :: , . .. ..."
        self.assertEqual([t.value for t in self.tokens(symbols)], symbols.split())

    def test_accepted_number_forms(self):
        forms = "0 123 00012 3. .5 3.25 1e2 1E-2 1.e+2 .5E3 0xff 0XFF 0x1.8p+1 0X.8P-1 0x1. 0x1p0"
        self.assertEqual([t.value for t in self.tokens(forms)], forms.split())
        self.assertTrue(all(t.kind == "number" for t in self.tokens(forms)))

    def test_number_scanner_does_not_consume_binary_signs(self):
        self.assertEqual([t.value for t in self.tokens("3-4 0xe+1 1e-2-3")],
                         ["3", "-", "4", "0xe", "+", "1", "1e-2", "-", "3"])

    def test_malformed_numbers_are_not_split(self):
        for value in ("1..2", "1...", "0x", "0x.", "0x1p", "0x1p+", "1e", "1e+", "1abc",
                      "1foo", "1_", "0b101", "0x1g", ".5.6", "1.2.3", "0x1p1.0", "1e2e3"):
            with self.subTest(value=value):
                self.error(value, "MALFORMED_NUMBER")

    def test_numbers_are_not_converted_or_truncated(self):
        number = "9" * 5000
        self.assertEqual(self.tokens(number)[0].value, number)
        self.assertEqual(self.tokens("1e9999999999")[0].value, "1e9999999999")

    def test_short_strings_preserve_utf8_and_arbitrary_bytes(self):
        self.assertEqual(self.string("'café😀'"), "café😀".encode())
        self.assertEqual(self.string(r'"\0\255\x00\xFF"'), b"\x00\xff\x00\xff")
        self.assertEqual(self.string("'\x00'"), b"\x00")
        self.assertEqual(self.string(r'"\1234"'), b"{4")

    def test_all_simple_escapes(self):
        self.assertEqual(self.string(r'''"\a\b\f\n\r\t\v\\\"\'"'''),
                         b"\a\b\f\n\r\t\v\\\"'")

    def test_unicode_escapes_match_lua_extended_utf8(self):
        self.assertEqual(self.string(r'"\u{0}\u{7f}\u{80}\u{7ff}\u{800}"'),
                         b"\x00\x7f\xc2\x80\xdf\xbf\xe0\xa0\x80")
        self.assertEqual(self.string(r'"\u{1F600}"'), "😀".encode())
        self.assertEqual(self.string(r'"\u{D800}\u{110000}\u{7fffffff}"'),
                         b"\xed\xa0\x80\xf4\x90\x80\x80\xfd\xbf\xbf\xbf\xbf\xbf")
        self.assertEqual(self.string('"\\u{' + "0" * 5000 + '41}"'), b"A")

    def test_escaped_newlines_are_normalized(self):
        for newline in ("\n", "\r", "\r\n", "\n\r"):
            with self.subTest(newline=repr(newline)):
                self.assertEqual(self.string('"a\\' + newline + 'b"'), b"a\nb")

    def test_z_escape_skips_only_lua_whitespace(self):
        self.assertEqual(self.string('"a\\z \t\v\f\r\n\n\r b"'), b"ab")
        self.assertEqual(self.string('"\\z\u00a0"'), "\u00a0".encode())

    def test_invalid_escapes(self):
        for source in (r'"\q"', r'"\256"', r'"\999"', r'"\x"', r'"\x0"', r'"\xgg"',
                       r'"\u"', r'"\u{}"', r'"\u{z}"', r'"\u{123"', r'"\u{80000000}"'):
            with self.subTest(source=source):
                self.error(source, "INVALID_ESCAPE")

    def test_unterminated_strings(self):
        for source in ("'", '"', "'abc", "'abc\\", "'a\nb'", "[[abc", "[=[x]]"):
            with self.subTest(source=source):
                self.error(source, "UNTERMINATED_STRING")

    def test_long_string_levels_and_literal_contents(self):
        self.assertEqual(self.string(r"[==[a]]b]=]c\n]==]"), b"a]]b]=]c\\n")
        self.assertEqual(self.string("[=[é\x00]=]"), "é\x00".encode())
        self.assertEqual(self.string("[[]]"), b"")
        self.assertEqual(self.string("[=[x]===]y]=]"), b"x]===]y")

    def test_long_string_normalizes_and_ignores_first_newline(self):
        for newline in ("\n", "\r", "\r\n", "\n\r"):
            with self.subTest(newline=repr(newline)):
                self.assertEqual(self.string("[[" + newline + "a" + newline + "b]]"), b"a\nb")
        self.assertEqual(self.string("[[ \n]]"), b" \n")
        self.assertEqual(self.string("[[\n\n]]"), b"\n")

    def test_malformed_long_delimiters(self):
        for source in ("[=", "[==x", "[==="):
            self.error(source, "INVALID_LONG_DELIMITER")
        self.assertEqual(self.tokens("[ a ]")[0].value, "[")

    def test_comments_are_retained_separately(self):
        source = "--hello\r\nx --[=[\nworld\r!]=] y --[= short"
        lexer = Lexer(source)
        self.assertEqual([t.value for t in lexer.tokenize()], ["x", "y", ""])
        self.assertEqual([t.kind for t in lexer.comments], ["comment"] * 3)
        self.assertEqual([t.value for t in lexer.comments], ["hello", "world\n!", "[= short"])
        for token in lexer.comments:
            self.assertEqual(source[token.span.start.offset:token.span.end.offset], token.raw)
        without_comments = Lexer(source, comments=False)
        self.assertEqual(without_comments.tokenize(), lexer.tokenize())
        self.assertEqual(without_comments.comments, ())

    def test_unterminated_comment(self):
        self.error("--[=[ abc", "UNTERMINATED_COMMENT")

    def test_spans_and_line_endings(self):
        source = "a\r\nb\n\rc\rd\ne"
        tokens = self.tokens(source)
        self.assertEqual([t.span.start for t in tokens],
                         [Position(0, 1, 1), Position(3, 2, 1), Position(6, 3, 1),
                          Position(8, 4, 1), Position(10, 5, 1)])
        self.assertEqual(tokens[-1].span.end, Position(11, 5, 2))
        self.assertEqual(self.tokens('"é" abc')[1].span.start, Position(4, 1, 5))
        self.assertEqual(self.tokens("\tname")[0].span.start, Position(1, 1, 2))

    def test_eof_is_zero_width_and_repeated_calls_are_cached(self):
        lexer = Lexer("--x\nx")
        tokens = lexer.tokenize()
        self.assertIs(tokens, lexer.tokenize())
        eof = tokens[-1]
        self.assertEqual((eof.kind, eof.value, eof.raw), ("eof", "", ""))
        self.assertEqual(eof.span.start, eof.span.end)
        self.assertEqual(tokenize("")[0].span.start, Position(0, 1, 1))

    def test_failed_lexer_remains_failed(self):
        lexer = Lexer("1..2")
        for _ in range(2):
            with self.assertRaises(LuaSyntaxError):
                lexer.tokenize()

    def test_bom_and_shebang(self):
        lexer = Lexer("\ufeff#!/usr/bin/env lua\r\nreturn 1")
        self.assertEqual(lexer.tokenize()[0].value, "return")
        self.assertEqual(lexer.tokenize()[0].span.start.line, 2)
        self.assertEqual(lexer.comments[0].raw, "#!/usr/bin/env lua")
        self.assertEqual(self.tokens("\ufeffx")[0].span.start, Position(1, 1, 2))
        self.error(" \ufeffx", "INVALID_CHARACTER")
        self.error("x\n#!/usr/bin/lua", "INVALID_CHARACTER")

    def test_any_first_line_starting_with_hash_is_a_comment(self):
        lexer = Lexer("# usage: lua script.lua\r\nreturn 1")
        self.assertEqual(lexer.tokenize()[0].value, "return")
        self.assertEqual(lexer.tokenize()[0].span.start, Position(25, 2, 1))
        self.assertEqual([(t.kind, t.value, t.raw) for t in lexer.comments],
                         [("comment", " usage: lua script.lua", "# usage: lua script.lua")])
        alone = Lexer("#")
        self.assertEqual([t.kind for t in alone.tokenize()], ["eof"])
        self.assertEqual(alone.comments[0].raw, "#")
        self.assertEqual(Lexer("\ufeff# note\nx").tokenize()[0].span.start.line, 2)
        # Anywhere else, # is the length operator.
        self.assertEqual([t.value for t in self.tokens("x\n# y")], ["x", "#", "y"])
        self.assertEqual([t.value for t in self.tokens(" # y")], ["#", "y"])

    def test_string_values_use_the_source_encoding(self):
        self.assertEqual(self.string('"\u00e9"'), b"\xc3\xa9")
        self.assertEqual(Lexer('"\u00e9\\255"', encoding="latin-1").tokenize()[0].value, b"\xe9\xff")
        self.assertEqual(Lexer('[[\u00e9]]', encoding="cp1252").tokenize()[0].value, b"\xe9")
        with self.assertRaises(LuaSyntaxError) as caught:
            Lexer('"\u20ac"', encoding="latin-1").tokenize()
        self.assertEqual(caught.exception.code, "INVALID_SOURCE")
        with self.assertRaises(ValueError):
            Lexer("", encoding="no-such-encoding")

    def test_tokens_positions_and_spans_are_tuples(self):
        token = tokenize("  nom")[0]
        kind, value, raw, span = token
        self.assertEqual((kind, value, raw), ("identifier", "nom", "nom"))
        self.assertEqual(token._fields, ("kind", "value", "raw", "span"))
        start, end = span
        self.assertEqual(tuple(start), (2, 1, 3))
        self.assertEqual((end.offset, end.line, end.column), (5, 1, 6))
        self.assertEqual(token, tokenize("  nom")[0])
        self.assertEqual(hash(token.span), hash(tokenize("  nom")[0].span))

    def test_invalid_characters_and_isolated_surrogates(self):
        for source in ("@", "!", "\\", "\x00", "café", "\u00a0", "１２"):
            with self.subTest(source=source):
                self.error(source, "INVALID_CHARACTER")
        for source in ("\ud800", "'\udfff'", "--\ud800", "\n\r\ud800"):
            with self.subTest(source=repr(source)):
                self.error(source, "INVALID_SOURCE")

    def test_limits_and_argument_validation(self):
        self.assertEqual(len(tokenize("x y", max_tokens=2)), 3)
        for kwargs in ({"max_tokens": 1}, {"max_source_length": 2}):
            with self.assertRaises(LuaSyntaxError) as caught:
                tokenize("x y", **kwargs)
            self.assertIn(caught.exception.code, ("TOKEN_LIMIT", "SOURCE_LIMIT"))
        with self.assertRaises(LuaSyntaxError):
            tokenize("--a\n--b", max_tokens=1, comments=False)
        for limit in (0, -1, True, 1.5, None):
            with self.assertRaises(ValueError):
                Lexer("", max_tokens=limit)
        with self.assertRaises(TypeError):
            Lexer(b"x")

    def test_diagnostic_identifies_filename_and_escape_position(self):
        with self.assertRaises(LuaSyntaxError) as caught:
            tokenize('local s = "\\q"', filename="example.lua")
        error = caught.exception
        self.assertEqual(error.filename, "example.lua")
        self.assertEqual(error.span.start, Position(11, 1, 12))
        self.assertIn("example.lua:1:12:", str(error))


if __name__ == "__main__":
    unittest.main()
