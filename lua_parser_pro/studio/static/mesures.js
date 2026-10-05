// Les mesures du script : quelques chiffres, puis des classements en barres.

import { $, etat, sur, emettre, api, annoncer, echapper, frais, nombre, duree, rienEncore } from "./noyau.js";
import * as editeur from "./editeur.js";
import { estVisible, ouvrir } from "./volets.js";

const vue = $("vue-mesures");
const zone = $("mesures");

const GENRES_JETONS = { keyword: "mots-clés", identifier: "noms", number: "nombres",
  string: "chaînes", symbol: "symboles" };

let rendue = null;        // analyse valide dont les mesures sont affichées
let demande = 0;

function tuile(valeur, nom) {
  if (valeur === null || valeur === undefined) return "";
  return `<div class="chiffre"><span class="chiffre-valeur">${nombre(valeur)}</span>`
    + `<span class="chiffre-nom">${nom}</span></div>`;
}

/** `lignes` : [{ nom, valeur, aide, attributs }] déjà triées, la plus grande d'abord. */
function bloc(titre, unite, lignes) {
  if (!lignes.length) return "";
  const maximum = Math.max(1, ...lignes.map((ligne) => ligne.valeur));
  let html = `<section><div class="bloc-titre">${titre}<small>${unite}</small></div><table class="barres"><tbody>`;
  for (const ligne of lignes) {
    const largeur = Math.max(1, Math.round((ligne.valeur / maximum) * 100));
    html += `<tr title="${echapper(ligne.aide)}">`
      + `<td class="nom${ligne.attributs ? " lien" : ""}"${ligne.attributs || ""}>${echapper(ligne.nom)}</td>`
      + `<td class="piste"><span class="barre" style="width:${largeur}%"></span></td>`
      + `<td class="valeur">${nombre(ligne.valeur)}</td></tr>`;
  }
  return html + `</tbody></table></section>`;
}

function nomFonction(f) {
  if (f.genre === "script") return "script, niveau principal";
  return f.nom || `fonction anonyme, ligne ${f.ligne}`;
}

async function dessiner() {
  if (!estVisible("mesures")) return;
  const source = etat.valide;
  if (!source) {
    vue.classList.remove("perime");
    rendue = null;
    zone.innerHTML = rienEncore() ? "" : `<div class="vide"><strong>Pas encore de mesures</strong>`
      + `Les mesures sont calculées dès que la syntaxe du script est valide.</div>`;
    return;
  }
  vue.classList.toggle("perime", !frais());
  if (rendue === source) return;
  // Les mesures d'un gros fichier coûtent un parcours complet : elles ne sont
  // demandées que lorsque cet onglet est visible.
  const numero = ++demande;
  let reponse;
  try {
    reponse = await api("mesures", { doc: source.doc });
  } catch (erreur) {
    if (numero !== demande) return;
    if (erreur.statut !== 410) annoncer(erreur.message);
    else if (!frais() && rendue === null) {
      zone.innerHTML = `<div class="vide"><strong>Mesures en attente</strong>`
        + `Elles seront calculées dès que l'erreur signalée sous l'éditeur sera corrigée.</div>`;
    }
    return;
  }
  if (numero !== demande || source !== etat.valide) return;
  rendue = source;
  const m = reponse.mesures;
  let html = `<div class="mesures-chiffres">`
    + tuile(m.lines.total, m.lines.total > 1 ? "lignes" : "ligne")
    + tuile(m.lines.code, "de code")
    + tuile(m.lines.comment_only, "de commentaire")
    + tuile(m.lines.blank, m.lines.blank > 1 ? "vides" : "vide")
    + tuile(m.functions.total, m.functions.total > 1 ? "fonctions" : "fonction")
    + tuile(m.calls.total, m.calls.total > 1 ? "appels" : "appel")
    + tuile(m.tokens ? m.tokens.total : null, "jetons")
    + tuile(m.nodes.total, "nœuds")
    + tuile(m.nodes.depth, "niveaux dans l'arbre")
    + tuile(m.strings.total, m.strings.total > 1 ? "chaînes" : "chaîne")
    + `</div>`;

  const complexes = source.fonctions
    .filter((f) => f.genre !== "script" || source.fonctions.length === 1)
    .sort((x, y) => y.complexity - x.complexity || x.a - y.a)
    .slice(0, 12);
  html += bloc("Fonctions les plus complexes", "complexité", complexes.map((f) => ({
    nom: nomFonction(f), valeur: f.complexity,
    aide: `${nomFonction(f)} : complexité ${f.complexity}, ligne ${f.ligne}. Cliquez pour voir ses décisions.`,
    attributs: ` data-fonction="${f.id}"`,
  })));
  const longues = source.fonctions
    .filter((f) => f.genre !== "script")
    .sort((x, y) => y.lignes - x.lignes || x.a - y.a)
    .slice(0, 12);
  html += bloc("Fonctions les plus longues", "lignes", longues.map((f) => ({
    nom: nomFonction(f), valeur: f.lignes,
    aide: `${nomFonction(f)} : ${f.lignes} lignes à partir de la ligne ${f.ligne}. Cliquez pour voir ses décisions.`,
    attributs: ` data-fonction="${f.id}"`,
  })));
  html += bloc("Appels les plus fréquents", "appels", m.calls.most_frequent.map((appel) => ({
    nom: appel.name, valeur: appel.count, aide: `${appel.name} : appelée ${appel.count} fois`,
  })));
  html += bloc("Nœuds de l'arbre les plus nombreux", "nœuds",
    Object.entries(m.nodes.types).slice(0, 12).map(([type, total]) => ({
      nom: type, valeur: total, aide: `${type} : ${nombre(total)} sur ${nombre(m.nodes.total)} nœuds`,
    })));
  if (m.tokens) {
    html += bloc("Jetons par genre", "jetons",
      Object.entries(m.tokens.kinds).sort((x, y) => y[1] - x[1]).map(([genre, total]) => ({
        nom: GENRES_JETONS[genre] || genre, valeur: total,
        aide: `${GENRES_JETONS[genre] || genre} : ${nombre(total)} sur ${nombre(m.tokens.total)} jetons`,
      })));
  }
  const ms = reponse.ms || {};
  html += `<p class="mesures-note">Analyse en ${duree((ms.lexique || 0) + (ms.syntaxe || 0))}`
    + ` (découpage ${duree(ms.lexique || 0)}, syntaxe ${duree(ms.syntaxe || 0)}).</p>`;
  zone.innerHTML = html;
}

zone.addEventListener("click", (evenement) => {
  const cellule = evenement.target.closest(".lien");
  if (!cellule || !frais()) return;
  if (cellule.dataset.fonction !== undefined) {
    const id = Number(cellule.dataset.fonction);
    const f = etat.valide.fonctions.find((candidate) => candidate.id === id);
    if (!f) return;
    editeur.marquer("sel", f.a, Math.min(f.b, editeur.finDeLigne(editeur.ligneDe(f.a))));
    editeur.montrer(f.a, "haut");
    editeur.poserCurseur(f.a, f.a, { source: "mesures" });
    ouvrir("decisions");
    emettre("fonction", { id, source: "mesures" });
  }
});

sur("analyse", dessiner);
sur("vue", ({ id }) => {
  if (id === "mesures") dessiner();
});
