"""French wording of the diagnostics, for the Studio.

The library reports diagnostics in English with a stable ``code``. The Studio
speaks French: each message is matched by its code and its shape, and anything
unknown is shown as written by the library.
"""
from __future__ import annotations

import re
from collections.abc import Callable

_Rule = tuple[str, "re.Pattern[str]", Callable[["re.Match[str]"], str]]


def _quoted(text: str) -> str:
    return "« " + text + " »"


def _found(text: str) -> str:
    return "la fin du fichier" if text == "end of input" else _quoted(text.strip("'\""))


def _rule(code: str, pattern: str, render: Callable[["re.Match[str]"], str]) -> _Rule:
    return code, re.compile(pattern, re.S), render


_RULES: tuple[_Rule, ...] = (
    _rule("SYNTAX_ERROR", r"Expected '(.+?)', found (.+)",
          lambda m: f"{_quoted(m[1])} attendu, mais on trouve {_found(m[2])}."),
    _rule("SYNTAX_ERROR", r"Expected an expression",
          lambda m: "Une expression est attendue ici."),
    _rule("SYNTAX_ERROR", r"Expected an identifier",
          lambda m: "Un nom est attendu ici."),
    _rule("SYNTAX_ERROR", r"Expected end of input",
          lambda m: "Le fichier devrait se terminer ici : ce mot ne commence aucune instruction."),
    _rule("SYNTAX_ERROR", r"Expected an assignment or a function call",
          lambda m: "Une instruction doit être une affectation ou un appel de fonction."),
    _rule("SYNTAX_ERROR", r"Expected function arguments.*",
          lambda m: "Des arguments sont attendus après le nom de la méthode : (...), {...} ou une chaîne."),
    _rule("SYNTAX_ERROR", r"A return statement must be the last statement in its block",
          lambda m: "« return » doit être la dernière instruction de son bloc."),
    _rule("INVALID_BREAK", r".*",
          lambda m: "« break » n'est permis qu'à l'intérieur d'une boucle."),
    _rule("INVALID_ASSIGNMENT", r".*",
          lambda m: "On ne peut pas affecter une valeur à cette expression."),
    _rule("INVALID_VARARG", r".*",
          lambda m: "« ... » n'est permis que dans une fonction à arguments variables."),
    _rule("INVALID_ATTRIBUTE", r"Unknown local attribute '(.+)'",
          lambda m: f"Attribut {_quoted(m[1])} inconnu : seuls <const> et <close> existent."),
    _rule("INVALID_ATTRIBUTE", r"Only one <close>.*",
          lambda m: "Une déclaration ne peut contenir qu'une seule variable <close>."),
    _rule("DEPTH_LIMIT", r"Maximum syntax depth exceeded",
          lambda m: "Trop de niveaux d'imbrication pour la profondeur maximale choisie."),
    _rule("DEPTH_LIMIT", r"Maximum syntax-tree depth exceeded",
          lambda m: "L'arbre dépasse la profondeur maximale choisie (longue chaîne d'opérateurs ou d'accès)."),
    _rule("DEPTH_LIMIT", r"Python recursion limit reached.*",
          lambda m: "Imbrication trop profonde pour être analysée."),
    _rule("MALFORMED_NUMBER", r"Malformed number (.+)",
          lambda m: f"Nombre mal formé : {_quoted(m[1].strip(chr(39) + chr(34)))}."),
    _rule("UNTERMINATED_STRING", r"Unterminated long string",
          lambda m: "Chaîne longue jamais refermée."),
    _rule("UNTERMINATED_STRING", r".*",
          lambda m: "Chaîne jamais refermée avant la fin de la ligne."),
    _rule("UNTERMINATED_COMMENT", r".*",
          lambda m: "Commentaire long jamais refermé."),
    _rule("INVALID_ESCAPE", r"Invalid escape sequence (.+)",
          lambda m: f"Séquence d'échappement {_quoted(m[1])} inconnue."),
    _rule("INVALID_ESCAPE", r"Decimal escape exceeds 255",
          lambda m: "Un échappement décimal ne peut pas dépasser 255."),
    _rule("INVALID_ESCAPE", r"Expected exactly two hexadecimal digits.*",
          lambda m: "« \\x » doit être suivi d'exactement deux chiffres hexadécimaux."),
    _rule("INVALID_ESCAPE", r"Unicode escape exceeds.*",
          lambda m: "Échappement Unicode trop grand (maximum 7FFFFFFF)."),
    _rule("INVALID_ESCAPE", r"Expected .* (after \\u|in Unicode escape|after Unicode escape)",
          lambda m: "Échappement Unicode mal formé : la forme attendue est \\u{XXXX}."),
    _rule("INVALID_LONG_DELIMITER", r".*",
          lambda m: "Délimiteur de chaîne longue invalide : [=[ ... ]=] attendu."),
    _rule("INVALID_CHARACTER", r"Unexpected character (.+)",
          lambda m: f"Caractère inattendu : {m[1]}."),
    _rule("INVALID_SOURCE", r"Source contains an isolated Unicode surrogate",
          lambda m: "Le texte contient un caractère Unicode invalide (substitut isolé)."),
    _rule("INVALID_SOURCE", r"String contains a character that (.+) cannot encode",
          lambda m: f"La chaîne contient un caractère que l'encodage {m[1]} ne sait pas représenter."),
    _rule("TOKEN_LIMIT", r"Source exceeds the limit of (\d+) tokens",
          lambda m: f"Le texte dépasse la limite de {int(m[1]):,} jetons.".replace(",", " ")),
    _rule("SOURCE_LIMIT", r"Source exceeds the limit of (\d+) characters",
          lambda m: f"Le texte dépasse la limite de {int(m[1]):,} caractères.".replace(",", " ")),
    _rule("UNREADABLE", r"(.*)", lambda m: f"Fichier illisible : {m[1]}"),
)

_NAMES = {
    "SYNTAX_ERROR": "Erreur de syntaxe",
    "INVALID_BREAK": "break hors boucle",
    "INVALID_ASSIGNMENT": "Affectation invalide",
    "INVALID_VARARG": "... hors fonction variadique",
    "INVALID_ATTRIBUTE": "Attribut invalide",
    "DEPTH_LIMIT": "Profondeur dépassée",
    "MALFORMED_NUMBER": "Nombre mal formé",
    "UNTERMINATED_STRING": "Chaîne non terminée",
    "UNTERMINATED_COMMENT": "Commentaire non terminé",
    "INVALID_ESCAPE": "Échappement invalide",
    "INVALID_LONG_DELIMITER": "Délimiteur invalide",
    "INVALID_CHARACTER": "Caractère inattendu",
    "INVALID_SOURCE": "Texte invalide",
    "TOKEN_LIMIT": "Trop de jetons",
    "SOURCE_LIMIT": "Texte trop long",
    "UNREADABLE": "Fichier illisible",
}


def translate(code: str, message: str) -> str:
    """French sentence for a diagnostic; the original message when none is known."""
    for rule_code, pattern, render in _RULES:
        if rule_code == code:
            match = pattern.fullmatch(message)
            if match is not None:
                return render(match)
    return message


def title(code: str) -> str:
    """Short French name of a diagnostic code."""
    return _NAMES.get(code, code)
