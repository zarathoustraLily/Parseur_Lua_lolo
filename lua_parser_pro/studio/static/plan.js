// Le plan : fonctions, tables et variables déclarées par le script, dans
// l'ordre du texte. Un clic mène à la déclaration.

import { $, etat, sur, emettre, differer, echapper, frais, pluriel, rienEncore } from "./noyau.js";
import * as editeur from "./editeur.js";
import { estVisible, compte } from "./volets.js";

const vue = $("vue-plan");
const liste = $("plan");
const filtre = $("filtre-plan");
const total = $("plan-compte");

const LIMITE = 3000;
const SIGNES = { function: "fn", method: "fn", callback: "fn", table: "{}", variable: "var" };
const GENRES = {
  function: ["fonction", "fonction locale"],
  method: ["méthode", "méthode"],
  callback: ["fonction passée en argument", "fonction passée en argument"],
  table: ["table", "table locale"],
  variable: ["variable globale", "variable locale"],
};

let aplat = [];           // { s: symbole, niveau, fn: fonction associée ou null }
let source = null;
let actif = -1;
let affiches = [];        // rangs de `aplat` actuellement affichés

/** La fonction la plus englobante écrite dans l'étendue du symbole. */
function fonctionDe(symbole, fonctions) {
  let bas = 1;                          // le rang 0 est le script lui-même
  let haut = fonctions.length;
  while (bas < haut) {
    const milieu = (bas + haut) >> 1;
    if (fonctions[milieu].a < symbole.a) bas = milieu + 1;
    else haut = milieu;
  }
  const candidate = fonctions[bas];
  return candidate && candidate.b <= symbole.b ? candidate : null;
}

function preparer() {
  aplat = [];
  source = etat.valide;
  if (!source) return;
  const fonctions = source.fonctions;
  const pile = [];
  for (let i = source.plan.length - 1; i >= 0; i--) pile.push([source.plan[i], 0]);
  while (pile.length) {
    const [symbole, niveau] = pile.pop();
    const fn = symbole.genre === "table" || symbole.genre === "variable"
      ? null : fonctionDe(symbole, fonctions);
    aplat.push({ s: symbole, niveau, fn });
    for (let i = symbole.enfants.length - 1; i >= 0; i--) pile.push([symbole.enfants[i], niveau + 1]);
  }
}

function nomAffiche(symbole) {
  if (symbole.nom) return echapper(symbole.nom);
  return "<i>fonction anonyme</i>";
}

function htmlSymbole(rang, aPlat) {
  const { s, niveau, fn } = aplat[rang];
  let suffixe = "";
  if (s.params && s.genre === "callback") suffixe = `<i>(function(${echapper(s.params.join(", "))}))</i>`;
  else if (s.params) suffixe = `<i>(${echapper(s.params.join(", "))})</i>`;
  else if (s.genre === "table") suffixe = `<i> ${pluriel(s.champs || 0, "champ", "champs")}</i>`;
  else if (s.valeur) suffixe = `<i> = ${echapper(s.valeur)}</i>`;
  const genre = GENRES[s.genre] || [s.genre, s.genre];
  let titre = `${genre[s.local ? 1 : 0]}, ligne ${s.ligne}`;
  if (s.nom === "return") titre = `valeur renvoyée par le script, ligne ${s.ligne}`;
  let detail = String(s.ligne);
  if (fn) {
    titre += `, complexité ${fn.complexity}`;
    detail = `<span class="pastille${fn.complexity > 10 ? " haute" : ""}">${fn.complexity}</span>${s.ligne}`;
  }
  return `<div class="symbole${rang === actif ? " actif" : ""}" role="option" data-i="${rang}"`
    + ` data-genre="${s.genre}" style="--niveau:${aPlat ? 0 : niveau}" title="${echapper(titre)}">`
    + `<span class="symbole-genre">${SIGNES[s.genre] || ""}</span>`
    + `<span class="symbole-nom">${nomAffiche(s)}${suffixe}</span>`
    + `<span class="symbole-detail">${detail}</span></div>`;
}

function dessiner() {
  if (!estVisible("plan")) return;
  if (!source) {
    vue.classList.remove("perime");
    total.textContent = "";
    liste.innerHTML = rienEncore() ? "" : `<div class="vide"><strong>Pas encore de plan</strong>`
      + `Le plan liste les fonctions et les tables dès que la syntaxe est valide.</div>`;
    return;
  }
  vue.classList.toggle("perime", !frais());
  const cherche = filtre.value.trim().toLowerCase();
  affiches = [];
  for (let rang = 0; rang < aplat.length; rang++) {
    if (!cherche || aplat[rang].s.nom.toLowerCase().includes(cherche)) affiches.push(rang);
  }
  total.textContent = cherche
    ? `${affiches.length} sur ${aplat.length}`
    : pluriel(aplat.length, "déclaration", "déclarations");
  if (!affiches.length) {
    liste.innerHTML = cherche
      ? `<div class="vide"><strong>Aucun nom ne contient « ${echapper(filtre.value.trim())} »</strong>`
        + `Essayez une partie plus courte du nom.</div>`
      : `<div class="vide"><strong>Rien à lister</strong>`
        + `Ce script ne déclare ni fonction, ni table, ni variable à son niveau principal.</div>`;
    return;
  }
  let html = "";
  const fin = Math.min(affiches.length, LIMITE);
  for (let i = 0; i < fin; i++) html += htmlSymbole(affiches[i], Boolean(cherche));
  if (affiches.length > LIMITE) {
    html += `<div class="vide">${pluriel(affiches.length - LIMITE, "autre déclaration", "autres déclarations")}`
      + ` : filtrez par nom pour les retrouver.</div>`;
  }
  liste.innerHTML = html;
}

function activer(rang, { defiler = false } = {}) {
  if (rang === actif) return;
  const ancien = liste.querySelector(".symbole.actif");
  if (ancien) ancien.classList.remove("actif");
  actif = rang;
  if (rang < 0) return;
  const element = liste.querySelector(`[data-i="${rang}"]`);
  if (!element) return;
  element.classList.add("actif");
  if (defiler) element.scrollIntoView({ block: "nearest" });
}

function aller(rang) {
  if (!frais()) return;
  const entree = aplat[rang];
  if (!entree) return;
  const { s, fn } = entree;
  activer(rang);
  editeur.marquer("sel", s.a, Math.min(s.b, editeur.finDeLigne(editeur.ligneDe(s.a))));
  editeur.montrer(s.a, "haut");
  editeur.poserCurseur(s.a, s.a, { source: "plan" });
  if (fn) emettre("fonction", { id: fn.id, source: "plan" });
}

function suivre(curseur) {
  if (!source || !frais() || !estVisible("plan")) return;
  let rang = -1;
  for (let i = 0; i < aplat.length; i++) {
    const s = aplat[i].s;
    if (s.a > curseur.position) break;
    if (curseur.position <= s.b) rang = i;      // le dernier trouvé est le plus intérieur
  }
  activer(rang, { defiler: true });
}

liste.tabIndex = 0;
liste.setAttribute("role", "listbox");
liste.setAttribute("aria-label", "Déclarations du script");

liste.addEventListener("click", (evenement) => {
  const element = evenement.target.closest(".symbole");
  if (element) aller(Number(element.dataset.i));
});

liste.addEventListener("keydown", (evenement) => {
  const pas = evenement.key === "ArrowDown" ? 1 : evenement.key === "ArrowUp" ? -1 : 0;
  if (!pas || !affiches.length) return;
  evenement.preventDefault();
  const position = affiches.indexOf(actif);
  const suivant = affiches[Math.min(affiches.length - 1, Math.max(0, position + pas))];
  aller(suivant);
  const element = liste.querySelector(`[data-i="${suivant}"]`);
  if (element) element.scrollIntoView({ block: "nearest" });
});

liste.addEventListener("pointerover", (evenement) => {
  const element = evenement.target.closest(".symbole");
  if (!element || !frais()) return;
  const s = aplat[Number(element.dataset.i)].s;
  editeur.marquer("survol", s.a, Math.min(s.b, editeur.finDeLigne(editeur.ligneDe(s.a))));
});
liste.addEventListener("pointerleave", () => editeur.demarquer("survol"));

filtre.addEventListener("input", dessiner);

const suivreBientot = differer(suivre, 70);

sur("analyse", () => {
  if (etat.valide !== source) {
    preparer();
    actif = -1;
    compte("plan", aplat.length);
  }
  dessiner();
  if (frais()) suivre(editeur.curseurActuel());
});

sur("curseur", (curseur) => {
  if (curseur.source !== "plan") suivreBientot(curseur);
});

sur("vue", ({ id }) => {
  if (id !== "plan") return;
  dessiner();
  if (frais()) suivre(editeur.curseurActuel());
});
