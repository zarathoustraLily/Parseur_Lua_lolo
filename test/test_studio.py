"""The Studio: its local server, what it answers and what it refuses."""
from __future__ import annotations

import http.client
import json
import os
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path

from lua_parser_pro import parse
from lua_parser_pro.studio import create_server
from lua_parser_pro.studio.messages import title, translate
from lua_parser_pro.studio.server import free_port
from lua_parser_pro.studio.session import Session, encode_tree, list_folders, utf16_mapper

SOURCE = '''-- combat
local Regles = { Seuil = 3 }
local function frappe(cible, force)
    if not cible or cible.Vie <= 0 then
        return false
    end
    for _, effet in ipairs(cible.Effets) do
        force = effet:Modifier(force)
    end
    cible.Vie = cible.Vie - force
    return true
end
Ecouter("mort", function(cible) Butin(cible) end)
return frappe
'''


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server(free_port())
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      kwargs={"poll_interval": 0.05}, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)

    def call(self, method: str, path: str, body: bytes | None = None,
             headers: dict[str, str] | None = None) -> tuple[int, bytes, dict[str, str]]:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read(), {k.lower(): v for k, v in response.getheaders()}
        finally:
            connection.close()

    def api(self, route: str, payload: object = None, **headers: str) -> tuple[int, dict]:
        sent = {"Content-Type": "application/json", "X-Lua-Studio": "1"}
        sent.update(headers)
        status, body, _ = self.call("POST", "/api/" + route, json.dumps(payload or {}).encode(), sent)
        return status, json.loads(body)

    def analyse(self, source: str = SOURCE, name: str = "essai.lua") -> dict:
        status, data = self.api("analyse", {"source": source, "nom": name})
        self.assertEqual(status, 200, data)
        return data


class PageTests(ServerCase):
    def test_page_and_static_files(self):
        status, body, headers = self.call("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers["content-type"])
        self.assertIn(b"Studio du parseur Lua", body)
        self.assertIn("script-src 'self'", headers["content-security-policy"])
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        for path, kind in (("/static/app.js", "text/javascript"), ("/static/app.css", "text/css"),
                           ("/static/decisions.js", "text/javascript"), ("/static/lune.svg", "image/svg+xml"),
                           ("/static/fonts/atkinson-hyperlegible-mono-latin-400-normal.woff2", "font/woff2")):
            with self.subTest(path=path):
                status, body, headers = self.call("GET", path)
                self.assertEqual(status, 200)
                self.assertIn(kind, headers["content-type"])
                self.assertTrue(body)

    def test_every_script_named_by_the_page_exists(self):
        _, page, _ = self.call("GET", "/")
        _, script, _ = self.call("GET", "/static/app.js")
        self.assertIn(b'src="/static/app.js"', page)
        modules = set(re.findall(r'(?:from|import) "\./([a-z]+\.js)"', script.decode("utf-8")))
        self.assertGreaterEqual(len(modules), 8)
        for module in modules:
            with self.subTest(module=module):
                self.assertEqual(self.call("GET", "/static/" + module)[0], 200)

    def test_head_has_no_body(self):
        status, body, headers = self.call("HEAD", "/")
        self.assertEqual((status, body), (200, b""))
        self.assertGreater(int(headers["content-length"]), 1000)

    def test_files_outside_the_static_folder_are_not_served(self):
        for path in ("/static/../server.py", "/static/..%2fserver.py", "/server.py", "/static/",
                     "/static/absent.js", "/../../etc/passwd"):
            with self.subTest(path=path):
                self.assertEqual(self.call("GET", path)[0], 404)

    def test_another_host_name_is_refused(self):
        for host in ("evil.example", f"evil.example:{self.port}", "127.0.0.1:1", ""):
            with self.subTest(host=host):
                self.assertEqual(self.call("GET", "/", headers={"Host": host})[0], 403)
                self.assertEqual(self.api("config", Host=host)[0], 403)
        self.assertEqual(self.call("GET", "/", headers={"Host": f"localhost:{self.port}"})[0], 200)


class InterfaceTests(ServerCase):
    def test_calls_need_the_studio_header(self):
        body = json.dumps({}).encode()
        status, answer, _ = self.call("POST", "/api/config", body, {"Content-Type": "application/json"})
        self.assertEqual(status, 403)
        self.assertIn("erreur", json.loads(answer))
        self.assertEqual(self.call("POST", "/api/config", body, {"X-Lua-Studio": "0"})[0], 403)

    def test_malformed_requests(self):
        headers = {"X-Lua-Studio": "1"}
        self.assertEqual(self.call("POST", "/api/analyse", b"{not json", headers)[0], 400)
        self.assertEqual(self.call("POST", "/api/analyse", b"[1, 2]", headers)[0], 400)
        self.assertEqual(self.call("POST", "/api/analyse", b"\xff\xfe", headers)[0], 400)
        self.assertEqual(self.api("analyse", {"nom": "x.lua"})[0], 400)
        self.assertEqual(self.api("analyse", {"source": 12})[0], 400)
        self.assertEqual(self.api("analyse", {"source": "", "profondeur": "150"})[0], 400)
        self.assertEqual(self.api("inconnue")[0], 404)

    def test_config(self):
        status, config = self.api("config")
        self.assertEqual(status, 200)
        self.assertEqual(config["exemples"], ["combat.lua", "demo.lua", "erreur.lua"])
        self.assertIsNone(config["fichier_initial"])
        self.assertTrue(os.path.isdir(config["dossier"]))

    def test_examples(self):
        status, example = self.api("exemple", {"nom": "combat.lua"})
        self.assertEqual(status, 200)
        self.assertTrue(self.analyse(example["texte"], example["nom"])["ok"])
        self.assertFalse(self.analyse(self.api("exemple", {"nom": "erreur.lua"})[1]["texte"])["ok"])
        for name in ("absent.lua", "../server.py", "../../cli.py", "combat"):
            with self.subTest(name=name):
                self.assertEqual(self.api("exemple", {"nom": name})[0], 404)

    def test_valid_analysis(self):
        data = self.analyse()
        self.assertTrue(data["ok"])
        self.assertIsNone(data["erreur"])
        self.assertEqual((data["nom"], data["commentaires"], data["elague"]), ("essai.lua", 1, False))
        self.assertEqual(data["arbre"]["t"], "Chunk")
        self.assertEqual(len(data["arbre"]["body"]), 4)
        self.assertEqual([(s["nom"], s["genre"]) for s in data["plan"]],
                         [("Regles", "table"), ("frappe", "function"), ("Ecouter", "callback")])
        functions = data["fonctions"]
        self.assertEqual([(f["id"], f["nom"], f["genre"]) for f in functions],
                         [(0, "", "script"), (1, "frappe", "fonction"), (2, "Ecouter(…)", "fonction")])
        self.assertEqual((functions[1]["complexity"], functions[1]["params"], functions[1]["ligne"],
                          functions[1]["lignes"]), (4, ["cible", "force"], 3, 10))
        self.assertEqual(SOURCE[functions[1]["a"]:functions[1]["b"]].split("\n")[0],
                         "local function frappe(cible, force)")
        self.assertEqual(set(data["ms"]), {"lexique", "syntaxe", "preparation"})

    def test_tree_omits_what_the_page_reads_from_the_text(self):
        tree = self.analyse('local nom = "abc"')["arbre"]
        variable = tree["body"][0]["variables"][0]["name"]
        self.assertEqual(variable, {"t": "Identifier", "a": 6, "b": 9})
        self.assertEqual(tree["body"][0]["values"][0], {"t": "StringLiteral", "a": 12, "b": 17, "n": 3})

    def test_error_analysis_speaks_french(self):
        data = self.analyse("local x = (1 +\n")
        self.assertFalse(data["ok"])
        self.assertIsNone(data["arbre"])
        error = data["erreur"]
        self.assertEqual((error["code"], error["titre"], error["etape"]), ("SYNTAX_ERROR", "Erreur de syntaxe", "syntaxe"))
        self.assertEqual(error["message"], "Expected an expression")
        self.assertEqual(error["message_fr"], "Une expression est attendue ici.")
        self.assertEqual((error["ligne"], error["colonne"]), (2, 1))
        self.assertLessEqual(error["a"], error["b"])
        self.assertEqual(data["jetons"], 6)
        lexical = self.analyse('x = "abc\n')
        self.assertEqual((lexical["erreur"]["code"], lexical["erreur"]["etape"], lexical["jetons"]),
                         ("UNTERMINATED_STRING", "lexique", None))

    def test_positions_count_utf16_units(self):
        source = '-- \U0001f319\nlocal function f() end\nreturn "\U0001f525", f\n'
        data = self.analyse(source)
        utf16 = source.encode("utf-16-le")
        symbol = data["plan"][0]
        self.assertEqual(utf16[2 * symbol["a"]:2 * symbol["b"]].decode("utf-16-le"), "local function f() end")
        self.assertEqual(symbol["a"], source.index("local") + 1)
        status, page = self.api("jetons", {"doc": data["doc"], "debut": 0, "nombre": 50})
        self.assertEqual(status, 200)
        for kind, start, end, line, column, value in page["jetons"]:
            text = utf16[2 * start:2 * end].decode("utf-16-le")
            if kind == 3:
                self.assertEqual((text, value), ('"\U0001f525"', "\\xf0\\x9f\\x94\\xa5"))
        self.assertEqual(page["jetons"][0][:5], [5, 0, 5, 1, 1])

    def test_latin_1_text_keeps_the_bytes_of_its_strings(self):
        source = 'return "\u00e9t\u00e9"'
        status, data = self.api("analyse", {"source": source, "nom": "ancien.lua", "encodage": "latin-1"})
        self.assertEqual((status, data["ok"], data["encodage"]), (200, True, "latin-1"))
        tree = json.loads(self.api("export", {"doc": data["doc"], "compact": True})[1]["json"])
        self.assertEqual(tree["body"][0]["arguments"][0]["value"], [0xe9, 0x74, 0xe9])
        _, page = self.api("jetons", {"doc": data["doc"]})
        self.assertEqual(page["jetons"][1][5], "\\xe9t\\xe9")
        utf8 = self.analyse(source)
        self.assertEqual(utf8["encodage"], "utf-8")
        tree = json.loads(self.api("export", {"doc": utf8["doc"], "compact": True})[1]["json"])
        self.assertEqual(tree["body"][0]["arguments"][0]["value"], [0xc3, 0xa9, 0x74, 0xc3, 0xa9])
        # Once a character that Latin-1 cannot hold is typed, the text is read as UTF-8 again.
        _, edited = self.api("analyse", {"source": 'return "\u00e9 \u20ac"', "encodage": "latin-1"})
        self.assertEqual((edited["ok"], edited["encodage"]), (True, "utf-8"))
        self.assertEqual(self.api("analyse", {"source": "", "encodage": "utf-16"})[0], 400)
        self.assertEqual(self.api("analyse", {"source": "", "encodage": 1})[0], 400)

    def test_nodes_on_demand(self):
        doc = self.analyse()["doc"]
        status, data = self.api("noeud", {"doc": doc, "chemin": [["body", 1], ["function", None]]})
        self.assertEqual((status, data["noeud"]["t"]), (200, "FunctionExpression"))
        self.assertEqual(len(data["noeud"]["parameters"]), 2)
        self.assertEqual(self.api("noeud", {"doc": doc, "chemin": []})[1]["noeud"]["t"], "Chunk")
        for path in ([["body", 99]], [["absent", None]], [["span", None]], [["__class__", None]],
                     [["body", 0], ["span", None]], [["comments", 0]]):
            with self.subTest(path=path):
                self.assertEqual(self.api("noeud", {"doc": doc, "chemin": path})[0], 404)
        for path in ("body", [["body"]], [[0, 0]], [["body", "0"]], None):
            with self.subTest(path=path):
                self.assertEqual(self.api("noeud", {"doc": doc, "chemin": path})[0], 400)

    def test_token_pages(self):
        data = self.analyse()
        total = data["jetons"] + data["commentaires"]
        status, page = self.api("jetons", {"doc": data["doc"], "debut": 0, "nombre": 10})
        self.assertEqual((status, page["total"], page["debut"], len(page["jetons"])), (200, total, 0, 10))
        self.assertIsNone(page["vise"])
        position = SOURCE.index("ipairs") + 2
        _, around = self.api("jetons", {"doc": data["doc"], "nombre": 10, "position": position})
        aimed = around["jetons"][around["vise"] - around["debut"]]
        self.assertEqual(SOURCE[aimed[1]:aimed[2]], "ipairs")
        self.assertEqual(around["debut"] % 10, 0)
        _, last = self.api("jetons", {"doc": data["doc"], "debut": 10**8, "nombre": 10})
        self.assertEqual(len(last["jetons"]), 1)
        self.assertEqual(self.api("jetons", {"doc": data["doc"], "position": "x"})[0], 400)
        lexical = self.analyse('x = "abc\n')
        self.assertEqual(self.api("jetons", {"doc": lexical["doc"]})[0], 409)

    def test_decisions(self):
        doc = self.analyse()["doc"]
        status, data = self.api("decisions", {"doc": doc, "fonction": 1})
        self.assertEqual(status, 200)
        self.assertEqual(data["mesures"]["complexity"], 4)
        self.assertEqual([step["kind"] for step in data["flux"]["steps"]], ["if", "for", "action", "return"])
        test = data["flux"]["steps"][0]["branches"][0]
        self.assertEqual((test["condition"], test["ligne"]), ("not cible or cible.Vie <= 0", 4))
        self.assertEqual(SOURCE[test["a"]:test["b"]], "not cible or cible.Vie <= 0")
        self.assertNotIn("offset", test)
        self.assertEqual(data["termes"][0], {"nom": "cible", "nombre": 1})
        self.assertEqual({terme["nom"] for terme in data["termes"]}, {"cible", "cible.Vie"})
        self.assertEqual(self.api("decisions", {"doc": doc, "fonction": 0})[1]["mesures"]["statements"], 4)
        self.assertEqual(self.api("decisions", {"doc": doc, "fonction": 99})[0], 404)
        self.assertEqual(self.api("decisions", {"doc": self.analyse("x = (")["doc"], "fonction": 0})[0], 404)

    def test_measures(self):
        status, data = self.api("mesures", {"doc": self.analyse()["doc"]})
        self.assertEqual(status, 200)
        self.assertEqual(data["mesures"]["lines"]["total"], 14)
        self.assertEqual(data["mesures"]["functions"]["total"], 2)
        self.assertEqual(self.api("mesures", {"doc": self.analyse("x = (")["doc"]})[0], 409)

    def test_export(self):
        doc = self.analyse()["doc"]
        status, pretty = self.api("export", {"doc": doc, "genre": "arbre"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(pretty["json"]), parse(SOURCE, filename="essai.lua").to_dict())
        self.assertIn("\n  ", pretty["json"])
        compact = self.api("export", {"doc": doc, "genre": "arbre", "compact": True})[1]["json"]
        self.assertEqual(len(compact.splitlines()), 1)
        self.assertEqual(json.loads(compact), json.loads(pretty["json"]))
        tokens = json.loads(self.api("export", {"doc": doc, "genre": "jetons"})[1]["json"])
        self.assertEqual((len(tokens["comments"]), tokens["tokens"][-1]["kind"]), (1, "eof"))
        broken = self.analyse("x = (")["doc"]
        self.assertEqual(self.api("export", {"doc": broken, "genre": "arbre"})[0], 409)
        self.assertEqual(self.api("export", {"doc": broken, "genre": "jetons"})[0], 200)
        self.assertEqual(self.api("export", {"doc": broken, "genre": "decisions"})[0], 409)

    def test_export_of_the_decisions(self):
        status, data = self.api("export", {"doc": self.analyse(name="combat/essai.lua")["doc"],
                                           "genre": "decisions"})
        self.assertEqual(status, 200)
        page = data["html"]
        self.assertTrue(page.startswith("<!doctype html>") and page.isascii())
        embedded = json.loads(re.search(r'id="donnees">(.*?)</script>', page, re.S)[1])
        self.assertEqual((embedded["nom"], embedded["source"]), ("essai.lua", SOURCE))
        names = [entry["nom"] for entry in embedded["fonctions"]]
        self.assertEqual(names, ["", "frappe", "Ecouter(\u2026)"])

    def test_old_analyses_are_forgotten(self):
        first = self.analyse("return 1")["doc"]
        for index in range(3):
            self.analyse(f"return {index}")
        self.assertEqual(self.api("jetons", {"doc": first})[0], 410)
        self.assertEqual(self.api("jetons", {"doc": "jamais-vu"})[0], 410)
        self.assertEqual(self.api("jetons", {})[0], 400)

    def test_deep_tree_is_answered(self):
        depth = 250
        status, data = self.api("analyse", {"source": "return " + "(" * depth + "1" + ")" * depth,
                                             "nom": "profond.lua", "profondeur": 2000})
        self.assertEqual((status, data["ok"]), (200, True))
        self.assertEqual(self.api("export", {"doc": data["doc"], "genre": "arbre", "compact": True})[0], 200)


class FolderTests(ServerCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(os.path.realpath(directory.name))
        (self.root / "Scripts" / "Combat").mkdir(parents=True)
        (self.root / "Scripts" / "ok.lua").write_text("return 1\n", encoding="utf-8")
        (self.root / "Scripts" / "Combat" / "bad.lua").write_text("return )\n", encoding="utf-8")
        (self.root / "Scripts" / "latin.lua").write_bytes(b'return "\xe9"\r\n')
        (self.root / "Scripts" / "notes.txt").write_text("pas du Lua", encoding="utf-8")
        (self.root / "dehors.lua").write_text("return 0\n", encoding="utf-8")
        self.folder = str(self.root / "Scripts")

    def test_browse_folders(self):
        status, listing = self.api("dossiers", {"chemin": str(self.root)})
        self.assertEqual(status, 200)
        self.assertEqual((listing["chemin"], listing["dossiers"], listing["lua"]),
                         (str(self.root), ["Scripts"], 1))
        self.assertEqual(listing["parent"], str(self.root.parent))
        self.assertEqual(listing["separateur"], os.sep)
        self.assertEqual(self.api("dossiers", {})[0], 200)
        self.assertEqual(self.api("dossiers", {"chemin": str(self.root / "absent")})[0], 404)

    def test_open_folder_and_read_files(self):
        status, folder = self.api("dossier", {"chemin": self.folder})
        self.assertEqual(status, 200)
        self.assertEqual(folder["racine"], self.folder)
        self.assertEqual([entry["chemin"] for entry in folder["fichiers"]],
                         ["Combat/bad.lua", "latin.lua", "ok.lua"])
        self.assertEqual(folder["octets"], sum(entry["octets"] for entry in folder["fichiers"]))
        self.assertFalse(folder["tronque"])
        status, file = self.api("fichier", {"racine": self.folder, "chemin": "Combat/bad.lua"})
        self.assertEqual((status, file["texte"], file["encodage"], file["nom"]),
                         (200, "return )\n", "utf-8", "bad.lua"))
        latin = self.api("fichier", {"racine": self.folder, "chemin": "latin.lua"})[1]
        self.assertEqual((latin["texte"], latin["encodage"], latin["octets"]), ('return "é"\r\n', "latin-1", 12))

    def test_only_lua_files_of_an_opened_folder_are_read(self):
        self.api("dossier", {"chemin": self.folder})
        for path in ("../dehors.lua", "notes.txt", "absent.lua/../../dehors.lua", str(self.root / "dehors.lua"),
                     "Combat", ""):
            with self.subTest(path=path):
                self.assertEqual(self.api("fichier", {"racine": self.folder, "chemin": path})[0], 403)
        self.assertEqual(self.api("fichier", {"racine": self.folder, "chemin": "absent.lua"})[0], 404)
        # A folder that was never opened gives access to nothing, even to its .lua files.
        self.assertEqual(self.api("fichier", {"racine": str(self.root), "chemin": "dehors.lua"})[0], 403)
        self.assertEqual(self.api("verifier", {"racine": str(self.root)})[0], 403)
        self.assertEqual(self.api("dossier", {"chemin": str(self.root / "absent")})[0], 404)

    def test_link_leaving_the_folder_is_refused(self):
        link = self.root / "Scripts" / "lien.lua"
        try:
            os.symlink(self.root / "dehors.lua", link)
        except (OSError, NotImplementedError):
            self.skipTest("symbolic links are not available here")
        self.api("dossier", {"chemin": self.folder})
        self.assertEqual(self.api("fichier", {"racine": self.folder, "chemin": "lien.lua"})[0], 403)

    def test_check_the_whole_folder(self):
        self.api("dossier", {"chemin": self.folder})
        status, state = self.api("verifier", {"racine": self.folder})
        self.assertEqual(status, 200)
        reports = list(state["nouveaux"])
        deadline = time.monotonic() + 30
        while not state["termine"]:
            self.assertLess(time.monotonic(), deadline, "the folder check did not finish")
            time.sleep(0.02)
            _, state = self.api("tache", {"tache": state["tache"], "depuis": len(reports)})
            reports.extend(state["nouveaux"])
        self.assertEqual((state["total"], state["faits"], state["valides"], state["erreurs"]), (3, 3, 2, 1))
        by_path = {report["chemin"]: report for report in reports}
        self.assertEqual(sorted(by_path), ["Combat/bad.lua", "latin.lua", "ok.lua"])
        bad = by_path["Combat/bad.lua"]
        self.assertFalse(bad["ok"])
        self.assertEqual((bad["erreur"]["code"], bad["erreur"]["ligne"], bad["erreur"]["colonne"]),
                         ("SYNTAX_ERROR", 1, 8))
        self.assertEqual(bad["erreur"]["message_fr"], "Une expression est attendue ici.")
        self.assertEqual((by_path["latin.lua"]["ok"], by_path["latin.lua"]["encodage"]), (True, "latin-1"))
        self.assertEqual(self.api("tache", {"tache": "inconnue"})[0], 410)

    def test_stop_request_is_recorded(self):
        self.api("dossier", {"chemin": self.folder})
        _, state = self.api("verifier", {"racine": self.folder})
        _, state = self.api("tache", {"tache": state["tache"], "arreter": True})
        self.assertTrue(state["arretee"])


class SessionTests(unittest.TestCase):
    def test_utf16_mapper(self):
        self.assertEqual([utf16_mapper("abc")(i) for i in range(4)], [0, 1, 2, 3])
        mapper = utf16_mapper("a\U0001f319b\U0001f319c")
        self.assertEqual([mapper(i) for i in range(6)], [0, 1, 3, 4, 6, 7])
        self.assertEqual(utf16_mapper("")(0), 0)

    def test_tree_budget_leaves_stubs_for_deep_nodes(self):
        tree = parse('f(a + b * c, { x = 1, "texte" })')
        full, complete = encode_tree(tree, lambda offset: offset, 10_000)
        self.assertTrue(complete)
        self.assertNotIn('"x": 1', json.dumps(full))
        cut, complete = encode_tree(tree, lambda offset: offset, 4)
        self.assertFalse(complete)
        call = cut["body"][0]["expression"]
        self.assertEqual(call["t"], "CallExpression")
        self.assertEqual(call["callee"], {"t": "Identifier", "a": 0, "b": 1})
        binary, table = call["arguments"]
        self.assertEqual((binary["operator"], binary.get("x"), "left" in binary), ("+", 1, False))
        self.assertEqual((table["t"], table.get("x"), "fields" in table), ("TableExpression", 1, False))

    def test_function_list_names_every_kind_of_function(self):
        source = ("local M = {}\nfunction M.a() end\nfunction M:b() end\nlocal c = function() end\n"
                  "M.d, M.e = 1, function() end\nM.t = { f = function() end, ['g h'] = function() end }\n"
                  "on('x', function() return function() end end)\nreturn function() end\n")
        document = Session().analyse(source, "noms.lua")
        names = [entry["nom"] for entry in document.functions()]
        self.assertEqual(names, ["", "M.a", "M:b", "c", "M.e", "f", "g h", "on(…)", "", ""])
        self.assertEqual([entry["id"] for entry in document.functions()], list(range(10)))
        starts = [entry["a"] for entry in document.functions()]
        self.assertEqual(starts, sorted(starts))
        self.assertIsNone(Session().analyse("x = (", "faux.lua").decisions(0))

    def test_resolve_stays_inside_opened_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.realpath(directory)
            Path(root, "a.lua").write_text("return 1", encoding="utf-8")
            session = Session()
            with self.assertRaises(PermissionError):
                session.resolve(root, "a.lua")
            session.open_folder(root)
            self.assertEqual(session.resolve(root, "a.lua"), os.path.join(root, "a.lua"))
            for path in ("../a.lua", "a.txt", "sub/../../a.lua", ""):
                with self.subTest(path=path), self.assertRaises(PermissionError):
                    session.resolve(root, path)
            with self.assertRaises(FileNotFoundError):
                session.open_folder(os.path.join(root, "absent"))

    def test_list_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = os.path.realpath(directory)
            for name in ("beta", "Alpha", "gamma"):
                os.mkdir(os.path.join(root, name))
            Path(root, "x.LUA").write_text("", encoding="utf-8")
            listing = list_folders(root)
            self.assertEqual((listing["dossiers"], listing["lua"]), (["Alpha", "beta", "gamma"], 1))
            with self.assertRaises(FileNotFoundError):
                list_folders(os.path.join(root, "absent"))


class MessageTests(unittest.TestCase):
    def test_known_messages_are_translated(self):
        def plain(text: str) -> str:      # French typography uses no-break spaces
            return text.replace("\xa0", " ").replace(chr(0x202f), " ")

        self.assertEqual(plain(translate("SYNTAX_ERROR", "Expected ')', found 'end'")),
                         "« ) » attendu, mais on trouve « end ».")
        self.assertEqual(plain(translate("SYNTAX_ERROR", "Expected 'end', found end of input")),
                         "« end » attendu, mais on trouve la fin du fichier.")
        self.assertIn("boucle", translate("INVALID_BREAK", "anything"))
        self.assertEqual(plain(translate("TOKEN_LIMIT", "Source exceeds the limit of 1000000 tokens")),
                         "Le texte dépasse la limite de 1 000 000 jetons.")

    def test_unknown_messages_are_kept(self):
        self.assertEqual(translate("SYNTAX_ERROR", "Something new"), "Something new")
        self.assertEqual(translate("NEW_CODE", "Something new"), "Something new")
        self.assertEqual(title("SYNTAX_ERROR"), "Erreur de syntaxe")
        self.assertTrue(title("NEW_CODE"))

    def test_every_parser_diagnostic_has_a_french_title(self):
        cases = ["x = (", "break", "1 = 2", "function f() return ... end", "local x <y> = 1", 'x = "a', "x = 1..2",
                 "--[[", "x = '\\q'", "x = [=", "x = @", "return " + "(" * 200 + "1"]
        from lua_parser_pro import LuaSyntaxError
        for source in cases:
            with self.subTest(source=source[:20]):
                with self.assertRaises(LuaSyntaxError) as caught:
                    parse(source)
                error = caught.exception
                self.assertNotEqual(title(error.code), error.code)
                self.assertNotEqual(translate(error.code, error.message), error.message)


if __name__ == "__main__":
    unittest.main()
