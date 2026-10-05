"""Outline, measures and decision mechanics computed from the syntax tree."""
from __future__ import annotations

import gc
import json
import unittest

from lua_parser_pro import Lexer, outline, parse, statistics, walk
from lua_parser_pro import analysis, ast
from lua_parser_pro.ast import iter_json, to_dict
from lua_parser_pro.model import gc_paused

SOURCE = '''-- module
local M = {}
local LIMITE <const> = 10
function M.calcule(a, b)
    if a > b and b > 0 then
        return a - b
    elseif a == b then
        return 0
    end
    for i = 1, LIMITE do
        while a < b do a = a + i end
    end
    repeat b = b - 1 until b <= 0 or a > 100
    error("jamais")
end
function M:methode(...) return ... end
M.table = { x = 1, f = function() end, ["y z"] = {} }
on("evt", function(e) if e then goto fin end ::fin:: end)
return M
'''


def function_named(tree: ast.Chunk, name: str) -> ast.FunctionExpression:
    for node in walk(tree):
        if isinstance(node, ast.FunctionStatement) and analysis.expression_text(node.name) == name:
            return node.function
    raise AssertionError(f"no function named {name}")


class OutlineTests(unittest.TestCase):
    def setUp(self):
        self.tree = parse(SOURCE)
        self.symbols = outline(self.tree)

    def test_declarations_in_source_order(self):
        self.assertEqual([(s.name, s.kind, s.local) for s in self.symbols], [
            ("M", "table", True), ("LIMITE", "variable", True), ("M.calcule", "function", False),
            ("M:methode", "method", False), ("M.table", "table", False), ("on", "callback", False),
        ])

    def test_details_of_each_kind(self):
        by_name = {symbol.name: symbol for symbol in self.symbols}
        self.assertEqual(by_name["LIMITE"].value, "10")
        self.assertEqual(by_name["M.calcule"].parameters, ("a", "b"))
        self.assertEqual(by_name["M:methode"].parameters, ("...",))
        self.assertEqual(by_name["M.table"].fields, 3)
        self.assertEqual(by_name["on"].parameters, ("e",))
        self.assertEqual((by_name["M.calcule"].span.start.line, by_name["M.calcule"].span.end.line), (4, 15))

    def test_table_lists_its_function_and_table_fields(self):
        table = next(symbol for symbol in self.symbols if symbol.name == "M.table")
        self.assertEqual([(child.name, child.kind) for child in table.children],
                         [("f", "function"), ('"y z"', "table")])

    def test_functions_nest_and_returned_values_are_named(self):
        tree = parse("local function a()\n  local function b() end\n  return function() end\nend\n"
                     "return { run = a }")
        symbols = outline(tree)
        self.assertEqual([symbol.name for symbol in symbols], ["a", "return"])
        self.assertEqual([(child.name, child.kind) for child in symbols[0].children],
                         [("b", "function"), ("", "function")])
        self.assertEqual((symbols[1].kind, symbols[1].fields), ("table", 1))

    def test_to_dict_is_json_data(self):
        data = [symbol.to_dict() for symbol in self.symbols]
        self.assertEqual(json.loads(json.dumps(data)), data)
        self.assertEqual(sorted(data[0]), ["children", "column", "end_line", "end_offset", "fields", "kind",
                                           "line", "local", "name", "offset", "parameters", "value"])

    def test_deeply_nested_tables_do_not_recurse(self):
        depth = 200
        tree = parse("t = " + "{ a = " * depth + "1" + " }" * depth, max_depth=2000)
        self.assertEqual(outline(tree)[0].name, "t")


class StatisticsTests(unittest.TestCase):
    def test_counts(self):
        tokens = Lexer(SOURCE).tokenize()
        stats = statistics(parse(SOURCE), tokens)
        self.assertEqual(stats["lines"], {"total": 19, "code": 18, "comment_only": 1, "blank": 0})
        self.assertEqual(stats["characters"], len(SOURCE))
        self.assertEqual(stats["tokens"]["total"], len(tokens) - 1)
        self.assertEqual(stats["comments"], {"total": 1, "characters": len("-- module")})
        self.assertEqual(stats["functions"]["total"], 4)
        self.assertEqual(stats["functions"]["longest"][0], {"name": "M.calcule", "lines": 12, "line": 4})
        self.assertEqual(stats["calls"]["total"], 2)
        self.assertEqual(stats["strings"], {"total": 3, "bytes": 12})
        self.assertEqual(stats["nodes"]["total"], sum(1 for _ in walk(parse(SOURCE))))
        self.assertEqual(json.loads(json.dumps(stats)), stats)

    def test_without_tokens_token_counts_are_unknown(self):
        stats = statistics(parse("return 1\n"))
        self.assertIsNone(stats["tokens"])
        self.assertIsNone(stats["lines"]["code"])
        self.assertEqual(stats["lines"]["total"], 1)

    def test_empty_source(self):
        stats = statistics(parse(""), Lexer("").tokenize())
        self.assertEqual(stats["lines"]["total"], 0)
        self.assertEqual(stats["nodes"]["total"], 1)


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.tree = parse(SOURCE)
        self.function = function_named(self.tree, "M.calcule")

    def test_metrics_of_one_function(self):
        self.assertEqual(analysis.function_metrics(self.function), {
            "complexity": 8,      # 1 + if + elseif + three loops + "and" + "or"
            "decisions": 2, "loops": 3, "nesting": 2, "exits": 2, "statements": 9})

    def test_metrics_do_not_enter_nested_functions(self):
        self.assertEqual(analysis.function_metrics(self.tree), {
            "complexity": 1, "decisions": 0, "loops": 0, "nesting": 0, "exits": 1, "statements": 7})

    def test_logical_operators_only_count_inside_conditions(self):
        tree = parse("local x = a and b or c\nif not (p or q) and f(r and s) then end")
        self.assertEqual(analysis.function_metrics(tree)["complexity"], 1 + 1 + 3)

    def test_condition_terms(self):
        self.assertEqual(analysis.condition_terms(self.function), [("b", 5), ("a", 4)])
        tree = parse("if joueur.Vie <= 0 or estMort(joueur) then end\nwhile file[1] do end")
        self.assertEqual(analysis.condition_terms(tree),
                         [("estMort()", 1), ("file[1]", 1), ("joueur.Vie", 1)])

    def test_flow_of_a_function(self):
        flow = analysis.decision_flow(self.function, SOURCE)
        self.assertEqual(flow["kind"], "sequence")
        kinds = [step["kind"] for step in flow["steps"]]
        self.assertEqual(kinds, ["if", "for", "repeat", "error"])
        test = flow["steps"][0]
        self.assertEqual([branch["condition"] for branch in test["branches"]], ["a > b and b > 0", "a == b"])
        self.assertIsNone(test["otherwise"])
        self.assertEqual(test["branches"][0]["body"]["steps"][0],
                         {"kind": "return", "text": "return a - b",
                          "offset": SOURCE.index("return a - b"),
                          "end_offset": SOURCE.index("return a - b") + len("return a - b"), "line": 6})
        loop = flow["steps"][1]
        self.assertEqual(loop["condition"], "i = 1, LIMITE")
        inner = loop["body"]["steps"][0]
        self.assertEqual((inner["kind"], inner["condition"]), ("while", "a < b"))
        self.assertEqual(inner["body"]["steps"][0]["lines"], ["a = a + i"])
        self.assertEqual(flow["steps"][2]["condition"], "b <= 0 or a > 100")
        self.assertEqual(flow["steps"][3]["text"], 'error("jamais")')
        for step in flow["steps"]:
            self.assertEqual(SOURCE[step["offset"]:step["end_offset"]].split()[0],
                             {"if": "if", "for": "for", "repeat": "repeat", "error": 'error("jamais")'}[step["kind"]])

    def test_plain_statements_share_one_action(self):
        source = "local a = 1\nlocal b = 2\nf()\ng()\nh()\nif a then else b = 3 end\nreturn a"
        flow = analysis.decision_flow(parse(source), source)
        action, test, exit_ = flow["steps"]
        self.assertEqual((action["kind"], action["count"], action["line"]), ("action", 5, 1))
        self.assertEqual(action["lines"], ["local a = 1", "local b = 2", "f()", "g()"])
        self.assertEqual(source[action["offset"]:action["end_offset"]], source[:source.index("\nif")])
        self.assertEqual(test["branches"][0]["body"]["steps"], [])
        self.assertEqual(test["otherwise"]["steps"][0]["lines"], ["b = 3"])
        self.assertEqual(exit_["kind"], "return")

    def test_blocks_jumps_and_function_definitions(self):
        source = ("do local x = 1 end\nfor _, v in pairs(t) do\n  if v then break end\n  goto suite\n"
                  "  ::suite::\nend\nlocal function aide(n)\n  return n\nend\n")
        flow = analysis.decision_flow(parse(source), source)
        self.assertEqual([step["kind"] for step in flow["steps"]], ["action", "for", "action"])
        self.assertEqual(flow["steps"][1]["condition"], "_, v in pairs(t)")
        body = flow["steps"][1]["body"]["steps"]
        self.assertEqual([step["kind"] for step in body], ["if", "goto", "label"])
        self.assertEqual(body[0]["branches"][0]["body"]["steps"][0]["kind"], "break")
        self.assertEqual((body[1]["text"], body[2]["text"]), ("goto suite", "::suite::"))
        self.assertEqual(flow["steps"][2]["lines"], ["local function aide(n)"])

    def test_budget_truncates_instead_of_growing(self):
        source = "".join(f"if c{i} then f{i}() end\n" for i in range(50))
        flow = analysis.decision_flow(parse(source), source, budget=10)
        kinds = [step["kind"] for step in flow["steps"]]
        self.assertEqual(len(kinds), 50)
        truncated = [step for step in flow["steps"]
                     if step["branches"][0]["body"]["steps"][:1] == [{"kind": "truncated", "count": 1}]]
        self.assertTrue(truncated)

    def test_long_statements_are_quoted_on_one_short_line(self):
        source = "x = {\n" + "    1234567890,\n" * 40 + "}\nif " + " and ".join(["condition"] * 40) + " then end"
        flow = analysis.decision_flow(parse(source), source, width=30)
        self.assertLessEqual(len(flow["steps"][0]["lines"][0]), 30)
        self.assertTrue(flow["steps"][0]["lines"][0].endswith("…"))
        self.assertNotIn("\n", flow["steps"][0]["lines"][0])
        self.assertLessEqual(len(flow["steps"][1]["branches"][0]["condition"]), 60)

    def test_expression_text(self):
        tree = parse('return a.b[1]:m("x"), not ok, -n, (f)(), ...')
        texts = [analysis.expression_text(argument) for argument in tree.body[0].arguments]
        self.assertEqual(texts, ["a.b[1]:m()", "not ok", "-n", "(f)()", "..."])
        self.assertLessEqual(len(analysis.expression_text(parse("return " + "a." * 100 + "b").body[0].arguments[0],
                                                          limit=20)), 20)


class SerialisationTests(unittest.TestCase):
    SAMPLES = [
        None, True, False, 0, -12, 3.5, "", "accentué … \U0001f319", 'quote " and \\ and \n',
        [], {}, [[]], [{}], {"a": []}, {"a": {}}, [1, [2, [3, []]], {"k": [None, {"z": "y"}]}],
        {"type": "Chunk", "body": [{"type": "ReturnStatement", "arguments": [{"value": [255, 0]}]}]},
    ]

    def test_same_text_as_the_standard_encoder(self):
        for sample in self.SAMPLES:
            with self.subTest(sample=sample):
                self.assertEqual("".join(iter_json(sample)), json.dumps(sample, separators=(",", ":")))
                self.assertEqual("".join(iter_json(sample, indent=2)), json.dumps(sample, indent=2))

    def test_tree_export_matches_the_standard_encoder(self):
        data = parse(SOURCE).to_dict()
        self.assertEqual("".join(iter_json(data, indent=2)), json.dumps(data, indent=2))
        self.assertEqual(json.loads("".join(iter_json(data))), data)

    def test_very_deep_data_is_written_without_recursion(self):
        data: list = []
        for _ in range(20_000):
            data = [data]
        text = "".join(iter_json(data))
        self.assertEqual(text, "[" * 20_001 + "]" * 20_001)

    def test_deep_tree_converts_and_exports(self):
        depth = 300
        tree = parse("return " + "(" * depth + "1" + ")" * depth, max_depth=1000)
        text = "".join(iter_json(to_dict(tree)))
        self.assertEqual(text.count('"ParenthesizedExpression"'), depth)

    def test_children_and_walk_agree(self):
        tree = parse(SOURCE)
        seen = []
        stack = [tree]
        while stack:
            node = stack.pop()
            seen.append(node)
            stack.extend(reversed(ast.children(node)))
        self.assertEqual([id(node) for node in seen], [id(node) for node in walk(tree)])
        self.assertNotIn("span", ast.child_fields(ast.BinaryExpression))
        self.assertEqual(ast.child_fields(ast.BinaryExpression), ("operator", "left", "right"))


class CollectorTests(unittest.TestCase):
    def test_gc_paused_restores_the_previous_state(self):
        was_enabled = gc.isenabled()
        try:
            gc.enable()
            with gc_paused():
                self.assertFalse(gc.isenabled())
                with gc_paused():
                    self.assertFalse(gc.isenabled())
                self.assertFalse(gc.isenabled())
            self.assertTrue(gc.isenabled())
            gc.disable()
            with gc_paused():
                self.assertFalse(gc.isenabled())
            self.assertFalse(gc.isenabled())
        finally:
            (gc.enable if was_enabled else gc.disable)()

    def test_gc_paused_restores_after_an_error(self):
        gc.enable()
        with self.assertRaises(ZeroDivisionError):
            with gc_paused():
                1 / 0
        self.assertTrue(gc.isenabled())


if __name__ == "__main__":
    unittest.main()
