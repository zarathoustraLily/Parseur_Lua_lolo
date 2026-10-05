"""Typed syntax tree. Numeric lexemes stay exact; Lua strings contain bytes."""
from __future__ import annotations

from dataclasses import dataclass, fields
from collections.abc import Iterator
from json.encoder import encode_basestring_ascii as _quote
from typing import Any
from .model import Position, Span, Token, gc_paused


@dataclass(frozen=True, slots=True)
class Node:
    span: Span

    @property
    def type(self) -> str:
        return type(self).__name__

    def to_dict(self) -> dict[str, Any]:
        return to_dict(self)


# Field names of each node class, without ``span``: the tree is walked millions
# of times, so the dataclass introspection is done once per class.
_CHILD_FIELDS: dict[type, tuple[str, ...]] = {}
_SCALARS = frozenset({str, bool, int, float, type(None)})


def child_fields(cls: type) -> tuple[str, ...]:
    """Names of the fields of a node class, in declaration order, without ``span``."""
    names = _CHILD_FIELDS.get(cls)
    if names is None:
        names = _CHILD_FIELDS[cls] = tuple(f.name for f in fields(cls) if f.name != "span")
    return names


def _position_dict(position: Position) -> dict[str, int]:
    return {"offset": position[0], "line": position[1], "column": position[2]}


def _span_dict(span: Span) -> dict[str, dict[str, int]]:
    start, end = span
    return {"start": {"offset": start[0], "line": start[1], "column": start[2]},
            "end": {"offset": end[0], "line": end[1], "column": end[2]}}


def to_dict(value: Any) -> Any:
    """Convert trees to JSON data, preserving Lua bytes as integer arrays."""
    with gc_paused():
        return _to_dict(value)


def _to_dict(value: Any) -> Any:
    holder: list[Any] = [None]
    pending: list[tuple[Any, Any, Any]] = [(value, holder, 0)]
    pop = pending.pop
    push = pending.append
    scalars = _SCALARS
    while pending:
        item, parent, key = pop()
        cls = item.__class__
        if cls in scalars:
            parent[key] = item
        elif isinstance(item, Node):
            output: dict[str, Any] = {"type": cls.__name__, "span": _span_dict(item.span)}
            parent[key] = output
            for name in _CHILD_FIELDS.get(cls) or child_fields(cls):
                child = getattr(item, name)
                if child.__class__ in scalars:
                    output[name] = child
                else:
                    output[name] = None
                    push((child, output, name))
        elif cls is Token:
            token_value = item.value
            parent[key] = {"kind": item.kind,
                           "value": list(token_value) if isinstance(token_value, bytes) else token_value,
                           "raw": item.raw, "span": _span_dict(item.span)}
        elif cls is Span:
            parent[key] = _span_dict(item)
        elif cls is Position:
            parent[key] = _position_dict(item)
        elif isinstance(item, bytes):
            parent[key] = list(item)
        elif isinstance(item, (list, tuple)):
            output_list: list[Any] = [None] * len(item)
            parent[key] = output_list
            for index, child in enumerate(item):
                push((child, output_list, index))
        else:
            parent[key] = item
    return holder[0]


def iter_json(data: Any, *, indent: int | None = None) -> Iterator[str]:
    """Serialize JSON data (the output of :func:`to_dict`) as text chunks.

    The text is the one ``json.dumps`` produces with ``ensure_ascii=True`` and
    either ``indent`` or compact separators, but no recursion is involved: a
    tree of any depth can be written.
    """
    key_separator = ":" if indent is None else ": "
    pad = None if indent is None else " " * indent
    chunks: list[str] = []
    write = chunks.append
    stack: list[list[Any]] = []  # [iterator, is_mapping, is_first]
    value = data
    while True:
        if isinstance(value, dict):
            if value:
                write("{")
                stack.append([iter(value.items()), True, True])
            else:
                write("{}")
        elif isinstance(value, (list, tuple)):
            if value:
                write("[")
                stack.append([iter(value), False, True])
            else:
                write("[]")
        elif isinstance(value, str):
            write(_quote(value))
        elif value is None:
            write("null")
        elif value is True:
            write("true")
        elif value is False:
            write("false")
        elif isinstance(value, int):
            write(int.__repr__(value))
        elif isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                raise ValueError("JSON cannot represent NaN or infinity")
            write(float.__repr__(value))
        else:
            raise TypeError(f"{type(value).__name__} is not JSON data")
        # Find the next value to write, closing finished containers on the way.
        while stack:
            frame = stack[-1]
            try:
                entry = next(frame[0])
            except StopIteration:
                stack.pop()
                if pad is not None:
                    write("\n" + pad * len(stack))
                write("}" if frame[1] else "]")
                continue
            if frame[2]:
                frame[2] = False
            else:
                write(",")
            if pad is not None:
                write("\n" + pad * len(stack))
            if frame[1]:
                name, value = entry
                write(_quote(name))
                write(key_separator)
            else:
                value = entry
            break
        else:
            break
        if len(chunks) >= 8192:
            yield "".join(chunks)
            chunks.clear()
    if chunks:
        yield "".join(chunks)


@dataclass(frozen=True, slots=True)
class Identifier(Node):
    name: str


@dataclass(frozen=True, slots=True)
class NumberLiteral(Node):
    raw: str


@dataclass(frozen=True, slots=True)
class StringLiteral(Node):
    value: bytes
    raw: str


@dataclass(frozen=True, slots=True)
class BooleanLiteral(Node):
    value: bool


@dataclass(frozen=True, slots=True)
class NilLiteral(Node):
    pass


@dataclass(frozen=True, slots=True)
class VarargExpression(Node):
    pass


@dataclass(frozen=True, slots=True)
class UnaryExpression(Node):
    operator: str
    argument: Expression


@dataclass(frozen=True, slots=True)
class BinaryExpression(Node):
    operator: str
    left: Expression
    right: Expression


@dataclass(frozen=True, slots=True)
class ParenthesizedExpression(Node):
    expression: Expression


@dataclass(frozen=True, slots=True)
class MemberExpression(Node):
    base: Expression
    name: Identifier


@dataclass(frozen=True, slots=True)
class IndexExpression(Node):
    base: Expression
    index: Expression


@dataclass(frozen=True, slots=True)
class CallExpression(Node):
    callee: Expression
    arguments: tuple[Expression, ...]
    method: Identifier | None = None


@dataclass(frozen=True, slots=True)
class TableField(Node):
    kind: str  # 'value', 'name', or 'index'
    key: Expression | None
    value: Expression


@dataclass(frozen=True, slots=True)
class TableExpression(Node):
    fields: tuple[TableField, ...]


@dataclass(frozen=True, slots=True)
class FunctionExpression(Node):
    parameters: tuple[Identifier, ...]
    variadic: bool
    body: Block


@dataclass(frozen=True, slots=True)
class Block(Node):
    body: tuple[Statement, ...]


@dataclass(frozen=True, slots=True)
class Chunk(Node):
    body: tuple[Statement, ...]
    comments: tuple[Token, ...] = ()


@dataclass(frozen=True, slots=True)
class EmptyStatement(Node):
    pass


@dataclass(frozen=True, slots=True)
class BreakStatement(Node):
    pass


@dataclass(frozen=True, slots=True)
class ReturnStatement(Node):
    arguments: tuple[Expression, ...]


@dataclass(frozen=True, slots=True)
class CallStatement(Node):
    expression: CallExpression


@dataclass(frozen=True, slots=True)
class AssignmentStatement(Node):
    targets: tuple[Expression, ...]
    values: tuple[Expression, ...]


@dataclass(frozen=True, slots=True)
class LocalVariable(Node):
    name: Identifier
    attribute: str | None


@dataclass(frozen=True, slots=True)
class LocalStatement(Node):
    variables: tuple[LocalVariable, ...]
    values: tuple[Expression, ...]


@dataclass(frozen=True, slots=True)
class FunctionStatement(Node):
    name: Expression
    function: FunctionExpression
    local: bool
    method: Identifier | None = None


@dataclass(frozen=True, slots=True)
class DoStatement(Node):
    body: Block


@dataclass(frozen=True, slots=True)
class WhileStatement(Node):
    condition: Expression
    body: Block


@dataclass(frozen=True, slots=True)
class RepeatStatement(Node):
    body: Block
    condition: Expression


@dataclass(frozen=True, slots=True)
class IfClause(Node):
    condition: Expression | None
    body: Block


@dataclass(frozen=True, slots=True)
class IfStatement(Node):
    clauses: tuple[IfClause, ...]


@dataclass(frozen=True, slots=True)
class NumericForStatement(Node):
    variable: Identifier
    start: Expression
    stop: Expression
    step: Expression | None
    body: Block


@dataclass(frozen=True, slots=True)
class GenericForStatement(Node):
    variables: tuple[Identifier, ...]
    iterators: tuple[Expression, ...]
    body: Block


@dataclass(frozen=True, slots=True)
class LabelStatement(Node):
    name: Identifier


@dataclass(frozen=True, slots=True)
class GotoStatement(Node):
    name: Identifier


Expression = (Identifier | NumberLiteral | StringLiteral | BooleanLiteral | NilLiteral
              | VarargExpression | UnaryExpression | BinaryExpression
              | ParenthesizedExpression | MemberExpression | IndexExpression
              | CallExpression | TableExpression | FunctionExpression)
Statement = (EmptyStatement | BreakStatement | ReturnStatement | CallStatement
             | AssignmentStatement | LocalStatement | FunctionStatement | DoStatement
             | WhileStatement | RepeatStatement | IfStatement | NumericForStatement
             | GenericForStatement | LabelStatement | GotoStatement)


def children(node: Node) -> list[Node]:
    """Direct child nodes of ``node``, in source order."""
    result: list[Node] = []
    for name in _CHILD_FIELDS.get(node.__class__) or child_fields(node.__class__):
        value = getattr(node, name)
        if value.__class__ is tuple:
            for item in value:
                if isinstance(item, Node):
                    result.append(item)
        elif isinstance(value, Node):
            result.append(value)
    return result


def walk(root: Node) -> Iterator[Node]:
    """Iterative preorder traversal, including non-expression syntax nodes."""
    stack = [root]
    pop = stack.pop
    while stack:
        node = pop()
        yield node
        found = children(node)
        if found:
            found.reverse()
            stack.extend(found)
