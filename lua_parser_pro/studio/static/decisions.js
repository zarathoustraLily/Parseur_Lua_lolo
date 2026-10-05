// La mécanique des décisions d'une fonction, dessinée comme un organigramme :
// les tests descendent le long d'une colonne, leurs issues partent à droite,
// les boucles reviennent par la gauche.

import {
  $, etat, sur, api, annoncer, differer, echapper, frais, pluriel, nombre, borne,
  policesPretes, largeurTexte, rienEncore,
} from "./noyau.js";
import * as editeur from "./editeur.js";
import { estVisible } from "./volets.js";

const vue = $("vue-decisions");
const choix = $("choix-fonction");
const suivreCase = $("suivre-decisions");
const resume = $("decisions-resume");
const toile = $("decisions-toile");

// Ces polices doivent rester celles de la feuille de style (.flux text, .etiquette).
const FAMILLE_CODE = '"Atkinson Hyperlegible Mono", "Cascadia Mono", Consolas, monospace';
const CODE = `12px ${FAMILLE_CODE}`;
const CODE_GRAS = `600 12px ${FAMILLE_CODE}`;
const TEXTE = '11.5px "Atkinson Hyperlegible Next", "Segoe UI", system-ui, sans-serif';
const G = { LH: 17, PX: 11, PY: 7, GAP: 26, COL: 34, MARGE: 28 };

let source = null;          // analyse valide dont viennent les fonctions listées
let fonctions = [];
let courante = null;        // fonction affichée
let aRefaire = true;
let demande = 0;
let dessin = null;          // { largeur, hauteur } du diagramme affiché
let cleAffichee = "";
let zoom = 1;
let ajuste = true;
let etapes = [];            // { a, b, element } pour chaque forme liée au texte
let active = null;
let donnees = null;         // dernière réponse du serveur, pour redessiner sans la redemander
let niveauMax = Infinity;   // niveaux d'imbrication dessinés ; les corps plus profonds sont repliés
let bascules = new Set();   // corps dont l'état est l'inverse de celui que donne le niveau

// ------------------------------------------------------------------ fonctions
function nomFonction(f) {
  if (f.genre === "script") return "script";
  const parametres = `(${(f.params || []).join(", ")})`;
  if (!f.nom) return `function${parametres}`;
  if (f.nom.endsWith("(…)")) return `${f.nom.slice(0, -3)}(function${parametres})`;
  return f.nom + parametres;
}

function libelle(f) {
  if (f.genre === "script") return `Script, niveau principal, complexité ${f.complexity}`;
  return `${nomFonction(f)}, ligne ${f.ligne}, complexité ${f.complexity}`;
}

/** Nom et rang parmi les homonymes : reconnaît une fonction d'une analyse à la suivante. */
function cleFonction(f) {
  let rang = 0;
  for (const autre of fonctions) {
    if (autre === f) break;
    if (autre.nom === f.nom) rang++;
  }
  return `${f.nom}#${rang}`;
}

function fonctionA(position) {
  let trouvee = fonctions[0];
  for (const f of fonctions) {
    if (f.a > position) break;
    if (position <= f.b) trouvee = f;       // la dernière trouvée est la plus intérieure
  }
  return trouvee;
}

function choisirFonction(nouveau) {
  if (!fonctions.length) return null;
  if (nouveau) {
    return fonctions.reduce((meilleure, f) => (f.complexity > meilleure.complexity ? f : meilleure));
  }
  if (suivreCase.checked) return fonctionA(editeur.curseurActuel().position);
  return fonctions.find((f) => cleFonction(f) === cleAffichee) || fonctions[0];
}

function remplirChoix() {
  let html = "";
  for (const f of fonctions) html += `<option value="${f.id}">${echapper(libelle(f))}</option>`;
  choix.innerHTML = html;
  choix.disabled = fonctions.length === 0;
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

const estReplie = (niveau, cle) => (niveau > niveauMax) !== bascules.has(cle);

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

function construire(flux, titre) {
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

// --------------------------------------------------------------------- rendu
function tuile(valeur, nom, aide) {
  return `<div class="chiffre" title="${echapper(aide)}"><span class="chiffre-valeur">${nombre(valeur)}</span>`
    + `<span class="chiffre-nom">${nom}</span></div>`;
}

function dessinerResume(mesures, termes) {
  const c = mesures.complexity;
  const niveau = c <= 5 ? "faible" : c <= 10 ? "modérée" : c <= 20 ? "élevée" : "très élevée";
  let html = tuile(c, `complexité ${niveau}`,
    "1, plus 1 par test, par boucle et par « and » ou « or » dans une condition")
    + tuile(mesures.decisions, mesures.decisions > 1 ? "tests" : "test", "Conditions if et elseif")
    + tuile(mesures.loops, mesures.loops > 1 ? "boucles" : "boucle", "Boucles while, repeat et for")
    + tuile(mesures.nesting, mesures.nesting > 1 ? "niveaux imbriqués" : "niveau imbriqué",
      "Profondeur maximale des tests et des boucles")
    + tuile(mesures.exits, mesures.exits > 1 ? "sorties return" : "sortie return", "Instructions return")
    + tuile(mesures.statements, mesures.statements > 1 ? "instructions" : "instruction",
      "Instructions de la fonction, sans compter celles des fonctions qu'elle contient");
  if (termes.length) {
    html += `<div class="termes"><div class="termes-titre">Ce que lisent les conditions</div>`
      + `<div class="termes-liste">`;
    for (const terme of termes) {
      html += `<span class="terme" title="${pluriel(terme.nombre, "lecture", "lectures")}">`
        + `${echapper(terme.nom)}<b>${terme.nombre}</b></span>`;
    }
    html += `</div></div>`;
  }
  resume.innerHTML = html;
}

function appliquerZoom() {
  const svg = toile.firstElementChild;
  if (!dessin || !svg || svg.tagName.toLowerCase() !== "svg" || !toile.clientWidth) return;
  // Ajusté à la largeur du volet, sans descendre sous une taille lisible.
  if (ajuste) zoom = borne((toile.clientWidth - 6) / dessin.largeur, 0.8, 1);
  svg.setAttribute("width", Math.round(dessin.largeur * zoom));
  svg.setAttribute("height", Math.round(dessin.hauteur * zoom));
}

function definirZoom(valeur) {
  ajuste = false;
  zoom = borne(valeur, 0.25, 2.5);
  appliquerZoom();
}

function marquerActive(position, defiler) {
  let meilleure = null;
  for (const etape of etapes) {
    if (etape.a <= position && position <= etape.b
        && (!meilleure || etape.b - etape.a < meilleure.b - meilleure.a)) meilleure = etape;
  }
  if (active && (!meilleure || active !== meilleure.element)) active.classList.remove("actif");
  active = meilleure ? meilleure.element : null;
  if (!active) return;
  active.classList.add("actif");
  if (defiler) active.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function vider(titre, texte) {
  dessin = null;
  etapes = [];
  active = null;
  resume.innerHTML = "";
  toile.innerHTML = `<div class="vide"><strong>${titre}</strong>${texte}</div>`;
}

async function rafraichir() {
  if (!estVisible("decisions")) return;
  if (!source) {
    vue.classList.remove("perime");
    choix.innerHTML = "";
    choix.disabled = true;
    if (rienEncore()) return;
    vider("Pas encore de diagramme",
      "Le diagramme des décisions apparaît dès que la syntaxe du script est valide.");
    return;
  }
  vue.classList.toggle("perime", !frais());
  if (!frais() || !aRefaire || !courante) return;
  aRefaire = false;
  const f = courante;
  const numero = ++demande;
  choix.value = String(f.id);
  let reponse;
  try {
    reponse = await api("decisions", { doc: source.doc, fonction: f.id });
  } catch (erreur) {
    if (numero === demande) {
      aRefaire = true;
      if (erreur.statut !== 410) annoncer(erreur.message);
    }
    return;
  }
  await policesPretes;
  if (numero !== demande) return;
  const memeFonction = cleFonction(f) === cleAffichee;
  cleAffichee = cleFonction(f);
  if (!memeFonction) bascules = new Set();
  donnees = reponse;
  dessinerResume(reponse.mesures, reponse.termes);
  tracer(memeFonction);
}

/** Dessine la dernière réponse reçue ; `garder` conserve le zoom et la position de lecture. */
function tracer(garder) {
  if (!donnees || !courante) return;
  const titre = courante.genre === "script" ? `script ${etat.nom}` : nomFonction(courante);
  dessin = construire(donnees.flux, titre);
  toile.innerHTML = dessin.svg;
  etapes = [];
  for (const element of toile.querySelectorAll("g.etape, g.pli[data-a]")) {
    etapes.push({ a: Number(element.dataset.a), b: Number(element.dataset.b), element });
  }
  active = null;
  if (!garder) {
    ajuste = true;
    toile.scrollTop = 0;
    toile.scrollLeft = 0;
  }
  appliquerZoom();
  marquerActive(editeur.curseurActuel().position, false);
}

// --------------------------------------------------------------------- replis
const niveauDe = (clePli) => clePli.split(":").length - 1;
const enTete = (clePli) => toile.querySelector(`g.etape[data-plis~="${clePli}"]`);

/** Replie les corps ouverts parmi `cles` ; s'ils sont tous repliés, les déplie. */
function basculerPlis(cles) {
  const ouverts = cles.filter((clePli) => !estReplie(niveauDe(clePli), clePli));
  for (const clePli of ouverts.length ? ouverts : cles) {
    if (bascules.has(clePli)) bascules.delete(clePli);
    else bascules.add(clePli);
  }
  // Le test ou la boucle concernés restent à la même place sous les yeux.
  const avant = enTete(cles[0]);
  const hautAvant = avant ? avant.getBoundingClientRect().top : null;
  tracer(true);
  const apres = enTete(cles[0]);
  if (apres && hautAvant !== null) toile.scrollTop += apres.getBoundingClientRect().top - hautAvant;
}

const boutonsNiveau = [...document.querySelectorAll("#niveaux [data-niveau]")];
for (const bouton of boutonsNiveau) {
  bouton.addEventListener("click", () => {
    niveauMax = bouton.dataset.niveau === "tout" ? Infinity : Number(bouton.dataset.niveau) - 1;
    bascules = new Set();
    for (const autre of boutonsNiveau) autre.setAttribute("aria-pressed", String(autre === bouton));
    tracer(false);
    if (active) active.scrollIntoView({ block: "center", inline: "nearest" });
  });
}

function montrer(f) {
  if (!f) return;
  courante = f;
  aRefaire = true;
  rafraichir();
}

// ---------------------------------------------------------------- interactions
choix.addEventListener("change", () => {
  const f = fonctions.find((candidate) => String(candidate.id) === choix.value);
  if (!f) return;
  suivreBientot.annuler();
  montrer(f);
  if (!frais()) return;
  editeur.marquer("sel", f.a, Math.min(f.b, editeur.finDeLigne(editeur.ligneDe(f.a))));
  editeur.montrer(f.a, "haut");
  editeur.poserCurseur(f.a, f.a, { source: "decisions" });
});

let glisse = null;
let ignorerClic = false;
let depliAuClic = false;        // le premier clic du double-clic en cours a déplié un cadre

toile.addEventListener("pointerdown", (evenement) => {
  if (evenement.button !== 0) return;
  glisse = { x: evenement.clientX, y: evenement.clientY, gauche: toile.scrollLeft,
    haut: toile.scrollTop, actif: false, id: evenement.pointerId };
});
toile.addEventListener("pointermove", (evenement) => {
  if (!glisse || evenement.pointerId !== glisse.id) return;
  const dx = evenement.clientX - glisse.x;
  const dy = evenement.clientY - glisse.y;
  if (!glisse.actif) {
    if (Math.abs(dx) + Math.abs(dy) < 5) return;
    glisse.actif = true;
    toile.setPointerCapture(evenement.pointerId);
    toile.classList.add("glisse");
  }
  toile.scrollLeft = glisse.gauche - dx;
  toile.scrollTop = glisse.haut - dy;
});
function finGlisse() {
  if (!glisse) return;
  if (glisse.actif) {
    ignorerClic = true;
    setTimeout(() => { ignorerClic = false; }, 0);
  }
  glisse = null;
  toile.classList.remove("glisse");
}
toile.addEventListener("pointerup", finGlisse);
toile.addEventListener("pointercancel", finGlisse);

function allerEtape(element, focus = false) {
  if (!frais()) return;
  if (active && active !== element) active.classList.remove("actif");
  active = element;
  element.classList.add("actif");
  editeur.selectionner(Number(element.dataset.a), Number(element.dataset.b), { source: "decisions", focus });
}

toile.addEventListener("click", (evenement) => {
  if (ignorerClic) return;
  // Un cadre se déplie au premier clic. Le second clic d'un double-clic tombe sur ce
  // qui vient d'apparaître à sa place : il ne doit rien déplier ni replier de plus.
  const premier = evenement.detail <= 1;
  const suite = !premier && depliAuClic;
  if (premier) depliAuClic = false;
  const pli = evenement.target.closest("g.pli");
  if (pli) {
    if (suite) return;
    depliAuClic = premier;
    basculerPlis([pli.dataset.pli]);
    return;
  }
  const element = evenement.target.closest("g.etape");
  if (element) allerEtape(element);
});

toile.addEventListener("dblclick", (evenement) => {
  if (depliAuClic) return;
  const element = evenement.target.closest("g.etape[data-plis]");
  if (!element) return;
  evenement.preventDefault();
  basculerPlis(element.dataset.plis.split(" "));
});

toile.addEventListener("pointerover", (evenement) => {
  const element = evenement.target.closest("g.etape, g.pli[data-a]");
  if (element && frais()) editeur.marquer("survol", Number(element.dataset.a), Number(element.dataset.b));
  else editeur.demarquer("survol");
});
toile.addEventListener("pointerleave", () => editeur.demarquer("survol"));

toile.addEventListener("keydown", (evenement) => {
  if (!etapes.length) return;
  const rang = etapes.findIndex((etape) => etape.element === document.activeElement);
  let cible = -1;
  if (evenement.key === "ArrowDown" || evenement.key === "ArrowRight") cible = Math.min(etapes.length - 1, rang + 1);
  else if (evenement.key === "ArrowUp" || evenement.key === "ArrowLeft") cible = Math.max(0, rang - 1);
  else if ((evenement.key === "Enter" || evenement.key === " ") && rang >= 0) {
    evenement.preventDefault();
    const choisie = etapes[rang].element;
    if (choisie.dataset.pli) basculerPlis([choisie.dataset.pli]);
    else allerEtape(choisie, evenement.key === "Enter");
    return;
  } else return;
  evenement.preventDefault();
  const element = etapes[cible].element;
  element.focus({ preventScroll: true });
  element.scrollIntoView({ block: "nearest", inline: "nearest" });
  allerEtape(element);
});

toile.addEventListener("wheel", (evenement) => {
  if (!evenement.ctrlKey || !dessin) return;
  evenement.preventDefault();
  const cadre = toile.getBoundingClientRect();
  const px = evenement.clientX - cadre.left;
  const py = evenement.clientY - cadre.top;
  const avant = zoom;
  definirZoom(zoom * Math.exp(-evenement.deltaY * 0.0018));
  const rapport = zoom / avant;
  toile.scrollLeft = (toile.scrollLeft + px) * rapport - px;
  toile.scrollTop = (toile.scrollTop + py) * rapport - py;
}, { passive: false });

$("zoom-plus").addEventListener("click", () => definirZoom(zoom * 1.2));
$("zoom-moins").addEventListener("click", () => definirZoom(zoom / 1.2));
$("zoom-ajuster").addEventListener("click", () => {
  ajuste = true;
  appliquerZoom();
});
new ResizeObserver(() => {
  if (ajuste) appliquerZoom();
}).observe(toile);

const suivreBientot = differer((curseur) => {
  if (!source || !frais() || !estVisible("decisions")) return;
  if (suivreCase.checked) {
    const f = fonctionA(curseur.position);
    if (f !== courante) {
      montrer(f);
      return;
    }
  }
  if (curseur.source !== "decisions") marquerActive(curseur.position, true);
}, 80);

suivreCase.addEventListener("change", () => {
  if (suivreCase.checked) suivreBientot(editeur.curseurActuel());
});

sur("analyse", ({ nouveau }) => {
  if (etat.valide !== source) {
    source = etat.valide;
    fonctions = source ? source.fonctions : [];
    remplirChoix();
    courante = choisirFonction(nouveau);
    if (nouveau) cleAffichee = "";
    aRefaire = true;
  }
  rafraichir();
});

sur("curseur", (curseur) => {
  if (curseur.source !== "chargement") suivreBientot(curseur);
});

sur("fonction", ({ id }) => {
  suivreBientot.annuler();
  montrer(fonctions.find((f) => f.id === id));
});

sur("vue", ({ id }) => {
  if (id === "decisions") rafraichir();
});
