"""Public API integration and Lua 5.4 syntax conformance regressions.

These tests validate syntax, AST shape, context checks, and bounded failure.
They intentionally do not treat parsing as execution or semantic compilation.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest
from uuid import uuid4

from lua_parser_pro import LuaSyntaxError, parse, walk
from lua_parser_pro import ast


def expression(source: str) -> ast.Expression:
    tree = parse("return " + source)
    statement = tree.body[0]
    assert isinstance(statement, ast.ReturnStatement)
    return statement.arguments[0]


def shape(node: ast.Expression):
    """Small semantic projection used to make precedence expectations legible."""
    if isinstance(node, ast.Identifier):
        return node.name
    if isinstance(node, ast.NumberLiteral):
        return node.raw
    if isinstance(node, ast.UnaryExpression):
        return (node.operator, shape(node.argument))
    if isinstance(node, ast.BinaryExpression):
        return (node.operator, shape(node.left), shape(node.right))
    if isinstance(node, ast.ParenthesizedExpression):
        return ("()", shape(node.expression))
    raise AssertionError(f"Unexpected node in expression projection: {node.type}")


class AcceptedSyntaxTests(unittest.TestCase):
    def test_empty_chunk_and_empty_statements(self):
        self.assertEqual(parse("").body, ())
        self.assertEqual(parse("  -- only a comment\n").body, ())
        self.assertEqual([n.type for n in parse(";;;").body],
                         ["EmptyStatement"] * 3)

    def test_assignment_preserves_order_and_lvalue_structure(self):
        tree = parse("a, obj.key, obj[index], factory().x = b, 2, nil, false")
        statement = tree.body[0]
        self.assertIsInstance(statement, ast.AssignmentStatement)
        self.assertEqual([n.type for n in statement.targets],
                         ["Identifier", "MemberExpression", "IndexExpression",
                          "MemberExpression"])
        self.assertEqual(statement.targets[0].name, "a")
        self.assertEqual(statement.targets[1].name.name, "key")
        self.assertIsInstance(statement.targets[3].base, ast.CallExpression)
        self.assertEqual([n.type for n in statement.values],
                         ["Identifier", "NumberLiteral", "NilLiteral", "BooleanLiteral"])

    def test_parenthesized_base_can_be_indexed_and_assigned(self):
        for source in ("(obj).key=3", "(obj)[index]=3", "(f())['x']=4"):
            with self.subTest(source=source):
                self.assertIsInstance(parse(source).body[0], ast.AssignmentStatement)

    def test_locals_and_attributes(self):
        tree = parse("local x <const>, file <close>, y = 1, open(), nil; local z")
        statement = tree.body[0]
        self.assertIsInstance(statement, ast.LocalStatement)
        self.assertEqual([(v.name.name, v.attribute) for v in statement.variables],
                         [("x", "const"), ("file", "close"), ("y", None)])
        self.assertEqual(len(statement.values), 3)
        self.assertEqual(tree.body[-1].values, ())
        for source in ("local x <const>", "local x <close>",
                       "local x <close>; local y <close>"):
            with self.subTest(source=source):
                parse(source)

    def test_all_control_statement_forms(self):
        source = """
do local x=1 end
while ready do if done then break end tick() end
repeat local x=read() until x
if a then first() elseif b then second() elseif c then third() else last() end
for i=1,10 do tick(i) end
for i=10,1,-1 do tick(i) end
for key,value in pairs(t), state, first do use(key,value) end
::again::
goto again
"""
        tree = parse(source)
        self.assertEqual([n.type for n in tree.body],
                         ["DoStatement", "WhileStatement", "RepeatStatement",
                          "IfStatement", "NumericForStatement", "NumericForStatement",
                          "GenericForStatement", "LabelStatement", "GotoStatement"])
        self.assertEqual(len(tree.body[3].clauses), 4)
        self.assertIsNone(tree.body[3].clauses[-1].condition)
        self.assertIsNone(tree.body[4].step)
        self.assertIsInstance(tree.body[5].step, ast.UnaryExpression)
        self.assertEqual([n.name for n in tree.body[6].variables], ["key", "value"])
        self.assertEqual(len(tree.body[6].iterators), 3)

    def test_function_declarations_and_anonymous_functions(self):
        tree = parse("""
function package.module:method(a,b,...) return self,a,b,... end
local function factorial(n) if n==0 then return 1 end return n*factorial(n-1) end
local f = function(...) return ... end
""")
        method, local_function, local_binding = tree.body
        self.assertIsInstance(method, ast.FunctionStatement)
        self.assertFalse(method.local)
        self.assertEqual(method.method.name, "method")
        self.assertTrue(method.function.variadic)
        # Parameters preserve the written syntax; implicit self need not be inserted.
        self.assertEqual([p.name for p in method.function.parameters][-2:], ["a", "b"])
        self.assertTrue(local_function.local)
        self.assertEqual(local_function.name.name, "factorial")
        self.assertFalse(local_function.function.variadic)
        self.assertIsInstance(local_binding.values[0], ast.FunctionExpression)
        self.assertTrue(local_binding.values[0].variadic)

    def test_call_sugar_and_suffix_chains(self):
        for source in ("f()", "f{1,2}", "f 'text'", "f [[text]]",
                       "f 'x' [[y]] {}", "(f or g)(1)",
                       "factory().items[1]:send('x')(2)"):
            with self.subTest(source=source):
                self.assertIsInstance(parse(source).body[0], ast.CallStatement)
        call = expression("object:send(1,2)")
        self.assertIsInstance(call, ast.CallExpression)
        self.assertEqual(call.method.name, "send")
        self.assertEqual(len(call.arguments), 2)

    def test_newline_does_not_separate_a_following_call(self):
        tree = parse("local result=f\n(1)")
        self.assertEqual(len(tree.body), 1)
        self.assertIsInstance(tree.body[0].values[0], ast.CallExpression)

    def test_table_field_kinds_and_trailing_separators(self):
        table = expression("{ 'first'; answer=42, [f()]=true, g(), }")
        self.assertIsInstance(table, ast.TableExpression)
        self.assertEqual([f.kind for f in table.fields], ["value", "name", "index", "value"])
        self.assertIsNone(table.fields[0].key)
        self.assertEqual(table.fields[1].key.name, "answer")
        self.assertIsInstance(table.fields[2].key, ast.CallExpression)
        self.assertEqual(expression("{}").fields, ())
        parse("return {1;}")

    def test_return_forms_and_block_finality(self):
        for source in ("return", "return;", "return 1,2,3;",
                       "do return end f()", "if yes then return else return; end",
                       "repeat return until ready"):
            with self.subTest(source=source):
                parse(source)

    def test_chunk_is_variadic(self):
        self.assertIsInstance(expression("..."), ast.VarargExpression)
        parse("do local args={...} end")
        parse("function f(...) return ... end return ...")

    def test_break_is_not_required_to_be_last(self):
        for source in ("while true do break; f() end",
                       "for i=1,2 do break print(i) end",
                       "repeat if done then break; f() end until ready"):
            with self.subTest(source=source):
                parse(source)

    def test_exact_numeric_lexemes_survive_parsing_and_json(self):
        lexemes = ["9223372036854775807", "0xffffffffffffffff", "0x.8",
                   "0x1.fp+2", ".25", "1.", "1e+8", "1e9999"]
        tree = parse("return " + ",".join(lexemes))
        self.assertEqual([node.raw for node in tree.body[0].arguments], lexemes)
        encoded = json.loads(json.dumps(tree.to_dict()))
        self.assertEqual([n["raw"] for n in encoded["body"][0]["arguments"]], lexemes)
        self.assertEqual(shape(expression("0xe+1")), ("+", "0xe", "1"))

    def test_byte_strings_remain_exact_in_ast_and_json(self):
        node = expression(r"'\0\255\x80\u{1f642}'")
        self.assertIsInstance(node, ast.StringLiteral)
        self.assertEqual(node.value, b"\x00\xff\x80\xf0\x9f\x99\x82")
        self.assertEqual(node.raw, r"'\0\255\x80\u{1f642}'")
        self.assertEqual(node.to_dict()["value"], [0, 255, 128, 240, 159, 153, 130])
        self.assertEqual(expression("[==[a]=]b]==]").value, b"a]=]b")

    def test_semantic_compiler_checks_are_outside_parser_scope(self):
        # All are syntactically valid, although the official compiler rejects them.
        for source in ("goto missing", "::again:: ::again::", 
                       "goto finish; local x=1; ::finish:: f(x)",
                       "local x <const> = 1; x=2"):
            with self.subTest(source=source):
                self.assertIsInstance(parse(source), ast.Chunk)


class PrecedenceTests(unittest.TestCase):
    def test_exponentiation_versus_unary_operators(self):
        self.assertEqual(shape(expression("-2^2")), ("-", ("^", "2", "2")))
        self.assertEqual(shape(expression("2^-3")), ("^", "2", ("-", "3")))
        self.assertEqual(shape(expression("~x^2")), ("~", ("^", "x", "2")))

    def test_associativity(self):
        self.assertEqual(shape(expression("a^b^c")), ("^", "a", ("^", "b", "c")))
        self.assertEqual(shape(expression("a..b..c")), ("..", "a", ("..", "b", "c")))
        self.assertEqual(shape(expression("a-b-c")), ("-", ("-", "a", "b"), "c"))
        self.assertEqual(shape(expression("a<b<c")), ("<", ("<", "a", "b"), "c"))

    def test_every_adjacent_precedence_level(self):
        # Operators listed from weakest to strongest; use distinct variables.
        operators = ["or", "and", "==", "|", "~", "&", "<<", "..", "+", "*"]
        for weak, strong in zip(operators, operators[1:]):
            with self.subTest(weak=weak, strong=strong):
                self.assertEqual(shape(expression(f"a {weak} b {strong} c")),
                                 (weak, "a", (strong, "b", "c")))
                self.assertEqual(shape(expression(f"a {strong} b {weak} c")),
                                 (weak, (strong, "a", "b"), "c"))
        self.assertEqual(shape(expression("not a==b")), ("==", ("not", "a"), "b"))
        self.assertEqual(shape(expression("a * -b")), ("*", "a", ("-", "b")))

    def test_parentheses_are_preserved(self):
        self.assertEqual(shape(expression("(a+b)*c")),
                         ("*", ("()", ("+", "a", "b")), "c"))
        self.assertIsInstance(expression("(f())"), ast.ParenthesizedExpression)

    def test_remaining_binary_operators(self):
        for operator in ("~=", ">", "<=", ">=", ">>", "/", "//", "%"):
            with self.subTest(operator=operator):
                self.assertEqual(shape(expression(f"a {operator} b")), (operator, "a", "b"))


class RejectedSyntaxTests(unittest.TestCase):
    def test_malformed_statements_and_expressions(self):
        rejected = [
            "a+b", "a", "{}", "(f())", "(a)=1", "f()=1", "1=2",
            "local", "local a,=1", "local a=", "local a b", "a,=1",
            "a=1,", "a,b", "return,", "return 1,", "return; f()", "return;;",
            "return 1 local a=2", "do return; f() end", "f(1,)", "f(",
            "return (1", "return 1)", "return a +", "return +1", "return !x",
            "return {,}", "return {1,,2}", "return {x=}", "return {[x] 1}",
            "return {end=1}", "a.end=1", "local end=1", "goto", "::name:",
            "if x do end", "if x then", "if x then else elseif y then end",
            "while x end", "repeat f() end", "for i=1 do end", "for a,b=1,2 do end",
            "for a in do end", "for i=1,2,3,4 do end", "do", "end", "until true",
            "local function a.b() end", "function a:b.c() end", "function () end",
            "function f(a,) end", "function f(...,a) end", "function f(a ...) end",
            "local f=function(a) return a", "f:method", "return a[ ]",
        ]
        for source in rejected:
            with self.subTest(source=source):
                with self.assertRaises(LuaSyntaxError):
                    parse(source)

    def test_invalid_lexemes_surface_as_syntax_errors(self):
        rejected = ["0x", "1e+", "1_2", "0b10", "1..2", "0x1p", "12abc",
                    r"'\q'", r"'\256'", r"'\xF'", r"'\u{}'", r"'\u{80000000}'",
                    "[=[unterminated]]", "'unfinished", "'raw\nnewline'"]
        for value in rejected:
            with self.subTest(value=value):
                with self.assertRaises(LuaSyntaxError):
                    parse("return " + value)

    def test_attribute_errors(self):
        for source in ("local x <unknown> = 1", "local x <const>=1",
                       "local x <close>, y <close> = a,b", "local x <const><close> = 1",
                       "local x <> = 1", "local x <const = 1"):
            with self.subTest(source=source):
                with self.assertRaises(LuaSyntaxError):
                    parse(source)

    def test_break_cannot_cross_function_boundaries(self):
        for source in ("break", "do break end", "if x then break end",
                       "while true do local f=function() break end end",
                       "for x in iter() do function f() break end end",
                       "repeat local function f() break end until true"):
            with self.subTest(source=source):
                with self.assertRaises(LuaSyntaxError):
                    parse(source)

    def test_varargs_cannot_cross_function_boundaries(self):
        for source in ("function f() return ... end", "local f=function(a) return ... end",
                       "function f(...) return function() return ... end end",
                       "local function f() do return ... end end"):
            with self.subTest(source=source):
                with self.assertRaises(LuaSyntaxError):
                    parse(source)

    def test_context_is_restored_after_nested_function(self):
        parse("function f(...) local g=function() end return ... end")
        parse("while true do local f=function() while true do break end end break end")
        parse("function f() local g=function(...) return ... end end")
        with self.assertRaises(LuaSyntaxError):
            parse("function f() local g=function(...) end return ... end")
        with self.assertRaises(LuaSyntaxError):
            parse("local f=function() while true do break end end break")


class PublicApiTests(unittest.TestCase):
    def test_source_locations_are_exclusive_and_one_based(self):
        source = "local answer = 42\r\nreturn answer"
        tree = parse(source)
        local, returned = tree.body
        self.assertEqual((local.span.start.offset, local.span.start.line,
                          local.span.start.column), (0, 1, 1))
        self.assertEqual(local.span.end.offset, 17)
        self.assertEqual((returned.span.start.offset, returned.span.start.line,
                          returned.span.start.column), (19, 2, 1))
        self.assertEqual(returned.span.end.offset, len(source))
        number = local.values[0]
        self.assertEqual(source[number.span.start.offset:number.span.end.offset], "42")
        self.assertEqual((number.span.start.column, number.span.end.column), (16, 18))

    def test_walk_is_preorder_and_spans_stay_inside_source(self):
        source = "local f=function(a) return {key=a+2,[a]=f(a)} end; f(3)"
        tree = parse(source)
        nodes = list(walk(tree))
        self.assertIs(nodes[0], tree)
        self.assertIs(nodes[1], tree.body[0])
        self.assertEqual(sum(isinstance(n, ast.Identifier) and n.name == "a" for n in nodes), 4)
        self.assertTrue(any(isinstance(n, ast.TableField) for n in nodes))
        for node in nodes:
            with self.subTest(type=node.type):
                self.assertGreaterEqual(node.span.start.offset, 0)
                self.assertLessEqual(node.span.start.offset, node.span.end.offset)
                self.assertLessEqual(node.span.end.offset, len(source))
                self.assertGreaterEqual(node.span.start.line, 1)
                self.assertGreaterEqual(node.span.start.column, 1)

    def test_comments_are_optional_and_do_not_change_statements(self):
        source = "-- first\nlocal x=1 -- second\n--[=[ third ]=]\nreturn x"
        included = parse(source)
        omitted = parse(source, comments=False)
        self.assertEqual(len(included.comments), 3)
        self.assertEqual(omitted.comments, ())
        self.assertEqual(included.body, omitted.body)
        for comment in included.comments:
            self.assertEqual(source[comment.span.start.offset:comment.span.end.offset], comment.raw)

    def test_diagnostics_include_file_and_position(self):
        source = "local x=1\nreturn )"
        with self.assertRaises(LuaSyntaxError) as caught:
            parse(source, filename="example.lua")
        error = caught.exception
        self.assertEqual(error.filename, "example.lua")
        self.assertEqual(error.span.start.line, 2)
        self.assertEqual(error.span.start.column, 8)
        self.assertEqual(error.source, source)
        self.assertIn("example.lua:2:8:", str(error))
        self.assertIn("^", str(error))
        self.assertEqual(error.to_dict()["offset"], source.index(")"))
        self.assertTrue(error.to_dict()["code"])

    def test_resource_limits_fail_with_controlled_diagnostics(self):
        with self.assertRaises(LuaSyntaxError):
            parse("return 1", max_source_length=3)
        with self.assertRaises(LuaSyntaxError):
            parse("local a,b,c=1,2,3", max_tokens=3)
        with self.assertRaises(LuaSyntaxError):
            parse("return " + "(" * 100 + "1" + ")" * 100, max_depth=20)
        with self.assertRaises(LuaSyntaxError):
            parse("do " * 100 + "end " * 100, max_depth=20)
        with self.assertRaises(LuaSyntaxError):
            parse("return " + "not " * 100 + "true", max_depth=20)
        parse("return " + "(" * 10 + "1" + ")" * 10)

    def test_parse_calls_are_independent_after_a_failure(self):
        with self.assertRaises(LuaSyntaxError):
            parse("function f() return ... end")
        self.assertIsInstance(parse("return ...").body[0], ast.ReturnStatement)
        with self.assertRaises(LuaSyntaxError):
            parse("break")
        parse("while true do break end")

    def test_parsing_never_executes_source(self):
        target = Path(__file__).resolve().parent / f"must-not-create-{uuid4().hex}.txt"
        # Forward slashes make the literal portable across Windows and Unix.
        source = f'local f=io.open("{target.as_posix()}","w"); f:write("bad"); f:close()'
        self.assertFalse(target.exists())
        tree = parse(source)
        self.assertIsInstance(tree, ast.Chunk)
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
