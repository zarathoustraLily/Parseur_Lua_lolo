// Le dessin d'un organigramme des décisions, en SVG : les tests descendent le
// long d'une colonne, leurs issues partent à droite, les boucles reviennent par
// la gauche. Le Studio s'en sert (decisions.js) et l'export HTML l'embarque
// dans sa page (report.py, rapport.js) : ce module n'importe donc rien.

// Ces polices doivent rester celles de la feuille de style (.flux text, .etiquette).
const FAMILLE_CODE = '"Atkinson Hyperlegible Mono", "Cascadia Mono", Consolas, monospace';
const CODE = `12px ${FAMILLE_CODE}`;
const CODE_GRAS = `600 12px ${FAMILLE_CODE}`;
const TEXTE = '11.5px "Atkinson Hyperlegible Next", "Segoe UI", system-ui, sans-serif';
const G = { LH: 17, PX: 11, PY: 7, GAP: 26, COL: 34, MARGE: 28 };

const ECHAPPE = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
const echapper = (texte) => String(texte).replace(/[&<>"]/g, (c) => ECHAPPE[c]);
const NOMBRE = new Intl.NumberFormat("fr-FR");
const pluriel = (n, un, plusieurs) => `${NOMBRE.format(n)} ${n > 1 ? plusieurs : un}`;

const contextes = new Map();

/** Largeur en pixels de `texte` dans la police CSS `police`. */
function largeurTexte(texte, police) {
  let contexte = contextes.get(police);
  if (!contexte) {
    contexte = document.createElement("canvas").getContext("2d");
    contexte.font = police;
    contextes.set(police, contexte);
  }
  return contexte.measureText(texte).width;
}

// Corps repliés du dessin en cours : les niveaux au-delà de `niveauMax` le sont,
// et `bascules` liste les corps dont l'état est l'inverse de celui que donne le niveau.
let reglages = { niveauMax: Infinity, bascules: new Set() };

// ------------------------------------------------------------------ fonctions
/** Nom affiché d'une fonction de l'analyse : `nom(paramètres)`. */
export function nomFonction(f) {
  if (f.genre === "script") return "script";
  const parametres = `(${(f.params || []).join(", ")})`;
  if (!f.nom) return `function${parametres}`;
  if (f.nom.endsWith("(…)")) return `${f.nom.slice(0, -3)}(function${parametres})`;
  return f.nom + parametres;
}

/** Appréciation d'une complexité : 1 plus le nombre de tests, de boucles, de « and » et de « or ». */
export function niveauComplexite(c) {
  return c <= 5 ? "faible" : c <= 10 ? "modérée" : c <= 20 ? "élevée" : "très élevée";
}

// ---------------------------------------------------------------- géométrie
const pair = (valeur) => 2 * Math.ceil(valeur / 2);
const largeurCode = (texte) => largeurTexte(texte, CODE);
const largeurNote = (texte) => largeurTexte(texte, TEXTE);
const couperFin = (texte, max) => (texte.length > max ? texte.slice(0, max - 1).trimEnd() + "…" : texte);

/**
 * Une condition longue est répartie sur quatre lignes au plus. La coupe se fait
 * avant « and » et « or » ; une clause reste entière tant qu'elle tient sur une
 * ligne large, sinon elle est coupée entre deux mots.
 */
function couper(texte, max = 44, lignesMax = 4) {
  const large = max + 18;
  if (texte.length <= max + 6) return [texte];
  const lignes = [];
  let ligne = "";
  const terminer = () => {
    if (ligne) lignes.push(ligne);
    ligne = "";
  };
  for (const clause of texte.split(/\s+(?=(?:and|or)\s)/)) {
    if (clause.length <= large) {
      if (ligne && ligne.length + 1 + clause.length > max) terminer();
      ligne = ligne ? `${ligne} ${clause}` : clause;
      continue;
    }
    terminer();
    const mots = clause.split(" ");
    if (mots.length > 1 && (mots[0] === "and" || mots[0] === "or")) {
      mots.splice(0, 2, `${mots[0]} ${mots[1]}`);       // l'opérateur ne reste jamais seul sur sa ligne
    }
    for (const mot of mots) {
      if (ligne && ligne.length + 1 + mot.length > large) terminer();
      ligne = ligne ? `${ligne} ${mot}` : mot;
    }
    terminer();
  }
  terminer();
  const gardees = lignes.slice(0, lignesMax).map((l) => couperFin(l, large + 2));
  if (lignes.length > lignesMax && !gardees[lignesMax - 1].endsWith("…")) gardees[lignesMax - 1] += " …";
  return gardees;
}

/** Tracé à angles droits arrondis passant par `points`. */
function chemin(points, rayon = 7) {
  let d = `M${points[0][0]} ${points[0][1]}`;
  for (let i = 1; i < points.length; i++) {
    const [x, y] = points[i];
    if (i === points.length - 1) {
      d += `L${x} ${y}`;
      break;
    }
    const [px, py] = points[i - 1];
    const [nx, ny] = points[i + 1];
    const r = Math.min(rayon, (Math.abs(x - px) + Math.abs(y - py)) / 2, (Math.abs(nx - x) + Math.abs(ny - y)) / 2);
    d += `L${x - Math.sign(x - px) * r} ${y - Math.sign(y - py) * r}`
      + `Q${x} ${y} ${x + Math.sign(nx - x) * r} ${y + Math.sign(ny - y) * r}`;
  }
  return d;
}

function lien(s, points, pointe) {
  const nets = points.filter((p, i) => i === 0 || p[0] !== points[i - 1][0] || p[1] !== points[i - 1][1]);
  if (nets.length < 2) return;
  let tete = "";
  if (pointe) {
    const [x, y] = nets[nets.length - 1];
    const [px, py] = nets[nets.length - 2];
    const dx = Math.sign(x - px);
    const dy = Math.sign(y - py);
    tete = `<path class="pointe" d="M${x} ${y}L${x - dx * 7 - dy * 3.5} ${y - dy * 7 + dx * 3.5}`
      + `L${x - dx * 7 + dy * 3.5} ${y - dy * 7 - dx * 3.5}Z"/>`;
    if (Math.abs(x - px) + Math.abs(y - py) > 7) nets[nets.length - 1] = [x - dx * 5, y - dy * 5];
  }
  s.liens.push(`<path class="lien" d="${chemin(nets)}"/>${tete}`);
}

function note(s, x, y, texte, ancre) {
  s.notes.push(`<text class="etiquette" x="${x}" y="${y}" text-anchor="${ancre}">${texte}</text>`);
}

function groupe(donnee, contenu, titre, plis = "") {
  if (!donnee) return `<g class="repere">${contenu}</g>`;
  const aide = plis ? "\nDouble-clic : replier ou déplier ce qui en dépend" : "";
  return `<g class="etape" tabindex="-1" data-a="${donnee.a}" data-b="${donnee.b}"`
    + `${plis ? ` data-plis="${plis}"` : ""}><title>${echapper(titre + aide)}</title>${contenu}</g>`;
}

function lignesTexte(lignes, x, y, ancre, classe = "") {
  let html = "";
  lignes.forEach((ligne, i) => {
    html += `<text x="${x}" y="${y + G.LH * (i + 0.5)}" text-anchor="${ancre}"`
      + `${classe ? ` class="${classe}"` : ""}>${echapper(ligne)}</text>`;
  });
  return html;
}

// ------------------------------------------------------------------- formes
// Chaque bloc connaît son étendue à gauche (g) et à droite (d) de la colonne
// où entre le flux, sa hauteur (h), et s'il laisse le flux continuer (sort).
// `entree` existe quand le flux peut entrer par la gauche de sa première forme :
// demi-largeur de cette forme (g) et hauteur de son centre (cy). `tete` est la
// hauteur où la colonne rencontre la première forme quand le flux entre par le haut.

function blocAction(etape) {
  const lignes = etape.lines.map((ligne) => couperFin(ligne, 52));
  const reste = etape.count - lignes.length;
  const suite = reste > 0 ? `et ${pluriel(reste, "autre instruction", "autres instructions")}` : "";
  let largeur = suite ? largeurNote(suite) : 0;
  for (const ligne of lignes) largeur = Math.max(largeur, largeurCode(ligne));
  const w = pair(Math.max(48, largeur) + 2 * G.PX);
  const h = (lignes.length + (suite ? 1 : 0)) * G.LH + 2 * G.PY;
  const titre = `${etape.lines.join("\n")}${suite ? "\n" + suite : ""}\nligne ${etape.ligne}`;
  return {
    g: w / 2, d: w / 2, h, sort: true, tete: 0, entree: { g: w / 2, cy: h / 2 },
    dessin(x, y, s) {
      let contenu = `<rect class="forme f-action" x="${x - w / 2}" y="${y}" width="${w}" height="${h}" rx="6"/>`
        + lignesTexte(lignes, x - w / 2 + G.PX, y + G.PY, "start");
      if (suite) {
        contenu += `<text class="etiquette" x="${x - w / 2 + G.PX}" `
          + `y="${y + G.PY + G.LH * (lignes.length + 0.5)}" text-anchor="start">${suite}</text>`;
      }
      s.formes.push(groupe(etape, contenu, titre));
    },
  };
}

function pilule(texte, classe, donnee, titre, { gras = false, classeTexte = "", sort = false } = {}) {
  const court = couperFin(texte, 48);
  const w = pair(largeurTexte(court, gras ? CODE_GRAS : CODE) + 30);
  const h = 26;
  return {
    g: w / 2, d: w / 2, h, sort, tete: 0, entree: { g: w / 2, cy: h / 2 },
    dessin(x, y, s) {
      s.formes.push(groupe(donnee,
        `<rect class="forme ${classe}" x="${x - w / 2}" y="${y}" width="${w}" height="${h}" rx="13"/>`
        + `<text x="${x}" y="${y + h / 2}" text-anchor="middle"${classeTexte ? ` class="${classeTexte}"` : ""}>`
        + `${echapper(court)}</text>`, titre));
    },
  };
}

function hexagone(lignes, classe, donnee, titre, plis = "") {
  let largeur = 40;
  for (const ligne of lignes) largeur = Math.max(largeur, largeurCode(ligne));
  const w = pair(largeur + 2 * (G.PX + 9));
  const h = lignes.length * G.LH + 2 * G.PY;
  const biseau = 11;
  return {
    g: w / 2, d: w / 2, h, sort: true,
    dessin(x, y, s) {
      const gauche = x - w / 2;
      const droite = x + w / 2;
      const points = `${gauche},${y + h / 2} ${gauche + biseau},${y} ${droite - biseau},${y} `
        + `${droite},${y + h / 2} ${droite - biseau},${y + h} ${gauche + biseau},${y + h}`;
      s.formes.push(groupe(donnee,
        `<polygon class="forme ${classe}" points="${points}"/>`
        + lignesTexte(lignes, x, y + (h - lignes.length * G.LH) / 2, "middle"), titre, plis));
    },
  };
}

// ------------------------------------------------------------------- replis
const comptes = new WeakMap();

/** Nombre d'étapes et de tests d'un corps, tous niveaux confondus. */
function compter(sequence) {
  let compte = comptes.get(sequence);
  if (compte) return compte;
  compte = { etapes: 0, tests: 0 };
  for (const etape of sequence.steps) {
    compte.etapes++;
    const corps = [];
    if (etape.kind === "if") {
      compte.tests += etape.branches.length;
      for (const branche of etape.branches) corps.push(branche.body);
      if (etape.otherwise) corps.push(etape.otherwise);
    } else if (etape.body) {
      corps.push(etape.body);
    }
    for (const interieur of corps) {
      const dedans = compter(interieur);
      compte.etapes += dedans.etapes;
      compte.tests += dedans.tests;
    }
  }
  comptes.set(sequence, compte);
  return compte;
}

/** Vrai si le flux ressort par le bas du corps (sa dernière étape n'est pas une sortie). */
function coule(sequence) {
  const derniere = sequence.steps[sequence.steps.length - 1];
  if (!derniere) return true;
  switch (derniere.kind) {
    case "return":
    case "break":
    case "goto":
    case "error":
      return false;
    case "if":
      return !derniere.otherwise || coule(derniere.otherwise) || derniere.branches.some((b) => coule(b.body));
    default:
      return true;
  }
}

/** Vrai si le corps `cle`, au niveau d'imbrication `niveau`, est replié selon `choix`. */
export const estReplie = (niveau, cle, choix = reglages) => (niveau > choix.niveauMax) !== choix.bascules.has(cle);

/** Niveau d'imbrication du corps nommé par une clé de pli (« /0:b1/2:c » est au niveau 2). */
export const niveauDuPli = (cle) => cle.split(":").length - 1;

/** Un corps d'une seule étape reste toujours dessiné : le replier ne gagnerait pas de place. */
const repliable = (sequence) => compter(sequence).etapes > 1;

/** Un corps replié : une seule forme en pointillés, qui se déplie d'un clic. */
function blocPli(sequence, cle) {
  const { etapes: total, tests } = compter(sequence);
  const texte = `+ ${pluriel(total, "étape", "étapes")}${tests ? `, ${pluriel(tests, "test", "tests")}` : ""}`;
  const w = pair(largeurNote(texte) + 26);
  const h = 26;
  const bornes = sequence.steps.filter((etape) => etape.a !== undefined);
  const etendue = bornes.length
    ? ` data-a="${bornes[0].a}" data-b="${bornes[bornes.length - 1].b}"` : "";
  return {
    g: w / 2, d: w / 2, h, sort: coule(sequence), tete: 0, entree: { g: w / 2, cy: h / 2 },
    dessin(x, y, s) {
      s.formes.push(`<g class="pli" tabindex="-1" data-pli="${cle}"${etendue}>`
        + `<title>Cliquez pour déplier ces étapes</title>`
        + `<rect class="forme f-pli" x="${x - w / 2}" y="${y}" width="${w}" height="${h}" rx="6"/>`
        + `<text class="etiquette" x="${x}" y="${y + h / 2}" text-anchor="middle">${texte}</text></g>`);
    },
  };
}

/** Le corps d'un test ou d'une boucle : replié ou dessiné, selon le niveau demandé. */
function blocCorps(sequence, niveau, cle) {
  if (repliable(sequence) && estReplie(niveau, cle)) return blocPli(sequence, cle);
  return blocSequence(sequence, niveau, cle);
}

function blocSequence(sequence, niveau, cle) {
  const blocs = sequence.steps.map((etape, i) => blocEtape(etape, niveau, `${cle}/${i}`));
  if (!blocs.length) return { g: 0, d: 0, h: 0, sort: true, vide: true, tete: 0, dessin() {} };
  let g = 0;
  let d = 0;
  let h = G.GAP * (blocs.length - 1);
  for (const bloc of blocs) {
    g = Math.max(g, bloc.g);
    d = Math.max(d, bloc.d);
    h += bloc.h;
  }
  return {
    g, d, h, sort: blocs[blocs.length - 1].sort, tete: blocs[0].tete, entree: blocs[0].entree,
    dessin(x, y, s) {
      blocs.forEach((bloc, i) => {
        bloc.dessin(x, y, s);
        y += bloc.h;
        if (i < blocs.length - 1) {
          if (bloc.sort) lien(s, [[x, y], [x, y + G.GAP + blocs[i + 1].tete]], true);
          y += G.GAP;
        }
      });
    },
  };
}

function blocSi(etape, niveau, cle) {
  const n = etape.branches.length;
  const dernier = n - 1;
  const cles = etape.branches.map((_, k) => `${cle}:b${k}`);
  const cleSinon = `${cle}:s`;
  // Chaque test porte les clés des corps qu'un double-clic replie : le sien, et le « sinon » pour le dernier.
  const plis = (k) => [
    repliable(etape.branches[k].body) ? cles[k] : "",
    k === dernier && etape.otherwise && repliable(etape.otherwise) ? cleSinon : "",
  ].filter(Boolean).join(" ");
  const tests = etape.branches.map((b, k) => hexagone(couper(b.condition), "f-test", b,
    `${b.condition}\nligne ${b.ligne}`, plis(k)));
  const corps = etape.branches.map((b, k) => blocCorps(b.body, niveau + 1, cles[k]));
  const sinon = etape.otherwise ? blocCorps(etape.otherwise, niveau + 1, cleSinon) : null;
  let demi = 0;
  let gCorps = 12;
  let dCorps = 0;
  for (let k = 0; k < n; k++) {
    demi = Math.max(demi, tests[k].g);
    gCorps = Math.max(gCorps, corps[k].g);
    dCorps = Math.max(dCorps, corps[k].d);
  }
  // Les issues « oui » partagent une colonne à droite ; celles qui ne sont pas
  // les dernières rejoignent la colonne principale par un couloir encore plus à droite.
  const xB = pair(Math.max(demi, sinon ? sinon.d : 0) + G.COL + gCorps);
  const xCouloir = xB + pair(dCorps) + 18;
  const yTest = [];
  const yCorps = [];
  const centres = [];
  const bas = [];
  let y = 0;
  for (let k = 0; k < n; k++) {
    const test = tests[k];
    const entree = corps[k].entree;
    if (entree) {
      // L'issue commence sur la ligne du test : le flux y entre par la gauche.
      const centre = y + Math.max(test.h / 2, entree.cy);
      centres.push(centre);
      yTest.push(centre - test.h / 2);
      yCorps.push(centre - entree.cy);
    } else {
      // L'issue commence par une boucle (ou est vide) : le flux y descend par le haut.
      centres.push(y + test.h / 2);
      yTest.push(y);
      yCorps.push(y + test.h / 2 + 22);
    }
    bas.push(yCorps[k] + corps[k].h);
    if (k < dernier) y = Math.max(yTest[k] + test.h + G.GAP, bas[k] + (corps[k].sort ? 24 : 12));
  }
  const yFinTests = yTest[dernier] + tests[dernier].h;
  const ySinon = yFinTests + G.GAP;
  const basColonne = sinon ? ySinon + sinon.h : yFinTests + 16;
  const colonneCoule = !sinon || sinon.sort;
  const fusion = corps.some((c) => c.sort);
  const couloir = corps.slice(0, dernier).some((c) => c.sort);
  const yFusion = Math.max(basColonne + (sinon ? 12 : 6), bas[dernier] + 10);
  const h = fusion ? yFusion : Math.max(basColonne, bas[dernier] + 6);
  return {
    g: Math.max(demi, sinon ? sinon.g : 0),
    d: couloir ? xCouloir + 4 : xB + dCorps,
    h,
    sort: colonneCoule || fusion,
    tete: yTest[0],
    entree: { g: tests[0].g, cy: centres[0] },
    dessin(x, y0, s) {
      for (let k = 0; k < n; k++) {
        const test = tests[k];
        const haut = y0 + yTest[k];
        const centre = y0 + centres[k];
        test.dessin(x, haut, s);
        if (corps[k].entree) {
          lien(s, [[x + test.d, centre], [x + xB - corps[k].entree.g, centre]], true);
        } else {
          lien(s, [[x + test.d, centre], [x + xB, centre], [x + xB, y0 + yCorps[k] + corps[k].tete]],
            !corps[k].vide);
        }
        note(s, x + test.d + 7, centre - 9, "oui", "start");
        corps[k].dessin(x + xB, y0 + yCorps[k], s);
        note(s, x + 7, haut + test.h + 10, "non", "start");
        if (k < dernier) lien(s, [[x, haut + test.h], [x, y0 + yTest[k + 1]]], true);
      }
      const finTests = y0 + yFinTests;
      if (sinon) {
        lien(s, [[x, finTests], [x, y0 + ySinon + sinon.tete]], !sinon.vide);
        sinon.dessin(x, y0 + ySinon, s);
        if (sinon.sort) lien(s, [[x, y0 + ySinon + sinon.h], [x, y0 + h]], false);
      } else {
        lien(s, [[x, finTests], [x, y0 + h]], false);
      }
      if (!fusion) return;
      const niveauFusion = y0 + yFusion;
      let principal = null;
      for (let k = 0; k < n; k++) {
        if (!corps[k].sort) continue;
        const xb = x + xB;
        const yb = y0 + bas[k];
        if (k < dernier) {
          const points = [[xb, yb], [xb, yb + 10], [x + xCouloir, yb + 10]];
          if (principal) lien(s, points, false);
          else principal = [...points, [x + xCouloir, niveauFusion]];
        } else if (principal) {
          lien(s, [[xb, yb], [xb, niveauFusion]], false);
        } else {
          principal = [[xb, yb], [xb, niveauFusion]];
        }
      }
      principal.push([x, niveauFusion]);
      lien(s, principal, colonneCoule);
    },
  };
}

function blocBoucle(etape, niveau, cle) {
  const pour = etape.kind === "for";
  const mot = pour ? "for" : "while";
  const cleCorps = `${cle}:c`;
  const tete = hexagone(couper(`${mot} ${etape.condition}`), "f-boucle", etape,
    `${mot} ${etape.condition}\nligne ${etape.ligne}`, repliable(etape.body) ? cleCorps : "");
  const corps = blocCorps(etape.body, niveau + 1, cleCorps);
  const tour = pour ? "à chaque tour" : "oui";
  const sortie = pour ? "terminé" : "non";
  const retour = pair(Math.max(corps.g, tete.g) + 20);       // le retour monte à gauche
  const issue = pair(Math.max(corps.d + 20, tete.d + largeurNote(sortie) + 16, largeurNote(tour) + 20));
  const yCorps = tete.h + G.GAP;
  const yBas = yCorps + corps.h;
  const h = yBas + (corps.sort ? 26 : 16);
  return {
    g: retour + 2, d: issue + 2, h, sort: true, tete: 0,
    dessin(x, y, s) {
      const centre = y + tete.h / 2;
      tete.dessin(x, y, s);
      lien(s, [[x, y + tete.h], [x, y + yCorps + corps.tete]], !corps.vide);
      note(s, x + 7, y + tete.h + 10, tour, "start");
      corps.dessin(x, y + yCorps, s);
      if (corps.sort) {
        lien(s, [[x, y + yBas], [x, y + yBas + 12], [x - retour, y + yBas + 12],
          [x - retour, centre], [x - tete.g, centre]], true);
      }
      lien(s, [[x + tete.d, centre], [x + issue, centre], [x + issue, y + h], [x, y + h]], false);
      note(s, x + tete.d + 7, centre - 9, sortie, "start");
    },
  };
}

function blocRepeter(etape, niveau, cle) {
  const cleCorps = `${cle}:c`;
  const tete = pilule("repeat", "f-boucle", etape, `repeat\nligne ${etape.ligne}`, { sort: true });
  const test = hexagone(couper(`until ${etape.condition}`), "f-boucle", etape,
    `until ${etape.condition}`, repliable(etape.body) ? cleCorps : "");
  const corps = blocCorps(etape.body, niveau + 1, cleCorps);
  const retour = pair(Math.max(corps.g, test.g + largeurNote("non") + 14, tete.g + 14) + 6);
  const yCorps = tete.h + G.GAP;
  const yTest = corps.vide ? yCorps : yCorps + corps.h + G.GAP;
  const h = yTest + test.h + 18;
  return {
    g: retour + 2, d: Math.max(corps.d, test.d, tete.d), h, sort: true, tete: 0,
    dessin(x, y, s) {
      tete.dessin(x, y, s);
      if (corps.vide) {
        lien(s, [[x, y + tete.h], [x, y + yTest]], true);
      } else {
        lien(s, [[x, y + tete.h], [x, y + yCorps + corps.tete]], true);
        corps.dessin(x, y + yCorps, s);
        if (corps.sort) lien(s, [[x, y + yCorps + corps.h], [x, y + yTest]], true);
      }
      test.dessin(x, y + yTest, s);
      const centre = y + yTest + test.h / 2;
      lien(s, [[x - test.g, centre], [x - retour, centre], [x - retour, y + tete.h / 2],
        [x - tete.g, y + tete.h / 2]], true);
      note(s, x - test.g - 7, centre - 9, "non", "end");
      lien(s, [[x, y + yTest + test.h], [x, y + h]], false);
      note(s, x + 7, y + yTest + test.h + 9, "oui", "start");
    },
  };
}

function blocEtape(etape, niveau, cle) {
  const titre = `${etape.text || ""}\nligne ${etape.ligne}`;
  switch (etape.kind) {
    case "action": return blocAction(etape);
    case "if": return blocSi(etape, niveau, cle);
    case "while":
    case "for": return blocBoucle(etape, niveau, cle);
    case "repeat": return blocRepeter(etape, niveau, cle);
    case "return":
    case "break":
    case "goto": return pilule(etape.text, "f-sortie", etape, titre);
    case "error": return pilule(etape.text, "f-erreur", etape, titre);
    case "label": return pilule(etape.text, "f-action", etape, titre, { sort: true });
    default:
      return pilule(pluriel(etape.count || 0, "instruction non affichée", "instructions non affichées"),
        "f-sortie", null, "", { classeTexte: "t-discret", sort: true });
  }
}

/**
 * L'organigramme de `flux` (la mécanique d'une fonction, telle que l'analyse la
 * donne), sous le départ `titre`. Le dernier argument dit quels corps sont
 * repliés, comme pour `estReplie`. Rend { largeur, hauteur, svg }.
 */
export function construire(flux, titre, { niveauMax = Infinity, bascules = new Set() } = {}) {
  reglages = { niveauMax, bascules };
  const depart = pilule(titre, "f-depart", null, "", { gras: true, classeTexte: "t-depart", sort: true });
  const corps = blocSequence(flux, 0, "");
  const fin = corps.sort ? pilule("fin", "f-sortie", null, "", { classeTexte: "t-discret" }) : null;
  const s = { liens: [], formes: [], notes: [] };
  const x = G.MARGE + pair(Math.max(depart.g, corps.g, fin ? fin.g : 0));
  let y = G.MARGE;
  depart.dessin(x, y, s);
  y += depart.h;
  if (!corps.vide) {
    lien(s, [[x, y], [x, y + G.GAP + corps.tete]], true);
    y += G.GAP;
    corps.dessin(x, y, s);
    y += corps.h;
  }
  if (fin) {
    lien(s, [[x, y], [x, y + G.GAP]], true);
    y += G.GAP;
    fin.dessin(x, y, s);
    y += fin.h;
  }
  const largeur = x + pair(Math.max(depart.d, corps.d, fin ? fin.d : 0)) + G.MARGE;
  const hauteur = y + G.MARGE;
  return {
    largeur, hauteur,
    svg: `<svg class="flux" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${largeur} ${hauteur}" `
      + `width="${largeur}" height="${hauteur}" role="img" `
      + `aria-label="Organigramme de ${echapper(titre)}">`
      + `${s.liens.join("")}${s.formes.join("")}${s.notes.join("")}</svg>`,
  };
}
