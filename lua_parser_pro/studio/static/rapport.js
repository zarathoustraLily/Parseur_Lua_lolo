// Lecteur de l'export HTML des décisions : la liste des fonctions d'un script,
// l'organigramme ou l'arbre des décisions de chacune, son code, et des
// infobulles qui décrivent les fonctions. La page est autonome : report.py y
// réunit ce script, organigramme.js et les données de l'analyse (#donnees).

import { construire, estReplie, niveauComplexite, niveauDuPli, nomFonction } from "./organigramme.js";

const $ = (id) => document.getElementById(id);
const donnees = JSON.parse($("donnees").textContent);
const source = donnees.source;
const fonctions = donnees.fonctions;
const parId = new Map(fonctions.map((f) => [f.id, f]));

const liste = $("liste");
const filtre = $("filtre");
const tri = $("tri");
const toile = $("toile");
const arbre = $("arbre");
const corps = $("fiche-corps");
const panneauCode = $("code");
const defileCode = $("code-defile");
const texteCode = $("code-texte");
const numerosCode = $("code-numeros");
const marqueCode = $("code-marque");
const boutonCode = $("btn-code");
const bulle = $("infobulle");

const NOMBRE = new Intl.NumberFormat("fr-FR");
const nombre = (n) => NOMBRE.format(n);
const pluriel = (n, un, plusieurs) => `${nombre(n)} ${n > 1 ? plusieurs : un}`;
const borne = (valeur, min, max) => Math.min(max, Math.max(min, valeur));

let courante = null;        // fonction affichée
let vue = "organigramme";   // ou « arbre »
let niveauMax = Infinity;   // niveaux d'imbrication dessinés ; les corps plus profonds sont repliés
let bascules = new Set();   // corps dont l'état est l'inverse de celui que donne le niveau
let selection = null;       // { a, b } de l'étape choisie
let dessin = null;          // { largeur, hauteur } de l'organigramme affiché
let zoom = 1;
let ajuste = true;
let affichees = [];         // fonctions de la liste, dans l'ordre affiché

/** Un élément HTML. Les enfants sont des nœuds ou du texte, jamais du HTML. */
function el(nom, classe = "", ...enfants) {
  const element = document.createElement(nom);
  if (classe) element.className = classe;
  element.append(...enfants.filter((enfant) => enfant !== null && enfant !== undefined && enfant !== false));
  return element;
}

const replis = () => ({ niveauMax, bascules });

// ------------------------------------------------------------------- texte
// Débuts de ligne, en unités UTF-16 : Lua compte \r\n, \n\r, \r et \n pour un retour.
const debutsLigne = [0];
{
  const retour = /\r\n|\n\r|\r|\n/g;
  let trouve;
  while ((trouve = retour.exec(source))) debutsLigne.push(trouve.index + trouve[0].length);
}

function ligneDe(position) {
  let bas = 0;
  let haut = debutsLigne.length - 1;
  while (bas < haut) {
    const milieu = (bas + haut + 1) >> 1;
    if (debutsLigne[milieu] <= position) bas = milieu;
    else haut = milieu - 1;
  }
  return bas + 1;
}

const finDeLigne = (ligne) => (ligne < debutsLigne.length ? debutsLigne[ligne] : source.length);
const unix = (texte) => texte.replace(/\r\n|\n\r|\r/g, "\n");
const couper = (texte, max) => (texte.length > max ? texte.slice(0, max - 1).trimEnd() + "…" : texte);
const surUneLigne = (texte, max) => couper(texte.replace(/\s+/g, " ").trim(), max);

/** Les lignes de code de [a, b), sans leur retrait commun, `max` au plus. */
function extraitLignes(a, b, max) {
  const lignes = unix(source.slice(debutsLigne[ligneDe(a) - 1], b)).split("\n");
  const retrait = Math.min(...lignes.filter((l) => l.trim()).map((l) => l.match(/^[ \t]*/)[0].length));
  let texte = lignes.slice(0, max).map((l) => couper(l.slice(retrait).trimEnd(), 110)).join("\n");
  if (lignes.length > max) texte += `\n… ${pluriel(lignes.length - max, "ligne de plus", "lignes de plus")}`;
  return texte;
}

// ---------------------------------------------------------------- fonctions
const titreFonction = (f) => (f.genre === "script" ? `script ${donnees.nom}` : nomFonction(f));

function genreFonction(f) {
  if (f.genre === "script") return "le script, niveau principal";
  if (!f.nom) return "fonction anonyme";
  if (f.nom.endsWith("(…)")) return `fonction anonyme passée à ${f.nom.slice(0, -3)}`;
  return f.nom.includes(":") ? "méthode" : "fonction";
}

function etendue(f) {
  if (f.genre === "script") return pluriel(f.lignes, "ligne", "lignes");
  if (f.ligne === f.fin) return "ligne " + nombre(f.ligne);
  return `lignes ${nombre(f.ligne)} à ${nombre(f.fin)}`;
}

/** Nom et paramètres séparés, pour les mettre en forme. */
function partiesNom(f) {
  if (f.genre === "script") return ["script", ` ${donnees.nom}`];
  const complet = nomFonction(f);
  const coupe = f.nom && !f.nom.endsWith("(…)") ? f.nom.length : complet.indexOf("(");
  return [complet.slice(0, coupe), complet.slice(coupe)];
}

/** Les formes de l'organigramme, par leur début dans le texte, et le compte des appels à error. */
function indexer(f) {
  if (f.index) return f.index;
  const index = new Map();
  let erreurs = 0;
  const pile = [f.flux];
  while (pile.length) {
    for (const etape of pile.pop().steps) {
      if (etape.kind === "if") {
        etape.branches.forEach((branche, rang) => {
          index.set(branche.a, { donnee: branche, etape, rang });
          pile.push(branche.body);
        });
        if (etape.otherwise) pile.push(etape.otherwise);
        continue;
      }
      if (etape.kind === "error") erreurs++;
      if (etape.a !== undefined) index.set(etape.a, { donnee: etape, etape });
      if (etape.body) pile.push(etape.body);
    }
  }
  f.index = index;
  f.erreurs = erreurs;
  return index;
}

function phraseMecanique(f) {
  const morceaux = [];
  if (f.decisions) morceaux.push(pluriel(f.decisions, "test", "tests"));
  if (f.loops) morceaux.push(pluriel(f.loops, "boucle", "boucles"));
  if (f.exits) morceaux.push(pluriel(f.exits, "sortie return", "sorties return"));
  let phrase = `Complexité ${nombre(f.complexity)} (${niveauComplexite(f.complexity)}) : `
    + (morceaux.length ? morceaux.join(", ") : "aucun test ni boucle");
  if (f.nesting > 1) phrase += `, sur ${nombre(f.nesting)} niveaux imbriqués`;
  phrase += ".";
  indexer(f);
  if (f.erreurs) phrase += ` Peut s'arrêter sur ${f.erreurs > 1 ? `${nombre(f.erreurs)} appels à error` : "un appel à error"}.`;
  return phrase;
}

/** Une phrase pour présenter une fonction ailleurs que dans sa fiche. */
function descriptionCourte(f) {
  if (f.doc && f.doc.texte) return couper(f.doc.texte.split(/\n\s*\n/)[0].replace(/\s+/g, " "), 220);
  return phraseMecanique(f);
}

/** Les paramètres écrits, avec ce qu'en disent les balises @param. */
function parametresDecrits(f) {
  const decrits = new Map();
  for (const [nom, texte] of (f.doc && f.doc.params) || []) decrits.set(nom.replace(/\?$/, ""), texte);
  return (f.params || []).map((nom) => [nom, decrits.get(nom) || ""]);
}

const nomLie = (id, depuis) => (depuis && id === depuis.id ? `${titreFonction(depuis)} (elle-même)` : titreFonction(parId.get(id)));

// --------------------------------------------------------------- infobulles
function carteFonction(f) {
  const carte = el("div", "carte",
    el("div", "carte-titre", titreFonction(f)),
    el("div", "carte-genre", `${genreFonction(f)}, ${etendue(f)}`));
  if (f.doc && f.doc.texte) carte.append(el("p", "carte-doc", f.doc.texte));
  for (const [nom, texte] of parametresDecrits(f)) {
    if (texte) carte.append(el("p", "carte-param", el("code", "", nom), ` ${texte}`));
  }
  for (const retour of (f.doc && f.doc.retours) || []) carte.append(el("p", "carte-param", el("code", "", "renvoie"), ` ${retour}`));
  carte.append(el("p", "carte-meca", phraseMecanique(f)));
  const rubrique = (titre, noms) => {
    if (!noms.length) return;
    const ligne = el("p", "carte-liste", `${titre} : `);
    noms.forEach((nom, i) => ligne.append(i ? ", " : "", el("code", "", nom)));
    carte.append(ligne);
  };
  rubrique("Ses conditions lisent", f.termes.slice(0, 6).map(([nom]) => nom));
  rubrique("Appelle", f.appelle.map((id) => nomLie(id, f)));
  rubrique("Appelée par", f.appelee_par.map((id) => nomLie(id, f)));
  rubrique("Autres appels", f.externes.slice(0, 6).map(([nom]) => `${nom}()`));
  if (!f.doc && f.genre !== "script") {
    carte.append(el("p", "carte-note", "Aucun commentaire ne la décrit dans le code : ce résumé vient de l'analyse."));
  }
  return carte;
}

const GENRES_ETAPE = {
  action: "Instructions", while: "Boucle while", for: "Boucle for", repeat: "Boucle repeat … until",
  return: "Sortie return", break: "Sortie de boucle (break)", goto: "Saut (goto)",
  label: "Étiquette", error: "Arrêt sur erreur (error)",
};

function codeEtape({ donnee, etape, rang }) {
  switch (etape.kind) {
    case "if": return `${rang ? "elseif" : "if"} ${surUneLigne(source.slice(donnee.a, donnee.b), 400)} then`;
    case "while": return `while ${etape.condition} do`;
    case "for": return `for ${etape.condition} do`;
    case "repeat": return `repeat … until ${etape.condition}`;
    case "action": return extraitLignes(donnee.a, donnee.b, 8);
    default: return surUneLigne(source.slice(donnee.a, donnee.b), 400);
  }
}

function carteEtape(entree, element) {
  const { donnee, etape, rang } = entree;
  const titre = etape.kind === "if" ? (rang ? "Autre test (elseif)" : "Test (if)") : GENRES_ETAPE[etape.kind] || etape.kind;
  const premiere = ligneDe(donnee.a);
  const derniere = ligneDe(Math.max(donnee.a, donnee.b - 1));
  const carte = el("div", "carte",
    el("div", "carte-titre carte-titre-texte", titre),
    el("div", "carte-genre", premiere === derniere ? `ligne ${nombre(premiere)}`
      : `lignes ${nombre(premiere)} à ${nombre(derniere)}`),
    el("pre", "carte-code", codeEtape(entree)));
  if (etape.kind === "action" && etape.count > 1) {
    carte.append(el("p", "carte-meca", `${pluriel(etape.count, "instruction", "instructions")} à la suite, sans décision.`));
  }
  const appels = donnee.appels || [];
  if (appels.length) {
    carte.append(el("p", "carte-rubrique", appels.length > 1 ? "Fonctions du script appelées ici :" : "Fonction du script appelée ici :"));
    for (const id of appels) {
      const f = parId.get(id);
      carte.append(el("p", "carte-appel", el("code", "", nomLie(id, courante)), ` ${descriptionCourte(f)}`));
    }
  }
  carte.append(el("p", "carte-aide", element.dataset.plis
    ? "Clic : voir le code. Double-clic : replier ou déplier ce qui en dépend." : "Clic : voir le code."));
  return carte;
}

function contenuBulle(element) {
  if (element.dataset.fonction !== undefined) return carteFonction(parId.get(Number(element.dataset.fonction)));
  if (element.dataset.aide) return el("div", "carte", el("p", "", element.dataset.aide));
  if (element.dataset.a !== undefined && courante) {
    const entree = indexer(courante).get(Number(element.dataset.a));
    if (entree) return carteEtape(entree, element);
  }
  return null;
}

const CIBLES_BULLE = "[data-fonction], [data-aide], #toile g.etape, #arbre .n-ligne[data-a]";
let cibleBulle = null;
let minuterieBulle = 0;
let montreeA = 0;
let pointeur = { x: 0, y: 0 };

function cacherBulle() {
  clearTimeout(minuterieBulle);
  cibleBulle = null;
  bulle.hidden = true;
}

/** Montre l'infobulle de `element` près du pointeur, ou sous l'élément si `x` est null. */
function montrerBulle(element, x = null, y = null) {
  const contenu = element.isConnected ? contenuBulle(element) : null;
  if (!contenu) {
    cacherBulle();
    return;
  }
  cibleBulle = element;
  montreeA = performance.now();
  bulle.replaceChildren(contenu);
  bulle.hidden = false;
  const marge = 10;
  const largeur = bulle.offsetWidth;
  const hauteur = bulle.offsetHeight;
  let gauche;
  let haut;
  if (x === null) {
    const cadre = element.getBoundingClientRect();
    gauche = cadre.left;
    haut = cadre.bottom + 8;
    if (haut + hauteur > innerHeight - marge) haut = cadre.top - hauteur - 8;
  } else {
    gauche = x + 14;
    haut = y + 18;
    if (haut + hauteur > innerHeight - marge) haut = y - hauteur - 12;
  }
  bulle.style.left = `${borne(gauche, marge, innerWidth - largeur - marge)}px`;
  bulle.style.top = `${borne(haut, marge, innerHeight - hauteur - marge)}px`;
}

document.addEventListener("pointermove", (evenement) => {
  pointeur = { x: evenement.clientX, y: evenement.clientY };
}, { passive: true });

document.addEventListener("pointerover", (evenement) => {
  if (evenement.pointerType === "touch" || glisse) return;
  const element = evenement.target.closest(CIBLES_BULLE);
  if (element === cibleBulle) return;
  clearTimeout(minuterieBulle);
  if (!element) {
    cacherBulle();
    return;
  }
  // Une infobulle déjà ouverte suit le pointeur sans attendre.
  minuterieBulle = setTimeout(() => montrerBulle(element, pointeur.x, pointeur.y), bulle.hidden ? 320 : 40);
});
document.addEventListener("pointerout", (evenement) => {
  if (!evenement.relatedTarget) cacherBulle();
});
document.addEventListener("pointerdown", cacherBulle);
// Défiler sous l'infobulle la ferme ; pas le défilement qu'a provoqué le clic qui l'a ouverte.
document.addEventListener("scroll", (evenement) => {
  if (!cibleBulle || performance.now() - montreeA < 400) return;
  const defile = evenement.target;
  if (defile === document || (defile.contains && defile.contains(cibleBulle))) cacherBulle();
}, true);
document.addEventListener("focusin", (evenement) => {
  const element = evenement.target.closest && evenement.target.closest(CIBLES_BULLE);
  if (element && evenement.target.matches(":focus-visible")) montrerBulle(element);
});
document.addEventListener("focusout", cacherBulle);
document.addEventListener("keydown", (evenement) => {
  if (evenement.key === "Escape") cacherBulle();
});

/** Au doigt, une infobulle s'ouvre au toucher et se ferme au toucher suivant. */
let dernierPointeur = "mouse";
document.addEventListener("pointerdown", (evenement) => {
  dernierPointeur = evenement.pointerType;
}, true);
function bulleAuToucher(element) {
  if (dernierPointeur === "touch") setTimeout(() => montrerBulle(element), 0);
}

// ---------------------------------------------------------------- la liste
const SIGNES = { script: "lua", fonction: "fn", anonyme: "λ" };

function genreListe(f) {
  if (f.genre === "script") return "script";
  if (!f.nom || f.nom.endsWith("(…)")) return "callback";
  return f.nom.includes(":") ? "method" : "function";
}

function entreeListe(f, aPlat) {
  const genre = genreListe(f);
  const [nom, suite] = partiesNom(f);
  const ligne = el("div", "symbole entree",
    el("span", "symbole-genre", genre === "script" ? SIGNES.script : genre === "callback" ? SIGNES.anonyme : SIGNES.fonction),
    el("span", "symbole-nom", el("b", "", nom), el("i", "", suite)),
    el("span", "symbole-detail",
      el("span", `pastille${f.complexity > 10 ? " haute" : ""}`, nombre(f.complexity)), nombre(f.ligne)));
  ligne.setAttribute("role", "option");
  ligne.setAttribute("aria-selected", String(f === courante));
  ligne.classList.toggle("actif", f === courante);
  ligne.dataset.fonction = f.id;
  ligne.dataset.genre = genre;
  ligne.style.setProperty("--niveau", aPlat ? 0 : f.profondeur);
  return ligne;
}

function remplirListe() {
  const motif = filtre.value.trim().toLowerCase();
  const ordre = [...fonctions];
  if (tri.value === "complexite") ordre.sort((x, y) => y.complexity - x.complexity || x.a - y.a);
  affichees = ordre.filter((f) => !motif || titreFonction(f).toLowerCase().includes(motif)
    || (f.doc && f.doc.texte.toLowerCase().includes(motif)));
  const aPlat = Boolean(motif) || tri.value !== "texte";
  liste.replaceChildren(...affichees.map((f) => entreeListe(f, aPlat)));
  if (!affichees.length) liste.append(el("div", "sans-resultat", "Aucune fonction ne correspond à ce filtre."));
  const total = fonctions.length - 1;
  $("sommaire-compte").textContent = motif ? `${nombre(affichees.length)} sur ${nombre(fonctions.length)}`
    : pluriel(total, "fonction", "fonctions") + " et le script";
}

function marquerListe() {
  for (const ligne of liste.children) {
    const actif = ligne.dataset.fonction === String(courante.id);
    ligne.classList.toggle("actif", actif);
    ligne.setAttribute("aria-selected", String(actif));
    if (actif) ligne.scrollIntoView({ block: "nearest" });
  }
}

filtre.addEventListener("input", remplirListe);
tri.addEventListener("change", remplirListe);
liste.addEventListener("click", (evenement) => {
  const ligne = evenement.target.closest(".entree");
  if (!ligne) return;
  aller(parId.get(Number(ligne.dataset.fonction)));
});
liste.addEventListener("keydown", (evenement) => {
  if (!affichees.length) return;
  const rang = affichees.indexOf(courante);
  let cible = -1;
  if (evenement.key === "ArrowDown") cible = Math.min(affichees.length - 1, rang + 1);
  else if (evenement.key === "ArrowUp") cible = Math.max(0, rang < 0 ? 0 : rang - 1);
  else if (evenement.key === "Home") cible = 0;
  else if (evenement.key === "End") cible = affichees.length - 1;
  else return;
  evenement.preventDefault();
  aller(affichees[cible]);
});

// ----------------------------------------------------------------- la fiche
function boutonFonction(id, depuis) {
  const bouton = el("button", "lien-fonction", nomLie(id, depuis));
  bouton.type = "button";
  bouton.dataset.fonction = id;
  return bouton;
}

function remplirEntete(f) {
  const [nom, suite] = partiesNom(f);
  const titre = el("h1", "fiche-titre", nom, el("i", "", suite));
  titre.id = "fiche-titre";
  const entete = $("fiche-entete");
  entete.replaceChildren(titre, el("div", "fiche-genre", `${genreFonction(f)}, ${etendue(f)}`));
  entete.lastChild.textContent = entete.lastChild.textContent.replace(/^./, (c) => c.toUpperCase());
  if (f.doc && f.doc.texte) entete.append(el("p", "fiche-doc", f.doc.texte));
  const parametres = parametresDecrits(f).filter(([, texte]) => texte);
  const retours = (f.doc && f.doc.retours) || [];
  if (parametres.length || retours.length) {
    const details = el("ul", "fiche-params");
    for (const [nom, texte] of parametres) details.append(el("li", "", el("code", "", nom), texte));
    for (const retour of retours) details.append(el("li", "", el("code", "", "renvoie"), retour));
    entete.append(details);
  }
  if (!f.doc && f.genre !== "script") {
    entete.append(el("p", "fiche-sans-doc", "Aucun commentaire au-dessus de cette fonction ne la décrit."));
  }
  const relation = (titreRelation, elements) => {
    if (!elements.length) return;
    entete.append(el("div", "relations", el("span", "relations-nom", titreRelation), ...elements));
  };
  relation("Appelle", f.appelle.map((id) => boutonFonction(id, f)));
  relation("Appelée par", f.appelee_par.map((id) => boutonFonction(id, f)));
  relation("Autres appels", f.externes.map(([nomAppel, fois]) => {
    const terme = el("span", "terme", `${nomAppel}()`, fois > 1 ? el("b", "", nombre(fois)) : null);
    return terme;
  }));
}

function tuile(valeur, nom, aide) {
  const element = el("div", "chiffre", el("span", "chiffre-valeur", nombre(valeur)), el("span", "chiffre-nom", nom));
  element.dataset.aide = aide;
  return element;
}

function remplirResume(f) {
  const c = f.complexity;
  const resume = $("resume");
  resume.replaceChildren(
    tuile(c, `complexité ${niveauComplexite(c)}`,
      "1, plus 1 par test, par boucle et par « and » ou « or » dans une condition : le nombre de chemins à essayer pour tester la fonction."),
    tuile(f.decisions, f.decisions > 1 ? "tests" : "test", "Conditions if et elseif"),
    tuile(f.loops, f.loops > 1 ? "boucles" : "boucle", "Boucles while, repeat et for"),
    tuile(f.nesting, f.nesting > 1 ? "niveaux imbriqués" : "niveau imbriqué", "Profondeur maximale des tests et des boucles"),
    tuile(f.exits, f.exits > 1 ? "sorties return" : "sortie return", "Instructions return"),
    tuile(f.statements, f.statements > 1 ? "instructions" : "instruction",
      "Instructions de la fonction, sans compter celles des fonctions qu'elle contient"));
  if (f.termes.length) {
    const termes = el("div", "termes-liste");
    for (const [nom, fois] of f.termes) {
      const terme = el("span", "terme", nom, el("b", "", nombre(fois)));
      terme.dataset.aide = pluriel(fois, "lecture", "lectures") + " dans les conditions";
      termes.append(terme);
    }
    resume.append(el("div", "termes", el("div", "termes-titre", "Ce que lisent les conditions"), termes));
  }
}

$("fiche-entete").addEventListener("click", (evenement) => {
  const lien = evenement.target.closest(".lien-fonction");
  if (lien) aller(parId.get(Number(lien.dataset.fonction)));
});

// ------------------------------------------------------------- organigramme
function appliquerZoom() {
  const svg = toile.firstElementChild;
  if (!dessin || !svg || !toile.clientWidth) return;
  // Ajusté à la largeur du volet, sans descendre sous une taille lisible.
  if (ajuste) zoom = borne((toile.clientWidth - 6) / dessin.largeur, 0.75, 1);
  svg.setAttribute("width", Math.round(dessin.largeur * zoom));
  svg.setAttribute("height", Math.round(dessin.hauteur * zoom));
}

function definirZoom(valeur) {
  ajuste = false;
  zoom = borne(valeur, 0.25, 2.5);
  appliquerZoom();
}

function tracerOrganigramme(garder) {
  dessin = construire(courante.flux, titreFonction(courante), replis());
  toile.innerHTML = dessin.svg;
  // Les infobulles de la page remplacent celles du dessin.
  for (const titre of toile.querySelectorAll("title")) titre.remove();
  for (const pli of toile.querySelectorAll("g.pli")) {
    pli.dataset.aide = "Étapes repliées : un clic les déplie.";
  }
  if (!garder) {
    ajuste = true;
    toile.scrollTop = 0;
    toile.scrollLeft = 0;
  }
  appliquerZoom();
  marquerSelection(false);
}

/** Replie les corps ouverts parmi `cles` ; s'ils sont tous repliés, les déplie. */
function basculerPlis(cles) {
  const ouverts = cles.filter((cle) => !estReplie(niveauDuPli(cle), cle, replis()));
  for (const cle of ouverts.length ? ouverts : cles) {
    if (bascules.has(cle)) bascules.delete(cle);
    else bascules.add(cle);
  }
  // Le test ou la boucle concernés restent à la même place sous les yeux.
  const enTete = () => toile.querySelector(`g.etape[data-plis~="${cles[0]}"]`);
  const avant = enTete();
  const hautAvant = avant ? avant.getBoundingClientRect().top : null;
  tracerOrganigramme(true);
  const apres = enTete();
  if (apres && hautAvant !== null) toile.scrollTop += apres.getBoundingClientRect().top - hautAvant;
}

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
    cacherBulle();
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
  if (!element) return;
  choisirEtape(Number(element.dataset.a), Number(element.dataset.b));
  bulleAuToucher(element);
});

toile.addEventListener("dblclick", (evenement) => {
  if (depliAuClic) return;
  const element = evenement.target.closest("g.etape[data-plis]");
  if (!element) return;
  evenement.preventDefault();
  basculerPlis(element.dataset.plis.split(" "));
});

toile.addEventListener("keydown", (evenement) => {
  const formes = [...toile.querySelectorAll("g.etape, g.pli")];
  if (!formes.length) return;
  const rang = formes.indexOf(document.activeElement);
  let cible = -1;
  if (evenement.key === "ArrowDown" || evenement.key === "ArrowRight") cible = Math.min(formes.length - 1, rang + 1);
  else if (evenement.key === "ArrowUp" || evenement.key === "ArrowLeft") cible = Math.max(0, rang - 1);
  else if ((evenement.key === "Enter" || evenement.key === " ") && rang >= 0) {
    evenement.preventDefault();
    const choisie = formes[rang];
    if (choisie.dataset.pli) basculerPlis([choisie.dataset.pli]);
    else choisirEtape(Number(choisie.dataset.a), Number(choisie.dataset.b));
    return;
  } else return;
  evenement.preventDefault();
  formes[cible].focus({ preventScroll: true });
  formes[cible].scrollIntoView({ block: "nearest", inline: "nearest" });
  montrerBulle(formes[cible]);
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

// -------------------------------------------------------------------- arbre
// Les mêmes décisions en liste indentée. Les clés des corps sont celles de
// l'organigramme : replier l'un replie l'autre.
const ICONES = {
  depart: '<rect class="forme f-depart" x="1" y="1" width="16" height="10" rx="5"/>',
  test: '<polygon class="forme f-test" points="1,6 4.5,1 13.5,1 17,6 13.5,11 4.5,11"/>',
  boucle: '<polygon class="forme f-boucle" points="1,6 4.5,1 13.5,1 17,6 13.5,11 4.5,11"/>',
  action: '<rect class="forme f-action" x="1" y="1" width="16" height="10" rx="2"/>',
  sortie: '<rect class="forme f-sortie" x="1" y="1" width="16" height="10" rx="5"/>',
  erreur: '<rect class="forme f-erreur" x="1" y="1" width="16" height="10" rx="5"/>',
  pli: '<rect class="forme f-pli" x="1" y="1" width="16" height="10" rx="2"/>',
};

function icone(genre) {
  const element = el("span");
  element.innerHTML = `<svg class="flux n-icone" viewBox="0 0 18 12" aria-hidden="true">${ICONES[genre]}</svg>`;
  return element.firstChild;
}

function lier(element, donnee) {
  element.dataset.a = donnee.a;
  element.dataset.b = donnee.b;
  return element;
}

function boutonsAppels(donnee) {
  return (donnee.appels || []).map((id) => {
    const bouton = el("button", "n-appel", `→ ${nomLie(id, courante)}`);
    bouton.type = "button";
    bouton.dataset.fonction = id;
    return bouton;
  });
}

/** Un test ou une boucle : sa ligne, que l'on replie, et son corps. */
function noeudCorps(sequence, niveau, cle, entete, forme, donnee) {
  const ouvert = !estReplie(niveau, cle, replis());
  const bascule = el("button", "n-bascule");
  bascule.type = "button";
  bascule.dataset.pli = cle;
  bascule.setAttribute("aria-expanded", String(ouvert));
  bascule.setAttribute("aria-label", "Replier ou déplier");
  const ligne = el("div", "n-ligne", bascule, icone(forme), ...entete);
  if (donnee) lier(ligne, donnee);
  const contenu = el("ul", "n-corps");
  contenu.hidden = !ouvert;
  noeuds(sequence, niveau, cle, contenu);
  return el("li", "n", ligne, contenu);
}

function noeudSimple(forme, donnee, ...contenu) {
  const ligne = el("div", "n-ligne", el("span", "n-espace"), icone(forme), ...contenu);
  if (donnee && donnee.a !== undefined) lier(ligne, donnee);
  return el("li", "n", ligne);
}

function noeuds(sequence, niveau, cle, cible) {
  if (!sequence.steps.length) {
    cible.append(el("li", "n-vide", "rien"));
    return;
  }
  sequence.steps.forEach((etape, i) => {
    const k = `${cle}/${i}`;
    switch (etape.kind) {
      case "if": {
        const branches = el("ul", "n-branches");
        etape.branches.forEach((branche, rang) => {
          branches.append(noeudCorps(branche.body, niveau + 1, `${k}:b${rang}`, [
            el("span", "n-mot", rang ? "sinon, si" : "si"), el("code", "n-code", branche.condition),
            el("span", "n-mot", "alors"), ...boutonsAppels(branche)], "test", branche));
        });
        if (etape.otherwise) {
          branches.append(noeudCorps(etape.otherwise, niveau + 1, `${k}:s`, [el("span", "n-mot", "sinon")], "test", null));
        }
        cible.append(el("li", "n", branches));
        break;
      }
      case "while":
      case "for":
      case "repeat": {
        const mot = { while: "tant que", for: "pour", repeat: "répéter jusqu'à ce que" }[etape.kind];
        cible.append(noeudCorps(etape.body, niveau + 1, `${k}:c`, [
          el("span", "n-mot", mot), el("code", "n-code", etape.condition), ...boutonsAppels(etape)], "boucle", etape));
        break;
      }
      case "action": {
        const lignes = el("span", "n-codes", ...etape.lines.map((ligne) => el("code", "n-code", ligne)));
        const reste = etape.count - etape.lines.length;
        if (reste > 0) lignes.append(el("span", "n-suite", `et ${pluriel(reste, "autre instruction", "autres instructions")}`));
        cible.append(noeudSimple("action", etape, lignes, ...boutonsAppels(etape)));
        break;
      }
      case "return":
      case "break":
      case "goto":
      case "error":
      case "label":
        cible.append(noeudSimple(etape.kind === "error" ? "erreur" : etape.kind === "label" ? "action" : "sortie",
          etape, el("code", "n-code", etape.text), ...boutonsAppels(etape)));
        break;
      default:
        cible.append(noeudSimple("pli", null, el("span", "n-suite",
          pluriel(etape.count || 0, "instruction non affichée", "instructions non affichées"))));
    }
  });
}

function tracerArbre() {
  const racine = el("ul", "arbre-racine");
  const depart = noeudSimple("depart", null, el("code", "n-code", titreFonction(courante)));
  depart.classList.add("n-depart");
  racine.append(depart);
  noeuds(courante.flux, 0, "", racine);
  arbre.replaceChildren(racine);
  marquerSelection(false);
}

arbre.addEventListener("click", (evenement) => {
  const appel = evenement.target.closest(".n-appel");
  if (appel) {
    aller(parId.get(Number(appel.dataset.fonction)));
    return;
  }
  const bascule = evenement.target.closest(".n-bascule");
  if (bascule) {
    const ouvert = bascule.getAttribute("aria-expanded") !== "true";
    bascule.setAttribute("aria-expanded", String(ouvert));
    bascule.closest(".n").querySelector(":scope > .n-corps").hidden = !ouvert;
    const cle = bascule.dataset.pli;
    if (!ouvert !== niveauDuPli(cle) > niveauMax) bascules.add(cle);
    else bascules.delete(cle);
    return;
  }
  const ligne = evenement.target.closest(".n-ligne[data-a]");
  if (!ligne) return;
  choisirEtape(Number(ligne.dataset.a), Number(ligne.dataset.b));
  bulleAuToucher(ligne);
});

// --------------------------------------------------------------------- code
const MOTS = new Set(["and", "break", "do", "else", "elseif", "end", "for", "function", "goto", "if", "in",
  "local", "not", "or", "repeat", "return", "then", "until", "while"]);
const CONSTANTES = new Set(["true", "false", "nil"]);
const NOM = /[A-Za-z_][A-Za-z0-9_]*/y;
const NOMBRE_LUA = /0[xX][0-9a-fA-F]*(?:\.[0-9a-fA-F]*)?(?:[pP][+-]?[0-9]+)?|[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?/y;
const CROCHETS = /\[(=*)\[/y;
const APPEL = /\s*[({"']/y;
const ECHAPPE = { "&": "&amp;", "<": "&lt;", ">": "&gt;" };
const echapper = (texte) => texte.replace(/[&<>]/g, (c) => ECHAPPE[c]);

/** Le texte en HTML coloré comme dans le Studio : commentaires, chaînes, nombres, mots clés, appels. */
function colorer(texte) {
  let html = "";
  let brut = 0;
  let i = 0;
  const n = texte.length;
  const marquer = (fin, classe) => {
    html += `${echapper(texte.slice(brut, i))}<span class="${classe}">${echapper(texte.slice(i, fin))}</span>`;
    brut = fin;
    i = fin;
  };
  const longue = (debut) => {
    CROCHETS.lastIndex = debut;
    const trouve = CROCHETS.exec(texte);
    if (!trouve) return -1;
    const fin = texte.indexOf(`]${trouve[1]}]`, debut + trouve[0].length);
    return fin < 0 ? n : fin + trouve[1].length + 2;
  };
  while (i < n) {
    const c = texte[i];
    if (c === "-" && texte[i + 1] === "-") {
      let fin = texte[i + 2] === "[" ? longue(i + 2) : -1;
      if (fin < 0) fin = texte.indexOf("\n", i) < 0 ? n : texte.indexOf("\n", i);
      marquer(fin, "j-c");
    } else if (c === '"' || c === "'") {
      let j = i + 1;
      while (j < n && texte[j] !== c && texte[j] !== "\n") j += texte[j] === "\\" ? 2 : 1;
      marquer(j < n && texte[j] === c ? j + 1 : Math.min(j, n), "j-s");
    } else if (c === "[" && (texte[i + 1] === "[" || texte[i + 1] === "=") && longue(i) > 0) {
      marquer(longue(i), "j-s");
    } else if ((c >= "0" && c <= "9") || (c === "." && texte[i + 1] >= "0" && texte[i + 1] <= "9")) {
      NOMBRE_LUA.lastIndex = i;
      const trouve = NOMBRE_LUA.exec(texte);
      marquer(i + (trouve && trouve[0].length ? trouve[0].length : 1), "j-n");
    } else if ((c >= "A" && c <= "Z") || (c >= "a" && c <= "z") || c === "_") {
      NOM.lastIndex = i;
      const mot = NOM.exec(texte)[0];
      const fin = i + mot.length;
      APPEL.lastIndex = fin;
      if (MOTS.has(mot)) marquer(fin, "j-k");
      else if (CONSTANTES.has(mot)) marquer(fin, "j-b");
      else if (APPEL.test(texte)) marquer(fin, "j-f");
      else i = fin;
    } else {
      i++;
    }
  }
  return html + echapper(texte.slice(brut));
}

let codeDe = null;          // fonction dont le code est affiché
let premiereLigneCode = 1;

function remplirCode() {
  if (codeDe === courante) return;
  codeDe = courante;
  premiereLigneCode = courante.ligne;
  const texte = unix(source.slice(debutsLigne[courante.ligne - 1], finDeLigne(courante.fin))).replace(/\n$/, "");
  texteCode.innerHTML = colorer(texte);
  const total = texte.split("\n").length;
  numerosCode.textContent = Array.from({ length: total }, (_, i) => premiereLigneCode + i).join("\n");
  defileCode.scrollTop = 0;
  defileCode.scrollLeft = 0;
}

function marquerCode(defiler) {
  if (panneauCode.hidden || !selection || codeDe !== courante) {
    marqueCode.hidden = true;
    return;
  }
  const style = getComputedStyle(texteCode);
  const hauteurLigne = parseFloat(style.lineHeight) || 19;
  const premiere = ligneDe(selection.a);
  const derniere = ligneDe(Math.max(selection.a, selection.b - 1));
  const haut = parseFloat(style.paddingTop) + (premiere - premiereLigneCode) * hauteurLigne;
  marqueCode.style.top = `${haut}px`;
  marqueCode.style.height = `${(derniere - premiere + 1) * hauteurLigne}px`;
  marqueCode.hidden = false;
  if (defiler) {
    const visible = defileCode.clientHeight;
    const hauteur = (derniere - premiere + 1) * hauteurLigne;
    if (haut < defileCode.scrollTop || haut + hauteur > defileCode.scrollTop + visible) {
      defileCode.scrollTop = Math.max(0, haut - Math.max(24, (visible - hauteur) / 3));
    }
  }
}

function montrerCode(visible) {
  panneauCode.hidden = !visible;
  corps.classList.toggle("avec-code", visible);
  boutonCode.setAttribute("aria-pressed", String(visible));
  if (visible) {
    remplirCode();
    marquerCode(true);
  }
}

boutonCode.addEventListener("click", () => montrerCode(panneauCode.hidden));

// ---------------------------------------------------------------- sélection
function choisirEtape(a, b) {
  selection = { a, b };
  marquerSelection(true);
  if (panneauCode.hidden) montrerCode(true);
  else marquerCode(true);
}

function marquerSelection(defiler) {
  const conteneur = vue === "arbre" ? arbre : toile;
  for (const ancien of conteneur.querySelectorAll(".actif")) ancien.classList.remove("actif");
  if (!selection) return;
  const element = vue === "arbre"
    ? arbre.querySelector(`.n-ligne[data-a="${selection.a}"]`)
    : toile.querySelector(`g.etape[data-a="${selection.a}"]`);
  if (element) {
    element.classList.add("actif");
    if (defiler) element.scrollIntoView({ block: "nearest", inline: "nearest" });
  }
  marquerCode(defiler);
}

// --------------------------------------------------------------- affichage
function tracer(garder) {
  if (!courante) return;
  if (vue === "arbre") tracerArbre();
  else tracerOrganigramme(garder);
}

function choisirVue(nouvelle) {
  vue = nouvelle;
  for (const bouton of document.querySelectorAll("[data-vue]")) {
    bouton.setAttribute("aria-pressed", String(bouton.dataset.vue === vue));
  }
  toile.hidden = vue !== "organigramme";
  arbre.hidden = vue !== "arbre";
  $("zoom").hidden = vue !== "organigramme";
  tracer(false);
}

for (const bouton of document.querySelectorAll("[data-vue]")) {
  bouton.addEventListener("click", () => choisirVue(bouton.dataset.vue));
}

const boutonsNiveau = [...document.querySelectorAll("#niveaux [data-niveau]")];
for (const bouton of boutonsNiveau) {
  bouton.addEventListener("click", () => {
    niveauMax = bouton.dataset.niveau === "tout" ? Infinity : Number(bouton.dataset.niveau) - 1;
    bascules = new Set();
    for (const autre of boutonsNiveau) autre.setAttribute("aria-pressed", String(autre === bouton));
    tracer(false);
  });
}

function choisir(f) {
  if (!f) return;
  cacherBulle();
  courante = f;
  bascules = new Set();
  selection = null;
  document.title = `${titreFonction(f)} – décisions de ${donnees.nom}`;
  remplirEntete(f);
  remplirResume(f);
  marquerListe();
  tracer(false);
  if (!panneauCode.hidden) {
    remplirCode();
    marquerCode(false);
  }
}

/** Montre `f` et le note dans l'adresse : le bouton Précédent du navigateur y ramène. */
function aller(f) {
  if (!f) return;
  const ancre = `#fonction-${f.id}`;
  if (location.hash === ancre) choisir(f);
  else location.hash = ancre;
}

/** La fonction que nomme l'adresse ; sans elle, la plus complexe. */
function depuisAdresse() {
  const trouve = /^#fonction-(\d+)$/.exec(location.hash);
  return (trouve && parId.get(Number(trouve[1])))
    || fonctions.reduce((meilleure, f) => (f.complexity > meilleure.complexity ? f : meilleure), fonctions[0]);
}

window.addEventListener("hashchange", () => {
  const f = depuisAdresse();
  if (f !== courante) choisir(f);
});

// -------------------------------------------------------------------- thème
const boutonTheme = $("btn-theme");

function appliquerTheme(theme) {
  document.documentElement.dataset.theme = theme;
  boutonTheme.textContent = theme === "nuit" ? "Jour" : "Nuit";
  boutonTheme.dataset.aide = theme === "nuit" ? "Passer au thème clair" : "Passer au thème sombre";
}

boutonTheme.addEventListener("click", () => {
  const theme = document.documentElement.dataset.theme === "nuit" ? "jour" : "nuit";
  appliquerTheme(theme);
  try {
    localStorage.setItem("lua-rapport:theme", theme);
  } catch {
    // Stockage indisponible : le choix vaut pour cette visite.
  }
});

// L'impression se fait sur fond clair.
let themeAvantImpression = null;
window.addEventListener("beforeprint", () => {
  themeAvantImpression = document.documentElement.dataset.theme;
  document.documentElement.dataset.theme = "jour";
});
window.addEventListener("afterprint", () => {
  if (themeAvantImpression) document.documentElement.dataset.theme = themeAvantImpression;
});

const boutonAide = $("btn-aide");
boutonAide.addEventListener("click", () => {
  const aide = $("aide");
  aide.hidden = !aide.hidden;
  boutonAide.setAttribute("aria-expanded", String(!aide.hidden));
});

// ---------------------------------------------------------------- démarrage
const policesPretes = (async () => {
  if (!document.fonts || !document.fonts.load) return;
  const attente = new Promise((resoudre) => setTimeout(resoudre, 1500));
  const chargement = Promise.all([
    document.fonts.load('12px "Atkinson Hyperlegible Mono"'),
    document.fonts.load('600 12px "Atkinson Hyperlegible Mono"'),
    document.fonts.load('11.5px "Atkinson Hyperlegible Next"'),
  ]).catch(() => null);
  await Promise.race([attente, chargement]);
})();

async function demarrer() {
  appliquerTheme(document.documentElement.dataset.theme === "jour" ? "jour" : "nuit");
  for (const place of document.querySelectorAll("[data-icone]")) place.replaceWith(icone(place.dataset.icone));
  const date = new Date(`${donnees.date}T12:00:00`);
  const quand = Number.isNaN(date.getTime()) ? donnees.date
    : date.toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
  const total = fonctions[0] ? fonctions[0].lignes : 0;
  $("document-detail").textContent = `${pluriel(total, "ligne", "lignes")}, `
    + `${pluriel(fonctions.length - 1, "fonction", "fonctions")}, exporté le ${quand} `
    + `par le parseur Lua ${donnees.version}`;
  remplirListe();
  await policesPretes;
  choisir(depuisAdresse());
}

demarrer();
