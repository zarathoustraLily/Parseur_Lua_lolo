"""The HTML export of the decision diagrams: its data, its descriptions and its page."""
from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lua_parser_pro import parse
from lua_parser_pro.model import LuaSyntaxError
from lua_parser_pro.studio.report import DESCRIPTION_LIMIT, build_report, documentation, report_data
from lua_parser_pro.studio.session import Document

ROOT = Path(__file__).resolve().parents[1]
DAY = datetime.date(2026, 10, 5)

SOURCE = '''-- Combat : un module d'essai.

--- Vrai si la liste contient la valeur.
-- @param liste la liste parcourue
-- @param valeur l'élément cherché
-- @return true ou false
local function contient(liste, valeur)
    for _, element in ipairs(liste) do
        if element == valeur then return true end
    end
    return false
end

-- Frappe une cible.
--
--Annoncer("ancien code")
function Frapper(cible, force)
    if contient(cible.Faiblesses, "feu") then
        force = force * 2
    end
    cible:Encaisser(force)
    return force
end

local Cible = {}
function Cible:Encaisser(force)
    self.Vie = self.Vie - force
    if self.Vie <= 0 then error("morte") end
end

Evenements.Ecouter("mort", function(cible)
    Frapper(cible, 1)
end)
'''


def report(source: str = SOURCE, name: str = "essai.lua") -> dict:
    return report_data(Document("essai", name, source, 150), date=DAY)


def by_name(data: dict) -> dict[str, dict]:
    return {entry["nom"]: entry for entry in data["fonctions"]}


def embedded(page: str) -> dict:
    match = re.search(r'<script type="application/json" id="donnees">(.*?)</script>', page, re.S)
    assert match is not None
    return json.loads(match[1])


def describe(source: str) -> dict | None:
    return documentation(parse(source + "\nreturn").comments)


class DataTests(unittest.TestCase):
    def test_every_function_with_its_description(self):
        data = report()
        self.assertEqual((data["nom"], data["date"], data["source"]), ("essai.lua", "2026-10-05", SOURCE))
        functions = by_name(data)
        self.assertEqual(list(functions), ["", "contient", "Frapper", "Cible:Encaisser",
                                           "Evenements.Ecouter(…)"])
        script = data["fonctions"][0]
        self.assertEqual((script["genre"], script["doc"]["texte"]), ("script", "Combat : un module d'essai."))
        contient = functions["contient"]
        self.assertEqual(contient["doc"], {
            "texte": "Vrai si la liste contient la valeur.",
            "params": [["liste", "la liste parcourue"], ["valeur", "l'élément cherché"]],
            "retours": ["true ou false"], "notes": []})
        self.assertEqual((contient["ligne"], contient["fin"], contient["profondeur"]), (7, 12, 0))
        # The commented-out call is not part of the description.
        self.assertEqual(functions["Frapper"]["doc"]["texte"], "Frappe une cible.")
        self.assertIsNone(functions["Cible:Encaisser"]["doc"])

    def test_calls_between_functions(self):
        functions = by_name(report())
        ids = {name: entry["id"] for name, entry in functions.items()}
        frapper = functions["Frapper"]
        self.assertEqual(frapper["appelle"], [ids["contient"], ids["Cible:Encaisser"]])
        self.assertEqual(frapper["appelee_par"], [ids["Evenements.Ecouter(…)"]])
        self.assertEqual(functions["contient"]["appelee_par"], [ids["Frapper"]])
        self.assertEqual(functions["contient"]["externes"], [["ipairs", 1]])
        self.assertEqual(functions[""]["externes"], [["Evenements.Ecouter", 1]])
        self.assertEqual(functions[""]["appelle"], [])
        self.assertEqual(functions["Cible:Encaisser"]["externes"], [["error", 1]])

    def test_shapes_name_the_functions_they_call(self):
        functions = by_name(report())
        steps = functions["Frapper"]["flux"]["steps"]
        self.assertEqual([step["kind"] for step in steps], ["if", "action", "return"])
        self.assertEqual(steps[0]["branches"][0]["appels"], [functions["contient"]["id"]])
        self.assertNotIn("appels", steps[0]["branches"][0]["body"]["steps"][0])
        self.assertEqual(steps[1]["appels"], [functions["Cible:Encaisser"]["id"]])
        self.assertNotIn("appels", steps[2])
        callback = functions["Evenements.Ecouter(…)"]
        self.assertEqual(callback["flux"]["steps"][0]["appels"], [functions["Frapper"]["id"]])
        self.assertEqual(callback["profondeur"], 0)

    def test_calls_in_loop_headings_and_bodies(self):
        source = ("local function f() end\nlocal function g() return true end\n"
                  "local function h()\n  while g() do\n    f()\n  end\n  repeat f() until g()\nend\n")
        functions = by_name(report(source))
        loop, repeat = functions["h"]["flux"]["steps"]
        self.assertEqual(loop["appels"], [functions["g"]["id"]])
        self.assertEqual(loop["body"]["steps"][0]["appels"], [functions["f"]["id"]])
        self.assertEqual(repeat["appels"], [functions["g"]["id"]])
        self.assertEqual(repeat["body"]["steps"][0]["appels"], [functions["f"]["id"]])

    def test_which_definition_a_call_names(self):
        source = ("local function f() return 1 end\nlocal function g() return f() end\n"
                  "local function f() return 2 end\nlocal function h() return f() end\n"
                  "local function insert() end\nlocal function k(t) table.insert(t, 1); self:m() end\n")
        entries = report(source)["fonctions"]
        self.assertEqual([entry["nom"] for entry in entries], ["", "f", "g", "f", "h", "insert", "k"])
        self.assertEqual(entries[2]["appelle"], [entries[1]["id"]])
        self.assertEqual(entries[4]["appelle"], [entries[3]["id"]])
        # A qualified call only falls back on qualified definitions.
        self.assertEqual(entries[6]["appelle"], [])
        self.assertEqual(entries[6]["externes"], [["table.insert", 1], ["self:m", 1]])

    def test_nested_functions_and_utf16_offsets(self):
        source = "-- \U0001F319 lune\nlocal function dehors()\n  local function dedans() end\n  dedans()\nend\n"
        functions = by_name(report(source))
        start = source.index("local function dedans")
        self.assertEqual(functions["dedans"]["a"], start + 1)   # The emoji is two UTF-16 units.
        self.assertEqual(functions["dedans"]["profondeur"], 1)
        self.assertEqual(functions["dehors"]["appelle"], [functions["dedans"]["id"]])
        call = functions["dehors"]["flux"]["steps"][0]
        self.assertEqual(call["appels"], [functions["dedans"]["id"]])


class DocumentationTests(unittest.TestCase):
    def test_tags_of_ldoc_and_emmylua(self):
        doc = describe("---Ajoute deux nombres.\n---@param a number le premier\n"
                       "---@param b? number le second,\n---  facultatif\n"
                       "-- @tparam string nom le nom\n---@return number la somme\n---@see autre\n")
        self.assertEqual(doc, {"texte": "Ajoute deux nombres.",
                               "params": [["a", "number le premier"],
                                          ["b?", "number le second, facultatif"],
                                          ["nom", "(string) le nom"]],
                               "retours": ["number la somme"], "notes": ["@see autre"]})

    def test_long_comments_rules_and_paragraphs(self):
        doc = describe("--[[\n  Première ligne.\n  -----------\n  Suite du texte.\n]]")
        self.assertEqual(doc["texte"], "Première ligne.\n\nSuite du texte.")
        self.assertEqual(describe("------------------\n-- Titre\n------------------")["texte"], "Titre")

    def test_commented_out_code_says_nothing(self):
        self.assertIsNone(describe("--wait(0.5)\n--Move({ Id = 1,\n--   Dest = 2 })"))
        self.assertIsNone(describe("--[[\nlocal x = f(1)\nif x then g() end\n]]"))
        self.assertIsNone(describe("-- ======"))
        self.assertIsNone(documentation(()))
        # Words that Lua could read stay text without brackets or an assignment.
        self.assertEqual(describe("-- local copy")["texte"], "local copy")

    def test_wrapped_lines_are_joined(self):
        doc = describe("-- Une phrase coupée\n-- en deux lignes :\n-- - un point\n-- - 2. un autre\n--\n-- Fin.")
        self.assertEqual(doc["texte"], "Une phrase coupée en deux lignes :\n- un point\n- 2. un autre\n\nFin.")

    def test_long_descriptions_are_cut(self):
        doc = describe("-- " + "mot " * 600)
        self.assertEqual(len(doc["texte"]), DESCRIPTION_LIMIT)
        self.assertTrue(doc["texte"].endswith("…"))

    def test_a_blank_line_or_code_ends_the_block(self):
        functions = by_name(report("-- Loin.\n\nlocal function a() end\n-- Près.\nlocal x = 1\n"
                                   "local function b() end\nlocal t = {\n  -- Champ.\n  c = function() end,\n}\n"))
        self.assertIsNone(functions["a"]["doc"])
        self.assertIsNone(functions["b"]["doc"])
        self.assertEqual(functions["c"]["doc"]["texte"], "Champ.")
        # The script's description is the comment written before any code.
        self.assertEqual(functions[""]["doc"]["texte"], "Loin.")
        header = by_name(report("-- Titre.\n\n-- Suite.\nlocal x = 1\n"))[""]["doc"]["texte"]
        self.assertEqual(header, "Titre.\n\nSuite.")


class PageTests(unittest.TestCase):
    def test_the_page_is_standalone_and_ascii(self):
        source = SOURCE + 'local piege = "</script><!-- été \U0001F319 & <b>"\n'
        page = build_report(source, "dossier/sous/essai.lua", date=DAY)
        self.assertTrue(page.isascii())
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn("<title>D&#233;cisions de essai.lua</title>", page)
        self.assertIn("Content-Security-Policy", page)
        # Three scripts: the theme, the data and the reader; the source cannot close one.
        self.assertEqual(page.lower().count("</script"), 3)
        self.assertNotIn("<!--", page)
        # Nothing is loaded from elsewhere: every address is written inside the page.
        self.assertEqual(re.findall(r'(?:src|href)="(?!data:)[^"]*"', page), [])
        self.assertNotIn("url(\"fonts/", page)
        data = embedded(page)
        self.assertEqual((data["nom"], data["source"]), ("essai.lua", source))
        self.assertEqual(data, json.loads(json.dumps(report_data(
            Document("x", "essai.lua", source, 150), date=DAY))))

    def test_one_script_holds_the_drawing_module(self):
        page = build_report(SOURCE, date=DAY)
        script = page[page.index('<script type="module">'):]
        self.assertIn("const __organigramme = (() => {", script)
        self.assertIn("function construire(flux, titre", script)
        self.assertIn("= __organigramme;", script)
        self.assertIsNone(re.search(r"^(import|export) ", script, re.M))

    def test_invalid_lua_is_refused(self):
        with self.assertRaises(LuaSyntaxError) as raised:
            build_report("x = (", "faux.lua")
        self.assertIn("faux.lua:1:", str(raised.exception))

    def test_command_line(self):
        def invoke(*arguments: str) -> subprocess.CompletedProcess:
            return subprocess.run([sys.executable, "-m", "lua_parser_pro", *arguments],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=ROOT, timeout=30)
        with tempfile.TemporaryDirectory() as directory:
            good = Path(directory) / "combat.lua"
            good.write_text(SOURCE, encoding="utf-8")
            bad = Path(directory) / "faux.lua"
            bad.write_text("if x then", encoding="utf-8")
            process = invoke(str(good), "--html")
            self.assertEqual(process.returncode, 0, process.stderr)
            self.assertTrue(process.stdout.isascii())
            self.assertEqual(embedded(process.stdout.decode("ascii"))["nom"], "combat.lua")
            process = invoke(str(bad), "--html")
            self.assertEqual((process.returncode, process.stdout), (1, b""))
            self.assertIn(b"faux.lua:1:", process.stderr)
            self.assertEqual(invoke(str(good), "--html", "--check").returncode, 2)


if __name__ == "__main__":
    unittest.main()
