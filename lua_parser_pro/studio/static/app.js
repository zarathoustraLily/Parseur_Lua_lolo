// Point d'entrée du Studio : analyse en direct du texte, en-tête, menus,
// ouverture de fichiers, export, thème et raccourcis.

import {
  $, etat, sur, emettre, api, annoncer, memoire, borne, nombre, pluriel, duree, octets,
} from "./noyau.js";
import * as editeur from "./editeur.js";
import * as volets from "./volets.js";
import * as dossier from "./dossier.js";
import "./arbre.js";
import "./plan.js";
import "./decisions.js";
import "./jetons.js";
import "./mesures.js";

const app = $("app");
const atelier = $("atelier");
const libelleEtat = $("etat");

// ----------------------------------------------------------------------- lune
// Pleine quand la syntaxe est valide, éclipsée (par la couleur) en cas d'erreur ;
// pendant une vérification de dossier, elle croît avec l'avancement.
const traceLune = $("lune-clair");
const mouvementReduit = window.matchMedia("(prefers-reduced-motion: reduce)");
let phase = 1;
let phaseCible = 1;
let animation = 0;

function dessinerLune(f) {
  const r = 13;
  const c = 20;
  const rx = (r * Math.abs(1 - 2 * f)).toFixed(2);
  traceLune.setAttribute("d",
    `M${c} ${c - r}A${r} ${r} 0 0 1 ${c} ${c + r}A${rx} ${r} 0 0 ${f < 0.5 ? 0 : 1} ${c} ${c - r}Z`);
}

function pasLune() {
  phase += (phaseCible - phase) * 0.2;
  if (Math.abs(phaseCible - phase) < 0.004) phase = phaseCible;
  dessinerLune(phase);
  animation = phase === phaseCible ? 0 : requestAnimationFrame(pasLune);
}

function luneVers(f) {
  phaseCible = borne(f, 0, 1);
  if (mouvementReduit.matches) {
    phase = phaseCible;
    dessinerLune(phase);
  } else if (!animation) {
    animation = requestAnimationFrame(pasLune);
  }
}

// ----------------------------------------------------------------------- état
let verification = null;      // avancement (0 à 1) d'une vérification de dossier, sinon null
let attenteLongue = false;

function majEtat() {
  if (verification !== null) {
    app.dataset.etat = "analyse";
    libelleEtat.textContent = "Vérification du dossier";
    luneVers(Math.max(0.03, verification));
    return;
  }
  const analyse = etat.analyse;
  if (attenteLongue || !analyse) {
    app.dataset.etat = "analyse";
    libelleEtat.textContent = analyse ? "Analyse en cours" : "Prêt";
    luneVers(analyse ? 0.5 : 1);
    return;
  }
  luneVers(1);
  if (analyse.ok) {
    app.dataset.etat = "valide";
    libelleEtat.textContent = "Syntaxe valide";
  } else {
    app.dataset.etat = "erreur";
    libelleEtat.textContent = `Erreur ligne ${nombre(analyse.erreur.ligne)}`;
  }
}

function majEntete() {
  $("document-nom").textContent = etat.nom;
  const details = [];
  if (etat.detail) details.push(etat.detail);
  if (etat.modifie) details.push(etat.origine ? "modifié ici, le fichier du disque reste intact" : "modifié");
  $("document-detail").textContent = details.join(", ");
  document.title = `${etat.nom} – Studio du parseur Lua`;
}

function majPied() {
  const analyse = etat.analyse;
  const texte = editeur.lire();
  // Un saut de ligne final ne commence pas une ligne de plus.
  const lignes = texte ? editeur.nombreDeLignes() - (texte.endsWith("\n") ? 1 : 0) : 0;
  const morceaux = [pluriel(lignes, "ligne", "lignes")];
  if (analyse && etat.versionAnalyse === etat.version) {
    if (analyse.jetons !== null) morceaux.push(pluriel(analyse.jetons, "jeton", "jetons"));
    morceaux.push(`analysé en ${duree(analyse.ms.lexique + analyse.ms.syntaxe)}`);
  }
  $("etat-mesures").textContent = morceaux.join(", ");
}

sur("curseur", (curseur) => {
  let texte = `Ligne ${nombre(curseur.ligne)}, colonne ${nombre(curseur.colonne)}`;
  if (curseur.fin > curseur.debut) {
    texte += `, ${pluriel(curseur.fin - curseur.debut, "caractère sélectionné", "caractères sélectionnés")}`;
  }
  $("etat-curseur").textContent = texte;
});

// ----------------------------------------------------------------- diagnostic
function montrerDiagnostic(erreur) {
  const boite = $("diagnostic");
  if (!erreur) {
    boite.hidden = true;
    editeur.demarquer("err");
    return;
  }
  $("diagnostic-titre").textContent = erreur.titre;
  $("diagnostic-message").textContent = erreur.message_fr;
  const origine = $("diagnostic-origine");
  origine.textContent = `ligne ${nombre(erreur.ligne)}, colonne ${nombre(erreur.colonne)}`;
  origine.title = `${erreur.code} : ${erreur.message}`;
  boite.hidden = false;
  // Une erreur sans largeur (fin de fichier, mot manquant) souligne le caractère voisin.
  const texte = editeur.lire();
  let a = erreur.a;
  let b = erreur.b;
  if (b <= a) {
    if (a < texte.length && texte[a] !== "\n") {
      b = a + 1;
    } else {
      while (a > 0 && /\s/.test(texte[a - 1])) a--;
      b = a;
      a = Math.max(0, a - 1);
    }
  }
  editeur.marquer("err", a, b);
}

function allerErreur() {
  const analyse = etat.analyse;
  if (!analyse || !analyse.erreur || etat.versionAnalyse !== etat.version) return;
  editeur.montrer(analyse.erreur.a);
  editeur.poserCurseur(analyse.erreur.a, analyse.erreur.a, { focus: true });
}

$("btn-aller-erreur").addEventListener("click", allerErreur);

// -------------------------------------------------------------------- analyse
let enVol = false;
let aRefaire = false;
let minuterie = 0;
let viserErreur = false;

function delai() {
  const taille = editeur.lire().length;
  return taille < 60_000 ? 160 : taille < 600_000 ? 380 : 800;
}

function planifier(ms) {
  clearTimeout(minuterie);
  minuterie = setTimeout(analyser, ms);
}

function appliquer(reponse, texte, version) {
  const nouveau = etat.nouveau;
  etat.nouveau = false;
  etat.analyse = reponse;
  etat.versionAnalyse = version;
  etat.texteAnalyse = texte;
  if (reponse.ok) etat.valide = { ...reponse, texte, version };
  montrerDiagnostic(reponse.erreur);
  majEtat();
  majPied();
  emettre("analyse", { nouveau });
  if (nouveau && viserErreur && reponse.erreur) allerErreur();
  viserErreur = false;
}

async function analyser() {
  clearTimeout(minuterie);
  if (enVol) {
    aRefaire = true;
    return;
  }
  enVol = true;
  aRefaire = false;
  const version = etat.version;
  const texte = editeur.lire();
  const sablier = setTimeout(() => {
    attenteLongue = true;
    majEtat();
  }, 350);
  let reponse = null;
  let echec = null;
  try {
    reponse = await api("analyse", { source: texte, nom: etat.nom, encodage: etat.encodage });
  } catch (erreur) {
    echec = erreur;
  }
  clearTimeout(sablier);
  attenteLongue = false;
  enVol = false;
  if (version === etat.version) {
    if (reponse) {
      appliquer(reponse, texte, version);
    } else {
      majEtat();
      annoncer(echec.message, { duree: 9000 });
    }
  }
  if (aRefaire) analyser();
}

sur("texte", ({ cause }) => {
  if (cause === "saisie") {
    if (!etat.modifie) {
      etat.modifie = true;
      majEntete();
    }
    planifier(delai());
  } else {
    planifier(0);
  }
  majPied();
});

// ------------------------------------------------------------------ documents
function charger({ texte, nom, origine = null, detail = "", encodage = "utf-8",
  allerErreur: viser = false, reprise = false }) {
  const ancien = etat.modifie && !reprise
    ? { texte: editeur.lire(), nom: etat.nom, origine: etat.origine, detail: etat.detail, encodage: etat.encodage }
    : null;
  etat.nom = nom;
  etat.origine = origine;
  etat.detail = detail;
  etat.encodage = encodage;
  etat.modifie = reprise;
  etat.nouveau = true;
  etat.valide = null;
  viserErreur = viser;
  editeur.definirTexte(texte);
  majEntete();
  emettre("document");
  if (!editeur.estColore()) {
    annoncer("Fichier très volumineux : il est analysé normalement, mais affiché sans couleurs.");
  }
  if (ancien) {
    annoncer(`Le texte modifié de ${ancien.nom} a laissé la place à ${nom}.`, {
      duree: 12000,
      action: { libelle: "Reprendre mon texte", fonction: () => charger({ ...ancien, reprise: true }) },
    });
  }
}

sur("charger", charger);

async function chargerExemple(nom) {
  try {
    const reponse = await api("exemple", { nom });
    charger({ texte: reponse.texte, nom: reponse.nom, detail: "exemple" });
  } catch (erreur) {
    annoncer(erreur.message);
  }
}

async function lireFichier(fichier) {
  if (fichier.size > 40 * 1024 * 1024) {
    annoncer("Ce fichier dépasse 40 Mo. Ouvrez plutôt son dossier pour le vérifier.");
    return;
  }
  const contenu = new Uint8Array(await fichier.arrayBuffer());
  let texte;
  let encodage = "utf-8";
  try {
    texte = new TextDecoder("utf-8", { fatal: true }).decode(contenu);
  } catch {
    // Ancien fichier : Latin-1, un caractère par octet, pour que les chaînes gardent leurs octets.
    texte = "";
    for (let i = 0; i < contenu.length; i += 8192) {
      texte += String.fromCharCode.apply(null, contenu.subarray(i, i + 8192));
    }
    encodage = "latin-1";
  }
  charger({
    texte, nom: fichier.name, encodage,
    detail: `${encodage === "utf-8" ? "UTF-8" : "Latin-1"}, ${octets(fichier.size)}`,
  });
}

const selecteur = $("selecteur-fichier");
$("btn-fichier").addEventListener("click", () => selecteur.click());
selecteur.addEventListener("change", () => {
  if (selecteur.files.length) lireFichier(selecteur.files[0]);
  selecteur.value = "";
});

const depot = $("depot");
const avecFichiers = (evenement) => Boolean(evenement.dataTransfer)
  && Array.from(evenement.dataTransfer.types).includes("Files");
let survols = 0;
window.addEventListener("dragenter", (evenement) => {
  if (!avecFichiers(evenement)) return;
  evenement.preventDefault();
  survols++;
  depot.hidden = false;
});
window.addEventListener("dragover", (evenement) => {
  if (avecFichiers(evenement)) evenement.preventDefault();
});
window.addEventListener("dragleave", (evenement) => {
  if (!avecFichiers(evenement)) return;
  survols = Math.max(0, survols - 1);
  if (!survols) depot.hidden = true;
});
window.addEventListener("drop", (evenement) => {
  if (!avecFichiers(evenement)) return;
  evenement.preventDefault();
  survols = 0;
  depot.hidden = true;
  if (evenement.dataTransfer.files.length) lireFichier(evenement.dataTransfer.files[0]);
});

$("btn-dossier").addEventListener("click", dossier.ouvrirDialogue);
$("btn-dossier-vide").addEventListener("click", dossier.ouvrirDialogue);

// ---------------------------------------------------------------------- menus
const fermetures = [];
const fermerMenus = () => fermetures.forEach((fermer) => fermer());

function menu(bouton, liste) {
  const fermer = () => {
    liste.hidden = true;
    bouton.setAttribute("aria-expanded", "false");
  };
  fermetures.push(fermer);
  bouton.addEventListener("click", (evenement) => {
    evenement.stopPropagation();
    const ouvrir = liste.hidden;
    fermerMenus();
    if (!ouvrir) return;
    liste.hidden = false;
    bouton.setAttribute("aria-expanded", "true");
    const premier = liste.querySelector("button");
    if (premier) premier.focus();
  });
  liste.addEventListener("keydown", (evenement) => {
    const elements = [...liste.querySelectorAll("button")];
    const rang = elements.indexOf(document.activeElement);
    if (evenement.key === "ArrowDown" || evenement.key === "ArrowUp") {
      evenement.preventDefault();
      const pas = evenement.key === "ArrowDown" ? 1 : -1;
      elements[(rang + pas + elements.length) % elements.length].focus();
    } else if (evenement.key === "Escape") {
      fermer();
      bouton.focus();
    }
  });
}

document.addEventListener("click", fermerMenus);

const EXEMPLES = {
  "combat.lua": "Résolution d'une attaque : tests, boucles et sorties",
  "demo.lua": "Tour de la syntaxe de Lua 5.4",
  "erreur.lua": "Un script fautif, pour voir un diagnostic",
};
const menuExemples = $("menu-exemples");
menu($("btn-exemples"), menuExemples);
menuExemples.addEventListener("click", (evenement) => {
  const bouton = evenement.target.closest("button[data-exemple]");
  if (bouton) chargerExemple(bouton.dataset.exemple);
});

function remplirExemples(noms) {
  menuExemples.replaceChildren();
  for (const nom of noms) {
    const bouton = document.createElement("button");
    bouton.type = "button";
    bouton.setAttribute("role", "menuitem");
    bouton.dataset.exemple = nom;
    bouton.textContent = EXEMPLES[nom] || nom;
    const fichier = document.createElement("small");
    fichier.textContent = nom;
    bouton.append(fichier);
    menuExemples.append(bouton);
  }
  $("btn-exemples").disabled = noms.length === 0;
}

// --------------------------------------------------------------------- export
// Le nom et le dossier de l'export se choisissent dans la fenêtre « Enregistrer sous »
// du système quand le navigateur l'offre aux pages web (Chrome, Edge, Opera). Ailleurs,
// le Studio demande le nom et le navigateur range le fichier dans ses téléchargements.
const dialogueExport = $("dialogue-export");
const champNomExport = $("export-nom");
let repondreExport = null;

const RESERVES = '\\/:*?"<>|';

/** Un nom de fichier valable partout : sans chemin ni caractère réservé, avec une extension. */
function nomDeFichier(saisie) {
  let nom = [...saisie].filter((c) => c >= " " && !RESERVES.includes(c)).join("").trim();
  while (nom.endsWith(".") || nom.endsWith(" ")) nom = nom.slice(0, -1);
  if (!nom) return "";
  return /\.[A-Za-z0-9]{1,8}$/.test(nom) ? nom : `${nom}.json`;
}

function telecharger(texte, nom) {
  const adresse = URL.createObjectURL(new Blob([texte], { type: "application/json" }));
  const lien = document.createElement("a");
  lien.href = adresse;
  lien.download = nom;
  document.body.append(lien);
  lien.click();
  lien.remove();
  setTimeout(() => URL.revokeObjectURL(adresse), 4000);
}

/** Fenêtre « Enregistrer sous » du système. Rend `null` si elle est fermée sans choisir. */
async function choisirDestination(propose) {
  let fichier;
  try {
    fichier = await window.showSaveFilePicker({
      id: "lua-studio-export",          // le navigateur rouvre la fenêtre dans le dernier dossier choisi
      startIn: "documents",
      suggestedName: propose,
      types: [{ description: "Fichier JSON", accept: { "application/json": [".json"] } }],
    });
  } catch (erreur) {
    if (erreur.name === "AbortError") return null;
    throw erreur;
  }
  return {
    nom: fichier.name,
    lieu: "",
    async ecrire(texte) {
      const flux = await fichier.createWritable();
      try {
        await flux.write(texte);
        await flux.close();
      } catch (erreur) {
        await flux.abort().catch(() => {});
        throw erreur;
      }
    },
  };
}

/** Demande le nom dans le Studio ; le navigateur choisit le dossier. Rend `null` si on annule. */
function demanderNom(propose) {
  champNomExport.value = propose;
  dialogueExport.returnValue = "";
  dialogueExport.showModal();
  champNomExport.focus();
  // Le nom est sélectionné sans ses extensions : taper le remplace et garde « .ast.json ».
  champNomExport.setSelectionRange(0, propose.replace(/(\.[a-z]+)?\.json$/i, "").length);
  return new Promise((resoudre) => {
    repondreExport = resoudre;
  });
}

$("export-formulaire").addEventListener("submit", (evenement) => {
  if (nomDeFichier(champNomExport.value)) return;
  evenement.preventDefault();           // rien d'utilisable dans le nom : la fenêtre reste ouverte
  champNomExport.value = "";
  champNomExport.reportValidity();
});
$("export-annuler").addEventListener("click", () => dialogueExport.close("annuler"));
dialogueExport.addEventListener("close", () => {
  const repondre = repondreExport;
  repondreExport = null;
  if (!repondre) return;
  const nom = dialogueExport.returnValue === "enregistrer" ? nomDeFichier(champNomExport.value) : "";
  repondre(nom ? {
    nom,
    lieu: " dans le dossier de téléchargements du navigateur",
    ecrire: (texte) => telecharger(texte, nom),
  } : null);
});

async function exporter(genre) {
  const analyse = etat.analyse;
  if (!analyse || etat.versionAnalyse !== etat.version) {
    annoncer("L'analyse est en cours : réessayez dans un instant.");
    return;
  }
  const jetons = genre === "jetons";
  // Vérifié avant d'ouvrir la fenêtre : on ne fait pas choisir un fichier pour rien.
  if (jetons ? analyse.jetons === null : !analyse.ok) {
    annoncer(jetons ? "Aucun jeton à exporter." : "Aucun arbre à exporter : la syntaxe est invalide.");
    return;
  }
  const base = etat.nom.split("/").pop().replace(/\.lua$/i, "") || "script";
  const propose = `${base}.${jetons ? "tokens" : "ast"}.json`;
  let destination = null;
  let demande = !window.showSaveFilePicker;
  if (!demande) {
    try {
      destination = await choisirDestination(propose);
    } catch {
      demande = true;                   // fenêtre du système refusée : on demande le nom ici
    }
  }
  if (demande) destination = await demanderNom(propose);
  if (!destination) return;
  let json;
  try {
    const reponse = await api("export", {
      doc: analyse.doc, genre: jetons ? "jetons" : "arbre", compact: genre === "arbre-compact",
    });
    json = reponse.json;
  } catch (erreur) {
    annoncer(erreur.message);
    return;
  }
  try {
    await destination.ecrire(json);
  } catch (erreur) {
    annoncer(`L'export n'a pas pu être enregistré : ${erreur.message}`);
    return;
  }
  annoncer(`${destination.nom} enregistré${destination.lieu} (${octets(new Blob([json]).size)}).`);
}

const menuExporter = $("menu-exporter");
menu($("btn-exporter"), menuExporter);
menuExporter.addEventListener("click", (evenement) => {
  const bouton = evenement.target.closest("button[data-export]");
  if (bouton) exporter(bouton.dataset.export);
});

// ---------------------------------------------------------------------- thème
const boutonTheme = $("btn-theme");

function appliquerTheme(theme) {
  document.documentElement.dataset.theme = theme;
  boutonTheme.textContent = theme === "nuit" ? "Jour" : "Nuit";
  boutonTheme.title = theme === "nuit" ? "Passer au thème clair" : "Passer au thème sombre";
}

boutonTheme.addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "nuit" ? "jour" : "nuit";
  appliquerTheme(theme);
  memoire.ecrire("theme", theme);
});

// ------------------------------------------------------------------- poignées
const largeurs = {};

function poserLargeur(variable, pixels) {
  const valeur = borne(Math.round(pixels), 220, Math.max(240, atelier.clientWidth - 440));
  atelier.style.setProperty(variable, `${valeur}px`);
  largeurs[variable] = valeur;
}

function poignee(id, variable, mesurer, sensClavier) {
  const element = $(id);
  element.addEventListener("pointerdown", (evenement) => {
    evenement.preventDefault();
    element.setPointerCapture(evenement.pointerId);
    element.classList.add("tire");
    const bouger = (mouvement) => poserLargeur(variable, mesurer(mouvement.clientX));
    const finir = () => {
      element.classList.remove("tire");
      element.removeEventListener("pointermove", bouger);
      element.removeEventListener("pointerup", finir);
      element.removeEventListener("pointercancel", finir);
      memoire.ecrire("largeurs", largeurs);
    };
    element.addEventListener("pointermove", bouger);
    element.addEventListener("pointerup", finir);
    element.addEventListener("pointercancel", finir);
  });
  element.addEventListener("keydown", (evenement) => {
    const pas = evenement.key === "ArrowRight" ? 24 : evenement.key === "ArrowLeft" ? -24 : 0;
    if (!pas) return;
    evenement.preventDefault();
    const actuelle = largeurs[variable] || mesurer(element.getBoundingClientRect().left + 3);
    poserLargeur(variable, actuelle + pas * sensClavier);
    memoire.ecrire("largeurs", largeurs);
  });
}

poignee("poignee-explorateur", "--l-explorateur",
  (x) => x - atelier.getBoundingClientRect().left, 1);
poignee("poignee-inspecteur", "--l-inspecteur",
  (x) => $("inspecteur-a").getBoundingClientRect().right - x, -1);
poignee("poignee-inspecteur-b", "--l-inspecteur-b",
  (x) => atelier.getBoundingClientRect().right - x, -1);

function restaurerLargeurs() {
  const souvenir = memoire.lire("largeurs", {});
  for (const variable of ["--l-explorateur", "--l-inspecteur", "--l-inspecteur-b"]) {
    if (Number.isFinite(souvenir[variable])) poserLargeur(variable, souvenir[variable]);
  }
}

window.addEventListener("resize", () => {
  for (const [variable, valeur] of Object.entries(largeurs)) poserLargeur(variable, valeur);
});

// ----------------------------------------------------------------- raccourcis
document.addEventListener("keydown", (evenement) => {
  const commande = evenement.ctrlKey || evenement.metaKey;
  if (commande && !evenement.altKey && evenement.key.toLowerCase() === "o") {
    evenement.preventDefault();
    if (evenement.shiftKey) dossier.ouvrirDialogue();
    else selecteur.click();
  } else if (evenement.key === "F8") {
    evenement.preventDefault();
    allerErreur();
  } else if (commande && evenement.key === "Enter") {
    evenement.preventDefault();
    analyser();
  } else if (evenement.key === "Escape") {
    fermerMenus();
  }
});

sur("verification", ({ fraction, termine }) => {
  verification = termine ? null : fraction;
  majEtat();
});

// ------------------------------------------------------------------ démarrage
async function demarrer() {
  appliquerTheme(memoire.lire("theme") === "jour" ? "jour" : "nuit");
  dessinerLune(1);
  restaurerLargeurs();
  dossier.montrerVolet(false);
  volets.demarrer();
  majEntete();
  try {
    etat.config = await api("config");
  } catch (erreur) {
    annoncer(erreur.message, { duree: 30000 });
    return;
  }
  const config = etat.config;
  remplirExemples(config.exemples);
  if (config.dossier_initial) {
    try {
      await dossier.ouvrirDossier(config.dossier_initial);
      const fichier = config.fichier_initial || dossier.premierFichier();
      if (fichier && dossier.ouvrirChemin(fichier)) return;
      if (config.fichier_initial) {
        annoncer(`${config.fichier_initial} n'est pas un fichier .lua : il ne peut pas être ouvert ici.`);
      }
    } catch (erreur) {
      annoncer(erreur.message);
    }
  }
  const exemple = config.exemples.includes("combat.lua") ? "combat.lua" : config.exemples[0];
  if (exemple) await chargerExemple(exemple);
}

demarrer();
