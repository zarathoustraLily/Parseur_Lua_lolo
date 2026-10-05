"""Recursive-descent statements and Pratt expressions for Lua 5.4."""
from __future__ import annotations

from . import ast
from .lexer import Lexer
from .model import LuaSyntaxError, Position, Span, Token, gc_paused


# Higher numbers bind more tightly. Exponentiation and concatenation associate right.
_BINARY = {
    "or": 1, "and": 2,
    "<": 3, ">": 3, "<=": 3, ">=": 3, "~=": 3, "==": 3,
    "|": 4, "~": 5, "&": 6, "<<": 7, ">>": 7,
    "..": 8, "+": 9, "-": 9, "*": 10, "/": 10, "//": 10, "%": 10,
    "^": 12,
}
_UNARY = frozenset({"not", "-", "#", "~"})
_RIGHT_ASSOCIATIVE = frozenset({"^", ".."})
_UNARY_PRECEDENCE = 11

# Tokens that close a block, by the construct that opened it.
_CHUNK_END: frozenset[str] = frozenset()
_BLOCK_END = frozenset({"end"})
_IF_END = frozenset({"elseif", "else", "end"})
_REPEAT_END = frozenset({"until"})
_RETURN_END = frozenset({";", "end", "else", "elseif", "until"})
_ASSIGNABLE = (ast.Identifier, ast.MemberExpression, ast.IndexExpression)


class Parser:
    """A single-use parser. Prefer :func:`parse` for the public convenience API.

    ``current`` is the token being examined and ``previous`` the last one
    consumed; both are plain attributes kept up to date by :meth:`_advance`.
    """

    def __init__(self, source: str, *, filename: str = "<input>",
                 comments: bool = True, max_depth: int = 150,
                 max_tokens: int = 1_000_000,
                 max_source_length: int = 10_000_000,
                 encoding: str = "utf-8") -> None:
        if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 1:
            raise ValueError("max_depth must be a positive integer")
        self.source = source
        self.filename = filename
        self.max_depth = max_depth
        self.lexer = Lexer(source, filename=filename, comments=comments,
                           max_tokens=max_tokens, max_source_length=max_source_length,
                           encoding=encoding)
        self.tokens = self.lexer.tokenize()
        self.index = 0
        self.current: Token = self.tokens[0]
        self.previous: Token = self.tokens[0]
        self.depth = 0
        self.loop_depth = 0
        # Lua chunks are implicitly variadic functions.
        self.variadic = True

    def _at(self, value: str) -> bool:
        return self.current.value == value

    def _advance(self) -> Token:
        token = self.current
        if token.kind != "eof":
            self.index += 1
            self.previous = token
            self.current = self.tokens[self.index]
        return token

    def _match(self, value: str) -> bool:
        if self.current.value == value:
            self._advance()
            return True
        return False

    def _error(self, message: str, token: Token | ast.Node | None = None,
               code: str = "SYNTAX_ERROR") -> None:
        raise LuaSyntaxError(message, (token or self.current).span,
                             self.source, self.filename, code)

    def _expect(self, value: str) -> Token:
        if self.current.value != value:
            found = "end of input" if self.current.kind == "eof" else repr(self.current.raw)
            self._error(f"Expected {value!r}, found {found}")
        return self._advance()

    def _name(self) -> ast.Identifier:
        token = self.current
        if token.kind != "identifier":
            self._error("Expected an identifier")
        self._advance()
        return ast.Identifier(token.span, str(token.value))

    def _span(self, start: Position) -> Span:
        return Span(start, self.previous.span.end)

    def _enter(self) -> None:
        """Count one level of syntactic nesting; the caller decrements on success."""
        self.depth += 1
        if self.depth > self.max_depth:
            self._error("Maximum syntax depth exceeded", code="DEPTH_LIMIT")

    def parse(self) -> ast.Chunk:
        try:
            with gc_paused():
                body = self._block(_CHUNK_END).body
                if self.current.kind != "eof":
                    self._error("Expected end of input")
                result = ast.Chunk(Span(Position(0, 1, 1), self.current.span.end),
                                   body, tuple(self.lexer.comments))
                self._check_tree_depth(result)
                return result
        except RecursionError:
            # An unusually small host recursion limit must remain a controlled diagnostic.
            self._error("Python recursion limit reached; reduce nesting", code="DEPTH_LIMIT")
        raise AssertionError("unreachable")

    def _check_tree_depth(self, root: ast.Node) -> None:
        # Left-associative chains and suffixes build deep trees without recursive parsing.
        limit = self.max_depth
        node_class = ast.Node
        child_fields = ast.child_fields
        nodes: list[ast.Node] = [root]
        depths = [0]
        while nodes:
            node = nodes.pop()
            depth = depths.pop()
            if depth > limit:
                self._error("Maximum syntax-tree depth exceeded", node, "DEPTH_LIMIT")
            depth += 1
            for name in child_fields(node.__class__):
                value = getattr(node, name)
                if value.__class__ is tuple:
                    for item in value:
                        if isinstance(item, node_class):
                            nodes.append(item)
                            depths.append(depth)
                elif isinstance(value, node_class):
                    nodes.append(value)
                    depths.append(depth)

    def _block(self, terminators: frozenset[str]) -> ast.Block:
        self._enter()
        start = self.current.span.start
        statements: list[ast.Statement] = []
        while True:
            token = self.current
            if token.kind == "eof" or token.value in terminators:
                break
            statement = self._statement()
            statements.append(statement)
            if statement.__class__ is ast.ReturnStatement:
                token = self.current
                if token.kind != "eof" and token.value not in terminators:
                    self._error("A return statement must be the last statement in its block")
                break
        end = statements[-1].span.end if statements else start
        self.depth -= 1
        return ast.Block(Span(start, end), tuple(statements))

    def _statement(self) -> ast.Statement:
        token = self.current
        start = token.span.start
        kind = token.kind
        if kind == "keyword":
            keyword = token.value
            if keyword == "local":
                self._advance()
                return self._local(start)
            if keyword == "if":
                self._advance()
                return self._if(start)
            if keyword == "return":
                self._advance()
                arguments: tuple[ast.Expression, ...] = ()
                following = self.current
                if following.kind != "eof" and following.value not in _RETURN_END:
                    arguments = self._expressions()
                self._match(";")
                return ast.ReturnStatement(self._span(start), arguments)
            if keyword == "function":
                self._advance()
                name: ast.Expression = self._name()
                while self._match("."):
                    member = self._name()
                    name = ast.MemberExpression(Span(name.span.start, member.span.end), name, member)
                method = self._name() if self._match(":") else None
                function = self._function(start)
                return ast.FunctionStatement(self._span(start), name, function, False, method)
            if keyword == "for":
                self._advance()
                return self._for(start)
            if keyword == "while":
                self._advance()
                condition = self._expression()
                self._expect("do")
                self.loop_depth += 1
                body = self._block(_BLOCK_END)
                self.loop_depth -= 1
                self._expect("end")
                return ast.WhileStatement(self._span(start), condition, body)
            if keyword == "do":
                self._advance()
                body = self._block(_BLOCK_END)
                self._expect("end")
                return ast.DoStatement(self._span(start), body)
            if keyword == "repeat":
                self._advance()
                self.loop_depth += 1
                body = self._block(_REPEAT_END)
                self._expect("until")
                condition = self._expression()
                self.loop_depth -= 1
                return ast.RepeatStatement(self._span(start), body, condition)
            if keyword == "break":
                self._advance()
                if self.loop_depth == 0:
                    self._error("break is only valid inside a loop", self.previous, "INVALID_BREAK")
                return ast.BreakStatement(self._span(start))
            if keyword == "goto":
                self._advance()
                label = self._name()
                return ast.GotoStatement(self._span(start), label)
        elif kind == "symbol":
            symbol = token.value
            if symbol == ";":
                self._advance()
                return ast.EmptyStatement(self._span(start))
            if symbol == "::":
                self._advance()
                label = self._name()
                self._expect("::")
                return ast.LabelStatement(self._span(start), label)

        expression = self._prefix()
        following_value = self.current.value
        if following_value == "=" or following_value == ",":
            targets = [expression]
            while self._match(","):
                targets.append(self._prefix())
            for target in targets:
                if not isinstance(target, _ASSIGNABLE):
                    self._error("Invalid assignment target", target, "INVALID_ASSIGNMENT")
            self._expect("=")
            values = self._expressions()
            return ast.AssignmentStatement(self._span(start), tuple(targets), values)
        if not isinstance(expression, ast.CallExpression):
            self._error("Expected an assignment or a function call", expression)
        return ast.CallStatement(self._span(start), expression)  # type: ignore[arg-type]

    def _local(self, start: Position) -> ast.Statement:
        if self._match("function"):
            name = self._name()
            function = self._function(start)
            return ast.FunctionStatement(self._span(start), name, function, True)
        variables: list[ast.LocalVariable] = []
        closes = 0
        while True:
            name = self._name()
            attribute = None
            if self._match("<"):
                attr = self._name()
                attribute = attr.name
                if attribute not in {"const", "close"}:
                    self._error(f"Unknown local attribute {attribute!r}", attr, "INVALID_ATTRIBUTE")
                self._expect(">")
                if attribute == "close":
                    closes += 1
                    if closes > 1:
                        self._error("Only one <close> variable is allowed per declaration", attr,
                                    "INVALID_ATTRIBUTE")
            variables.append(ast.LocalVariable(self._span(name.span.start), name, attribute))
            if not self._match(","):
                break
        values = self._expressions() if self._match("=") else ()
        return ast.LocalStatement(self._span(start), tuple(variables), values)

    def _if(self, start: Position) -> ast.IfStatement:
        clauses: list[ast.IfClause] = []
        clause_start = start
        while True:
            condition = self._expression()
            self._expect("then")
            body = self._block(_IF_END)
            clauses.append(ast.IfClause(Span(clause_start, body.span.end), condition, body))
            if not self._match("elseif"):
                break
            clause_start = self.previous.span.start
        if self._match("else"):
            clause_start = self.previous.span.start
            body = self._block(_BLOCK_END)
            clauses.append(ast.IfClause(Span(clause_start, body.span.end), None, body))
        self._expect("end")
        return ast.IfStatement(self._span(start), tuple(clauses))

    def _for(self, start: Position) -> ast.Statement:
        name = self._name()
        if self._match("="):
            first = self._expression()
            self._expect(",")
            last = self._expression()
            step = self._expression() if self._match(",") else None
            self._expect("do")
            self.loop_depth += 1
            body = self._block(_BLOCK_END)
            self.loop_depth -= 1
            self._expect("end")
            return ast.NumericForStatement(self._span(start), name, first, last, step, body)
        names = [name]
        while self._match(","):
            names.append(self._name())
        self._expect("in")
        iterators = self._expressions()
        self._expect("do")
        self.loop_depth += 1
        body = self._block(_BLOCK_END)
        self.loop_depth -= 1
        self._expect("end")
        return ast.GenericForStatement(self._span(start), tuple(names), iterators, body)

    def _function(self, start: Position) -> ast.FunctionExpression:
        self._expect("(")
        parameters: list[ast.Identifier] = []
        variadic = False
        if not self._at(")"):
            while True:
                if self._match("..."):
                    variadic = True
                    break
                parameters.append(self._name())
                if not self._match(","):
                    break
        self._expect(")")
        previous_context = self.loop_depth, self.variadic
        self.loop_depth, self.variadic = 0, variadic
        try:
            body = self._block(_BLOCK_END)
            self._expect("end")
        finally:
            self.loop_depth, self.variadic = previous_context
        return ast.FunctionExpression(self._span(start), tuple(parameters), variadic, body)

    def _expressions(self) -> tuple[ast.Expression, ...]:
        values = [self._expression()]
        while self._match(","):
            values.append(self._expression())
        return tuple(values)

    def _expression(self, minimum: int = 1) -> ast.Expression:
        self._enter()
        token = self.current
        if token.value in _UNARY:
            self._advance()
            argument = self._expression(_UNARY_PRECEDENCE)
            left: ast.Expression = ast.UnaryExpression(
                Span(token.span.start, argument.span.end), str(token.value), argument)
        else:
            left = self._primary()
        binary = _BINARY
        while True:
            # A string token holds bytes: it is never an operator.
            operator = self.current.value
            precedence = binary.get(operator, 0)  # type: ignore[arg-type]
            if precedence < minimum:
                break
            self._advance()
            right = self._expression(
                precedence if operator in _RIGHT_ASSOCIATIVE else precedence + 1)
            left = ast.BinaryExpression(Span(left.span.start, right.span.end),
                                        operator, left, right)  # type: ignore[arg-type]
        self.depth -= 1
        return left

    def _primary(self) -> ast.Expression:
        token = self.current
        kind = token.kind
        if kind == "identifier":
            return self._prefix()
        if kind == "number":
            self._advance()
            return ast.NumberLiteral(token.span, token.raw)
        if kind == "string":
            self._advance()
            return ast.StringLiteral(token.span, token.value, token.raw)  # type: ignore[arg-type]
        value = token.value
        if value == "nil":
            self._advance()
            return ast.NilLiteral(token.span)
        if value == "true":
            self._advance()
            return ast.BooleanLiteral(token.span, True)
        if value == "false":
            self._advance()
            return ast.BooleanLiteral(token.span, False)
        if value == "...":
            self._advance()
            if not self.variadic:
                self._error("... is only valid inside a variadic function", token, "INVALID_VARARG")
            return ast.VarargExpression(token.span)
        if value == "function":
            self._advance()
            return self._function(token.span.start)
        if value == "{":
            return self._table()
        return self._prefix()

    def _prefix(self) -> ast.Expression:
        token = self.current
        start = token.span.start
        if token.kind == "identifier":
            self._advance()
            expression: ast.Expression = ast.Identifier(token.span, token.value)  # type: ignore[arg-type]
        elif token.value == "(":
            self._advance()
            inner = self._expression()
            self._expect(")")
            expression = ast.ParenthesizedExpression(self._span(start), inner)
        else:
            self._error("Expected an expression")
            raise AssertionError("unreachable")
        while True:
            token = self.current
            value = token.value
            if value == ".":
                self._advance()
                name = self._name()
                expression = ast.MemberExpression(self._span(start), expression, name)
            elif value == "[":
                self._advance()
                index = self._expression()
                self._expect("]")
                expression = ast.IndexExpression(self._span(start), expression, index)
            elif value == ":":
                self._advance()
                method = self._name()
                arguments = self._arguments()
                expression = ast.CallExpression(self._span(start), expression, arguments, method)
            elif value == "(" or value == "{" or token.kind == "string":
                arguments = self._arguments()
                expression = ast.CallExpression(self._span(start), expression, arguments)
            else:
                return expression

    def _arguments(self) -> tuple[ast.Expression, ...]:
        if self._match("("):
            values = () if self._at(")") else self._expressions()
            self._expect(")")
            return values
        if self._at("{"):
            return (self._table(),)
        if self.current.kind == "string":
            token = self._advance()
            return (ast.StringLiteral(token.span, token.value, token.raw),)  # type: ignore[arg-type]
        self._error("Expected function arguments: (...), {...}, or a string")
        raise AssertionError("unreachable")

    def _table(self) -> ast.TableExpression:
        # Tables passed as call arguments do not pass through _expression first.
        self._enter()
        start = self._expect("{").span.start
        items: list[ast.TableField] = []
        while not self._at("}"):
            token = self.current
            field_start = token.span.start
            key: ast.Expression | None = None
            if token.value == "[":
                self._advance()
                kind = "index"
                key = self._expression()
                self._expect("]")
                self._expect("=")
                value = self._expression()
            elif token.kind == "identifier" and self.tokens[self.index + 1].value == "=":
                kind = "name"
                key = self._name()
                self._expect("=")
                value = self._expression()
            else:
                kind = "value"
                value = self._expression()
            items.append(ast.TableField(self._span(field_start), kind, key, value))
            if not (self._match(",") or self._match(";")):
                break
        self._expect("}")
        self.depth -= 1
        return ast.TableExpression(self._span(start), tuple(items))


def parse(source: str, *, filename: str = "<input>", comments: bool = True,
          max_depth: int = 150, max_tokens: int = 1_000_000,
          max_source_length: int = 10_000_000, encoding: str = "utf-8") -> ast.Chunk:
    """Parse UTF-8 text represented as str; raise LuaSyntaxError on the first error.

    This builds a syntax tree and checks break/vararg/attribute context. It does
    not resolve goto labels, enforce const assignments, or execute source code.
    ``encoding`` selects the codec that turns literal string characters into bytes.
    """
    return Parser(source, filename=filename, comments=comments, max_depth=max_depth,
                  max_tokens=max_tokens, max_source_length=max_source_length,
                  encoding=encoding).parse()
