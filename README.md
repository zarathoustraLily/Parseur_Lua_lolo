# Parseur Lua 5.4 en Python

Un analyseur de code Lua écrit en Python pur : il lit un script **sans jamais l'exécuter**, en construit l'arbre syntaxique et en tire ce qui aide à le comprendre. Il se compose de trois étages :

- un **parseur** de Lua 5.4 (analyse lexicale et syntaxique, arbre typé, positions exactes, diagnostics) ;
- des **analyses** : plan du script, mesures, complexité de chaque fonction, mécanique de ses décisions ;
- le **Studio**, une interface locale dans le navigateur, qui montre tout cela en direct pendant que l'on lit ou modifie le code.

Python **3.10 ou plus récent**. Aucune dépendance, aucune installation de Lua, aucune connexion à Internet.

## Le Studio

Sous Windows, double-cliquez sur `LANCER_STUDIO.bat` (on peut aussi glisser un dossier ou un fichier `.lua` sur ce fichier). Partout ailleurs, depuis le dossier du projet :

```console
python -m lua_parser_pro --gui
python -m lua_parser_pro --gui chemin/vers/mes/scripts
python -m lua_parser_pro --gui chemin/vers/un/script.lua
```

Le navigateur s'ouvre sur `http://127.0.0.1:8642/`. Pour arrêter le Studio, fermez la fenêtre de commande ou appuyez sur `Ctrl+C`.

À gauche, le code, coloré et analysé à chaque frappe. La lune de l'en-tête dit l'état : pleine quand la syntaxe est valide, rouge dès qu'une erreur est trouvée ; l'erreur est alors soulignée dans le code et expliquée en français sous l'éditeur (`F8` y conduit). À droite, cinq onglets :

| Onglet | Ce qu'il montre |
| --- | --- |
| **Décisions** | L'organigramme de la fonction où se trouve le curseur : ses tests, ses boucles, ses sorties. C'est la « mécanique » de la fonction. |
| **Plan** | Les fonctions, tables et variables déclarées, dans l'ordre du texte, avec la complexité de chaque fonction. Un clic y conduit. |
| **Arbre** | L'arbre syntaxique complet, dépliable ; il suit le curseur. |
| **Mesures** | Lignes, jetons, nœuds, puis les fonctions les plus complexes, les plus longues et les appels les plus fréquents. |
| **Jetons** | Ce que voit l'analyseur lexical, jeton par jeton. |

Le bouton **Ouvrir un dossier** liste tous les fichiers `.lua` d'un dossier et de ses sous-dossiers ; **Vérifier tous les fichiers** contrôle leur syntaxe en parallèle et marque ceux qui contiennent une erreur. Les fichiers qui ne sont pas en UTF-8 sont lus en Latin-1, octet pour octet. **Exporter** enregistre l'arbre ou les jetons en JSON, ou les organigrammes des décisions dans une page HTML autonome (voir plus bas) : la fenêtre « Enregistrer sous » du système demande le nom et le dossier. Les navigateurs qui n'offrent pas cette fenêtre aux pages web (Firefox, par exemple) laissent choisir le nom, et rangent le fichier dans leur dossier de téléchargements.

### Lire le diagramme des décisions

Le flux descend le long d'une colonne.

- **Pastille pleine**, tout en haut : l'entrée dans la fonction.
- **Hexagone bleu** : un test (`if`, `elseif`). Si la réponse est « oui », le flux part à droite ; sinon il continue vers le bas.
- **Hexagone doré** : une boucle (`while`, `for`, `repeat … until`). Le retour remonte par la gauche, la sortie de boucle passe par la droite.
- **Rectangle** : des instructions qui se suivent sans décision. Quatre lignes au plus sont citées, le reste est compté.
- **Pastille** : une sortie (`return`, `break`, `goto`), en rouge pour un appel à `error`.

Un clic sur une forme montre le code correspondant ; placer le curseur dans le code cercle d'or l'étape correspondante. `Ctrl` + molette pour zoomer, glisser pour se déplacer, **Ajuster** pour revenir à la largeur du volet.

Pour une longue fonction, **Niveaux** replie le diagramme. Au niveau 1, seules les étapes principales sont dessinées : le contenu de chaque test et de chaque boucle tient dans un cadre en pointillés, par exemple « + 10 étapes, 3 tests ». Les niveaux 2 et 3 ouvrent un et deux étages de plus, **Tous** dessine tout. Un clic sur un cadre en pointillés le déplie ; un double-clic sur un test ou une boucle replie, ou déplie, ce qui en dépend. Un contenu d'une seule étape reste toujours dessiné.

La **complexité** affichée vaut 1, plus 1 par `if` ou `elseif`, par boucle, et par `and` ou `or` écrit dans une condition : c'est le nombre de chemins à essayer pour tester la fonction. Les fonctions imbriquées sont comptées à part. « Ce que lisent les conditions » liste les noms dont dépendent les décisions de la fonction.

### Exporter les organigrammes en HTML

**Exporter › Organigrammes des décisions en HTML…** enregistre une seule page, `script.decisions.html`, qui se lit sans le Studio : on l'ouvre d'un double-clic dans n'importe quel navigateur récent, on l'envoie par courriel, on la dépose sur un partage. Elle contient tout ce qu'il lui faut (données, scripts, styles, polices), ne charge rien et n'envoie rien sur Internet. La même page s'obtient en ligne de commande :

```console
python -m lua_parser_pro mon_script.lua --html > mon_script.decisions.html
```

On y trouve, pour le script et chacune de ses fonctions :

- à gauche, la liste des fonctions, imbriquées comme dans le texte, avec leur complexité ; un filtre cherche dans les noms et les descriptions, et on peut les ranger des plus complexes aux plus simples ;
- l'**organigramme** des décisions, dessiné comme dans le Studio (niveaux, replis, zoom, glisser), ou le même contenu en **arbre** : une liste indentée « si … alors / sinon, si … / sinon », « pour … », « tant que … », plus facile à parcourir ou à chercher avec `Ctrl+F` ;
- le **code** de la fonction, coloré ; un clic sur une forme de l'organigramme ou une ligne de l'arbre y marque les lignes correspondantes ;
- les fonctions du script qu'elle **appelle** et celles qui l'**appellent**, en liens : un clic mène à leur organigramme, et le bouton Précédent du navigateur ramène à la fonction d'avant (chaque fonction a sa propre adresse, `page.html#fonction-12`) ;
- des **infobulles** partout : sur une fonction (dans la liste ou dans un lien), elles donnent sa **description**, ses paramètres, sa complexité, ce que lisent ses conditions et ce qu'elle appelle ; sur une forme de l'organigramme, elles citent le code de l'étape et décrivent les fonctions du script qui y sont appelées.

La description d'une fonction est le **commentaire écrit juste au-dessus d'elle**, sans ligne vide entre les deux. Les trois tirets de LDoc et d'EmmyLua (`---`) sont acceptés, de même que les balises `@param nom texte`, `@tparam type nom texte` et `@return texte` ; les filets (`-----`) et le code mis en commentaire sont ignorés. Le commentaire du début du fichier décrit le script lui-même. Sans commentaire, l'infobulle résume ce que l'analyse lit dans le code :

```lua
--- Vrai si la valeur figure dans la liste ; une liste absente compte pour vide.
-- @param liste les éléments à parcourir, ou nil
-- @param valeur l'élément cherché
local function contient(liste, valeur)
```

Les appels sont reconnus par leur nom, tel qu'il est écrit : `contient(...)`, `Module.f(...)`, `objet:Methode(...)` (ce dernier quand une seule méthode du script porte ce nom). Rien n'est exécuté ni résolu : un appel à travers une variable intermédiaire n'est pas relié. La page **contient le code du script** : ne la partagez que là où ce code peut l'être.

### Raccourcis

| Touche | Action |
| --- | --- |
| `Ctrl+O` | Ouvrir un fichier |
| `Ctrl+Maj+O` | Ouvrir un dossier |
| `F8` | Aller à l'erreur |
| `Ctrl+Entrée` | Analyser tout de suite |
| `Tab` / `Maj+Tab` | Indenter / quitter l'éditeur au clavier |

### Ce que le Studio ne fait pas

Il **ne modifie jamais vos fichiers** : l'éditeur est un brouillon. Le seul fichier créé est un export, enregistré par votre navigateur à l'endroit que vous indiquez. Il **n'exécute pas** le code Lua. Il n'écoute que sur cet ordinateur (`127.0.0.1`), refuse les requêtes venues d'un autre site, ne lit que les fichiers `.lua` des dossiers que vous avez ouverts, et n'envoie rien sur Internet : les polices et les scripts de la page sont dans le paquet.

Un très gros fichier (1 Mo, 35 000 lignes) est analysé en une à deux secondes ; l'arbre de ses niveaux profonds est alors chargé à la demande.

## Démarrage en ligne de commande

Depuis le dossier du projet, sans rien installer :

```console
python -m lua_parser_pro examples/demo.lua --check
python -m lua_parser_pro examples/demo.lua
python -m lua_parser_pro examples/demo.lua --outline
python -m lua_parser_pro mon/dossier --check
python examples/inspect_ast.py
python -m unittest discover -s test
```

Pour installer le paquet et disposer de la commande `lua-parser` :

```console
python -m pip install .
lua-parser examples/demo.lua --compact
lua-parser --gui
```

L'installation utilise `setuptools`. Les tests n'utilisent que `unittest`, fourni avec Python.

## Ligne de commande

```console
python -m lua_parser_pro programme.lua                  # arbre syntaxique en JSON
python -m lua_parser_pro programme.lua --compact > arbre.json
python -m lua_parser_pro programme.lua --tokens         # jetons et commentaires
python -m lua_parser_pro programme.lua --outline        # fonctions, tables, variables
python -m lua_parser_pro programme.lua --stats          # mesures
python -m lua_parser_pro programme.lua --check          # syntaxe seulement
python -m lua_parser_pro programme.lua --html > page.html  # organigrammes des décisions
python -m lua_parser_pro dossier --check                # tous les .lua d'un dossier
python -m lua_parser_pro ancien.lua --check --encoding auto
python -m lua_parser_pro - --check                      # entrée standard
python -m lua_parser_pro --gui [fichier ou dossier]     # le Studio
```

| Option | Effet |
| --- | --- |
| `--check` | Vérifie la syntaxe sans rien écrire si tout est valide. Avec un dossier : vérifie tous ses fichiers `.lua`, affiche chaque erreur puis un bilan. |
| `--tokens` | Écrit un objet JSON contenant `tokens` et `comments`. |
| `--outline` | Écrit la liste des déclarations (voir `outline` plus bas). |
| `--stats` | Écrit les mesures du script (voir `statistics`). |
| `--html` | Écrit une page HTML autonome : les organigrammes des décisions de toutes les fonctions, leur code et leurs descriptions (voir « Exporter les organigrammes en HTML »). La page ne contient que des caractères ASCII : une redirection `>` ne peut pas l'abîmer, quel que soit l'encodage de la console. |
| `--gui`, `--studio` | Ouvre le Studio. `--port` choisit le port, `--no-browser` n'ouvre pas le navigateur. |
| `--compact` | JSON sur une seule ligne. |
| `--no-comments` | Ne collecte pas les commentaires. |
| `--encoding NOM` | Encodage du fichier : `utf-8` par défaut, `latin-1`, `cp1252`… ou `auto` (UTF-8, sinon Latin-1). Un dossier est lu en `auto`. |
| `--jobs N` | Nombre de processus pour vérifier un dossier (par défaut un par cœur, 16 au plus). |
| `--max-depth`, `--max-tokens`, `--max-source-length` | Limites de l'analyse (150 niveaux, 1 000 000 jetons, 10 000 000 caractères). |

Ces modes sont exclusifs. Les diagnostics vont sur la sortie d'erreur.

| Code de sortie | Signification |
| --- | --- |
| `0` | Analyse réussie |
| `1` | Erreur lexicale, syntaxique ou limite d'analyse dépassée |
| `2` | Mauvais arguments, fichier inaccessible ou illisible dans l'encodage demandé |

## API Python

```python
from lua_parser_pro import LuaSyntaxError, parse, walk
from lua_parser_pro.ast import NumberLiteral

source = 'local valeur <const> = 0x1.fp+3; return valeur'
try:
    tree = parse(source, filename="exemple.lua")
    for node in walk(tree):
        if isinstance(node, NumberLiteral):
            print(node.raw, node.span.start.line)
    data = tree.to_dict()  # Valeurs compatibles avec json.dumps.
except LuaSyntaxError as error:
    print(error)            # Fichier, ligne, colonne, extrait et curseur.
    print(error.to_dict())  # Diagnostic exploitable par un outil.
```

Signature principale :

```python
parse(
    source: str,
    *,
    filename="<input>",
    comments=True,
    max_depth=150,
    max_tokens=1_000_000,
    max_source_length=10_000_000,
    encoding="utf-8",
) -> Chunk
```

`walk(tree)` parcourt les nœuds en profondeur, parent avant enfants, sans récursion. Les classes de nœuds se trouvent dans `lua_parser_pro.ast`. `encoding` est l'encodage dans lequel les caractères des chaînes sont remis en octets : passez celui qui a servi à lire le fichier.

Pour utiliser uniquement l'analyse lexicale :

```python
from lua_parser_pro import Lexer, tokenize

tokens = tokenize('return "\\255", 0x1.fp+3')
lexer = Lexer('-- note\nreturn 42', filename="exemple.lua")
tokens = lexer.tokenize()
comments = lexer.comments
```

`tokenize` et `Lexer` acceptent `filename`, `comments`, `max_tokens`, `max_source_length` et `encoding`. La liste de jetons est un tuple terminé par un jeton de fin ; les commentaires sont collectés séparément. `tokenize` renvoie uniquement les jetons : employer `Lexer` pour récupérer aussi les commentaires.

### Analyses

```python
from lua_parser_pro import outline, parse, statistics
from lua_parser_pro.analysis import condition_terms, decision_flow, function_metrics

tree = parse(source)
for symbol in outline(tree):                 # fonctions, tables, variables du niveau principal
    print(symbol.kind, symbol.name, symbol.span.start.line, symbol.parameters)

statistics(tree, tokens)                     # lignes, jetons, nœuds, fonctions, appels, chaînes
function_metrics(fonction)                   # {"complexity", "decisions", "loops", "nesting", "exits", "statements"}
condition_terms(fonction)                    # [("cible.Vie", 3), ...] : ce que lisent les conditions
decision_flow(fonction, source)              # la structure de contrôle, en données JSON
```

`outline` donne à chaque déclaration un genre : `function`, `method`, `callback` (fonction anonyme passée à un appel, nommée d'après la fonction appelée), `table` ou `variable`. `function_metrics`, `condition_terms` et `decision_flow` reçoivent un nœud `FunctionExpression` ou le `Chunk` entier ; les fonctions imbriquées n'y sont pas comptées. `decision_flow` renvoie une `sequence` d'étapes : `action`, `if` (avec `branches` et `otherwise`), `while`, `repeat`, `for`, `return`, `break`, `goto`, `label`, `error`. Tous ces parcours sont itératifs et rien n'est exécuté ni résolu : ce sont des lectures du texte.

La page HTML des organigrammes se construit aussi depuis Python :

```python
from pathlib import Path
from lua_parser_pro.studio.report import build_report

page = build_report(source, "combat.lua")   # lève LuaSyntaxError si le texte n'est pas du Lua valide
Path("combat.decisions.html").write_text(page, encoding="ascii")
```

### Fichiers et dossiers

```python
from lua_parser_pro import check_file, check_files, find_lua_files, read_source

text, encoding = read_source("ancien.lua", "auto")     # UTF-8, sinon Latin-1
report = check_file("script.lua")                      # FileReport : ok, error, lines, tokens…
reports = check_files(find_lua_files("mon/dossier"))   # en parallèle quand cela vaut la peine
```

`check_file` ne lève pas d'exception : `report.error` vaut `None` ou le diagnostic sous forme de dictionnaire.

## Syntaxe prise en charge

- Déclarations locales, attributs `<const>` et `<close>`, affectations multiples.
- Fonctions locales et globales, méthodes, fonctions anonymes, arguments variables et appels abrégés.
- `if` / `elseif` / `else`, `do`, `while`, `repeat`, boucles `for` numériques et génériques, `break` et `return`.
- Étiquettes `::nom::` et instructions `goto`.
- Tables, accès aux champs et index, chaînes courtes ou longues, commentaires courts ou longs.
- Nombres décimaux et hexadécimaux, exposants, opérateurs logiques, arithmétiques et binaires de Lua 5.4.
- Priorités et associativités de Lua, notamment puissance, concaténation et opérateurs unaires.
- BOM UTF-8 accepté ; une première ligne commençant par `#` est ignorée, comme le fait Lua en chargeant un fichier, et conservée parmi les commentaires.

La cible est **Lua 5.4**, pas Luau ni les extensions spécifiques de LuaJIT. La référence de grammaire est le [manuel officiel de Lua 5.4](https://www.lua.org/manual/5.4/manual.html#9).

## AST et fidélité des données

Les nœuds sont des dataclasses immuables ; leurs collections sont des tuples. Chaque nœud porte `span`, chaque jeton porte `kind`, `value`, `raw` et `span`. `Position`, `Span` et `Token` sont des tuples nommés. Un `Chunk` contient les instructions dans `body` et les commentaires dans `comments`. Les parenthèses d'une expression sont représentées explicitement.

- `span.start.offset` et `span.end.offset` utilisent les **points de code Python**, à partir de zéro, avec une fin exclue. `source[start.offset:end.offset]` retrouve la portion de texte correspondante. Ces positions ne sont ni des offsets UTF-8 en octets, ni des positions UTF-16.
- Lignes et colonnes commencent à **1**. Les tabulations comptent pour un point de code. `CRLF` et `LFCR` comptent chacun pour un seul retour à la ligne, conformément à Lua ; `CR` et `LF` isolés sont aussi acceptés.
- Les nombres conservent leur texte dans `NumberLiteral.raw`. Aucune conversion flottante ne leur fait perdre de précision.
- Les chaînes Lua sont des **octets** : `StringLiteral.value` est un `bytes`, y compris pour les échappements comme `\255` et les octets nuls. Les caractères littéraux sont encodés dans l'encodage indiqué à `parse` (UTF-8 par défaut). `raw` conserve la forme originale, délimiteurs compris.
- `to_dict()` convertit les chaînes Lua en tableaux d'entiers de `0` à `255` pour un JSON sans perte. Par exemple, la valeur de `"A\255"` devient `[65, 255]`.
- Les commentaires sont conservés dans l'ordre de source, séparément des instructions ; aucune association implicite à un nœud voisin. `comments=False` supprime leur collecte.

L'AST décrit la syntaxe. Ce n'est pas un arbre conservant tous les espaces et il ne fournit pas de fonction de réécriture ou de formatage du code.

## Limites explicites

L'analyse s'arrête à la **première erreur**, sans récupération. Les erreurs exposent un code, un message, le fichier et une position. Les limites par défaut sont de 150 niveaux de profondeur, 1 000 000 jetons et 10 000 000 points de code de source. Les commentaires comptent dans le budget de jetons même si leur collecte est désactivée ; le jeton de fin n'y compte pas. La profondeur protège à la fois l'analyse et l'arbre produit : une chaîne de plus de 150 opérateurs ou accès consécutifs (`a.b.c…`, `x + x + x…`) est refusée tant que `max_depth` n'est pas relevé, alors que Lua l'accepte. La CLI borne la lecture de la source avant l'analyse.

Ces budgets sont configurables pour adapter la charge de travail ; ils ne remplacent pas une limite de mémoire ou de temps imposée au processus lors d'un service d'analyse exposé au public.

Les identifiants sont limités à `[A-Za-z_][A-Za-z0-9_]*`, indépendamment de la locale. L'API reçoit un `str` Python ; la CLI attend de l'UTF-8 sauf option `--encoding`.

Il s'agit d'un **parseur, pas d'un compilateur ou d'une machine virtuelle**. Il ne résout pas les variables et ne vérifie pas les portées de `goto`, les écritures dans une variable `<const>`, les contraintes d'exécution de `<close>` ou toutes les limites internes de compilation de Lua. Un AST valide ne garantit donc pas qu'un programme sera accepté par le compilateur Lua ou réussira à l'exécution. Le diagramme des décisions décrit le texte : il ne sait pas quelles branches seront réellement prises.

## Vérifications

La suite livrée compte 175 tests (`python -m unittest discover -s test`) : lexique, syntaxe, ligne de commande, analyses, lecture de dossiers, serveur du Studio et ce qu'il refuse, export HTML des décisions.

Pendant le développement, le parseur a aussi été comparé au vrai Lua 5.4 (par le module `lupa`, qui n'est pas nécessaire à l'usage) :

- 60 000 programmes obtenus en mutilant des jetons : même verdict accepté ou refusé, hors les contrôles que le parseur ne fait pas (portée des `goto`, écriture dans une variable `<const>`) ;
- 39 000 chaînes littérales : octets identiques ;
- 30 000 expressions aléatoires : même priorité des opérateurs, vérifiée sur le code compilé par Lua ;
- les 33 fichiers de la suite de tests officielle de Lua 5.4 : tous acceptés.

L'interface a été essayée dans Chromium sans écran : toutes les vues, la saisie, les grands fichiers, et 5 700 modifications aléatoires pour la coloration.

## Organisation

```text
lua_parser_pro/
  model.py       Positions, jetons et diagnostics
  lexer.py       Analyse lexicale
  ast.py         Nœuds typés, sérialisation et parcours
  parser.py      Analyse syntaxique
  analysis.py    Plan, mesures, complexité, mécanique des décisions
  batch.py       Lecture des fichiers, vérification d'un dossier
  cli.py         Interface en ligne de commande
  studio/        Le Studio : serveur local, messages en français, page et scripts,
                 export HTML des organigrammes (report.py, static/rapport.*)
examples/        Exemples Lua et Python
test/            Tests de régression
LANCER_STUDIO.bat   Lance le Studio sous Windows
```

## Nouveautés de la version 1.1

**Corrections**

- L'export JSON d'un arbre profond (avec `--max-depth` relevé) plantait sur une `RecursionError` ; l'écriture du JSON et `to_dict` sont maintenant itératifs.
- Une première ligne commençant par `#` n'était acceptée que sous la forme `#!` ; Lua ignore toute première ligne en `#`.
- Un fichier qui n'était pas en UTF-8 ne pouvait pas être lu : option `--encoding`, avec `auto` pour les anciens fichiers.
- Fermer le lecteur d'un tube (`lua-parser f.lua | head`) n'affiche plus d'erreur.

**Vitesse**

- Analyse lexicale et syntaxique environ 2,3 fois plus rapides, `to_dict` environ 3,5 fois, à résultat identique : jetons, arbres et diagnostics ont été comparés à ceux de la version 1.0 sur plus de 700 000 textes.

**Ajouts**

- Le Studio, avec le diagramme des décisions.
- `--outline`, `--stats`, vérification d'un dossier entier, `--encoding`, `--jobs`.
- Modules `analysis` et `batch`.

**À savoir si vous utilisiez la version 1.0**

- `Position`, `Span` et `Token` sont devenus des tuples nommés. Leurs champs et leur construction ne changent pas ; `dataclasses.replace`, `fields` ou `asdict` ne s'y appliquent plus (utiliser `_replace` et `_asdict`).
- `--check` accepte un dossier ; une première ligne en `#` est désormais valide.
