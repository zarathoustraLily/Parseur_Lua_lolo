// L'arbre syntaxique : une ligne par nœud, dépliée à la demande. Les nœuds
// très profonds d'un grand fichier ne sont demandés au serveur qu'au dépliage.

import { $, etat, sur, api, annoncer, differer, echapper, extrait, frais, pluriel, rienEncore } from "./noyau.js";
import * as editeur from "./editeur.js";
import { estVisible } from "./volets.js";

const vue = $("vue-arbre");
const conteneur = $("arbre");
const avis = $("arbre-avis");
const fil = $("fil");
const suivre = $("suivre-arbre");

const RESERVES = new Set(["t", "a", "b", "n", "x"]);
const TRANCHE = 200;                // enfants affichés d'emblée sous un même nœud
const RALLONGE = 1000;              // enfants ajoutés par « Afficher la suite »

let racine = null;
let texte = "";
let ouverts = new Set([""]);        // clés des nœuds dépliés ; la racine a la clé vide
let fenetres = new Map();           // clé -> [premier, dernier + 1] des enfants affichés
let lignes = [];
let rangs = new Map();              // clé -> numéro de ligne
let selection = null;
let cheminFil = [];
const cacheEnfants = new WeakMap();

function enfants(noeud) {
  let liste = cacheEnfants.get(noeud);
  if (liste) return liste;
  liste = [];
  for (const champ in noeud) {
    if (RESERVES.has(champ)) continue;
    const valeur = noeud[champ];
    if (valeur === null || typeof valeur !== "object") continue;
    if (Array.isArray(valeur)) {
      for (let i = 0; i < valeur.length; i++) liste.push({ champ, index: i, noeud: valeur[i] });
    } else {
      liste.push({ champ, index: null, noeud: valeur });
    }
  }
  cacheEnfants.set(noeud, liste);
  return liste;
}

const cleEnfant = (parent, champ, index) => `${parent}/${champ}${index === null ? "" : ":" + index}`;

/** Sous un nœud aux très nombreux enfants, seule une fenêtre d'enfants est affichée. */
function cadre(noeud, cle, niveau, ligne) {
  const liste = enfants(noeud);
  const [debut, fin] = fenetres.get(cle) || [0, TRANCHE];
  if (debut > 0) lignes.push({ suite: "avant", cle, niveau: niveau + 1, restants: debut, parent: ligne });
  return { liste, i: Math.min(debut, liste.length), fin: Math.min(liste.length, fin), cle, niveau, ligne };
}

/** Liste à plat des lignes visibles, dans l'ordre d'affichage. */
function construire() {
  lignes = [];
  rangs = new Map();
  if (!racine) return;
  lignes.push({ noeud: racine, cle: "", niveau: 0, champ: null, index: null, parent: -1 });
  rangs.set("", 0);
  const pile = [];
  if (ouverts.has("")) pile.push(cadre(racine, "", 0, 0));
  while (pile.length) {
    const courant = pile[pile.length - 1];
    if (courant.i >= courant.fin) {
      if (courant.fin < courant.liste.length) {
        lignes.push({ suite: "apres", cle: courant.cle, niveau: courant.niveau + 1,
          restants: courant.liste.length - courant.fin, parent: courant.ligne });
      }
      pile.pop();
      continue;
    }
    const enfant = courant.liste[courant.i++];
    const cle = cleEnfant(courant.cle, enfant.champ, enfant.index);
    const numero = lignes.length;
    lignes.push({ noeud: enfant.noeud, cle, niveau: courant.niveau + 1, champ: enfant.champ,
      index: enfant.index, parent: courant.ligne });
    rangs.set(cle, numero);
    if (ouverts.has(cle) && !enfant.noeud.x) pile.push(cadre(enfant.noeud, cle, courant.niveau + 1, numero));
  }
}

function categorie(type) {
  if (type.endsWith("Statement")) return "cat-inst";
  if (type.endsWith("Literal") || type === "Identifier" || type === "VarargExpression") return "cat-lit";
  if (type.endsWith("Expression")) return "cat-expr";
  return "cat-struct";
}

/** L'opérateur d'une expression ou le genre d'un champ de table : absents de l'extrait. */
function precisions(noeud) {
  if (typeof noeud.operator === "string") return noeud.operator;
  if (typeof noeud.kind === "string") return noeud.kind;
  return "";
}

function resume(noeud) {
  if (noeud.t === "Chunk" || noeud.t === "Block") {
    return noeud.x ? "" : pluriel(noeud.body ? noeud.body.length : 0, "instruction", "instructions");
  }
  return extrait(texte, noeud.a, noeud.b, 56);
}

function htmlLigne(ligne, i, actuel) {
  if (ligne.suite) {
    const libelle = ligne.suite === "avant"
      ? `Afficher ce qui précède, ${pluriel(ligne.restants, "nœud", "nœuds")}`
      : `Afficher la suite, ${pluriel(ligne.restants, "nœud restant", "nœuds restants")}`;
    return `<div class="noeud-suite" data-i="${i}" style="--niveau:${ligne.niveau}">`
      + `<button class="bouton bouton-discret" type="button">${libelle}</button></div>`;
  }
  const noeud = ligne.noeud;
  const parent = noeud.x === 1 || enfants(noeud).length > 0;
  const ouvert = parent && !noeud.x && ouverts.has(ligne.cle);
  const champ = ligne.champ === null ? ""
    : `<span class="noeud-champ">${ligne.champ}${ligne.index === null ? "" : `[${ligne.index}]`}</span>`;
  const details = precisions(noeud);
  return `<div class="noeud" role="treeitem" id="arbre-${i}" data-i="${i}" aria-level="${ligne.niveau + 1}"`
    + ` aria-selected="${ligne.cle === selection}"${parent ? ` aria-expanded="${ouvert}"` : ""}`
    + ` style="--niveau:${ligne.niveau}">`
    + `<span class="noeud-pli${parent ? "" : " sans"}"></span>${champ}`
    + `<span class="noeud-type ${categorie(noeud.t)}">${noeud.t}</span>`
    + (details ? `<span class="noeud-precision">${echapper(details)}</span>` : "")
    + `<span class="noeud-resume">${echapper(resume(noeud))}</span>`
    + (actuel ? `<span class="noeud-ligne">${editeur.ligneDe(noeud.a) + 1}</span>` : "")
    + `</div>`;
}

function dessiner() {
  if (!estVisible("arbre")) return;
  const source = etat.valide;
  if (!source) {
    vue.classList.remove("perime");
    avis.hidden = true;
    conteneur.innerHTML = rienEncore() ? "" : `<div class="vide"><strong>Pas encore d'arbre</strong>`
      + `Corrigez l'erreur signalée sous l'éditeur : l'arbre apparaît dès que la syntaxe est valide.</div>`;
    return;
  }
  const actuel = frais();
  vue.classList.toggle("perime", !actuel);
  avis.hidden = actuel && !source.elague;
  avis.textContent = actuel
    ? "Grand fichier : les niveaux profonds se chargent au dépliage."
    : "Arbre de la dernière version valide";
  construire();
  let html = "";
  for (let i = 0; i < lignes.length; i++) html += htmlLigne(lignes[i], i, actuel);
  conteneur.innerHTML = html;
  const rang = rangs.get(selection);
  if (rang !== undefined) conteneur.setAttribute("aria-activedescendant", "arbre-" + rang);
  else conteneur.removeAttribute("aria-activedescendant");
}

// ------------------------------------------------------------------ sélection
function choisir(cle, { defiler = true } = {}) {
  const ancien = rangs.get(selection);
  if (ancien !== undefined && conteneur.children[ancien]) {
    conteneur.children[ancien].setAttribute("aria-selected", "false");
  }
  selection = cle;
  const rang = rangs.get(cle);
  if (rang === undefined) return;
  const element = conteneur.children[rang];
  if (!element) return;
  element.setAttribute("aria-selected", "true");
  conteneur.setAttribute("aria-activedescendant", element.id);
  if (defiler) element.scrollIntoView({ block: "nearest" });
}

/** Nœuds de la racine au plus petit nœud qui contient l'étendue [debut, fin]. */
function cheminVers(debut, fin) {
  const chemin = [{ noeud: racine, cle: "" }];
  let courant = racine;
  let cle = "";
  for (;;) {
    let meilleur = null;
    for (const champ in courant) {
      if (RESERVES.has(champ)) continue;
      const valeur = courant[champ];
      if (valeur === null || typeof valeur !== "object") continue;
      let candidat = null;
      if (Array.isArray(valeur)) {
        let bas = 0;
        let haut = valeur.length - 1;
        let rang = -1;
        while (bas <= haut) {                 // dernier élément qui commence avant `debut`
          const milieu = (bas + haut) >> 1;
          if (valeur[milieu].a <= debut) {
            rang = milieu;
            bas = milieu + 1;
          } else {
            haut = milieu - 1;
          }
        }
        if (rang >= 0 && fin <= valeur[rang].b) candidat = { champ, index: rang, noeud: valeur[rang] };
      } else if (valeur.a <= debut && fin <= valeur.b) {
        candidat = { champ, index: null, noeud: valeur };
      }
      if (candidat && (!meilleur
          || candidat.noeud.b - candidat.noeud.a < meilleur.noeud.b - meilleur.noeud.a)) {
        meilleur = candidat;
      }
    }
    if (!meilleur) return chemin;
    cle = cleEnfant(cle, meilleur.champ, meilleur.index);
    chemin.push({ noeud: meilleur.noeud, cle, champ: meilleur.champ, index: meilleur.index });
    courant = meilleur.noeud;
  }
}

function dessinerFil(chemin) {
  cheminFil = chemin;
  let html = "";
  chemin.forEach((etape, i) => {
    html += `${i ? "<span>›</span>" : ""}<button type="button" data-i="${i}">${etape.noeud.t}</button>`;
  });
  fil.innerHTML = html;
  fil.scrollLeft = fil.scrollWidth;
}

/** Déplie les ancêtres du dernier nœud de `chemin`, puis le sélectionne. */
function reveler(chemin) {
  let change = false;
  for (let i = 0; i < chemin.length - 1; i++) {
    const etape = chemin[i];
    if (!ouverts.has(etape.cle)) {
      ouverts.add(etape.cle);
      change = true;
    }
    const suivant = chemin[i + 1];
    const rang = enfants(etape.noeud).findIndex(
      (enfant) => enfant.champ === suivant.champ && enfant.index === suivant.index);
    const [debut, fin] = fenetres.get(etape.cle) || [0, TRANCHE];
    if (rang < debut || rang >= fin) {
      fenetres.set(etape.cle, [Math.max(0, rang - TRANCHE / 4), rang + TRANCHE]);
      change = true;
    }
  }
  const cle = chemin[chemin.length - 1].cle;
  if (change || !rangs.has(cle)) {
    selection = cle;
    dessiner();
    const rang = rangs.get(cle);
    if (rang !== undefined && conteneur.children[rang]) {
      conteneur.children[rang].scrollIntoView({ block: "center" });
    }
  } else {
    choisir(cle);
  }
}

function greffer(noeud, recu) {
  delete noeud.x;
  Object.assign(noeud, recu);
  cacheEnfants.delete(noeud);
}

const cheminServeurDe = (chemin) => chemin.slice(1).map((etape) => [etape.champ, etape.index]);

let suivi = 0;

async function suivreCurseur(curseur) {
  const numero = ++suivi;
  if (!racine || !frais()) {
    dessinerFil([]);
    return;
  }
  let chemin = cheminVers(curseur.debut, curseur.fin);
  const montre = estVisible("arbre") && suivre.checked;
  // Grand fichier : les niveaux profonds sous le curseur sont demandés au serveur.
  for (let tour = 0; montre && tour < 12 && chemin[chemin.length - 1].noeud.x === 1; tour++) {
    const dernier = chemin[chemin.length - 1].noeud;
    let reponse;
    try {
      reponse = await api("noeud", { doc: etat.valide.doc, chemin: cheminServeurDe(chemin) });
    } catch {
      break;
    }
    if (numero !== suivi || !frais()) return;
    greffer(dernier, reponse.noeud);
    chemin = cheminVers(curseur.debut, curseur.fin);
  }
  dessinerFil(chemin);
  if (montre) reveler(chemin);
}

// ----------------------------------------------------------------- dépliage
/** Le chemin de la racine jusqu'à une ligne affichée, pour le fil d'Ariane. */
function cheminDeLigne(ligne) {
  const chemin = [];
  for (let courante = ligne; courante; courante = lignes[courante.parent]) {
    chemin.push({ noeud: courante.noeud, cle: courante.cle, champ: courante.champ, index: courante.index });
  }
  return chemin.reverse();
}

function cheminServeur(ligne) {
  const etapes = [];
  for (let courante = ligne; courante.parent >= 0; courante = lignes[courante.parent]) {
    etapes.push([courante.champ, courante.index]);
  }
  return etapes.reverse();
}

async function basculer(ligne) {
  const noeud = ligne.noeud;
  if (noeud.x === 1) {
    if (!frais()) return;
    try {
      const reponse = await api("noeud", { doc: etat.valide.doc, chemin: cheminServeur(ligne) });
      greffer(noeud, reponse.noeud);
      ouverts.add(ligne.cle);
    } catch (erreur) {
      annoncer(erreur.message);
      return;
    }
  } else if (ouverts.has(ligne.cle)) {
    ouverts.delete(ligne.cle);
  } else if (enfants(noeud).length) {
    ouverts.add(ligne.cle);
  } else {
    return;
  }
  dessiner();
}

function activer(ligne, { viaPli = false } = {}) {
  if (ligne.suite) {
    const [debut, fin] = fenetres.get(ligne.cle) || [0, TRANCHE];
    fenetres.set(ligne.cle, ligne.suite === "avant"
      ? [Math.max(0, debut - RALLONGE), fin] : [debut, fin + RALLONGE]);
    const haut = conteneur.scrollTop;
    const hauteur = conteneur.scrollHeight;
    dessiner();
    // Ce qui s'ajoute au-dessus ne doit pas faire sauter ce que l'on regardait.
    if (ligne.suite === "avant") conteneur.scrollTop = haut + conteneur.scrollHeight - hauteur;
    return;
  }
  const dejaChoisie = ligne.cle === selection;
  const repliee = !ouverts.has(ligne.cle) || ligne.noeud.x === 1;
  if (!viaPli) {
    choisir(ligne.cle, { defiler: false });
    if (frais()) {
      dessinerFil(cheminDeLigne(ligne));
      editeur.selectionner(ligne.noeud.a, ligne.noeud.b, { source: "arbre" });
    }
  }
  if (viaPli || dejaChoisie || repliee) basculer(ligne);
}

conteneur.addEventListener("click", (evenement) => {
  const element = evenement.target.closest("[data-i]");
  if (!element) return;
  const ligne = lignes[Number(element.dataset.i)];
  if (ligne) activer(ligne, { viaPli: evenement.target.classList.contains("noeud-pli") });
});

conteneur.addEventListener("pointerover", (evenement) => {
  const element = evenement.target.closest(".noeud");
  if (!element || !frais()) return;
  const ligne = lignes[Number(element.dataset.i)];
  if (ligne && ligne.noeud) editeur.marquer("survol", ligne.noeud.a, ligne.noeud.b);
});
conteneur.addEventListener("pointerleave", () => editeur.demarquer("survol"));

conteneur.addEventListener("keydown", (evenement) => {
  if (!lignes.length) return;
  let rang = rangs.get(selection);
  if (rang === undefined) rang = 0;
  const ligne = lignes[rang];
  let cible = null;
  switch (evenement.key) {
    case "ArrowDown": cible = Math.min(lignes.length - 1, rang + 1); break;
    case "ArrowUp": cible = Math.max(0, rang - 1); break;
    case "Home": cible = 0; break;
    case "End": cible = lignes.length - 1; break;
    case "ArrowRight":
      if (ligne.suite) return;
      if (ligne.noeud.x === 1 || (enfants(ligne.noeud).length && !ouverts.has(ligne.cle))) basculer(ligne);
      else if (enfants(ligne.noeud).length) cible = rang + 1;
      break;
    case "ArrowLeft":
      if (!ligne.suite && ouverts.has(ligne.cle) && enfants(ligne.noeud).length) basculer(ligne);
      else if (ligne.parent >= 0) cible = ligne.parent;
      break;
    case "Enter":
    case " ":
      if (ligne.suite) activer(ligne);
      else if (frais()) {
        editeur.selectionner(ligne.noeud.a, ligne.noeud.b, { focus: evenement.key === "Enter", source: "arbre" });
      }
      break;
    default:
      return;
  }
  evenement.preventDefault();
  if (cible === null || cible === rang && rangs.has(selection)) return;
  const suivante = lignes[cible];
  if (suivante.suite) {
    activer(suivante);
    return;
  }
  choisir(suivante.cle);
  if (frais()) {
    dessinerFil(cheminDeLigne(suivante));
    editeur.selectionner(suivante.noeud.a, suivante.noeud.b, { source: "arbre" });
  }
});

fil.addEventListener("click", (evenement) => {
  const bouton = evenement.target.closest("button");
  if (!bouton || !frais()) return;
  const chemin = cheminFil.slice(0, Number(bouton.dataset.i) + 1);
  const noeud = chemin[chemin.length - 1].noeud;
  editeur.selectionner(noeud.a, noeud.b, { source: "arbre" });
  dessinerFil(chemin);
  if (estVisible("arbre")) reveler(chemin);
});

$("btn-replier").addEventListener("click", () => {
  ouverts = new Set([""]);
  fenetres = new Map();
  dessiner();
  conteneur.scrollTop = 0;
});

suivre.addEventListener("change", () => {
  if (suivre.checked) suivreCurseur(editeur.curseurActuel());
});

sur("analyse", ({ nouveau }) => {
  const source = etat.valide;
  if (source && source.arbre !== racine) {
    racine = source.arbre;
    texte = source.texte;
  }
  if (nouveau) {
    ouverts = new Set([""]);
    fenetres = new Map();
    selection = null;
    conteneur.scrollTop = 0;
  }
  dessiner();
  if (frais()) suivreCurseur(editeur.curseurActuel());
  else dessinerFil([]);
});

const suivreBientot = differer(suivreCurseur, 70);
sur("curseur", (curseur) => {
  if (curseur.source !== "arbre") suivreBientot(curseur);
});

sur("vue", ({ id }) => {
  if (id !== "arbre") return;
  dessiner();
  if (frais()) suivreCurseur(editeur.curseurActuel());
});
