"""Read a Lua file without running it: python examples/inspect_ast.py [file.lua]

Lists the declarations of the file, then the decision counts of each function.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # Runs without installing the package.

from lua_parser_pro import LuaSyntaxError, outline, parse, walk
from lua_parser_pro.analysis import expression_text, function_metrics
from lua_parser_pro.ast import FunctionStatement
from lua_parser_pro.batch import read_source

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("demo.lua")
source, encoding = read_source(path, "auto")
try:
    tree = parse(source, filename=str(path), encoding=encoding)
except LuaSyntaxError as error:
    raise SystemExit(str(error))

print(f"{path.name} : {len(tree.body)} instruction(s), {len(tree.comments)} commentaire(s)")
for symbol in outline(tree):
    print(f"  ligne {symbol.span.start.line:>4}  {symbol.kind:<9} {symbol.name}")

for node in walk(tree):
    if isinstance(node, FunctionStatement):
        name = expression_text(node.name) + (f":{node.method.name}" if node.method else "")
        counts = function_metrics(node.function)
        print(f"{name} : complexité {counts['complexity']}, {counts['decisions']} test(s), "
              f"{counts['loops']} boucle(s), {counts['exits']} return")
