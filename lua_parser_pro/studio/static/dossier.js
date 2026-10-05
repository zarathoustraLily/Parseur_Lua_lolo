// Le volet « Dossier » : les scripts d'un dossier, leur vérification en lot,
// et la fenêtre qui permet de choisir ce dossier. Rien n'est écrit sur le disque.

import { $, etat, sur, emettre, api, annoncer, echapper, octets, nombre, pluriel, duree, memoire } from "./noyau.js";

const atelier = $("atelier");
const boutonVolet = $("btn-explorateur");
const racineTexte = $("dossier-racine");
const outils = $("explorateur-outils");
const accueil = $("explorateur-vide");
const liste = $("liste-fichiers");
const boutonVerifier = $("btn-verifier");
const avancement = $("avancement");
const barre = $("avancement-barre");
const texteAvancement = $("avancement-texte");
const filtreNom = $("filtre-fichiers");
const filtreErreurs = $("filtre-erreurs");

const dialogue = $("dialogue-dossier");
const champChemin = $("dossier-chemin");
const zoneLecteurs = $("dossier-lecteurs");
const zoneDossiers = $("dossier-liste");
const noteDialogue = $("dossier-note");
const boutonOuvrir = $("dossier-ouvrir");

const H_FICHIER = 26;
const H_ERREUR = 46;
const GAUCHE_A_DROITE = String.fromCharCode(0x200e);

let racine = null;
let fichiers = [];          // { chemin, octets, etat: "" | "ok" | "erreur", erreur, minuscules }
let rangs = new Map();      // chemin -> rang dans `fichiers`
let visibles = [];          // rangs retenus par les filtres
let hauts = new Float64Array(1);
let actif = null;
let tache = null;
let demande = 0;
let cheminDialogue = null;

// ---------------------------------------------------------------------- volet
export function montrerVolet(visible) {
  atelier.classList.toggle("sans-explorateur", !visible);
  boutonVolet.setAttribute("aria-pressed", String(visible));
}

boutonVolet.addEventListener("click", () => {
  montrerVolet(atelier.classList.contains("sans-explorateur"));
});

// ---------------------------------------------------------------------- liste
function htmlFichier(j) {
  const rang = visibles[j];
  const f = fichiers[rang];
  const coupe = f.chemin.lastIndexOf("/");
  const etatTexte = f.etat === "ok" ? "syntaxe valide" : f.etat === "erreur" ? "erreur" : "pas encore vérifié";
  return `<div class="fichier${f.chemin === actif ? " actif" : ""}" role="option" tabindex="-1" data-i="${rang}"`
    + ` data-etat="${f.etat}" style="top:${hauts[j]}px" title="${echapper(f.chemin)} : ${etatTexte}">`
    + `<span class="fichier-etat"></span>`
    + `<span class="fichier-nom"><i>${echapper(f.chemin.slice(0, coupe + 1))}</i>`
    + `<b>${echapper(f.chemin.slice(coupe + 1))}</b></span>`
    + `<span class="fichier-taille">${octets(f.octets)}</span>`
    + (f.erreur ? `<span class="fichier-erreur">ligne ${f.erreur.ligne} : ${echapper(f.erreur.message_fr)}</span>` : "")
    + `</div>`;
}

function dessiner() {
  demande = 0;
  if (!racine) return;
  if (!visibles.length) {
    let message = `<strong>Aucun fichier .lua</strong>Ce dossier et ses sous-dossiers n'en contiennent pas.`;
    if (fichiers.length) {
      message = filtreErreurs.checked && !filtreNom.value.trim()
        ? `<strong>Aucune erreur à montrer</strong>Lancez une vérification, ou décochez « Erreurs seulement ».`
        : `<strong>Aucun fichier ne correspond</strong>Modifiez le filtre pour retrouver vos fichiers.`;
    }
    liste.innerHTML = `<div class="vide">${message}</div>`;
    return;
  }
  const haut = liste.scrollTop;
  const bas = haut + (liste.clientHeight || 600) + 160;
  let debut = 0;
  let fin = visibles.length;
  while (debut < fin) {                         // première ligne visible
    const milieu = (debut + fin) >> 1;
    if (hauts[milieu + 1] <= haut - 160) debut = milieu + 1;
    else fin = milieu;
  }
  let html = `<div class="fichiers-pile" style="height:${hauts[visibles.length]}px">`;
  for (let j = debut; j < visibles.length && hauts[j] < bas; j++) html += htmlFichier(j);
  liste.innerHTML = html + `</div>`;
}

function planifier() {
  if (!demande) demande = requestAnimationFrame(dessiner);
}

function filtrer() {
  const cherche = filtreNom.value.trim().toLowerCase();
  const erreurs = filtreErreurs.checked;
  visibles = [];
  for (let rang = 0; rang < fichiers.length; rang++) {
    const f = fichiers[rang];
    if (erreurs && f.etat !== "erreur") continue;
    if (cherche && !f.minuscules.includes(cherche)) continue;
    visibles.push(rang);
  }
  hauts = new Float64Array(visibles.length + 1);
  let y = 0;
  for (let j = 0; j < visibles.length; j++) {
    hauts[j] = y;
    y += fichiers[visibles[j]].erreur ? H_ERREUR : H_FICHIER;
  }
  hauts[visibles.length] = y;
  planifier();
}

async function ouvrirFichier(rang) {
  const f = fichiers[rang];
  if (!f) return;
  let reponse;
  try {
    reponse = await api("fichier", { racine, chemin: f.chemin });
  } catch (erreur) {
    annoncer(erreur.message);
    return;
  }
  const utf8 = reponse.encodage.toLowerCase().startsWith("utf");
  emettre("charger", {
    texte: reponse.texte,
    nom: reponse.chemin,
    origine: { racine, chemin: reponse.chemin },
    encodage: utf8 ? "utf-8" : "latin-1",
    detail: `${utf8 ? "UTF-8" : "Latin-1"}, ${octets(reponse.octets)}${reponse.tronque ? ", début du fichier seulement" : ""}`,
    allerErreur: f.etat === "erreur",
  });
}

/** Ouvre dans l'éditeur le fichier `chemin` (relatif au dossier ouvert). */
export function ouvrirChemin(chemin) {
  const rang = rangs.get(chemin.replace(/\\/g, "/"));
  if (rang === undefined) return false;
  ouvrirFichier(rang);
  return true;
}

export const premierFichier = () => (fichiers.length ? fichiers[0].chemin : null);

liste.addEventListener("click", (evenement) => {
  const element = evenement.target.closest(".fichier");
  if (element) ouvrirFichier(Number(element.dataset.i));
});
liste.addEventListener("keydown", (evenement) => {
  if (evenement.key !== "ArrowDown" && evenement.key !== "ArrowUp") return;
  if (!visibles.length) return;
  evenement.preventDefault();
  const position = visibles.indexOf(rangs.get(actif));
  const suivant = Math.min(visibles.length - 1, Math.max(0, position + (evenement.key === "ArrowDown" ? 1 : -1)));
  if (hauts[suivant] < liste.scrollTop) liste.scrollTop = hauts[suivant];
  else if (hauts[suivant + 1] > liste.scrollTop + liste.clientHeight) {
    liste.scrollTop = hauts[suivant + 1] - liste.clientHeight;
  }
  ouvrirFichier(visibles[suivant]);
});
liste.addEventListener("scroll", planifier, { passive: true });
new ResizeObserver(planifier).observe(liste);
filtreNom.addEventListener("input", () => {
  liste.scrollTop = 0;
  filtrer();
});
filtreErreurs.addEventListener("change", () => {
  liste.scrollTop = 0;
  filtrer();
});

// --------------------------------------------------------------- vérification
function appliquer(suivi, rapport) {
  for (const resultat of rapport.nouveaux) {
    const rang = rangs.get(resultat.chemin);
    if (rang === undefined) continue;
    fichiers[rang].etat = resultat.ok ? "ok" : "erreur";
    fichiers[rang].erreur = resultat.erreur;
  }
  suivi.recus += rapport.nouveaux.length;
  const fraction = rapport.total ? rapport.faits / rapport.total : 1;
  barre.style.width = `${Math.round(fraction * 100)}%`;
  texteAvancement.textContent = `${nombre(rapport.faits)} sur ${nombre(rapport.total)}, `
    + pluriel(rapport.erreurs, "erreur", "erreurs");
  filtrer();
  emettre("verification", { fraction, termine: rapport.termine });
}

async function verifier() {
  if (tache) {                        // le même bouton arrête la vérification en cours
    tache.arret = true;
    return;
  }
  if (!racine) return;
  let rapport;
  try {
    rapport = await api("verifier", { racine });
  } catch (erreur) {
    annoncer(erreur.message);
    return;
  }
  const suivi = { id: rapport.tache, recus: 0, arret: false };
  tache = suivi;
  for (const f of fichiers) {
    f.etat = "";
    f.erreur = null;
  }
  boutonVerifier.textContent = "Arrêter la vérification";
  avancement.hidden = false;
  appliquer(suivi, rapport);
  while (!rapport.termine && tache === suivi) {
    await new Promise((resoudre) => setTimeout(resoudre, 180));
    try {
      rapport = await api("tache", { tache: suivi.id, depuis: suivi.recus, arreter: suivi.arret });
    } catch (erreur) {
      annoncer(erreur.message);
      break;
    }
    if (tache !== suivi) return;      // un autre dossier a été ouvert entre-temps
    appliquer(suivi, rapport);
  }
  if (tache !== suivi) return;
  tache = null;
  boutonVerifier.textContent = "Vérifier tous les fichiers";
  emettre("verification", { fraction: 1, termine: true });
  if (!rapport.termine) return;
  const bilan = `${pluriel(rapport.faits, "fichier vérifié", "fichiers vérifiés")} en ${duree(rapport.duree * 1000)} : `
    + `${pluriel(rapport.valides, "valide", "valides")}, ${pluriel(rapport.erreurs, "avec erreur", "avec erreurs")}`;
  const debut = rapport.arretee && rapport.faits < rapport.total ? "Vérification arrêtée. " : "";
  annoncer(debut + bilan, rapport.erreurs ? {
    duree: 10000,
    action: {
      libelle: "Voir les erreurs",
      fonction: () => {
        filtreErreurs.checked = true;
        liste.scrollTop = 0;
        filtrer();
      },
    },
  } : {});
}

boutonVerifier.addEventListener("click", verifier);

// -------------------------------------------------------------------- dossier
/** Liste les fichiers .lua de `chemin` dans le volet. */
export async function ouvrirDossier(chemin) {
  const reponse = await api("dossier", { chemin });
  racine = reponse.racine;
  fichiers = reponse.fichiers.map((f) => ({
    chemin: f.chemin, octets: f.octets, etat: "", erreur: null, minuscules: f.chemin.toLowerCase(),
  }));
  rangs = new Map(fichiers.map((f, rang) => [f.chemin, rang]));
  tache = null;
  actif = etat.origine && etat.origine.racine === racine ? etat.origine.chemin : null;
  memoire.ecrire("dossier", racine);
  racineTexte.textContent = GAUCHE_A_DROITE + racine;
  racineTexte.title = racine;
  accueil.hidden = true;
  outils.hidden = false;
  avancement.hidden = true;
  boutonVerifier.textContent = "Vérifier tous les fichiers";
  boutonVerifier.disabled = fichiers.length === 0;
  filtreNom.value = "";
  filtreErreurs.checked = false;
  liste.scrollTop = 0;
  montrerVolet(true);
  filtrer();
  emettre("verification", { fraction: 1, termine: true });
  annoncer(pluriel(fichiers.length, "fichier .lua trouvé", "fichiers .lua trouvés")
    + ` (${octets(reponse.octets)})` + (reponse.tronque ? ". La liste s'arrête aux 50 000 premiers." : ""));
  return reponse;
}

// ------------------------------------------------------------------- dialogue
const joindre = (base, nom, separateur) => (base.endsWith(separateur) ? base + nom : base + separateur + nom);

async function parcourir(chemin) {
  noteDialogue.textContent = "Lecture du dossier…";
  let reponse;
  try {
    reponse = await api("dossiers", { chemin });
  } catch (erreur) {
    noteDialogue.textContent = erreur.message;
    return false;
  }
  cheminDialogue = reponse.chemin;
  champChemin.value = reponse.chemin;
  zoneLecteurs.hidden = reponse.lecteurs.length === 0;
  zoneLecteurs.innerHTML = reponse.lecteurs.map((lecteur) =>
    `<button class="bouton" type="button" data-chemin="${echapper(lecteur)}">${echapper(lecteur)}</button>`).join("");
  let html = reponse.parent
    ? `<button type="button" class="parent" data-chemin="${echapper(reponse.parent)}">Dossier parent</button>` : "";
  for (const nom of reponse.dossiers) {
    html += `<button type="button" data-chemin="${echapper(joindre(reponse.chemin, nom, reponse.separateur))}">`
      + `${echapper(nom)}</button>`;
  }
  if (!reponse.dossiers.length) html += `<p class="dialogue-note">Ce dossier n'a pas de sous-dossier.</p>`;
  zoneDossiers.innerHTML = html;
  zoneDossiers.scrollTop = 0;
  noteDialogue.textContent = reponse.lua
    ? `${pluriel(reponse.lua, "fichier .lua", "fichiers .lua")} directement dans ce dossier.`
    : "Aucun fichier .lua directement dans ce dossier ; ses sous-dossiers seront aussi explorés.";
  boutonOuvrir.disabled = false;
  return true;
}

export async function ouvrirDialogue() {
  if (!dialogue.open) dialogue.showModal();
  const config = etat.config || {};
  const depart = racine || memoire.lire("dossier") || config.dossier_initial || config.dossier || "";
  if (!(await parcourir(depart)) && depart !== (config.dossier || "")) await parcourir(config.dossier || "");
  champChemin.focus();
  champChemin.select();
}

function suivreClic(evenement) {
  const bouton = evenement.target.closest("button[data-chemin]");
  if (bouton) parcourir(bouton.dataset.chemin);
}
zoneDossiers.addEventListener("click", suivreClic);
zoneLecteurs.addEventListener("click", suivreClic);

$("dossier-aller").addEventListener("click", () => parcourir(champChemin.value.trim()));
champChemin.addEventListener("keydown", (evenement) => {
  if (evenement.key !== "Enter") return;
  evenement.preventDefault();          // Entrée explore le chemin saisi au lieu de fermer la fenêtre
  parcourir(champChemin.value.trim());
});

boutonOuvrir.addEventListener("click", async () => {
  const chemin = champChemin.value.trim() || cheminDialogue;
  if (!chemin) return;
  boutonOuvrir.disabled = true;
  noteDialogue.textContent = "Recherche des fichiers .lua…";
  try {
    await ouvrirDossier(chemin);
    dialogue.close();
  } catch (erreur) {
    noteDialogue.textContent = erreur.message;
  }
  boutonOuvrir.disabled = false;
});

sur("document", () => {
  actif = etat.origine && etat.origine.racine === racine ? etat.origine.chemin : null;
  planifier();
});
