"""Export of the decision diagrams of a Lua script as one standalone HTML page.

The page holds everything it needs: the analysis as JSON data, the drawing
module shared with the Studio (``organigramme.js``), the reader script
(``rapport.js``), the styles and the fonts. It opens from a file in any recent
web browser, without the Studio or a network connection, and loads nothing.
Every character of it is ASCII, so that no console code page or shell
redirection can damage it.

The description of a function is the block of comments written right above
it (the ``@param`` and ``@return`` tags of LDoc and EmmyLua are recognised),
completed by what the analysis reads in its text: its decisions, the names
its conditions read, the functions of the script it calls and those that
call it. Nothing is executed.
"""
from __future__ import annotations

import base64
import datetime
import html
import json
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .. import __version__, ast
from ..analysis import expression_text
from ..model import LuaSyntaxError, Token
from ..parser import parse
from .session import Document

STATIC = Path(__file__).resolve().parent / "static"
DESCRIPTION_LIMIT = 1200

_DECORATION = re.compile(r"[\s\-=*#~_+/\\|.:<>]*")
_TAG = re.compile(r"@([A-Za-z_]+)(?:\[[^\]]*\])?\s*(.*)", re.S)
_CODE_MARKS = frozenset("()={}[]")
_LIST_ITEM = re.compile(r"(?:[-*+\u2022]|\d+[.)])\s")
_SEGMENT = re.compile(r"[.:]")
_FONT = re.compile(r'url\("fonts/([A-Za-z0-9.-]+\.woff2)"\)')
_EXPORT = re.compile(r"^export (?:async )?(?:function\*?|const|let|class) ([A-Za-z_$][\w$]*)", re.M)
_IMPORT = re.compile(r'^import \{([^}]*)\} from "\./organigramme\.js";$', re.M)
_NON_ASCII = re.compile(r"[^\x00-\x7f]")


# ---------------------------------------------------------------- the page
def build_report(source: str, name: str = "script.lua", *, max_depth: int = 150,
                 max_tokens: int = 1_000_000, max_source_length: int = 10_000_000,
                 encoding: str = "utf-8", date: datetime.date | None = None) -> str:
    """The HTML page of ``source``; raise :class:`LuaSyntaxError` if it is not valid Lua.

    ``name`` is shown in the page without its folders. ``date`` is the date of
    the export written in the page, today by default.
    """
    document = Document("export", name, source, max_depth, encoding,
                        max_tokens=max_tokens, max_source_length=max_source_length)
    if document.exception is not None:
        raise document.exception
    return report_page(document, date=date)


def report_page(document: Document, *, date: datetime.date | None = None) -> str:
    """The HTML page of a document analysed without error."""
    return render_page(report_data(document, date=date))


def render_page(data: dict[str, Any]) -> str:
    """Assemble the page around the data of :func:`report_data`."""
    styles = _FONT.sub(_font_url, _read("app.css")) + "\n" + _read("rapport.css")
    script = _bundle(_read("organigramme.js"), _read("rapport.js"))
    if "</style" in styles.lower():
        raise RuntimeError("the style sheets must not close their element")
    head = _HEAD.replace("{titre}", html.escape(f"Décisions de {data['nom']}"))
    head = head.replace("{version}", html.escape(data["version"]))
    head = head.replace("{icone}", _ICON)
    body = _BODY.replace("{nom}", html.escape(data["nom"]))
    page = "".join((
        _html_ascii(head), "<style>\n", _css_ascii(styles), "</style>\n</head>\n",
        _html_ascii(body),
        '<script type="application/json" id="donnees">', _json_ascii(data), "</script>\n",
        '<script type="module">\n', _script_safe(_js_ascii(script)), "</script>\n",
        "</body>\n</html>\n",
    ))
    assert page.isascii()
    return page


def _read(name: str) -> str:
    return (STATIC / name).read_text(encoding="utf-8")


def _font_url(match: re.Match[str]) -> str:
    data = base64.b64encode((STATIC / "fonts" / match[1]).read_bytes()).decode("ascii")
    return f'url("data:font/woff2;base64,{data}")'


def _bundle(shared: str, reader: str) -> str:
    """One script: the shared drawing module, wrapped, then the reader that imports it."""
    names = _EXPORT.findall(shared)
    body = re.sub(r"^export ", "", shared, flags=re.M)
    module = f"const __organigramme = (() => {{\n{body}\nreturn {{ {', '.join(names)} }};\n}})();\n"
    reader, count = _IMPORT.subn(lambda match: f"const {{{match[1]}}} = __organigramme;", reader)
    if count != 1 or re.search(r"^import\b", reader, re.M):
        raise RuntimeError("rapport.js must import organigramme.js, and nothing else")
    return module + reader


def _html_ascii(text: str) -> str:
    return text.encode("ascii", "xmlcharrefreplace").decode("ascii")


def _css_ascii(text: str) -> str:
    return _NON_ASCII.sub(lambda match: f"\\{ord(match[0]):06X}", text)


def _js_escape(match: re.Match[str]) -> str:
    code = ord(match[0])
    if code <= 0xFFFF:
        return f"\\u{code:04x}"
    code -= 0x10000
    return f"\\u{0xD800 + (code >> 10):04x}\\u{0xDC00 + (code & 0x3FF):04x}"


def _js_ascii(text: str) -> str:
    # Valid everywhere in this code: strings, templates, regular expressions and comments.
    return _NON_ASCII.sub(_js_escape, text)


def _script_safe(text: str) -> str:
    """Nothing in a script may end its element or open an HTML comment."""
    return re.sub(r"<(/script|!--)", lambda match: "<\\" + match[1], text, flags=re.I)


def _json_ascii(data: Any) -> str:
    text = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    # « < » only appears inside strings, where < means the same.
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


_ICON = "data:image/svg+xml," + quote(
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>"
    "<rect width='32' height='32' rx='7' fill='#121935'/>"
    "<circle cx='16' cy='16' r='10.5' fill='#f6e7b4'/>"
    "<g fill='#786020' fill-opacity='.28'><circle cx='19.6' cy='11.6' r='1.9'/>"
    "<circle cx='12.4' cy='18.4' r='2.5'/><circle cx='20' cy='20.4' r='1.2'/></g></svg>",
    safe="/:=' ")

_HEAD = """<!doctype html>
<html lang="fr" data-theme="nuit">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark light">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; font-src data:; img-src data:; base-uri 'none'; form-action 'none'">
<meta name="generator" content="lua-parser-pro {version}">
<title>{titre}</title>
<link rel="icon" href="{icone}">
<script>
var theme = null;
try { theme = localStorage.getItem("lua-rapport:theme"); } catch (erreur) {}
if (theme !== "jour" && theme !== "nuit") theme = matchMedia("(prefers-color-scheme: light)").matches ? "jour" : "nuit";
document.documentElement.dataset.theme = theme;
</script>
"""

_BODY = """<body>
<div class="app rapport" id="rapport" data-etat="valide">

  <header class="entete">
    <div class="marque">
      <svg class="lune" viewBox="0 0 40 40" aria-hidden="true">
        <circle class="lune-halo" cx="20" cy="20" r="17"></circle>
        <circle class="lune-ombre" cx="20" cy="20" r="13"></circle>
        <path class="lune-clair" d="M20 7A13 13 0 0 1 20 33A13 13 0 0 1 20 7Z"></path>
        <g class="lune-relief">
          <circle cx="24.5" cy="14.5" r="2.4"></circle>
          <circle cx="15.5" cy="23" r="3.1"></circle>
          <circle cx="25" cy="25.5" r="1.5"></circle>
        </g>
      </svg>
      <div class="marque-texte">
        <span class="marque-nom">Parseur Lua</span>
        <span class="marque-etat">Décisions exportées</span>
      </div>
    </div>
    <div class="document">
      <span class="document-nom">{nom}</span>
      <span class="document-detail" id="document-detail"></span>
    </div>
    <nav class="actions" aria-label="Affichage">
      <button class="bouton" id="btn-aide" type="button" aria-expanded="false" aria-controls="aide">Lire ce diagramme</button>
      <button class="bouton" id="btn-theme" type="button">Jour</button>
    </nav>
  </header>

  <main class="lecture" id="lecture">
    <aside class="volet sommaire" aria-label="Fonctions du script">
      <div class="volet-entete">
        <h2 class="volet-titre">Fonctions</h2>
        <span class="vue-note" id="sommaire-compte"></span>
      </div>
      <div class="sommaire-outils">
        <input class="champ" id="filtre" type="search" placeholder="Filtrer par nom ou description" aria-label="Filtrer les fonctions">
        <select class="champ" id="tri" aria-label="Ordre des fonctions">
          <option value="texte">Dans l'ordre du texte</option>
          <option value="complexite">Les plus complexes d'abord</option>
        </select>
      </div>
      <div class="sommaire-liste" id="liste" role="listbox" tabindex="0" aria-label="Fonctions"></div>
    </aside>

    <section class="volet fiche" aria-labelledby="fiche-titre">
      <div class="aide" id="aide" hidden>
        <strong>Lire l'organigramme</strong>
        <ul>
          <li><span data-icone="depart"></span><span>En haut, l'entrée dans la fonction. Le flux descend le long d'une colonne.</span></li>
          <li><span data-icone="test"></span><span>Un test (<code>if</code>, <code>elseif</code>) : si la réponse est « oui », le flux part à droite ; sinon il continue vers le bas.</span></li>
          <li><span data-icone="boucle"></span><span>Une boucle (<code>while</code>, <code>for</code>, <code>repeat … until</code>) : le retour remonte par la gauche, la sortie passe par la droite.</span></li>
          <li><span data-icone="action"></span><span>Des instructions qui se suivent sans décision. Quatre lignes au plus sont citées, le reste est compté.</span></li>
          <li><span data-icone="sortie"></span><span>Une sortie (<code>return</code>, <code>break</code>, <code>goto</code>), en rouge pour un appel à <code>error</code>.</span></li>
          <li><span data-icone="pli"></span><span>Des étapes repliées : un clic les déplie. Un double-clic sur un test ou une boucle replie ou déplie ce qui en dépend ; « Niveaux » replie tout un étage.</span></li>
        </ul>
        <p>Survolez une fonction ou une forme pour lire sa description et les fonctions qu'elle appelle ; un clic sur une forme montre son code. « Arbre » présente les mêmes décisions en liste indentée. Ctrl + molette pour zoomer, glisser pour se déplacer. La description d'une fonction vient des commentaires écrits juste au-dessus d'elle ; le reste est lu dans son code, sans l'exécuter.</p>
      </div>
      <div class="fiche-entete" id="fiche-entete"></div>
      <div class="decisions-resume" id="resume"></div>
      <div class="vue-outils">
        <span class="onglets-vue" role="group" aria-label="Présentation">
          <button class="bouton bouton-discret" type="button" data-vue="organigramme" aria-pressed="true">Organigramme</button>
          <button class="bouton bouton-discret" type="button" data-vue="arbre" aria-pressed="false">Arbre</button>
        </span>
        <span class="niveaux" id="niveaux" role="group" aria-label="Niveaux d'imbrication montrés">
          <span class="niveaux-nom">Niveaux</span>
          <button class="bouton bouton-discret" type="button" data-niveau="1" aria-pressed="false">1</button>
          <button class="bouton bouton-discret" type="button" data-niveau="2" aria-pressed="false">2</button>
          <button class="bouton bouton-discret" type="button" data-niveau="3" aria-pressed="false">3</button>
          <button class="bouton bouton-discret" type="button" data-niveau="tout" aria-pressed="true">Tous</button>
        </span>
        <span class="zoom" id="zoom">
          <button class="bouton bouton-discret" id="zoom-moins" type="button" aria-label="Réduire">−</button>
          <button class="bouton bouton-discret" id="zoom-ajuster" type="button">Ajuster</button>
          <button class="bouton bouton-discret" id="zoom-plus" type="button" aria-label="Agrandir">+</button>
        </span>
        <button class="bouton bouton-discret bouton-code" id="btn-code" type="button" aria-pressed="false" aria-controls="code">Code</button>
      </div>
      <div class="fiche-corps" id="fiche-corps">
        <div class="decisions-toile" id="toile" tabindex="0" aria-label="Organigramme des décisions"></div>
        <div class="arbre-decisions" id="arbre" hidden></div>
        <aside class="code" id="code" aria-label="Code de la fonction" hidden>
          <div class="code-defile" id="code-defile">
            <pre class="code-numeros" id="code-numeros" aria-hidden="true"></pre>
            <div class="code-zone">
              <div class="code-marque" id="code-marque" hidden></div>
              <pre class="code-texte" id="code-texte"></pre>
            </div>
          </div>
        </aside>
      </div>
    </section>
  </main>
</div>
<div class="infobulle" id="infobulle" role="tooltip" hidden></div>
<noscript><p class="sans-script">Cette page a besoin de JavaScript pour dessiner les organigrammes.</p></noscript>
"""


# ---------------------------------------------------------------- the data
def report_data(document: Document, *, date: datetime.date | None = None) -> dict[str, Any]:
    """The analysis written into the page, as JSON data with French keys like the Studio's.

    Each function of :meth:`Document.functions` gains its decision flow
    (``flux``), the names its conditions read (``termes``), its description
    (``doc``), the functions of the script it calls (``appelle``) and those
    that call it (``appelee_par``), its other calls (``externes``), its last
    line (``fin``) and the number of functions around it (``profondeur``).
    In the flow, a shape that calls functions of the script lists them in
    ``appels``. Offsets are UTF-16 offsets into ``source``.
    """
    tree = document.tree
    if tree is None:
        raise ValueError("the document has no syntax tree")
    to16 = document.to16
    comments = _CommentIndex(document)
    resolver = _Resolver(document.functions())
    entries: list[dict[str, Any]] = []
    callers: dict[int, list[int]] = {}
    enclosing: list[dict[str, Any]] = []
    first_function = min((function["ligne"] for function in document.functions()
                          if function["genre"] != "script"), default=0)
    for function in document.functions():
        identifier = function["id"]
        node = document.function_node(identifier)
        decisions = document.decisions(identifier)
        assert node is not None and decisions is not None
        resolved: list[tuple[int, int]] = []
        external: Counter[str] = Counter()
        for name, offset in _calls(node):
            start = to16(offset)
            target = resolver.resolve(name, start)
            if target is None:
                external[name] += 1
            else:
                resolved.append((start, target))
        _annotate(decisions["flux"], resolved)
        called = list(dict.fromkeys(target for _, target in resolved))
        for target in called:
            callers.setdefault(target, []).append(identifier)
        if function["genre"] == "script":
            depth = 0
            block = comments.header(first_function)
        else:
            while enclosing and enclosing[-1]["b"] <= function["a"]:
                enclosing.pop()
            depth = len(enclosing)
            enclosing.append(function)
            block = comments.above(function["ligne"])
        entry = dict(function)
        entry.update({
            "fin": function["ligne"] + max(function["lignes"], 1) - 1,
            "profondeur": depth,
            "doc": documentation(block),
            "termes": [[term["nom"], term["nombre"]] for term in decisions["termes"]],
            "appelle": called,
            "externes": [[name, count] for name, count in external.most_common(12)],
            "flux": decisions["flux"],
        })
        entries.append(entry)
    for entry in entries:
        entry["appelee_par"] = callers.get(entry["id"], [])
    return {
        "version": __version__,
        "nom": re.split(r"[\\/]", document.name)[-1] or "script.lua",
        "date": (date or datetime.date.today()).isoformat(),
        "source": document.source,
        "fonctions": entries,
    }


def _calls(node: ast.FunctionExpression | ast.Chunk) -> list[tuple[str, int]]:
    """Callee and start offset of every call in one function body, nested functions excluded."""
    body = node.body.body if isinstance(node, ast.FunctionExpression) else node.body
    found: list[tuple[str, int]] = []
    stack: list[ast.Node] = list(body)
    while stack:
        item = stack.pop()
        cls = item.__class__
        if cls is ast.FunctionExpression:
            continue  # Another function: its calls are its own.
        if cls is ast.CallExpression:
            name = expression_text(item.callee, 60)  # type: ignore[attr-defined]
            if item.method is not None:  # type: ignore[attr-defined]
                name = f"{name}:{item.method.name}"  # type: ignore[attr-defined]
            found.append((name, item.span.start.offset))
        stack.extend(ast.children(item))
    found.sort(key=lambda call: call[1])
    return found


class _Resolver:
    """Which function of the script a callee names, as far as the text tells.

    A name is matched exactly (``contient``, ``M.f``, ``Classe:m``); among
    several definitions of a name, the last one written before the call wins.
    ``objet:m()`` or ``self.m()`` also designate the only method or field
    function of the script whose name ends with ``m``.
    """

    def __init__(self, functions: Sequence[dict[str, Any]]) -> None:
        self.exact: dict[str, list[tuple[int, int]]] = {}
        self.member: dict[str, list[int]] = {}
        for function in functions:
            name = function["nom"]
            if function["genre"] == "script" or not name or name.endswith("(…)"):
                continue
            self.exact.setdefault(name, []).append((function["a"], function["id"]))
            parts = _SEGMENT.split(name)
            if len(parts) > 1:
                self.member.setdefault(parts[-1], []).append(function["id"])

    def resolve(self, name: str, offset: int) -> int | None:
        candidates = self.exact.get(name)
        if candidates:
            target = candidates[0][1]
            for start, identifier in candidates:
                if start > offset:
                    break
                target = identifier
            return target
        parts = _SEGMENT.split(name)
        if len(parts) > 1:
            methods = self.member.get(parts[-1], ())
            if len(methods) == 1:
                return methods[0]
        return None


def _annotate(flow: dict[str, Any], calls: Sequence[tuple[int, int]]) -> None:
    """Write in each shape of ``flow`` the functions called by the text it stands for.

    A call belongs to the smallest shape around it: a box of statements, the
    condition of a test, the heading of a loop or an exit. The shapes of one
    flow are nested or apart, never astride, so one sweep is enough.
    """
    if not calls:
        return
    shapes: list[dict[str, Any]] = []
    pending = [flow]
    while pending:
        sequence = pending.pop()
        for step in sequence["steps"]:
            if step["kind"] == "if":
                for branch in step["branches"]:
                    shapes.append(branch)
                    pending.append(branch["body"])
                if step["otherwise"]:
                    pending.append(step["otherwise"])
                continue
            if "a" in step:
                shapes.append(step)
            if step.get("body"):
                pending.append(step["body"])
    shapes.sort(key=lambda shape: (shape["a"], -shape["b"]))
    around: list[dict[str, Any]] = []
    index = 0
    for start, target in calls:
        while index < len(shapes) and shapes[index]["a"] <= start:
            shape = shapes[index]
            index += 1
            while around and around[-1]["b"] <= shape["a"]:
                around.pop()
            around.append(shape)
        while around and around[-1]["b"] <= start:
            around.pop()
        if around:
            called = around[-1].setdefault("appels", [])
            if target not in called:
                called.append(target)


# ---------------------------------------------------------- descriptions
class _CommentIndex:
    """The comments alone on their lines, found by the line where they end."""

    def __init__(self, document: Document) -> None:
        code_lines: set[int] = set()
        for token in document.tokens or ():
            if token.kind != "eof":
                first, last = token.span.start.line, token.span.end.line
                code_lines.add(first)
                if last != first:
                    code_lines.update(range(first + 1, last + 1))
        self.first_code_line = min(code_lines, default=0)
        self.alone: list[Token] = []
        self.ending: dict[int, Token] = {}
        for comment in document.comments:
            first, last = comment.span.start.line, comment.span.end.line
            if comment.raw.startswith("#") or any(line in code_lines for line in range(first, last + 1)):
                continue
            self.alone.append(comment)
            self.ending[last] = comment

    def above(self, line: int) -> list[Token]:
        """The comments written on the lines right above ``line``, without a blank line."""
        block: list[Token] = []
        comment = self.ending.get(line - 1)
        while comment is not None:
            block.append(comment)
            comment = self.ending.get(comment.span.start.line - 1)
        block.reverse()
        return block

    def header(self, first_function: int = 0) -> list[Token]:
        """The comments at the top of the file, before its first line of code.

        When that line starts a function (``first_function``), the comments
        right above it describe the function, not the file.
        """
        if not self.first_code_line:
            return list(self.alone)
        header = [comment for comment in self.alone if comment.span.end.line < self.first_code_line]
        if first_function == self.first_code_line:
            attached = {id(comment) for comment in self.above(first_function)}
            header = [comment for comment in header if id(comment) not in attached]
        return header


def _is_code(text: str) -> bool:
    """Commented-out Lua: it parses, and holds brackets or an assignment."""
    text = text.strip()
    if not text or not _CODE_MARKS.intersection(text):
        return False
    try:
        tree = parse(text, comments=False, max_tokens=20_000, max_depth=60)
    except LuaSyntaxError:
        return False
    return bool(tree.body)


def documentation(comments: Sequence[Token]) -> dict[str, Any] | None:
    """The description written in a block of comments, or ``None`` if it says nothing.

    Returns ``{"texte", "params", "retours", "notes"}``: the text, its
    paragraphs apart; the ``@param`` (or ``@tparam``) tags as ``[name, text]``;
    the ``@return`` texts; the other tags. Comment markers, rules such as
    ``-----`` and commented-out code are left out.
    """
    if not comments or _is_code("\n".join(str(comment.value) for comment in comments)):
        return None
    lines: list[str] = []
    previous = comments[0].span.start.line
    for comment in comments:
        if comment.span.start.line > previous + 1:
            lines.append("")  # A blank line between two comments separates paragraphs.
        previous = comment.span.end.line
        text = comment.value if isinstance(comment.value, str) else ""
        if comment.raw.startswith("---") and text.startswith("-"):
            text = text[1:]  # LDoc and EmmyLua write three dashes.
        if _is_code(text):
            continue
        for line in text.splitlines() or [""]:
            line = line.strip()
            lines.append("" if _DECORATION.fullmatch(line) or _is_code(line) else line)
    description: list[str] = []
    params: list[list[str]] = []
    returns: list[str] = []
    notes: list[str] = []
    following: tuple[list[Any], int] | None = None   # the tag that a line may continue
    for line in lines:
        if not line:
            following = None
            description.append("")
            continue
        match = _TAG.fullmatch(line)
        if match is None:
            if following is None:
                description.append(line)
            else:
                target, index = following
                if isinstance(target[index], list):
                    target[index][1] = f"{target[index][1]} {line}".strip()
                else:
                    target[index] = f"{target[index]} {line}".strip()
            continue
        tag, rest = match[1].lower(), match[2].strip()
        if tag in ("param", "tparam", "arg"):
            if tag == "tparam":
                kind, _, rest = rest.partition(" ")
                name, _, text = rest.strip().partition(" ")
                text = f"({kind}) {text.strip()}".strip()
            else:
                name, _, text = rest.partition(" ")
            params.append([name, text.strip()])
            following = (params, len(params) - 1)
        elif tag in ("return", "returns", "treturn"):
            returns.append(rest)
            following = (returns, len(returns) - 1)
        else:
            notes.append(f"@{tag} {rest}".rstrip())
            following = (notes, len(notes) - 1)
    # Comments are wrapped by hand: the lines of a paragraph are joined again, list items aside.
    paragraphs: list[str] = []
    for line in [*description, ""]:
        if not line:
            if paragraphs and paragraphs[-1]:
                paragraphs.append("")
        elif paragraphs and paragraphs[-1]:
            paragraphs[-1] += ("\n" if _LIST_ITEM.match(line) else " ") + line
        else:
            paragraphs[-1:] = [line]
    text = "\n\n".join(paragraph for paragraph in paragraphs if paragraph)
    if len(text) > DESCRIPTION_LIMIT:
        text = text[:DESCRIPTION_LIMIT - 1].rstrip() + "…"
    if not (text or params or returns or notes):
        return None
    return {"texte": text, "params": params, "retours": returns, "notes": notes}
