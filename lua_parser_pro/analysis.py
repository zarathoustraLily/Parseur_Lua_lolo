"""Read a syntax tree: outline of its functions and tables, and a few measures.

Nothing here executes or resolves Lua. The outline reports what the text
declares: named functions, tables and module-level variables, with the
anonymous functions handed to calls (callbacks). Every traversal is iterative.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from . import ast
from .model import Span, Token

_LEAVES = (ast.Identifier, ast.NumberLiteral, ast.StringLiteral, ast.BooleanLiteral,
           ast.NilLiteral, ast.VarargExpression)
_PLAIN_KEY = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")
_ELLIPSIS = "\u2026"


def expression_text(node: ast.Node | None, limit: int = 80) -> str:
    """A short source-like rendering of a name or callee: ``a.b[1]:m``, ``f()``."""
    parts: list[str] = []
    stack: list[Any] = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, ast.Identifier):
            parts.append(item.name)
        elif isinstance(item, ast.MemberExpression):
            stack.extend((item.name, ".", item.base))
        elif isinstance(item, ast.IndexExpression):
            stack.extend(("]", item.index, "[", item.base))
        elif isinstance(item, ast.CallExpression):
            if item.method is not None:
                stack.extend(("()", item.method, ":", item.callee))
            else:
                stack.extend(("()", item.callee))
        elif isinstance(item, ast.ParenthesizedExpression):
            stack.extend((")", item.expression, "("))
        elif isinstance(item, (ast.NumberLiteral, ast.StringLiteral)):
            parts.append(item.raw if len(item.raw) <= 24 else item.raw[:21] + "...")
        elif isinstance(item, ast.BooleanLiteral):
            parts.append("true" if item.value else "false")
        elif isinstance(item, ast.NilLiteral):
            parts.append("nil")
        elif isinstance(item, ast.VarargExpression):
            parts.append("...")
        elif isinstance(item, ast.UnaryExpression):
            stack.extend((item.argument, "not " if item.operator == "not" else item.operator))
        elif item is not None:
            parts.append(_ELLIPSIS)
        if sum(map(len, parts)) > limit:
            break
    text = "".join(parts)
    return text if len(text) <= limit else text[:limit - 1] + _ELLIPSIS


@dataclass(slots=True)
class Symbol:
    """One entry of the outline.

    ``kind`` is ``function``, ``method``, ``callback``, ``table`` or
    ``variable``. A callback is an anonymous function passed to a call; its
    name is the callee. ``name`` is empty for any other anonymous function and
    ``return`` for a table or function returned by the chunk. ``parameters``
    lists the written parameters of a function, ``...`` included. ``fields``
    counts the fields of a table constructor and ``value`` previews a literal.
    """

    name: str
    kind: str
    span: Span
    local: bool = False
    parameters: tuple[str, ...] | None = None
    fields: int | None = None
    value: str | None = None
    children: list[Symbol] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        output: list[dict[str, Any]] = []
        pending: list[tuple[Symbol, list[dict[str, Any]]]] = [(self, output)]
        while pending:
            symbol, target = pending.pop()
            children: list[dict[str, Any]] = []
            target.append({
                "name": symbol.name, "kind": symbol.kind, "local": symbol.local,
                "line": symbol.span.start.line, "column": symbol.span.start.column,
                "end_line": symbol.span.end.line,
                "offset": symbol.span.start.offset, "end_offset": symbol.span.end.offset,
                "parameters": None if symbol.parameters is None else list(symbol.parameters),
                "fields": symbol.fields, "value": symbol.value, "children": children,
            })
            # Reversed, so that the first child is popped (and appended) first.
            for child in reversed(symbol.children):
                pending.append((child, children))
        return output[0]


def _parameters(function: ast.FunctionExpression) -> tuple[str, ...]:
    names = [parameter.name for parameter in function.parameters]
    if function.variadic:
        names.append("...")
    return tuple(names)


def _field_name(table_field: ast.TableField) -> str | None:
    key = table_field.key
    if table_field.kind == "name" and isinstance(key, ast.Identifier):
        return key.name
    if table_field.kind == "index":
        if isinstance(key, ast.StringLiteral):
            try:
                text = key.value.decode("utf-8")
            except UnicodeDecodeError:
                return key.raw
            return text if text and len(text) <= 60 and set(text) <= _PLAIN_KEY else key.raw
        if isinstance(key, ast.NumberLiteral):
            return f"[{key.raw}]"
    return None


def outline(tree: ast.Chunk) -> list[Symbol]:
    """Named functions, tables and module-level variables of ``tree``, in source order.

    Functions are reported wherever they are defined; a function's children are
    the functions defined inside it. A table bound at module level lists its
    named fields that are functions or tables. Variables are only reported at
    module level.
    """
    result: list[Symbol] = []
    # Work items: (node, output list, at module level, binding, depth of table nesting).
    # ``binding`` names the value being visited: (name, is_local, span, kind).
    stack: list[tuple[Any, list[Symbol], bool, tuple[str, bool, Span, str] | None, int]] = [
        (statement, result, True, None, 0) for statement in reversed(tree.body)]
    push = stack.append
    while stack:
        node, out, top, binding, nesting = stack.pop()
        cls = node.__class__
        if cls is ast.FunctionExpression:
            if binding is None:
                name, local, span, kind = "", False, node.span, "function"
            else:
                name, local, span, kind = binding
            symbol = Symbol(name, kind, span, local, _parameters(node))
            out.append(symbol)
            for statement in reversed(node.body.body):
                push((statement, symbol.children, False, None, 0))
        elif cls is ast.TableExpression:
            target = out
            if binding is not None and binding[3] != "callback" and (top or nesting == 1):
                name, local, span, _ = binding
                symbol = Symbol(name, "table", span, local, fields=len(node.fields))
                out.append(symbol)
                target = symbol.children
            callback = binding if binding is not None and binding[3] == "callback" else None
            for table_field in reversed(node.fields):
                key_name = _field_name(table_field)
                value = table_field.value
                if key_name is not None:
                    field_binding = (key_name, False, table_field.span, "function")
                elif callback is not None and value.__class__ is ast.FunctionExpression:
                    field_binding = (callback[0], False, value.span, "callback")
                else:
                    field_binding = None
                if table_field.kind == "index" and key_name is None:
                    push((table_field.key, target, False, None, 0))
                push((value, target, False, field_binding, nesting + 1 if target is not out else 9))
        elif cls is ast.FunctionStatement:
            name = expression_text(node.name)
            if node.method is not None:
                name = f"{name}:{node.method.name}"
            symbol = Symbol(name, "method" if node.method is not None else "function",
                            node.span, node.local, _parameters(node.function))
            out.append(symbol)
            for statement in reversed(node.function.body.body):
                push((statement, symbol.children, False, None, 0))
        elif cls is ast.LocalStatement or cls is ast.AssignmentStatement:
            local = cls is ast.LocalStatement
            names = node.variables if local else node.targets
            values = node.values
            for index in range(max(len(names), len(values)) - 1, -1, -1):
                value = values[index] if index < len(values) else None
                if index >= len(names):
                    push((value, out, False, None, 0))
                    continue
                target = names[index]
                text = target.name.name if local else expression_text(target)
                if not local and target.__class__ is not ast.Identifier:
                    # a.b[k] = value: the index expressions may hold functions too.
                    push((target, out, False, None, 0))
                value_class = value.__class__
                if value_class is ast.FunctionExpression or value_class is ast.TableExpression:
                    push((value, out, top, (text, local, node.span, "function"), 0))
                else:
                    if value is not None:
                        push((value, out, False, None, 0))
                    if top:
                        push((_Variable(text, local, target.span, value), out, True, None, 0))
        elif cls is _Variable:
            value = node.value
            simple = isinstance(value, _LEAVES) or (
                value.__class__ is ast.UnaryExpression and isinstance(value.argument, _LEAVES))
            out.append(Symbol(node.name, "variable", node.span, node.local,
                              value=expression_text(value, 40) if simple else None))
        elif cls is ast.ReturnStatement:
            for argument in reversed(node.arguments):
                named = top and argument.__class__ in (ast.TableExpression, ast.FunctionExpression)
                push((argument, out, top,
                      ("return", False, argument.span, "function") if named else None, 0))
        elif cls is ast.CallExpression:
            callee = expression_text(node.callee, 60)
            if node.method is not None:
                callee = f"{callee}:{node.method.name}"
            for argument in reversed(node.arguments):
                argument_class = argument.__class__
                if argument_class is ast.FunctionExpression or argument_class is ast.TableExpression:
                    push((argument, out, False, (callee, False, argument.span, "callback"), 0))
                else:
                    push((argument, out, False, None, 0))
            push((node.callee, out, False, None, 0))
        elif cls in _LEAVES_SET:
            continue
        else:
            # Any other statement or expression: look inside, module level is over.
            for child in reversed(ast.children(node)):
                push((child, out, False, None, 0))
    return result


@dataclass(frozen=True, slots=True)
class _Variable:
    """A module-level name without a function or table value (internal work item)."""

    name: str
    local: bool
    span: Span
    value: Any


_LEAVES_SET = frozenset(_LEAVES) | {ast.EmptyStatement, ast.BreakStatement,
                                    ast.GotoStatement, ast.LabelStatement}


def statistics(tree: ast.Chunk, tokens: Sequence[Token] = (), *, top: int = 12) -> dict[str, Any]:
    """Counts describing ``tree`` (and ``tokens`` when given), as JSON data.

    ``depth`` is the height of the tree. ``functions`` lists the longest
    functions and ``calls`` the most frequent callees, ``top`` entries each.
    """
    nodes: Counter[str] = Counter()
    calls: Counter[str] = Counter()
    functions: list[tuple[int, str, int]] = []
    string_bytes = 0
    depth = 0
    stack: list[tuple[ast.Node, int, str | None]] = [(tree, 1, None)]
    pop = stack.pop
    push = stack.append
    children = ast.children
    while stack:
        node, level, name = pop()
        cls = node.__class__
        nodes[cls.__name__] += 1
        if level > depth:
            depth = level
        if cls is ast.CallExpression:
            callee = expression_text(node.callee, 60)  # type: ignore[attr-defined]
            if node.method is not None:  # type: ignore[attr-defined]
                callee = f"{callee}:{node.method.name}"  # type: ignore[attr-defined]
            calls[callee] += 1
        elif cls is ast.StringLiteral:
            string_bytes += len(node.value)  # type: ignore[attr-defined]
        elif cls is ast.FunctionExpression:
            span = node.span
            functions.append((span.end.line - span.start.line + 1,
                              name or "", span.start.line))
        hint: str | None = None
        if cls is ast.FunctionStatement:
            hint = expression_text(node.name)  # type: ignore[attr-defined]
            if node.method is not None:  # type: ignore[attr-defined]
                hint = f"{hint}:{node.method.name}"  # type: ignore[attr-defined]
            push((node.function, level + 1, hint))  # type: ignore[attr-defined]
            push((node.name, level + 1, None))  # type: ignore[attr-defined]
            if node.method is not None:  # type: ignore[attr-defined]
                push((node.method, level + 1, None))  # type: ignore[attr-defined]
            continue
        if cls is ast.LocalStatement or cls is ast.AssignmentStatement:
            names = node.variables if cls is ast.LocalStatement else node.targets  # type: ignore[attr-defined]
            values = node.values  # type: ignore[attr-defined]
            for index, value in enumerate(values):
                bound = None
                if value.__class__ is ast.FunctionExpression and index < len(names):
                    target = names[index]
                    bound = (target.name.name if cls is ast.LocalStatement
                             else expression_text(target))
                push((value, level + 1, bound))
            for target in names:
                push((target, level + 1, None))
            continue
        if cls is ast.TableField and node.value.__class__ is ast.FunctionExpression:  # type: ignore[attr-defined]
            if node.key is not None:  # type: ignore[attr-defined]
                push((node.key, level + 1, None))  # type: ignore[attr-defined]
            push((node.value, level + 1, _field_name(node)))  # type: ignore[attr-defined, arg-type]
            continue
        for child in children(node):
            push((child, level + 1, None))

    span = tree.span
    kinds: Counter[str] = Counter(token.kind for token in tokens if token.kind != "eof")
    code_lines: set[int] = set()
    for token in tokens:
        if token.kind != "eof":
            code_lines.update(range(token.span.start.line, token.span.end.line + 1))
    comment_lines: set[int] = set()
    comment_characters = 0
    for comment in tree.comments:
        comment_lines.update(range(comment.span.start.line, comment.span.end.line + 1))
        comment_characters += len(comment.raw)
    # A final newline does not start another line.
    total_lines = span.end.line if span.end.column > 1 else span.end.line - 1
    functions.sort(key=lambda entry: (-entry[0], entry[2]))
    return {
        "lines": {"total": total_lines, "code": len(code_lines) if tokens else None,
                  "comment_only": len(comment_lines - code_lines) if tokens else None,
                  "blank": max(0, total_lines - len(code_lines | comment_lines)) if tokens else None},
        "characters": span.end.offset,
        "tokens": {"total": sum(kinds.values()), "kinds": dict(sorted(kinds.items()))} if tokens else None,
        "comments": {"total": len(tree.comments), "characters": comment_characters},
        "nodes": {"total": sum(nodes.values()), "depth": depth,
                  "types": dict(sorted(nodes.items(), key=lambda item: (-item[1], item[0])))},
        "functions": {"total": nodes["FunctionExpression"],
                      "longest": [{"name": name, "lines": lines, "line": line}
                                  for lines, name, line in functions[:top]]},
        "calls": {"total": nodes["CallExpression"],
                  "most_frequent": [{"name": name, "count": count}
                                    for name, count in calls.most_common(top)]},
        "strings": {"total": nodes["StringLiteral"], "bytes": string_bytes},
    }


# --------------------------------------------------------------------------- decisions
_LOOPS = (ast.WhileStatement, ast.RepeatStatement, ast.NumericForStatement,
          ast.GenericForStatement)


def excerpt(source: str, span: Span, limit: int = 72) -> str:
    """The source text of ``span`` on one line: spaces collapsed, cut at ``limit``."""
    text = source[span.start.offset:span.end.offset]
    # Reading a little more than needed is enough to fill the excerpt.
    text = " ".join(text[:limit * 6].split())
    if len(text) > limit:
        return text[:limit - 1].rstrip() + _ELLIPSIS
    if span.end.offset - span.start.offset > limit * 6:
        return text + _ELLIPSIS
    return text


def _statement_summary(source: str, statement: ast.Node, limit: int) -> str:
    """One line describing a statement; a definition is cut after its heading."""
    span = statement.span
    if statement.__class__ is ast.FunctionStatement:
        body = statement.function.body.span  # type: ignore[attr-defined]
        heading = Span(span.start, body.start)
        text = excerpt(source, heading, limit).rstrip()
        return text if text.endswith(")") else text + " " + _ELLIPSIS
    return excerpt(source, span, limit)


def function_metrics(function: ast.FunctionExpression | ast.Chunk) -> dict[str, int]:
    """Decision counts of one function body; nested functions are not included.

    ``complexity`` is one plus the number of tests the body can take: each
    ``if``/``elseif``, each loop, and each ``and``/``or`` in their conditions.
    ``nesting`` is the deepest level of control structures and ``exits`` the
    number of ``return`` statements.
    """
    body = function.body.body if isinstance(function, ast.FunctionExpression) else function.body
    decisions = loops = exits = statements = nesting = 0
    logical = 0
    stack: list[tuple[ast.Node, int, bool]] = [(statement, 0, False) for statement in body]
    while stack:
        node, level, in_condition = stack.pop()
        cls = node.__class__
        if cls is ast.FunctionExpression:
            continue  # Another function: it has its own mechanics.
        if cls is ast.FunctionStatement:
            statements += 1
            continue
        if isinstance(node, ast.BinaryExpression):
            if in_condition and node.operator in ("and", "or"):
                logical += 1
            stack.append((node.left, level, in_condition))
            stack.append((node.right, level, in_condition))
            continue
        if cls is ast.IfStatement:
            statements += 1
            nesting = max(nesting, level + 1)
            for clause in node.clauses:  # type: ignore[attr-defined]
                if clause.condition is not None:
                    decisions += 1
                    stack.append((clause.condition, level + 1, True))
                for statement in clause.body.body:
                    stack.append((statement, level + 1, False))
            continue
        if cls in _LOOPS:
            statements += 1
            loops += 1
            nesting = max(nesting, level + 1)
            condition = getattr(node, "condition", None)
            for child in ast.children(node):
                if child.__class__ is ast.Block:
                    for statement in child.body:  # type: ignore[attr-defined]
                        stack.append((statement, level + 1, False))
                else:
                    stack.append((child, level + 1, child is condition))
            continue
        if cls is ast.DoStatement:
            for statement in node.body.body:  # type: ignore[attr-defined]
                stack.append((statement, level, False))
            continue
        if cls in _STATEMENTS:
            # A plain statement: nothing inside its expressions is a decision of this body.
            statements += 1
            if cls is ast.ReturnStatement:
                exits += 1
            continue
        for child in ast.children(node):
            stack.append((child, level, in_condition))
    return {"complexity": 1 + decisions + loops + logical, "decisions": decisions,
            "loops": loops, "nesting": nesting, "exits": exits, "statements": statements}


_STATEMENTS = frozenset({ast.EmptyStatement, ast.BreakStatement, ast.ReturnStatement,
                         ast.CallStatement, ast.AssignmentStatement, ast.LocalStatement,
                         ast.GotoStatement, ast.LabelStatement})


def condition_terms(function: ast.FunctionExpression | ast.Chunk) -> list[tuple[str, int]]:
    """What the conditions of one function read: names and calls, most frequent first."""
    body = function.body.body if isinstance(function, ast.FunctionExpression) else function.body
    terms: Counter[str] = Counter()
    stack: list[tuple[ast.Node, bool]] = [(statement, False) for statement in body]
    while stack:
        node, in_condition = stack.pop()
        cls = node.__class__
        if cls is ast.FunctionExpression or cls is ast.FunctionStatement:
            continue
        if not in_condition and cls in _STATEMENTS:
            continue  # No condition is written inside a plain statement.
        if in_condition:
            if cls in (ast.Identifier, ast.MemberExpression, ast.IndexExpression):
                terms[expression_text(node, 60)] += 1
                continue
            if cls is ast.CallExpression:
                name = expression_text(node.callee, 60)  # type: ignore[attr-defined]
                if node.method is not None:  # type: ignore[attr-defined]
                    name = f"{name}:{node.method.name}"  # type: ignore[attr-defined]
                terms[name + "()"] += 1
                continue
        if cls is ast.IfStatement:
            for clause in node.clauses:  # type: ignore[attr-defined]
                if clause.condition is not None:
                    stack.append((clause.condition, True))
                stack.append((clause.body, False))
            continue
        if cls is ast.WhileStatement or cls is ast.RepeatStatement:
            stack.append((node.condition, True))  # type: ignore[attr-defined]
            stack.append((node.body, False))  # type: ignore[attr-defined]
            continue
        for child in ast.children(node):
            stack.append((child, in_condition))
    return sorted(terms.items(), key=lambda item: (-item[1], item[0]))


def decision_flow(function: ast.FunctionExpression | ast.Chunk, source: str, *,
                  budget: int = 4000, width: int = 72) -> dict[str, Any]:
    """The control structure of one function as nested JSON data.

    A ``sequence`` holds ``steps``. A step is an ``action`` (consecutive plain
    statements), an ``if`` with its ``branches`` and optional ``otherwise``, a
    loop (``while``, ``repeat``, ``for``) with its ``body``, or an exit
    (``return``, ``break``, ``goto``, ``error``). Offsets are code points.
    Statements are quoted on at most ``width`` characters, conditions on twice that.
    Nested function definitions are reported as actions, not expanded. When
    more than ``budget`` steps would be produced, the remaining bodies are
    replaced by a ``truncated`` step.
    """
    remaining = [budget]

    def sequence(statements: tuple[ast.Node, ...], depth: int) -> dict[str, Any]:
        steps: list[dict[str, Any]] = []
        action: dict[str, Any] | None = None
        if depth > 80 or remaining[0] <= 0:
            if statements:
                steps.append({"kind": "truncated", "count": len(statements)})
            return {"kind": "sequence", "steps": steps}
        for statement in statements:
            cls = statement.__class__
            span = statement.span
            step: dict[str, Any] | None = None
            if cls is ast.IfStatement:
                clauses = statement.clauses  # type: ignore[attr-defined]
                branches = [{"condition": excerpt(source, clause.condition.span, 2 * width),
                             "offset": clause.condition.span.start.offset,
                             "end_offset": clause.condition.span.end.offset,
                             "line": clause.condition.span.start.line,
                             "body": sequence(clause.body.body, depth + 1)}
                            for clause in clauses if clause.condition is not None]
                last = clauses[-1]
                step = {"kind": "if", "branches": branches,
                        "otherwise": sequence(last.body.body, depth + 1)
                        if last.condition is None else None}
            elif cls is ast.WhileStatement:
                step = {"kind": "while",
                        "condition": excerpt(source, statement.condition.span, 2 * width),  # type: ignore[attr-defined]
                        "body": sequence(statement.body.body, depth + 1)}  # type: ignore[attr-defined]
            elif cls is ast.RepeatStatement:
                step = {"kind": "repeat",
                        "condition": excerpt(source, statement.condition.span, 2 * width),  # type: ignore[attr-defined]
                        "body": sequence(statement.body.body, depth + 1)}  # type: ignore[attr-defined]
            elif cls is ast.NumericForStatement or cls is ast.GenericForStatement:
                heading = Span(span.start, statement.body.span.start)  # type: ignore[attr-defined]
                text = excerpt(source, heading, width + 8)
                if text.startswith("for "):
                    text = text[4:]
                if text.endswith(" do"):
                    text = text[:-3]
                step = {"kind": "for", "condition": text,
                        "body": sequence(statement.body.body, depth + 1)}  # type: ignore[attr-defined]
            elif cls is ast.DoStatement:
                inner = sequence(statement.body.body, depth)  # type: ignore[attr-defined]
                for inner_step in inner["steps"]:
                    if inner_step["kind"] == "action" and action is not None:
                        action["count"] += inner_step["count"]
                        action["lines"] = (action["lines"] + inner_step["lines"])[:4]
                        action["end_offset"] = inner_step["end_offset"]
                    else:
                        steps.append(inner_step)
                        action = inner_step if inner_step["kind"] == "action" else None
                continue
            elif cls is ast.ReturnStatement:
                step = {"kind": "return", "text": excerpt(source, span, width)}
            elif cls is ast.BreakStatement:
                step = {"kind": "break", "text": "break"}
            elif cls is ast.GotoStatement:
                step = {"kind": "goto", "text": "goto " + statement.name.name}  # type: ignore[attr-defined]
            elif cls is ast.LabelStatement:
                step = {"kind": "label", "text": "::" + statement.name.name + "::"}  # type: ignore[attr-defined]
            elif (cls is ast.CallStatement
                  and statement.expression.callee.__class__ is ast.Identifier  # type: ignore[attr-defined]
                  and statement.expression.callee.name == "error"  # type: ignore[attr-defined]
                  and statement.expression.method is None):  # type: ignore[attr-defined]
                step = {"kind": "error", "text": excerpt(source, span, width)}
            elif cls is ast.EmptyStatement:
                continue
            if step is None:
                # A plain statement: extend the current action box.
                if action is None:
                    action = {"kind": "action", "count": 0, "lines": [],
                              "offset": span.start.offset, "line": span.start.line,
                              "end_offset": span.end.offset}
                    steps.append(action)
                    remaining[0] -= 1
                action["count"] += 1
                action["end_offset"] = span.end.offset
                if len(action["lines"]) < 4:
                    action["lines"].append(_statement_summary(source, statement, width))
                continue
            step.setdefault("offset", span.start.offset)
            step.setdefault("end_offset", span.end.offset)
            step.setdefault("line", span.start.line)
            steps.append(step)
            remaining[0] -= 1
            action = None
        return {"kind": "sequence", "steps": steps}

    body = function.body.body if isinstance(function, ast.FunctionExpression) else function.body
    return sequence(body, 0)
