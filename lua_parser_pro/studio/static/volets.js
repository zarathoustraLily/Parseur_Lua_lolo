// Les volets d'analyse et leurs onglets. Sur un écran très large, deux volets
// sont affichés côte à côte ; chaque vue n'apparaît que dans un volet à la fois.

import { $, emettre, memoire, nombre } from "./noyau.js";

const VUES = [
  { id: "decisions", nom: "Décisions" },
  { id: "plan", nom: "Plan" },
  { id: "arbre", nom: "Arbre" },
  { id: "mesures", nom: "Mesures" },
  { id: "jetons", nom: "Jetons" },
];
const SEUIL_LARGE = 2200;

const atelier = $("atelier");
const reserve = $("vues");
const volets = {
  a: { hote: $("hote-a"), onglets: document.querySelector('.onglets[data-volet="a"]'), vue: "decisions" },
  b: { hote: $("hote-b"), onglets: document.querySelector('.onglets[data-volet="b"]'), vue: "plan" },
};
const comptes = new Map();
let large = false;

const connue = (id) => VUES.some((vue) => vue.id === id);

export const estLarge = () => large;

export function estVisible(id) {
  return volets.a.vue === id || (large && volets.b.vue === id);
}

function placer() {
  const visibles = [];
  for (const { id } of VUES) {
    const element = $("vue-" + id);
    const volet = volets.a.vue === id ? volets.a : large && volets.b.vue === id ? volets.b : null;
    const cible = volet ? volet.hote : reserve;
    if (element.parentElement !== cible) {
      cible.append(element);
      if (volet) visibles.push(id);
    }
  }
  for (const volet of Object.values(volets)) {
    for (const onglet of volet.onglets.children) {
      const actif = onglet.dataset.vue === volet.vue;
      onglet.setAttribute("aria-selected", String(actif));
      onglet.tabIndex = actif ? 0 : -1;
    }
  }
  for (const id of visibles) emettre("vue", { id });
}

/** Affiche la vue `id` dans le volet `nom` (« a » ou « b »). */
export function choisir(nom, id) {
  const volet = volets[nom];
  const autre = volets[nom === "a" ? "b" : "a"];
  if (volet.vue === id) return;
  if (autre.vue === id) autre.vue = volet.vue;     // les deux volets échangent leurs vues
  volet.vue = id;
  memoire.ecrire("volets", { a: volets.a.vue, b: volets.b.vue });
  placer();
}

/** Rend la vue `id` visible si elle ne l'est pas déjà. */
export function ouvrir(id) {
  if (!estVisible(id)) choisir("a", id);
}

/** Petit nombre affiché à côté du nom d'un onglet (ou rien si `n` est nul). */
export function compte(id, n) {
  comptes.set(id, n);
  for (const volet of Object.values(volets)) {
    const marque = volet.onglets.querySelector(`[data-vue="${id}"] .onglet-compte`);
    if (marque) marque.textContent = n ? nombre(n) : "";
  }
}

function construire(nom) {
  const volet = volets[nom];
  for (const { id, nom: libelle } of VUES) {
    const onglet = document.createElement("button");
    onglet.type = "button";
    onglet.className = "onglet";
    onglet.setAttribute("role", "tab");
    onglet.setAttribute("aria-controls", "vue-" + id);
    onglet.dataset.vue = id;
    onglet.append(libelle);
    const marque = document.createElement("span");
    marque.className = "onglet-compte";
    onglet.append(marque);
    onglet.addEventListener("click", () => choisir(nom, id));
    volet.onglets.append(onglet);
  }
  volet.onglets.addEventListener("keydown", (evenement) => {
    const pas = evenement.key === "ArrowRight" ? 1 : evenement.key === "ArrowLeft" ? -1 : 0;
    if (!pas) return;
    evenement.preventDefault();
    const index = VUES.findIndex((vue) => vue.id === volet.vue);
    const suivante = VUES[(index + pas + VUES.length) % VUES.length].id;
    choisir(nom, suivante);
    volet.onglets.querySelector(`[data-vue="${suivante}"]`).focus();
  });
}

function mesurer() {
  const maintenant = window.innerWidth >= SEUIL_LARGE;
  if (maintenant === large) return;
  large = maintenant;
  atelier.classList.toggle("large", large);
  placer();
}

export function demarrer() {
  const souvenir = memoire.lire("volets");
  if (souvenir && connue(souvenir.a) && connue(souvenir.b) && souvenir.a !== souvenir.b) {
    volets.a.vue = souvenir.a;
    volets.b.vue = souvenir.b;
  }
  for (const { id } of VUES) $("vue-" + id).setAttribute("role", "tabpanel");
  construire("a");
  construire("b");
  large = window.innerWidth >= SEUIL_LARGE;
  atelier.classList.toggle("large", large);
  placer();
  window.addEventListener("resize", mesurer);
}
