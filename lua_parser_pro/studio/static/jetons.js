// Les jetons du texte, page par page : ce que voit l'analyseur lexical.

import { $, etat, sur, api, annoncer, echapper, extrait, nombre } from "./noyau.js";
import * as editeur from "./editeur.js";
import { estVisible } from "./volets.js";

const zone = $("jetons");
const precedent = $("jetons-precedent");
const suivant = $("jetons-suivant");
const sousCurseur = $("jetons-curseur");
const total = $("jetons-compte");

const PAGE = 200;
const GENRES = ["mot-clé", "nom", "nombre", "chaîne", "symbole", "commentaire"];

let debut = 0;
let nombreTotal = 0;
let docAffiche = null;
let demande = 0;

/** L'analyse du texte tel qu'il est dans l'éditeur, ou rien si elle est en cours. */
const analyseActuelle = () => (etat.versionAnalyse === etat.version ? etat.analyse : null);

function boutons() {
  precedent.disabled = debut <= 0;
  suivant.disabled = debut + PAGE >= nombreTotal;
  sousCurseur.disabled = nombreTotal === 0;
}

function vider(titre, texte) {
  nombreTotal = 0;
  total.textContent = "";
  zone.innerHTML = `<div class="vide"><strong>${titre}</strong>${texte}</div>`;
  boutons();
}

async function charger({ position = null } = {}) {
  if (!estVisible("jetons")) return;
  const analyse = analyseActuelle();
  if (!analyse) return;
  if (analyse.jetons === null) {
    docAffiche = analyse.doc;
    vider("Aucun jeton", "Le texte n'a pas pu être découpé : corrigez d'abord l'erreur signalée sous l'éditeur.");
    return;
  }
  const numero = ++demande;
  let page;
  try {
    page = await api("jetons", { doc: analyse.doc, debut, nombre: PAGE, position });
  } catch (erreur) {
    if (numero === demande && erreur.statut !== 410) annoncer(erreur.message);
    return;
  }
  if (numero !== demande || analyse !== analyseActuelle()) return;
  docAffiche = analyse.doc;
  debut = page.debut;
  nombreTotal = page.total;
  if (!page.total) {
    vider("Aucun jeton", "Ce texte est vide ou ne contient que des espaces.");
    return;
  }
  const texte = etat.texteAnalyse;
  let html = `<table class="table"><thead><tr><th class="num">n°</th><th>genre</th><th>texte</th>`
    + `<th class="num">ligne</th><th class="num">colonne</th></tr></thead><tbody>`;
  page.jetons.forEach(([genre, a, b, ligne, colonne, valeur], i) => {
    const rang = page.debut + i;
    const aide = valeur === null ? "" : ` title="octets de la chaîne : ${echapper(valeur)}"`;
    html += `<tr data-a="${a}" data-b="${b}"${rang === page.vise ? ' class="vise"' : ""}${aide}>`
      + `<td class="num">${nombre(rang + 1)}</td><td><span class="genre">${GENRES[genre]}</span></td>`
      + `<td class="code">${echapper(extrait(texte, a, b, 110))}</td>`
      + `<td class="num">${nombre(ligne)}</td><td class="num">${nombre(colonne)}</td></tr>`;
  });
  zone.innerHTML = html + `</tbody></table>`;
  total.textContent = `${nombre(page.debut + 1)} à ${nombre(page.debut + page.jetons.length)} sur ${nombre(page.total)}`
    + (analyse.commentaires ? ", commentaires compris" : "");
  boutons();
  const vise = zone.querySelector("tr.vise");
  if (vise) vise.scrollIntoView({ block: "center" });
  else if (position === null) zone.scrollTop = 0;
}

precedent.addEventListener("click", () => {
  debut = Math.max(0, debut - PAGE);
  charger();
});
suivant.addEventListener("click", () => {
  debut += PAGE;
  charger();
});
sousCurseur.addEventListener("click", () => charger({ position: editeur.curseurActuel().position }));

zone.addEventListener("click", (evenement) => {
  const ligne = evenement.target.closest("tr[data-a]");
  if (!ligne || !analyseActuelle()) return;
  const ancienne = zone.querySelector("tr.vise");
  if (ancienne) ancienne.classList.remove("vise");
  ligne.classList.add("vise");
  editeur.selectionner(Number(ligne.dataset.a), Number(ligne.dataset.b), { source: "jetons" });
});

sur("analyse", ({ nouveau }) => {
  if (nouveau) debut = 0;
  charger();
});

sur("vue", ({ id }) => {
  const analyse = analyseActuelle();
  if (id === "jetons" && analyse && analyse.doc !== docAffiche) charger();
});
