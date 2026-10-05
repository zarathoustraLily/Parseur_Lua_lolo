"""State of a running Studio: analysed documents and folder checks.

Everything sent to the browser is plain JSON with French keys. Offsets are
converted to UTF-16 code units, the unit of a JavaScript string.
"""
from __future__ import annotations

import os
import threading
import time
from bisect import bisect_left
from collections import OrderedDict, deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import ast
from ..analysis import (Symbol, condition_terms, decision_flow, expression_text,
                        function_metrics, outline, statistics)
from ..batch import AUTO, FileReport, check_files, find_lua_files, read_source
from ..model import LuaSyntaxError, Token, gc_paused
from ..parser import Parser
from .messages import title, translate

TREE_BUDGET = 25_000        # Nodes sent with an analysis; deeper ones are fetched on demand.
SUBTREE_BUDGET = 6_000
MAX_FILES = 50_000
_KINDS = {"keyword": 0, "identifier": 1, "number": 2, "string": 3, "symbol": 4, "comment": 5}


def utf16_mapper(source: str) -> Callable[[int], int]:
    """Map a code-point offset of ``source`` to its UTF-16 offset."""
    if not source or max(source) <= "\uffff":
        return lambda offset: offset
    astral = [index for index, char in enumerate(source) if char > "\uffff"]
    return lambda offset: offset + bisect_left(astral, offset)


def encode_tree(root: ast.Node, to16: Callable[[int], int], budget: int) -> tuple[dict[str, Any], bool]:
    """Compact tree for the browser, breadth first so that a cut keeps the upper levels.

    A node becomes ``{"t": type, "a": start, "b": end, ...fields}``. Names and
    literals are read back from the source by the browser. A node whose
    children were left out carries ``"x": 1``.
    """
    def shell(node: ast.Node) -> dict[str, Any]:
        span = node.span
        return {"t": node.__class__.__name__, "a": to16(span.start.offset), "b": to16(span.end.offset)}

    result = shell(root)
    queue: deque[tuple[ast.Node, dict[str, Any]]] = deque([(root, result)])
    count = 1
    complete = True
    node_class = ast.Node
    identifier = ast.Identifier
    while queue:
        node, out = queue.popleft()
        cls = node.__class__
        for name in ast.child_fields(cls):
            value = getattr(node, name)
            value_class = value.__class__
            if value_class is tuple:
                if name == "comments":
                    continue
                items = []
                for item in value:
                    child = shell(item)
                    items.append(child)
                    count += 1
                    if count <= budget:
                        queue.append((item, child))
                    else:
                        _fill_stub(item, child)
                        complete = complete and "x" not in child
                out[name] = items
            elif isinstance(value, node_class):
                child = shell(value)
                out[name] = child
                count += 1
                if count <= budget:
                    queue.append((value, child))
                else:
                    _fill_stub(value, child)
                    complete = complete and "x" not in child
            elif value_class is bytes:
                out["n"] = len(value)
            elif name == "raw" or (name == "name" and cls is identifier):
                continue
            else:
                out[name] = value
    return result, complete


def _fill_stub(node: ast.Node, out: dict[str, Any]) -> None:
    """Scalar fields of a node that is sent without its children."""
    for name in ast.child_fields(node.__class__):
        value = getattr(node, name)
        if value.__class__ is tuple:
            if value and name != "comments":
                out["x"] = 1
        elif isinstance(value, ast.Node):
            out["x"] = 1
        elif value.__class__ is bytes:
            out["n"] = len(value)
        elif name != "raw" and not (name == "name" and node.__class__ is ast.Identifier):
            out[name] = value


def _symbol(symbol: Symbol, to16: Callable[[int], int]) -> dict[str, Any]:
    output: list[dict[str, Any]] = []
    pending: list[tuple[Symbol, list[dict[str, Any]]]] = [(symbol, output)]
    while pending:
        current, target = pending.pop()
        children: list[dict[str, Any]] = []
        entry: dict[str, Any] = {
            "nom": current.name, "genre": current.kind, "local": current.local,
            "ligne": current.span.start.line,
            "a": to16(current.span.start.offset), "b": to16(current.span.end.offset),
            "enfants": children}
        if current.parameters is not None:
            entry["params"] = list(current.parameters)
        if current.fields is not None:
            entry["champs"] = current.fields
        if current.value is not None:
            entry["valeur"] = current.value
        target.append(entry)
        for child in reversed(current.children):
            pending.append((child, children))
    return output[0]


class Document:
    """One analysed text, kept so that the browser can ask for more detail."""

    def __init__(self, identifier: str, name: str, source: str, max_depth: int,
                 encoding: str = "utf-8") -> None:
        self.id = identifier
        self.name = name
        self.source = source
        if encoding != "utf-8":
            # The text of an old Latin-1 file keeps its bytes, unless it was edited
            # with characters that this encoding cannot hold.
            try:
                source.encode(encoding)
            except UnicodeEncodeError:
                encoding = "utf-8"
        self.encoding = encoding
        self.to16 = utf16_mapper(source)
        self.tokens: tuple[Token, ...] | None = None
        self.comments: tuple[Token, ...] = ()
        self.tree: ast.Chunk | None = None
        self.error: dict[str, Any] | None = None
        self._merged: list[Token] | None = None
        self._measures: dict[str, Any] | None = None
        self._functions: list[dict[str, Any]] | None = None
        self._function_nodes: dict[int, ast.FunctionExpression] = {}
        self.milliseconds: dict[str, float] = {}
        started = time.perf_counter()
        lexed = started
        try:
            parser = Parser(source, filename=name, max_depth=max_depth, encoding=encoding)
            self.tokens = parser.tokens
            self.comments = parser.lexer.comments
            lexed = time.perf_counter()
            self.tree = parser.parse()
        except LuaSyntaxError as error:
            if self.tokens is None:
                lexed = time.perf_counter()
            self.error = self._diagnostic(error, "syntaxe" if self.tokens is not None else "lexique")
        finished = time.perf_counter()
        self.milliseconds = {"lexique": round((lexed - started) * 1000, 2),
                             "syntaxe": round((finished - lexed) * 1000, 2)}

    def _diagnostic(self, error: LuaSyntaxError, stage: str) -> dict[str, Any]:
        start, end = error.span
        a = self.to16(start.offset)
        return {"code": error.code, "titre": title(error.code), "message": error.message,
                "message_fr": translate(error.code, error.message),
                "ligne": start.line, "colonne": start.column, "etape": stage,
                "a": a, "b": max(a, self.to16(end.offset))}

    # ------------------------------------------------------------------ summary
    def summary(self, budget: int = TREE_BUDGET) -> dict[str, Any]:
        started = time.perf_counter()
        data: dict[str, Any] = {
            "doc": self.id, "nom": self.name, "ok": self.error is None, "erreur": self.error,
            "encodage": self.encoding,
            "arbre": None, "elague": False, "plan": None, "fonctions": None,
            "jetons": None if self.tokens is None else len(self.tokens) - 1,
            "commentaires": len(self.comments),
        }
        if self.tree is not None:
            with gc_paused():
                tree, complete = encode_tree(self.tree, self.to16, budget)
                data["arbre"] = tree
                data["elague"] = not complete
                data["plan"] = [_symbol(symbol, self.to16) for symbol in outline(self.tree)]
                data["fonctions"] = self.functions()
        self.milliseconds["preparation"] = round((time.perf_counter() - started) * 1000, 2)
        data["ms"] = dict(self.milliseconds)
        return data

    def measures(self) -> dict[str, Any] | None:
        """Counts of the whole document, computed when the browser first asks for them."""
        if self.tree is None:
            return None
        if self._measures is None:
            with gc_paused():
                self._measures = statistics(self.tree, self.tokens or ())
        return self._measures

    # ---------------------------------------------------------------- functions
    def functions(self) -> list[dict[str, Any]]:
        """Every function of the document with its decision counts, in source order."""
        if self._functions is not None:
            return self._functions
        assert self.tree is not None
        found: list[dict[str, Any]] = []
        # Only the parts of the tree whose text holds a ``function`` keyword are visited.
        keywords = [token.span.start.offset for token in self.tokens or ()
                    if token.kind == "keyword" and token.value == "function"]
        chunk = function_metrics(self.tree)
        end = self.tree.span.end
        found.append(dict(chunk, nom="", genre="script", ligne=1, a=0, b=self.to16(end.offset),
                          lignes=end.line if end.column > 1 else end.line - 1, params=None, id=0))
        stack: list[tuple[ast.Node, str]] = [(self.tree, "")]
        while stack:
            node, hint = stack.pop()
            span = node.span
            if bisect_left(keywords, span.start.offset) == bisect_left(keywords, span.end.offset):
                continue
            cls = node.__class__
            if cls is ast.FunctionExpression:
                identifier = len(self._function_nodes) + 1
                self._function_nodes[identifier] = node  # type: ignore[assignment]
                parameters = [parameter.name for parameter in node.parameters]  # type: ignore[attr-defined]
                if node.variadic:  # type: ignore[attr-defined]
                    parameters.append("...")
                found.append(dict(function_metrics(node),  # type: ignore[arg-type]
                                  nom=hint, genre="fonction", ligne=node.span.start.line,
                                  lignes=node.span.end.line - node.span.start.line + 1,
                                  a=self.to16(node.span.start.offset),
                                  b=self.to16(node.span.end.offset), params=parameters,
                                  id=identifier))
            if cls is ast.FunctionStatement:
                name = expression_text(node.name)  # type: ignore[attr-defined]
                if node.method is not None:  # type: ignore[attr-defined]
                    name = f"{name}:{node.method.name}"  # type: ignore[attr-defined]
                stack.append((node.function, name))  # type: ignore[attr-defined]
                continue
            if cls is ast.LocalStatement or cls is ast.AssignmentStatement:
                names = node.variables if cls is ast.LocalStatement else node.targets  # type: ignore[attr-defined]
                values = node.values  # type: ignore[attr-defined]
                for index in range(len(values) - 1, -1, -1):
                    bound = ""
                    if index < len(names) and values[index].__class__ is ast.FunctionExpression:
                        target = names[index]
                        bound = (target.name.name if cls is ast.LocalStatement
                                 else expression_text(target))
                    stack.append((values[index], bound))
                for target in reversed(names):
                    stack.append((target, ""))
                continue
            if cls is ast.TableField and node.value.__class__ is ast.FunctionExpression:  # type: ignore[attr-defined]
                key = node.key  # type: ignore[attr-defined]
                bound = key.name if node.kind == "name" else ""  # type: ignore[attr-defined]
                if not bound and key.__class__ is ast.StringLiteral:
                    bound = key.value.decode("utf-8", "replace")
                stack.append((node.value, bound))  # type: ignore[attr-defined]
                continue
            if cls is ast.CallExpression:
                callee = expression_text(node.callee, 60)  # type: ignore[attr-defined]
                if node.method is not None:  # type: ignore[attr-defined]
                    callee = f"{callee}:{node.method.name}"  # type: ignore[attr-defined]
                for argument in reversed(node.arguments):  # type: ignore[attr-defined]
                    anonymous = argument.__class__ is ast.FunctionExpression
                    stack.append((argument, f"{callee}(\u2026)" if anonymous else ""))
                stack.append((node.callee, ""))  # type: ignore[attr-defined]
                continue
            for child in reversed(ast.children(node)):
                stack.append((child, ""))
        found.sort(key=lambda entry: (entry["a"], -entry["b"]))
        self._functions = found
        return found

    def decisions(self, identifier: int) -> dict[str, Any] | None:
        """The decision diagram of one function (0 is the script itself)."""
        if self.tree is None:
            return None
        self.functions()
        node: ast.FunctionExpression | ast.Chunk | None
        node = self.tree if identifier == 0 else self._function_nodes.get(identifier)
        if node is None:
            return None
        flow = decision_flow(node, self.source)
        to16 = self.to16
        pending = [flow]
        while pending:  # Offsets become UTF-16 offsets, keys become French.
            item = pending.pop()
            for key in ("offset", "end_offset"):
                if key in item:
                    item["a" if key == "offset" else "b"] = to16(item.pop(key))
            if "line" in item:
                item["ligne"] = item.pop("line")
            for key in ("steps", "branches"):
                pending.extend(item.get(key, ()))
            for key in ("body", "otherwise"):
                if item.get(key):
                    pending.append(item[key])
        return {"flux": flow, "mesures": function_metrics(node),
                "termes": [{"nom": name, "nombre": count}
                           for name, count in condition_terms(node)[:14]]}

    # ------------------------------------------------------------------- tokens
    def merged(self) -> list[Token]:
        if self._merged is None:
            tokens = list(self.tokens[:-1]) if self.tokens else []
            tokens.extend(self.comments)
            tokens.sort(key=lambda token: token.span.start.offset)
            self._merged = tokens
        return self._merged

    def token_page(self, start: int, count: int, around: int | None = None) -> dict[str, Any]:
        tokens = self.merged()
        to16 = self.to16
        located = None
        if around is not None and tokens:
            located = bisect_left(tokens, around, key=lambda token: to16(token.span.end.offset))
            located = min(located, len(tokens) - 1)
            start = located - located % count
        start = max(0, min(start, max(0, len(tokens) - 1)))
        rows = []
        for token in tokens[start:start + count]:
            position = token.span.start
            value = token.value
            rows.append([_KINDS[token.kind], to16(position.offset), to16(token.span.end.offset),
                         position.line, position.column,
                         repr(value)[2:-1][:200] if isinstance(value, bytes) else None])
        return {"total": len(tokens), "debut": start, "jetons": rows, "vise": located}

    # --------------------------------------------------------------------- tree
    def subtree(self, path: list[list[Any]]) -> dict[str, Any] | None:
        node: Any = self.tree
        try:
            for name, index in path:
                if name == "span" or name.startswith("_"):
                    return None
                node = getattr(node, name)
                if index is not None and index >= 0:
                    node = node[index]
        except (AttributeError, IndexError, TypeError):
            return None
        if not isinstance(node, ast.Node):
            return None
        return encode_tree(node, self.to16, SUBTREE_BUDGET)[0]


class Job:
    """A folder check running in the background."""

    def __init__(self, identifier: str, root: str, files: list[Path]) -> None:
        self.id = identifier
        self.root = root
        self.files = files
        self.reports: list[dict[str, Any]] = []
        self.valid = 0
        self.failed = 0
        self.finished = False
        self.stopped = False
        self.started = time.perf_counter()
        self.seconds = 0.0
        self.lock = threading.Lock()

    def run(self) -> None:
        def receive(report: FileReport) -> None:
            entry = file_report(report, self.root)
            with self.lock:
                self.reports.append(entry)
                if report.ok:
                    self.valid += 1
                else:
                    self.failed += 1
        try:
            check_files(self.files, encoding=AUTO, on_result=receive,
                        should_stop=lambda: self.stopped)
        finally:
            with self.lock:
                self.seconds = time.perf_counter() - self.started
                self.finished = True

    def state(self, since: int) -> dict[str, Any]:
        with self.lock:
            return {"tache": self.id, "total": len(self.files), "faits": len(self.reports),
                    "valides": self.valid, "erreurs": self.failed, "termine": self.finished,
                    "arretee": self.stopped,
                    "duree": round(self.seconds if self.finished
                                   else time.perf_counter() - self.started, 2),
                    "nouveaux": self.reports[since:]}


def relative(path: str, root: str) -> str:
    try:
        return Path(path).relative_to(root).as_posix()
    except ValueError:
        return Path(path).as_posix()


def file_report(report: FileReport, root: str) -> dict[str, Any]:
    entry: dict[str, Any] = {"chemin": relative(report.path, root), "ok": report.ok,
                             "octets": report.size, "lignes": report.lines,
                             "jetons": report.tokens, "ms": round(report.seconds * 1000, 1),
                             "encodage": report.encoding, "erreur": None}
    if report.error is not None:
        error = report.error
        entry["erreur"] = {"code": error["code"], "titre": title(error["code"]),
                           "message": error["message"],
                           "message_fr": translate(error["code"], error["message"]),
                           "ligne": error["line"], "colonne": error["column"]}
    return entry


class Session:
    """Documents and folders opened from one Studio."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.documents: OrderedDict[str, Document] = OrderedDict()
        self.jobs: dict[str, Job] = {}
        self.roots: list[str] = []
        self._counter = 0

    def _next(self, prefix: str) -> str:
        with self.lock:
            self._counter += 1
            return f"{prefix}{self._counter}"

    def analyse(self, source: str, name: str, max_depth: int = 150,
                encoding: str = "utf-8") -> Document:
        document = Document(self._next("d"), name, source, max_depth, encoding)
        with self.lock:
            self.documents[document.id] = document
            while len(self.documents) > 3:
                self.documents.popitem(last=False)
        return document

    def document(self, identifier: str) -> Document | None:
        with self.lock:
            return self.documents.get(identifier)

    # ------------------------------------------------------------------ folders
    def open_folder(self, path: str) -> dict[str, Any]:
        root = os.path.realpath(path)
        if not os.path.isdir(root):
            raise FileNotFoundError(path)
        files = find_lua_files(root)
        truncated = len(files) > MAX_FILES
        files = files[:MAX_FILES]
        entries = []
        total = 0
        for file in files:
            try:
                size = file.stat().st_size
            except OSError:
                size = 0
            total += size
            entries.append({"chemin": relative(str(file), root), "octets": size})
        with self.lock:
            if root not in self.roots:
                self.roots.append(root)
        return {"racine": root, "fichiers": entries, "octets": total, "tronque": truncated}

    def resolve(self, root: str, relative_path: str) -> str:
        """Absolute path of a ``.lua`` file inside a folder opened in this session."""
        base = os.path.realpath(root)
        with self.lock:
            allowed = base in self.roots
        target = os.path.realpath(os.path.join(base, relative_path))
        inside = target == base or target.startswith(base.rstrip("\\/") + os.sep)
        if not allowed or not inside or not target.lower().endswith(".lua"):
            raise PermissionError(relative_path)
        return target

    def read_file(self, root: str, relative_path: str, limit: int = 10_000_000) -> dict[str, Any]:
        target = self.resolve(root, relative_path)
        text, encoding = read_source(target, AUTO, limit=limit)
        return {"texte": text[:limit], "encodage": encoding, "octets": os.path.getsize(target),
                "nom": os.path.basename(target), "chemin": relative_path,
                "tronque": len(text) > limit}

    def start_check(self, root: str) -> Job:
        base = os.path.realpath(root)
        with self.lock:
            if base not in self.roots:
                raise PermissionError(root)
        job = Job(self._next("t"), base, find_lua_files(base)[:MAX_FILES])
        with self.lock:
            self.jobs[job.id] = job
            for identifier in list(self.jobs)[:-4]:
                if self.jobs[identifier].finished:
                    del self.jobs[identifier]
        threading.Thread(target=job.run, name=f"verification-{job.id}", daemon=True).start()
        return job


def list_folders(path: str | None) -> dict[str, Any]:
    """Sub-folders of ``path`` for the folder picker; drives on Windows when ``path`` is empty."""
    drives: list[str] = []
    if os.name == "nt":
        lister = getattr(os, "listdrives", None)
        if lister is not None:
            drives = list(lister())
        else:
            drives = [f"{letter}:\\" for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
                      if os.path.isdir(f"{letter}:\\")]
    if not path:
        path = os.getcwd()
    current = os.path.realpath(path)
    if not os.path.isdir(current):
        raise FileNotFoundError(path)
    folders: list[str] = []
    scripts = 0
    try:
        with os.scandir(current) as entries:
            for entry in entries:
                try:
                    if entry.is_dir():
                        folders.append(entry.name)
                    elif entry.name.lower().endswith(".lua"):
                        scripts += 1
                except OSError:
                    continue
    except OSError as error:
        raise PermissionError(str(error)) from error
    folders.sort(key=str.lower)
    parent = os.path.dirname(current)
    return {"chemin": current, "parent": parent if parent and parent != current else None,
            "dossiers": folders, "lua": scripts, "lecteurs": drives, "separateur": os.sep}
