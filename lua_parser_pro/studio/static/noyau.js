// Outils partagés par les modules du Studio : accès au serveur local, état
// commun, petit bus d'événements, mise en forme des nombres et annonces.

export const $ = (id) => document.getElementById(id);

const ECHAPPE = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" };
export const echapper = (texte) => String(texte).replace(/[&<>"]/g, (c) => ECHAPPE[c]);

const NOMBRE = new Intl.NumberFormat("fr-FR");
const DECIMAL = new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 1 });
export const nombre = (n) => NOMBRE.format(n);
export const decimal = (n) => DECIMAL.format(n);
export const pluriel = (n, un, plusieurs) => `${nombre(n)} ${n > 1 ? plusieurs : un}`;

export function octets(n) {
  if (n < 1024) return `${n} o`;
  if (n < 1048576) return `${decimal(n / 1024)} Ko`;
  return `${decimal(n / 1048576)} Mo`;
}

export function duree(ms) {
  if (ms < 1000) return `${decimal(ms)} ms`;
  return `${decimal(ms / 1000)} s`;
}

export const borne = (valeur, min, max) => Math.min(max, Math.max(min, valeur));

/** Texte ramené sur une ligne et coupé à `max` caractères. */
export function extrait(texte, a, b, max = 60) {
  const brut = texte.slice(a, Math.min(b, a + max * 4)).replace(/\s+/g, " ").trim();
  if (brut.length > max) return brut.slice(0, max - 1).trimEnd() + "…";
  return b - a > max * 4 ? brut + "…" : brut;
}

export function differer(fonction, delai) {
  let minuterie = 0;
  const appel = (...args) => {
    clearTimeout(minuterie);
    minuterie = setTimeout(() => fonction(...args), delai);
  };
  appel.annuler = () => clearTimeout(minuterie);
  return appel;
}

// ---------------------------------------------------------------- événements
const ecouteurs = new Map();

export function sur(nom, fonction) {
  if (!ecouteurs.has(nom)) ecouteurs.set(nom, []);
  ecouteurs.get(nom).push(fonction);
}

export function emettre(nom, detail) {
  for (const fonction of ecouteurs.get(nom) || []) {
    try {
      fonction(detail);
    } catch (erreur) {
      console.error(`[studio] ${nom}`, erreur);
    }
  }
}

// ----------------------------------------------------------------------- état
/** État commun. `version` change à chaque modification du texte. */
export const etat = {
  config: null,
  nom: "sans-titre.lua",
  origine: null,        // { racine, chemin } quand le texte vient d'un dossier ouvert
  detail: "",
  encodage: "utf-8",    // encodage du fichier d'origine : les chaînes gardent ainsi leurs octets
  modifie: false,
  nouveau: true,        // vrai jusqu'à la première analyse d'un texte tout juste chargé
  version: 0,
  analyse: null,        // dernière réponse du serveur, pour la version `versionAnalyse`
  versionAnalyse: -1,
  texteAnalyse: "",     // le texte que décrit `analyse`
  valide: null,         // dernière analyse sans erreur : { ...réponse, texte, version }
};

/** Vrai tant qu'aucune analyse n'est revenue : les vues restent vides plutôt que d'annoncer un manque. */
export const rienEncore = () => etat.analyse === null;

/** Vrai quand l'arbre affiché décrit exactement le texte de l'éditeur. */
export const frais = () => etat.valide !== null && etat.valide.version === etat.version;

// -------------------------------------------------------------------- serveur
export class ErreurStudio extends Error {
  constructor(message, statut) {
    super(message);
    this.statut = statut;
  }
}

export async function api(action, corps = {}) {
  let reponse;
  try {
    reponse = await fetch("/api/" + action, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Lua-Studio": "1" },
      body: JSON.stringify(corps),
    });
  } catch {
    throw new ErreurStudio(
      "Le Studio ne répond plus. Relancez-le, puis rechargez cette page.", 0);
  }
  let donnees = null;
  try {
    donnees = await reponse.json();
  } catch {
    donnees = null;
  }
  if (!reponse.ok) {
    throw new ErreurStudio((donnees && donnees.erreur) || `Erreur ${reponse.status}`, reponse.status);
  }
  return donnees;
}

// -------------------------------------------------------------------- mémoire
export const memoire = {
  lire(cle, defaut = null) {
    try {
      const brut = localStorage.getItem("lua-studio:" + cle);
      return brut === null ? defaut : JSON.parse(brut);
    } catch {
      return defaut;
    }
  },
  ecrire(cle, valeur) {
    try {
      localStorage.setItem("lua-studio:" + cle, JSON.stringify(valeur));
    } catch {
      // Stockage indisponible : le réglage vaudra pour cette session seulement.
    }
  },
};

// ------------------------------------------------------------------- annonces
/** Message bref en bas de page. `action` ajoute un bouton : { libelle, fonction }. */
export function annoncer(message, { action = null, duree: delai = 5200 } = {}) {
  const zone = $("annonces");
  for (const ancienne of [...zone.children]) {
    if (ancienne.firstChild.textContent === message) ancienne.remove();   // pas deux fois le même message
  }
  const boite = document.createElement("div");
  boite.className = "annonce";
  const texte = document.createElement("span");
  texte.textContent = message;
  boite.append(texte);
  const fermer = () => boite.remove();
  if (action) {
    const bouton = document.createElement("button");
    bouton.type = "button";
    bouton.className = "annonce-action";
    bouton.textContent = action.libelle;
    bouton.addEventListener("click", () => {
      fermer();
      action.fonction();
    });
    boite.append(bouton);
  }
  zone.append(boite);
  while (zone.children.length > 3) zone.firstElementChild.remove();
  setTimeout(fermer, delai);
}

// --------------------------------------------------------------------- polices
/** Résolue quand les deux polices sont chargées (ou après un court délai). */
export const policesPretes = (async () => {
  if (!document.fonts || !document.fonts.load) return;
  const attente = new Promise((resoudre) => setTimeout(resoudre, 1800));
  const chargement = Promise.all([
    document.fonts.load('13px "Atkinson Hyperlegible Mono"'),
    document.fonts.load('600 12px "Atkinson Hyperlegible Mono"'),
    document.fonts.load('12px "Atkinson Hyperlegible Next"'),
  ]).catch(() => null);
  await Promise.race([attente, chargement]);
})();

const mesures = new Map();

/** Largeur en pixels de `texte` dans la police CSS `police` (ex. '12px "…"'). */
export function largeurTexte(texte, police) {
  let contexte = mesures.get(police);
  if (!contexte) {
    contexte = document.createElement("canvas").getContext("2d");
    contexte.font = police;
    mesures.set(police, contexte);
  }
  return contexte.measureText(texte).width;
}

export function oublierMesures() {
  mesures.clear();
}
