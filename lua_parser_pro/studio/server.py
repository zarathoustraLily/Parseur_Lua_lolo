"""Local web server of the Studio: static files and a small JSON interface.

The server only listens on the loopback address. Requests must name it in
their ``Host`` header (this defeats DNS rebinding) and every call to the JSON
interface must carry the ``X-Lua-Studio`` header, which a page from another
site cannot send. No file outside the folders opened by the user is read.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .. import __version__
from ..ast import iter_json, to_dict
from .report import report_page
from .session import Session, list_folders

DEFAULT_PORT = 8642
STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 48 * 1024 * 1024
_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".js": "text/javascript; charset=utf-8", ".woff2": "font/woff2",
          ".svg": "image/svg+xml", ".lua": "text/plain; charset=utf-8",
          ".json": "application/json; charset=utf-8", ".txt": "text/plain; charset=utf-8"}
_POLICY = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
           "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; "
           "frame-ancestors 'none'")


class StudioError(Exception):
    """A request the Studio refuses, with the HTTP status and a French explanation."""

    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class StudioServer(ThreadingHTTPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets two programs listen on the same port.
    allow_reuse_address = os.name != "nt"

    def __init__(self, address: tuple[str, int], initial: dict[str, Any]) -> None:
        super().__init__(address, Handler)
        self.session = Session()
        self.initial = initial


class Handler(BaseHTTPRequestHandler):
    server: StudioServer
    server_version = "LuaParserStudio/" + __version__

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - signature of the base class
        return

    # ------------------------------------------------------------------ replies
    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", _POLICY)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send(status, _dumps(data).encode("ascii"), "application/json; charset=utf-8")

    def _refuse(self, status: HTTPStatus, message: str) -> None:
        self._json({"erreur": message}, status)

    def _local(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        port = self.server.server_address[1]
        return host in {f"127.0.0.1:{port}", f"localhost:{port}", f"[::1]:{port}"}

    # ------------------------------------------------------------------- routes
    def do_GET(self) -> None:  # noqa: N802 - name required by http.server
        if not self._local():
            self._refuse(HTTPStatus.FORBIDDEN, "Adresse refusée.")
            return
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._file(STATIC / "index.html")
        elif path.startswith("/static/"):
            relative = path[len("/static/"):]
            target = (STATIC / relative).resolve()
            if STATIC in target.parents and target.is_file():
                self._file(target)
            else:
                self._refuse(HTTPStatus.NOT_FOUND, "Fichier introuvable.")
        elif path == "/favicon.ico":
            self._send(HTTPStatus.NO_CONTENT, b"", "image/x-icon")
        else:
            self._refuse(HTTPStatus.NOT_FOUND, "Page introuvable.")

    do_HEAD = do_GET  # noqa: N815

    def _file(self, target: Path) -> None:
        try:
            body = target.read_bytes()
        except OSError:
            self._refuse(HTTPStatus.NOT_FOUND, "Fichier introuvable.")
            return
        self._send(HTTPStatus.OK, body, _TYPES.get(target.suffix.lower(), "application/octet-stream"))

    def do_POST(self) -> None:  # noqa: N802 - name required by http.server
        try:
            if not self._local():
                raise StudioError(HTTPStatus.FORBIDDEN, "Adresse refusée.")
            if self.headers.get("X-Lua-Studio") != "1":
                raise StudioError(HTTPStatus.FORBIDDEN, "Requête refusée.")
            route = _ROUTES.get(self.path.split("?", 1)[0])
            if route is None:
                raise StudioError(HTTPStatus.NOT_FOUND, "Action inconnue.")
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= MAX_BODY:
                raise StudioError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Texte trop volumineux.")
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except (ValueError, UnicodeDecodeError):
                raise StudioError(HTTPStatus.BAD_REQUEST, "Requête illisible.") from None
            if not isinstance(payload, dict):
                raise StudioError(HTTPStatus.BAD_REQUEST, "Requête illisible.")
            self._json(route(self.server, payload))
        except StudioError as error:
            self._refuse(error.status, error.message)
        except FileNotFoundError:
            self._refuse(HTTPStatus.NOT_FOUND, "Fichier ou dossier introuvable.")
        except PermissionError:
            self._refuse(HTTPStatus.FORBIDDEN, "Accès refusé à ce fichier ou à ce dossier.")
        except (OSError, UnicodeError) as error:
            self._refuse(HTTPStatus.INTERNAL_SERVER_ERROR, f"Lecture impossible : {error}")
        except (BrokenPipeError, ConnectionError):
            return
        except Exception as error:  # noqa: BLE001 - reported to the page instead of a silent 500
            self._refuse(HTTPStatus.INTERNAL_SERVER_ERROR,
                         f"Erreur interne du Studio : {type(error).__name__}: {error}")


def _dumps(data: Any, indent: int | None = None) -> str:
    """JSON text of ``data``; a tree too deep for the standard encoder is written iteratively."""
    if indent is None:
        try:
            return json.dumps(data, separators=(",", ":"))
        except RecursionError:
            pass
    return "".join(iter_json(data, indent=indent))


def _text(payload: dict[str, Any], key: str, default: str | None = None) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str):
        raise StudioError(HTTPStatus.BAD_REQUEST, f"Champ « {key} » manquant.")
    return value


def _number(payload: dict[str, Any], key: str, default: int, low: int, high: int) -> int:
    value = payload.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise StudioError(HTTPStatus.BAD_REQUEST, f"Champ « {key} » invalide.")
    return max(low, min(high, value))


def _document(server: StudioServer, payload: dict[str, Any]) -> Any:
    document = server.session.document(_text(payload, "doc"))
    if document is None:
        raise StudioError(HTTPStatus.GONE, "Cette analyse n'est plus en mémoire.")
    return document


def _config(server: StudioServer, payload: dict[str, Any]) -> dict[str, Any]:
    examples = sorted(path.name for path in (STATIC / "exemples").glob("*.lua"))
    return {"version": __version__, "python": sys.version.split()[0],
            "dossier": os.getcwd(), "exemples": examples,
            "fichier_initial": None, "dossier_initial": None, **server.initial}


def _analyse(server: StudioServer, payload: dict[str, Any]) -> dict[str, Any]:
    source = _text(payload, "source")
    name = _text(payload, "nom", "sans-titre.lua")[:240] or "sans-titre.lua"
    depth = _number(payload, "profondeur", 150, 1, 5000)
    encoding = _text(payload, "encodage", "utf-8")
    if encoding not in ("utf-8", "latin-1"):
        raise StudioError(HTTPStatus.BAD_REQUEST, "Encodage inconnu.")
    return server.session.analyse(source, name, depth, encoding).summary()


def _node(server: StudioServer, payload: dict[str, Any]) -> dict[str, Any]:
    path = payload.get("chemin")
    if not isinstance(path, list) or not all(
            isinstance(step, list) and len(step) == 2 and isinstance(step[0], str)
            and (step[1] is None or isinstance(step[1], int)) for step in path):
        raise StudioError(HTTPStatus.BAD_REQUEST, "Chemin invalide.")
    subtree = _document(server, payload).subtree(path)
    if subtree is None:
        raise StudioError(HTTPStatus.NOT_FOUND, "Nœud introuvable.")
    return {"noeud": subtree}


def _tokens(server: StudioServer, payload: dict[str, Any]) -> dict[str, Any]:
    document = _document(server, payload)
    if document.tokens is None:
        raise StudioError(HTTPStatus.CONFLICT, "Le texte n'a pas pu être découpé en jetons.")
    around = payload.get("position")
    if around is not None and (isinstance(around, bool) or not isinstance(around, int)):
        raise StudioError(HTTPStatus.BAD_REQUEST, "Position invalide.")
    return document.token_page(_number(payload, "debut", 0, 0, 10**9),
                               _number(payload, "nombre", 200, 1, 2000), around)


def _measures(server: StudioServer, payload: dict[str, Any]) -> dict[str, Any]:
    document = _document(server, payload)
    measures = document.measures()
    if measures is None:
        raise StudioError(HTTPStatus.CONFLICT, "Aucune mesure : la syntaxe est invalide.")
    return {"mesures": measures, "ms": document.milliseconds}


def _decisions(server: StudioServer, payload: dict[str, Any]) -> dict[str, Any]:
    document = _document(server, payload)
    result = document.decisions(_number(payload, "fonction", 0, 0, 10**9))
    if result is None:
        raise StudioError(HTTPStatus.NOT_FOUND, "Fonction introuvable.")
    return result


def _export(server: StudioServer, payload: dict[str, Any]) -> dict[str, Any]:
    document = _document(server, payload)
    kind = _text(payload, "genre", "arbre")
    indent = None if payload.get("compact") else 2
    if kind == "decisions":
        if document.tree is None:
            raise StudioError(HTTPStatus.CONFLICT,
                              "Aucun organigramme à exporter : la syntaxe est invalide.")
        return {"html": report_page(document)}
    if kind == "jetons":
        if document.tokens is None:
            raise StudioError(HTTPStatus.CONFLICT, "Aucun jeton à exporter.")
        data: Any = {"tokens": to_dict(document.tokens), "comments": to_dict(document.comments)}
    else:
        if document.tree is None:
            raise StudioError(HTTPStatus.CONFLICT, "Aucun arbre à exporter : la syntaxe est invalide.")
        data = document.tree.to_dict()
    return {"json": _dumps(data, indent) + "\n"}


def _folders(server: StudioServer, payload: dict[str, Any]) -> dict[str, Any]:
    path = payload.get("chemin")
    return list_folders(path if isinstance(path, str) and path else None)


def _folder(server: StudioServer, payload: dict[str, Any]) -> dict[str, Any]:
    return server.session.open_folder(_text(payload, "chemin"))


def _file(server: StudioServer, payload: dict[str, Any]) -> dict[str, Any]:
    return server.session.read_file(_text(payload, "racine"), _text(payload, "chemin"))


def _check(server: StudioServer, payload: dict[str, Any]) -> dict[str, Any]:
    return server.session.start_check(_text(payload, "racine")).state(0)


def _job(server: StudioServer, payload: dict[str, Any]) -> dict[str, Any]:
    job = server.session.jobs.get(_text(payload, "tache"))
    if job is None:
        raise StudioError(HTTPStatus.GONE, "Cette vérification n'existe plus.")
    if payload.get("arreter"):
        job.stopped = True
    return job.state(_number(payload, "depuis", 0, 0, 10**9))


def _example(server: StudioServer, payload: dict[str, Any]) -> dict[str, Any]:
    name = os.path.basename(_text(payload, "nom"))
    target = STATIC / "exemples" / name
    if target.suffix != ".lua" or not target.is_file():
        raise StudioError(HTTPStatus.NOT_FOUND, "Exemple introuvable.")
    return {"texte": target.read_text(encoding="utf-8"), "nom": name}


_ROUTES = {
    "/api/config": _config, "/api/analyse": _analyse, "/api/noeud": _node,
    "/api/jetons": _tokens, "/api/decisions": _decisions, "/api/mesures": _measures,
    "/api/export": _export,
    "/api/dossiers": _folders, "/api/dossier": _folder, "/api/fichier": _file,
    "/api/verifier": _check, "/api/tache": _job, "/api/exemple": _example,
}


def create_server(port: int | None = None, initial: dict[str, Any] | None = None) -> StudioServer:
    """Bind the Studio to the loopback address, on ``port`` or the next free one."""
    initial = initial or {}
    if port is not None:
        return StudioServer(("127.0.0.1", port), initial)
    last: OSError | None = None
    for candidate in range(DEFAULT_PORT, DEFAULT_PORT + 20):
        try:
            return StudioServer(("127.0.0.1", candidate), initial)
        except OSError as error:
            last = error
    try:
        return StudioServer(("127.0.0.1", 0), initial)
    except OSError:
        assert last is not None
        raise last from None


def serve(path: str | None = None, *, port: int | None = None, open_browser: bool = True) -> int:
    """Run the Studio until interrupted; return a process exit code."""
    initial: dict[str, Any] = {"fichier_initial": None, "dossier_initial": None}
    if path and path != "-":
        absolute = os.path.abspath(path)
        if os.path.isdir(absolute):
            initial["dossier_initial"] = absolute
        elif os.path.isfile(absolute):
            initial["dossier_initial"] = os.path.dirname(absolute)
            initial["fichier_initial"] = os.path.basename(absolute)
        else:
            print(f"lua-parser: {path}: fichier ou dossier introuvable", file=sys.stderr)
            return 2
    try:
        server = create_server(port, initial)
    except OSError as error:
        print(f"lua-parser: impossible d'ouvrir le Studio sur le port {port}: {error}",
              file=sys.stderr)
        return 2
    address = f"http://127.0.0.1:{server.server_address[1]}/"
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:  # An accent the console cannot show must not stop the Studio.
            reconfigure(errors="replace")
    print(f"Studio du parseur Lua {__version__}")
    print(f"  Adresse : {address}")
    print("  Pour arrêter : fermez cette fenêtre ou appuyez sur Ctrl+C.", flush=True)
    if open_browser:
        threading.Timer(0.3, _open, args=(address,)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nStudio arrêté.")
    finally:
        server.server_close()
    return 0


def _open(address: str) -> None:
    try:
        webbrowser.open(address)
    except Exception:  # noqa: BLE001 - the address is printed; opening it is a convenience
        pass


def free_port() -> int:
    """A port nobody listens on right now (used by the tests)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
