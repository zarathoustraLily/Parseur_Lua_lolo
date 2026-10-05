"""Lossless Lua 5.4 lexer for Unicode source text.

Identifiers use Lua's portable ASCII alphabet. Ordinary string characters are
encoded as UTF-8 (or as the requested ``encoding``), while Lua escapes produce
bytes directly. Spans have zero-based code-point offsets and one-based
lines/columns, with an exclusive end position. An initial Unicode BOM and a
first line starting with ``#`` are accepted, as the reference ``lua`` program
does when it loads a file.

The scanner works on whole lexemes with compiled patterns; the character-level
helpers remain for escapes, diagnostics and other uncommon paths.
"""
from __future__ import annotations

import codecs
import re
from typing import NoReturn

from .model import LuaSyntaxError, Position, Span, Token, gc_paused


KEYWORDS = frozenset({
    "and", "break", "do", "else", "elseif", "end", "false", "for",
    "function", "goto", "if", "in", "local", "nil", "not", "or",
    "repeat", "return", "then", "true", "until", "while",
})
_DIGITS = frozenset("0123456789")
_HEX = frozenset("0123456789abcdefABCDEF")
_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_IDENTIFIER = _LETTERS | _DIGITS
_SPACE = frozenset(" \t\v\f\r\n")
_SINGLE_SYMBOLS = frozenset("+-*/%^#&~|<>=(){}[];:,.")
_DOUBLE_SYMBOLS = frozenset({"//", "<<", ">>", "==", "~=", "<=", ">=", "::", ".."})
_NEWLINES = re.compile(r"\r\n|\n\r|\r|\n")
_SURROGATES = re.compile("[\ud800-\udfff]")
_DECIMAL = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
_HEXADECIMAL = re.compile(
    r"0[xX](?:[0-9a-fA-F]+(?:\.[0-9a-fA-F]*)?|\.[0-9a-fA-F]+)"
    r"(?:[pP][+-]?[0-9]+)?"
)
_ESCAPES = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13,
            "t": 9, "v": 11, "\\": 92, '"': 34, "'": 39}

# Whole-lexeme patterns used by the main loop.
_WHITESPACE = re.compile(r"[ \t\v\f\r\n]+")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_LINE_REST = re.compile(r"[^\r\n]*")
_LONG_OPEN = re.compile(r"\[(=*)\[")
# Lua's numeral scanner is deliberately permissive: it swallows hexadecimal
# digits, dots and exponent markers (with their sign), then one trailing letter,
# and validates the lexeme afterwards. 1..2 and 1abc are malformed numbers.
_NUMBER_SCAN = re.compile(r"(?:[eE][+-]?|[0-9a-dfA-DF.])*[A-Za-z_]?")
_HEX_NUMBER_SCAN = re.compile(r"0[xX](?:[pP][+-]?|[0-9a-fA-F.])*[A-Za-z_]?")
_PLAIN_STRING = re.compile(r"\"[^\"\\\r\n]*\"|'[^'\\\r\n]*'")


def _lua_utf8(value: int) -> bytes:
    """Lua permits escaped UTF-8 values up to 0x7fffffff, even surrogates."""
    if value < 0x80:
        return bytes((value,))
    tail = bytearray()
    mask = 0x3F
    while value > mask:
        tail.append(0x80 | (value & 0x3F))
        value >>= 6
        mask >>= 1
    tail.append(((~mask << 1) & 0xFF) | value)
    tail.reverse()
    return bytes(tail)


class Lexer:
    """Tokenize a source once; repeated calls return the same immutable result.

    ``comments`` controls retention in :attr:`comments`, never parsing. The
    token limit counts all source tokens and comments, excluding EOF. Limits
    must be positive integers. The source length limit counts code points.

    ``encoding`` names the codec that turns the literal characters of a string
    into bytes. Decode a file as ``latin-1`` and pass ``encoding="latin-1"`` to
    get the exact bytes of a source that is not valid UTF-8.
    """

    def __init__(self, source: str, filename: str = "<input>", *,
                 max_tokens: int = 1_000_000,
                 max_source_length: int = 10_000_000,
                 comments: bool = True,
                 encoding: str = "utf-8") -> None:
        if not isinstance(source, str):
            raise TypeError("source must be a str")
        if not isinstance(filename, str):
            raise TypeError("filename must be a str")
        for name, limit in (("max_tokens", max_tokens),
                            ("max_source_length", max_source_length)):
            if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(comments, bool):
            raise TypeError("comments must be a bool")
        if not isinstance(encoding, str):
            raise TypeError("encoding must be a str")
        try:
            codecs.lookup(encoding)
        except LookupError:
            raise ValueError(f"unknown encoding {encoding!r}") from None
        self.source = source
        self.filename = filename
        self.max_tokens = max_tokens
        self.max_source_length = max_source_length
        self.encoding = encoding
        self._keep_comments = comments
        self.comments: tuple[Token, ...] = ()
        self._result: tuple[Token, ...] | None = None
        self._error: LuaSyntaxError | None = None
        self._i = 0
        self._line = 1
        self._column = 1
        self._count = 0
        if len(source) > max_source_length:
            self._fail(f"Source exceeds the limit of {max_source_length} characters",
                       self._position(), "SOURCE_LIMIT")
        invalid = _SURROGATES.search(source)
        if invalid:
            self._advance_to(invalid.start())
            start = self._position()
            self._advance()
            self._fail("Source contains an isolated Unicode surrogate", start,
                       "INVALID_SOURCE")

    # ------------------------------------------------------------------ helpers
    def _position(self) -> Position:
        return Position(self._i, self._line, self._column)

    def _peek(self, distance: int = 0) -> str:
        index = self._i + distance
        return self.source[index] if index < len(self.source) else ""

    def _advance(self) -> None:
        """Consume one source character or one Lua newline sequence."""
        char = self.source[self._i]
        self._i += 1
        if char in "\r\n":
            if self._i < len(self.source):
                following = self.source[self._i]
                if following in "\r\n" and following != char:
                    self._i += 1
            self._line += 1
            self._column = 1
        else:
            self._column += 1

    def _advance_to(self, end: int) -> None:
        while self._i < end:
            self._advance()

    def _skip_to(self, end: int) -> None:
        """Move to ``end`` in one step; ``end`` must not split a newline pair."""
        source = self.source
        start = self._i
        if start >= end:
            return
        last = -1
        count = 0
        if source.find("\r", start, end) < 0:
            count = source.count("\n", start, end)
            if count:
                last = source.rfind("\n", start, end) + 1
        else:
            for match in _NEWLINES.finditer(source, start, end):
                count += 1
                last = match.end()
        if count:
            self._line += count
            self._column = end - last + 1
        else:
            self._column += end - start
        self._i = end

    def _fail(self, message: str, start: Position, code: str) -> NoReturn:
        raise LuaSyntaxError(message, Span(start, self._position()), self.source,
                             self.filename, code)

    def _token(self, kind: str, value: str | bytes, start: Position) -> Token:
        return Token(kind, value, self.source[start.offset:self._i],
                     Span(start, self._position()))

    def _encode(self, text: str, start: Position) -> bytes:
        try:
            return text.encode(self.encoding)
        except UnicodeEncodeError:
            self._fail(f"String contains a character that {self.encoding} cannot encode",
                       start, "INVALID_SOURCE")

    def _long_opener(self) -> int | None:
        """Return the number of '=' signs without advancing the source."""
        match = _LONG_OPEN.match(self.source, self._i)
        return len(match.group(1)) if match else None

    def _long(self, start: Position, level: int, *, comment: bool) -> Token:
        source = self.source
        self._i += level + 2
        self._column += level + 2
        if self._peek() in ("\r", "\n"):
            self._advance()  # Lua ignores the first newline after the opener.
        body_start = self._i
        close = "]" + "=" * level + "]"
        end = source.find(close, body_start)
        if end < 0:
            self._skip_to(len(source))
            self._fail("Unterminated long comment" if comment else "Unterminated long string",
                       start, "UNTERMINATED_COMMENT" if comment else "UNTERMINATED_STRING")
        value = source[body_start:end]
        if "\r" in value:
            value = _NEWLINES.sub("\n", value)
        self._skip_to(end)
        self._i += len(close)
        self._column += len(close)
        return self._token("comment" if comment else "string",
                           value if comment else self._encode(value, start), start)

    def _comment(self, *, marker: int = 2, first_line: bool = False) -> Token:
        start = self._position()
        self._i += marker
        self._column += marker
        if not first_line:
            level = self._long_opener()
            if level is not None:
                return self._long(start, level, comment=True)
        body_start = self._i
        end = _LINE_REST.match(self.source, body_start).end()  # type: ignore[union-attr]
        self._column += end - body_start
        self._i = end
        return self._token("comment", self.source[body_start:end], start)

    def _unicode_escape(self, start: Position) -> bytes:
        if self._peek() != "{":
            self._fail("Expected '{' after \\u", start, "INVALID_ESCAPE")
        self._advance()
        if self._peek() not in _HEX:
            self._fail("Expected a hexadecimal digit in Unicode escape", start,
                       "INVALID_ESCAPE")
        value = 0
        while self._peek() in _HEX:
            value = value * 16 + int(self._peek(), 16)
            self._advance()
            if value > 0x7FFFFFFF:
                self._fail("Unicode escape exceeds 0x7fffffff", start, "INVALID_ESCAPE")
        if self._peek() != "}":
            self._fail("Expected '}' after Unicode escape", start, "INVALID_ESCAPE")
        self._advance()
        return _lua_utf8(value)

    def _short_string(self) -> Token:
        start = self._position()
        quote = self._peek()
        self._advance()
        parts: list[bytes] = []
        while True:
            char = self._peek()
            if not char or char in ("\r", "\n"):
                self._fail("Unterminated string literal", start, "UNTERMINATED_STRING")
            if char == quote:
                self._advance()
                return self._token("string", b"".join(parts), start)
            if char != "\\":
                begin = self._i
                while self._peek() and self._peek() not in (quote, "\\", "\r", "\n"):
                    self._advance()
                parts.append(self._encode(self.source[begin:self._i], start))
                continue
            escape_start = self._position()
            self._advance()
            char = self._peek()
            if not char:
                self._fail("Unterminated string literal", start, "UNTERMINATED_STRING")
            if char in _ESCAPES:
                parts.append(bytes((_ESCAPES[char],)))
                self._advance()
            elif char in ("\r", "\n"):
                self._advance()
                parts.append(b"\n")
            elif char == "z":
                self._advance()
                while self._peek() in _SPACE:
                    self._advance()
            elif char == "x":
                self._advance()
                digits = self.source[self._i:self._i + 2]
                if len(digits) != 2 or any(digit not in _HEX for digit in digits):
                    self._fail("Expected exactly two hexadecimal digits after \\x",
                               escape_start, "INVALID_ESCAPE")
                self._advance_to(self._i + 2)
                parts.append(bytes((int(digits, 16),)))
            elif char == "u":
                self._advance()
                parts.append(self._unicode_escape(escape_start))
            elif char in _DIGITS:
                begin = self._i
                for _ in range(3):
                    if self._peek() not in _DIGITS:
                        break
                    self._advance()
                value = int(self.source[begin:self._i], 10)
                if value > 255:
                    self._fail("Decimal escape exceeds 255", escape_start, "INVALID_ESCAPE")
                parts.append(bytes((value,)))
            else:
                self._advance()
                self._fail(f"Invalid escape sequence \\{char}", escape_start, "INVALID_ESCAPE")

    # ---------------------------------------------------------------- main loop
    def tokenize(self) -> tuple[Token, ...]:
        """Return tokens without comments; raise :class:`LuaSyntaxError` on failure."""
        if self._result is not None:
            return self._result
        if self._error is not None:
            raise self._error
        tokens: list[Token] = []
        comments: list[Token] = []
        try:
            with gc_paused():
                self._scan(tokens, comments)
        except LuaSyntaxError as error:
            self.comments = tuple(comments)
            self._error = error
            raise
        self.comments = tuple(comments)
        self._result = tuple(tokens)
        return self._result

    def _scan(self, tokens: list[Token], comments: list[Token]) -> None:
        source = self.source
        length = len(source)
        keep_comments = self._keep_comments
        max_tokens = self.max_tokens
        keywords = KEYWORDS
        letters = _LETTERS
        digits = _DIGITS
        single_symbols = _SINGLE_SYMBOLS
        double_symbols = _DOUBLE_SYMBOLS
        whitespace = _WHITESPACE.match
        name = _NAME.match
        plain_string = _PLAIN_STRING.match
        line_rest = _LINE_REST.match
        long_open = _LONG_OPEN.match
        number_scan = _NUMBER_SCAN.match
        hex_scan = _HEX_NUMBER_SCAN.match
        decimal_number = _DECIMAL.fullmatch
        hex_number = _HEXADECIMAL.fullmatch
        newlines = _NEWLINES.finditer
        has_cr = "\r" in source
        utf8 = self.encoding.lower().replace("_", "-") in ("utf-8", "utf8")
        append = tokens.append
        new = tuple.__new__  # Named tuples built without the generated __new__ wrapper.

        if source.startswith("\ufeff"):
            self._i = 1
            self._column = 2
        if source.startswith("#", self._i):
            marker = 2 if source.startswith("#!", self._i) else 1
            token = self._comment(marker=marker, first_line=True)
            self._count += 1
            if self._count > max_tokens:
                self._fail(f"Source exceeds the limit of {max_tokens} tokens",
                           token.span.start, "TOKEN_LIMIT")
            if keep_comments:
                comments.append(token)

        # The loop keeps its own cursor: ``i`` is the offset, ``line`` the line
        # number and ``line_start`` the offset of the first character of the line.
        i = self._i
        line = self._line
        line_start = i - (self._column - 1)
        count = self._count
        while i < length:
            char = source[i]
            if char in " \t\v\f\r\n":
                end = whitespace(source, i).end()  # type: ignore[union-attr]
                if has_cr:
                    last = -1
                    for match in newlines(source, i, end):
                        line += 1
                        last = match.end()
                    if last >= 0:
                        line_start = last
                else:
                    found = source.count("\n", i, end)
                    if found:
                        line += found
                        line_start = source.rfind("\n", i, end) + 1
                i = end
                continue
            if char in letters:
                end = name(source, i).end()  # type: ignore[union-attr]
                value = source[i:end]
                token = new(Token, ("keyword" if value in keywords else "identifier", value, value,
                                    new(Span, (new(Position, (i, line, i - line_start + 1)),
                                               new(Position, (end, line, end - line_start + 1))))))
                i = end
            elif char in digits or (char == "." and source[i + 1:i + 2] in digits):
                hexadecimal = char == "0" and source[i + 1:i + 2] in ("x", "X")
                end = (hex_scan if hexadecimal else number_scan)(source, i).end()  # type: ignore[union-attr]
                value = source[i:end]
                if (hex_number if hexadecimal else decimal_number)(value) is None:
                    self._i = end
                    self._line = line
                    self._column = end - line_start + 1
                    self._fail(f"Malformed number {value[:80]!r}",
                               Position(i, line, i - line_start + 1), "MALFORMED_NUMBER")
                token = new(Token, ("number", value, value,
                                    new(Span, (new(Position, (i, line, i - line_start + 1)),
                                               new(Position, (end, line, end - line_start + 1))))))
                i = end
            elif char in single_symbols:
                pair = source[i:i + 2]
                if pair == "--":
                    if source.startswith("[", i + 2) and long_open(source, i + 2) is not None:
                        self._i = i
                        self._line = line
                        self._column = i - line_start + 1
                        token = self._comment()
                        end = self._i
                        line = self._line
                        line_start = end - (self._column - 1)
                    else:
                        end = line_rest(source, i + 2).end()  # type: ignore[union-attr]
                        token = new(Token, ("comment", source[i + 2:end], source[i:end],
                                            new(Span, (new(Position, (i, line, i - line_start + 1)),
                                                       new(Position, (end, line, end - line_start + 1))))))
                    i = end
                    count += 1
                    if count > max_tokens:
                        self._i = i
                        self._line = line
                        self._column = i - line_start + 1
                        self._fail(f"Source exceeds the limit of {max_tokens} tokens",
                                   token.span.start, "TOKEN_LIMIT")
                    if keep_comments:
                        comments.append(token)
                    continue
                if pair == "[[" or pair == "[=":
                    # A long string, or a malformed long delimiter.
                    self._i = i
                    self._line = line
                    self._column = i - line_start + 1
                    start = self._position()
                    level = self._long_opener()
                    if level is None:
                        self._advance()
                        while self._peek() == "=":
                            self._advance()
                        self._fail("Invalid long string delimiter", start,
                                   "INVALID_LONG_DELIMITER")
                    token = self._long(start, level, comment=False)
                    i = self._i
                    line = self._line
                    line_start = i - (self._column - 1)
                else:
                    if pair in double_symbols:
                        end = i + 3 if pair == ".." and source.startswith("...", i) else i + 2
                    else:
                        end = i + 1
                    value = source[i:end]
                    token = new(Token, ("symbol", value, value,
                                        new(Span, (new(Position, (i, line, i - line_start + 1)),
                                                   new(Position, (end, line, end - line_start + 1))))))
                    i = end
            elif char == '"' or char == "'":
                match = plain_string(source, i) if utf8 else None
                if match is not None:
                    end = match.end()
                    token = new(Token, ("string", source[i + 1:end - 1].encode("utf-8"), source[i:end],
                                        new(Span, (new(Position, (i, line, i - line_start + 1)),
                                                   new(Position, (end, line, end - line_start + 1))))))
                    i = end
                else:
                    # Escapes, unterminated strings and other codecs: character by character.
                    self._i = i
                    self._line = line
                    self._column = i - line_start + 1
                    token = self._short_string()
                    i = self._i
                    line = self._line
                    line_start = i - (self._column - 1)
            else:
                self._i = i
                self._line = line
                self._column = i - line_start + 1
                start = self._position()
                self._advance()
                self._fail(f"Unexpected character {char!r}", start, "INVALID_CHARACTER")
            count += 1
            if count > max_tokens:
                self._i = i
                self._line = line
                self._column = i - line_start + 1
                self._fail(f"Source exceeds the limit of {max_tokens} tokens",
                           token.span.start, "TOKEN_LIMIT")
            append(token)
        self._i = i
        self._line = line
        self._column = i - line_start + 1
        self._count = count
        end_position = self._position()
        append(Token("eof", "", "", Span(end_position, end_position)))


def tokenize(source: str, **kwargs: object) -> tuple[Token, ...]:
    """Convenience wrapper for ``Lexer(source, **kwargs).tokenize()``."""
    return Lexer(source, **kwargs).tokenize()  # type: ignore[arg-type]
