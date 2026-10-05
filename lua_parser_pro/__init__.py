"""Lua 5.4 syntax analysis, without executing the input program."""
from .analysis import Symbol, outline, statistics
from .ast import Chunk, Node, walk
from .batch import FileReport, check_file, check_files, find_lua_files, read_source
from .lexer import Lexer, tokenize
from .model import LuaSyntaxError, Position, Span, Token
from .parser import parse

__version__ = "1.1.0"
__all__ = ["parse", "tokenize", "Lexer", "LuaSyntaxError", "Node", "Chunk", "walk",
           "Position", "Span", "Token", "outline", "statistics", "Symbol",
           "read_source", "check_file", "check_files", "find_lua_files", "FileReport",
           "__version__"]
