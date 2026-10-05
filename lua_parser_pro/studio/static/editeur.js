// L'éditeur : une zone de saisie au texte transparent, posée sur un calque qui
// redessine en couleurs les seules lignes visibles. Le texte reste donc
// fluide même pour un fichier de plusieurs dizaines de milliers de lignes.

import { $, etat, emettre, borne, echapper, policesPretes, largeurTexte, oublierMesures } from "./noyau.js";

const saisie = $("saisie");
const calque = $("calque");
const zone = $("zone");
const gouttiere = $("gouttiere");
const numeros = $("gouttiere-lignes");
const barre = $("ligne-courante");

const H = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--h-ligne")) || 21;
const MARGE_HAUT = 10;
const MARGE_GAUCHE = 14;
const PAS = 8;                        // le calque est redessiné toutes les 8 lignes défilées
const LIMITE_COULEUR = 2_500_000;     // au-delà, le texte reste affiché mais sans couleurs
const LIMITE_FENETRE = 300_000;
const SEUIL_PARTIEL = 40_000;         // au-delà, une frappe ne redécoupe que la zone touchée
const BLOC = 4096;

let texte = "";
let debuts = [0];                     // position du début de chaque ligne
let jetons = new Int32Array(3072);    // triplets (début, fin, classe)
let nJetons = 0;
const marques = new Map();            // nom -> { a, b, classe }
let listeMarques = [];
let curseur = { debut: 0, fin: 0 };
let ligneCurseur = 0;
let premiere = -1;
let derniere = -1;
let sale = true;
let demande = 0;
let largeurCar = 7.8;

// ----------------------------------------------------------------- coloration
const MOTS = new Set(["and", "break", "do", "else", "elseif", "end", "for", "function", "goto",
  "if", "in", "local", "not", "or", "repeat", "return", "then", "until", "while"]);
const CONSTANTES = new Set(["true", "false", "nil"]);
const CLASSES = ["", "j-c", "j-s", "j-n", "j-k", "j-b", "j-f", "j-p"];
const MOTIF = new RegExp([
  "--\\[(=*)\\[[\\s\\S]*?(?:\\]\\1\\]|$)",                      // commentaire long
  "--[^\\n]*",                                                  // commentaire de ligne
  "\\[(=*)\\[[\\s\\S]*?(?:\\]\\2\\]|$)",                        // chaîne longue
  "\"(?:[^\"\\\\\\n]|\\\\(?:z\\s*|[\\s\\S]))*\"?",              // chaîne entre guillemets
  "'(?:[^'\\\\\\n]|\\\\(?:z\\s*|[\\s\\S]))*'?",                 // chaîne entre apostrophes
  "0[xX][0-9a-fA-F.]*(?:[pP][+-]?[0-9]*)?",                     // nombre hexadécimal
  "(?:[0-9]+\\.?[0-9]*|\\.[0-9]+)(?:[eE][+-]?[0-9]*)?",         // nombre décimal
  "[A-Za-z_][A-Za-z0-9_]*",                                     // nom ou mot-clé
  "\\.\\.\\.?|[=~<>]=|<<|>>|//|::|[-+*/%^#&~|<>=(){}\\[\\];:,.]", // symbole
].join("|"), "g");

function ajouter(a, b, classe) {
  if (3 * nJetons + 3 > jetons.length) {
    const plusGrand = new Int32Array(jetons.length * 2);
    plusGrand.set(jetons);
    jetons = plusGrand;
  }
  jetons[3 * nJetons] = a;
  jetons[3 * nJetons + 1] = b;
  jetons[3 * nJetons + 2] = classe;
  nJetons++;
}

/** Classe d'un fragment reconnu à la position `a` ; 0 pour un nom ordinaire, laissé sans couleur. */
function classer(mot, a) {
  const c = mot.charCodeAt(0);
  const c2 = mot.length > 1 ? mot.charCodeAt(1) : 0;
  if (c === 45 && c2 === 45) return 1;                                   // --
  if (c === 34 || c === 39 || (c === 91 && mot.length > 1)) return 2;
  if ((c >= 48 && c <= 57) || (c === 46 && c2 >= 48 && c2 <= 57)) return 3;
  if ((c >= 65 && c <= 90) || (c >= 97 && c <= 122) || c === 95) {
    if (MOTS.has(mot)) return 4;
    if (CONSTANTES.has(mot)) return 5;
    let suite = a + mot.length;
    let code = texte.charCodeAt(suite);
    while (code === 32 || code === 9) code = texte.charCodeAt(++suite);
    return code === 40 ? 6 : 0;                                          // nom suivi de « ( » : un appel
  }
  return 7;
}

function decouper() {
  nJetons = 0;
  if (texte.length > LIMITE_COULEUR) return;
  let depart = texte.charCodeAt(0) === 0xfeff ? 1 : 0;
  if (texte.charCodeAt(depart) === 35) {        // première ligne en « # » : ignorée par Lua
    let fin = texte.indexOf("\n", depart);
    if (fin < 0) fin = texte.length;
    ajouter(depart, fin, 1);
    depart = fin;
  }
  MOTIF.lastIndex = depart;
  let trouve;
  while ((trouve = MOTIF.exec(texte)) !== null) {
    const mot = trouve[0];
    const a = trouve.index;
    if (mot.length === 0) {
      MOTIF.lastIndex = a + 1;
      continue;
    }
    const classe = classer(mot, a);
    if (classe) ajouter(a, a + mot.length, classe);
  }
}

function prefixeCommun(a, b) {
  const limite = Math.min(a.length, b.length);
  let i = 0;
  while (i + BLOC <= limite && a.slice(i, i + BLOC) === b.slice(i, i + BLOC)) i += BLOC;
  while (i < limite && a.charCodeAt(i) === b.charCodeAt(i)) i++;
  return i;
}

function suffixeCommun(a, b, limite) {
  let k = 0;
  while (k + BLOC <= limite
      && a.slice(a.length - k - BLOC, a.length - k) === b.slice(b.length - k - BLOC, b.length - k)) k += BLOC;
  while (k < limite && a.charCodeAt(a.length - 1 - k) === b.charCodeAt(b.length - 1 - k)) k++;
  return k;
}

/**
 * Après une frappe dans un grand texte, seule la zone touchée est redécoupée :
 * les jetons d'avant sont gardés et ceux d'après simplement décalés, dès que le
 * nouveau découpage retombe sur une frontière de l'ancien. Le découpage ne
 * dépend que du texte qui suit sa position de départ, ce qui rend le raccord sûr.
 */
function redecouper(ancien) {
  const prefixe = prefixeCommun(ancien, texte);
  const suffixe = suffixeCommun(ancien, texte, Math.min(ancien.length, texte.length) - prefixe);
  const delta = texte.length - ancien.length;
  const finAncienne = ancien.length - suffixe;      // fin de la zone modifiée, dans l'ancien texte
  const finNouvelle = texte.length - suffixe;       // la même, dans le nouveau
  const debutLigne = prefixe === 0 ? 0 : texte.lastIndexOf("\n", prefixe - 1) + 1;
  // Sont gardés les jetons finis avant le saut de ligne précédent : un jeton qui
  // l'englobe (chaîne ou commentaire non refermé) peut encore s'allonger.
  const gardes = premierJeton(Math.max(0, debutLigne - 1));
  let depart = debutLigne;
  if (gardes < nJetons && jetons[3 * gardes] < debutLigne) depart = jetons[3 * gardes];
  if (depart === 0) {
    decouper();
    return;
  }
  const anciens = jetons;
  const nAnciens = nJetons;
  let reprise = gardes;                             // premier ancien jeton situé après la zone modifiée
  let haut = nAnciens;
  while (reprise < haut) {
    const milieu = (reprise + haut) >> 1;
    if (anciens[3 * milieu] < finAncienne) reprise = milieu + 1;
    else haut = milieu;
  }
  jetons = new Int32Array(Math.max(3072, 3 * (nAnciens + 256)));
  jetons.set(anciens.subarray(0, 3 * gardes));
  nJetons = gardes;
  MOTIF.lastIndex = depart;
  let raccord = -1;
  let trouve;
  while ((trouve = MOTIF.exec(texte)) !== null) {
    const mot = trouve[0];
    const a = trouve.index;
    if (mot.length === 0) {
      MOTIF.lastIndex = a + 1;
      continue;
    }
    const classe = classer(mot, a);
    if (!classe) continue;
    if (a >= finNouvelle) {
      const cible = a - delta;
      while (reprise < nAnciens && anciens[3 * reprise] < cible) reprise++;
      if (reprise < nAnciens && anciens[3 * reprise] === cible) {
        raccord = reprise;
        break;
      }
    }
    ajouter(a, a + mot.length, classe);
  }
  if (raccord < 0) return;
  const total = nJetons + nAnciens - raccord;
  if (3 * total > jetons.length) {
    const plusGrand = new Int32Array(3 * total + 768);
    plusGrand.set(jetons.subarray(0, 3 * nJetons));
    jetons = plusGrand;
  }
  let sortie = 3 * nJetons;
  for (let i = 3 * raccord; i < 3 * nAnciens; i += 3) {
    jetons[sortie++] = anciens[i] + delta;
    jetons[sortie++] = anciens[i + 1] + delta;
    jetons[sortie++] = anciens[i + 2];
  }
  nJetons = total;
}

/** Vérifie que le découpage courant est celui d'un découpage complet (sert aux essais). */
export function controlerDecoupage() {
  const actuels = jetons.slice(0, 3 * nJetons);
  decouper();
  if (actuels.length !== 3 * nJetons) return false;
  for (let i = 0; i < actuels.length; i++) if (actuels[i] !== jetons[i]) return false;
  return true;
}

function premierJeton(position) {
  let bas = 0;
  let haut = nJetons;
  while (bas < haut) {
    const milieu = (bas + haut) >> 1;
    if (jetons[3 * milieu + 1] <= position) bas = milieu + 1;
    else haut = milieu;
  }
  return bas;
}

function enrober(a, b, classe) {
  const contenu = echapper(texte.slice(a, b));
  return classe ? `<span class="${classe}">${contenu}</span>` : contenu;
}

/** Un fragment de texte, recoupé par les marques qui le traversent. */
function morceau(a, b, classe) {
  if (listeMarques.length === 0) return enrober(a, b, classe);
  let html = "";
  let position = a;
  while (position < b) {
    let suivant = b;
    let classes = classe;
    for (const marque of listeMarques) {
      if (marque.b <= position || marque.a >= b) continue;
      if (marque.a > position) {
        if (marque.a < suivant) suivant = marque.a;
      } else {
        classes = classes ? classes + " " + marque.classe : marque.classe;
        if (marque.b < suivant) suivant = marque.b;
      }
    }
    html += enrober(position, suivant, classes);
    position = suivant;
  }
  return html;
}

function htmlPlage(a, b) {
  let html = "";
  let position = a;
  for (let i = premierJeton(a); i < nJetons; i++) {
    const debut = jetons[3 * i];
    if (debut >= b) break;
    const fin = Math.min(jetons[3 * i + 1], b);
    if (debut > position) html += morceau(position, debut, "");
    html += morceau(Math.max(debut, a), fin, CLASSES[jetons[3 * i + 2]]);
    position = fin;
  }
  if (position < b) html += morceau(position, b, "");
  return html;
}

function htmlNumeros(p, d) {
  const largeur = String(debuts.length).length;
  const erreur = marques.has("err") ? ligneDe(marques.get("err").a) : -1;
  const lignes = [];
  for (let ligne = p; ligne < d; ligne++) {
    const numero = String(ligne + 1).padStart(largeur);
    if (ligne === erreur) lignes.push(`<span class="faute">${numero}</span>`);
    else if (ligne === ligneCurseur) lignes.push(`<span class="ici">${numero}</span>`);
    else lignes.push(numero);
  }
  return lignes.join("\n");
}

// --------------------------------------------------------------------- rendu
function planifier() {
  if (!demande) demande = requestAnimationFrame(rendre);
}

function rendre() {
  demande = 0;
  const haut = saisie.scrollTop;
  const lignes = debuts.length;
  const visible = Math.floor(Math.max(0, haut - MARGE_HAUT) / H);
  const p = borne(Math.floor(visible / PAS) * PAS - PAS, 0, Math.max(0, lignes - 1));
  const d = Math.min(lignes, p + Math.ceil(zone.clientHeight / H) + 3 * PAS);
  if (sale || p !== premiere || d !== derniere) {
    premiere = p;
    derniere = d;
    sale = false;
    const a = debuts[p];
    const b = d < lignes ? debuts[d] - 1 : texte.length;
    calque.innerHTML = b - a > LIMITE_FENETRE
      ? echapper(texte.slice(a, a + LIMITE_FENETRE))
      : htmlPlage(a, b);
    numeros.innerHTML = htmlNumeros(p, d);
  }
  const dy = p * H - haut;
  calque.style.transform = `translate(${-saisie.scrollLeft}px, ${dy}px)`;
  numeros.style.transform = `translateY(${dy}px)`;
  barre.style.transform = `translateY(${MARGE_HAUT + ligneCurseur * H - haut}px)`;
}

function indexer() {
  const liste = [0];
  let position = texte.indexOf("\n");
  while (position !== -1) {
    liste.push(position + 1);
    position = texte.indexOf("\n", position + 1);
  }
  debuts = liste;
}

// --------------------------------------------------------------------- lignes
/** Numéro (à partir de 0) de la ligne qui contient `position`. */
export function ligneDe(position) {
  let bas = 0;
  let haut = debuts.length - 1;
  while (bas < haut) {
    const milieu = (bas + haut + 1) >> 1;
    if (debuts[milieu] <= position) bas = milieu;
    else haut = milieu - 1;
  }
  return bas;
}

export const debutDeLigne = (ligne) => debuts[borne(ligne, 0, debuts.length - 1)];

export function finDeLigne(ligne) {
  return ligne + 1 < debuts.length ? debuts[ligne + 1] - 1 : texte.length;
}

export const nombreDeLignes = () => debuts.length;
export const lire = () => texte;

function colonnesEcran(ligne, position) {
  const fin = Math.min(position, debuts[ligne] + 4000);
  let colonnes = 0;
  for (let i = debuts[ligne]; i < fin; i++) {
    colonnes += texte.charCodeAt(i) === 9 ? 4 - (colonnes % 4) : 1;
  }
  return colonnes;
}

// -------------------------------------------------------------------- curseur
function infos() {
  const position = saisie.selectionDirection === "backward" ? curseur.debut : curseur.fin;
  const ligne = ligneDe(position);
  let colonne = 0;
  for (let i = debuts[ligne]; i < position; i++) {
    const code = texte.charCodeAt(i);
    if (code < 0xdc00 || code > 0xdfff) colonne++;   // une paire de substituts compte pour un caractère
  }
  return { debut: curseur.debut, fin: curseur.fin, position, ligne: ligne + 1, colonne: colonne + 1 };
}

function majLigne() {
  const position = saisie.selectionDirection === "backward" ? curseur.debut : curseur.fin;
  const ligne = ligneDe(position);
  if (ligne !== ligneCurseur) {
    ligneCurseur = ligne;
    sale = true;
  }
  planifier();
}

function lireCurseur() {
  const debut = saisie.selectionStart;
  const fin = saisie.selectionEnd;
  if (debut === curseur.debut && fin === curseur.fin) return;
  curseur = { debut, fin };
  majLigne();
  emettre("curseur", { ...infos(), source: "utilisateur" });
}

export const curseurActuel = () => infos();

/** Place le curseur ; `source` nomme la vue à l'origine du geste, qui n'a pas à le suivre. */
export function poserCurseur(a, b = a, { focus = false, source = "vue" } = {}) {
  a = borne(a, 0, texte.length);
  b = borne(b, a, texte.length);
  curseur = { debut: a, fin: b };
  saisie.setSelectionRange(a, b);
  if (focus) saisie.focus({ preventScroll: true });
  majLigne();
  emettre("curseur", { ...infos(), source });
}

/** Fait défiler l'éditeur pour montrer `position`. */
export function montrer(position, viser = "proche") {
  position = borne(position, 0, texte.length);
  const ligne = ligneDe(position);
  const y = ligne * H;
  const hauteur = saisie.clientHeight;
  const haut = saisie.scrollTop;
  if (viser === "haut") saisie.scrollTop = Math.max(0, y - Math.round(hauteur * 0.2));
  else if (y < haut + H || y > haut + hauteur - 3 * H) {
    saisie.scrollTop = Math.max(0, y - Math.round(hauteur * 0.38));
  }
  const x = MARGE_GAUCHE + colonnesEcran(ligne, position) * largeurCar;
  const gauche = saisie.scrollLeft;
  const largeur = saisie.clientWidth;
  if (x < gauche + 30 || x > gauche + largeur - 60) {
    saisie.scrollLeft = Math.max(0, x - Math.round(largeur * 0.3));
  }
  planifier();
}

// -------------------------------------------------------------------- marques
const CLASSES_MARQUES = { sel: "m-sel", survol: "m-survol", err: "m-err" };

export function marquer(nom, a, b) {
  a = borne(a, 0, texte.length);
  b = borne(b, a, texte.length);
  const actuelle = marques.get(nom);
  if (actuelle && actuelle.a === a && actuelle.b === b) return;
  if (b > a) marques.set(nom, { a, b, classe: CLASSES_MARQUES[nom] });
  else marques.delete(nom);
  listeMarques = [...marques.values()];
  sale = true;
  planifier();
}

export function demarquer(nom) {
  if (!marques.delete(nom)) return;
  listeMarques = [...marques.values()];
  sale = true;
  planifier();
}

/** Montre une étendue du texte : marque, défilement et curseur à son début. */
export function selectionner(a, b, { viser = "proche", focus = false, source = "vue" } = {}) {
  marquer("sel", a, b);
  montrer(a, viser);
  poserCurseur(a, a, { focus, source });
}

/** Après une frappe, l'erreur soulignée suit le texte jusqu'à la prochaine analyse. */
function ajusterMarques(position, delta) {
  marques.delete("sel");
  marques.delete("survol");
  const erreur = marques.get("err");
  if (erreur && delta !== 0) {
    const point = delta > 0 ? position - delta : position;
    if (point <= erreur.a) {
      erreur.a = Math.max(point, erreur.a + delta);
      erreur.b = Math.max(erreur.a + 1, erreur.b + delta);
    } else if (point < erreur.b) {
      erreur.b = Math.max(erreur.a + 1, erreur.b + delta);
    }
    erreur.a = borne(erreur.a, 0, texte.length);
    erreur.b = borne(erreur.b, erreur.a, texte.length);
  }
  listeMarques = [...marques.values()];
}

// ---------------------------------------------------------------------- texte
/** Remplace tout le texte (ouverture d'un fichier, d'un exemple). */
export function definirTexte(nouveau) {
  saisie.value = nouveau;
  texte = saisie.value;             // la zone de saisie normalise les fins de ligne
  marques.clear();
  listeMarques = [];
  indexer();
  decouper();
  curseur = { debut: 0, fin: 0 };
  ligneCurseur = 0;
  saisie.setSelectionRange(0, 0);
  saisie.scrollTop = 0;
  saisie.scrollLeft = 0;
  sale = true;
  planifier();
  etat.version++;
  emettre("texte", { cause: "chargement" });
  emettre("curseur", { ...infos(), source: "chargement" });
}

export const focaliser = () => saisie.focus({ preventScroll: true });
export const estColore = () => texte.length <= LIMITE_COULEUR;

saisie.addEventListener("input", () => {
  const ancien = texte;
  texte = saisie.value;
  ajusterMarques(saisie.selectionStart, texte.length - ancien.length);
  indexer();
  if (ancien.length > SEUIL_PARTIEL && nJetons > 0 && texte.length <= LIMITE_COULEUR) redecouper(ancien);
  else decouper();
  sale = true;
  etat.version++;
  curseur = { debut: saisie.selectionStart, fin: saisie.selectionEnd };
  majLigne();
  emettre("texte", { cause: "saisie" });
  emettre("curseur", { ...infos(), source: "utilisateur" });
});

saisie.addEventListener("keydown", (evenement) => {
  if (evenement.key !== "Tab" || evenement.shiftKey || evenement.ctrlKey
      || evenement.altKey || evenement.metaKey) return;
  // Tab indente ; Maj+Tab quitte la zone de saisie, pour la navigation au clavier.
  evenement.preventDefault();
  if (!document.execCommand("insertText", false, "    ")) {
    saisie.setRangeText("    ", saisie.selectionStart, saisie.selectionEnd, "end");
    saisie.dispatchEvent(new Event("input", { bubbles: true }));
  }
});

saisie.addEventListener("scroll", planifier, { passive: true });
for (const nom of ["keyup", "pointerup", "focus", "select"]) saisie.addEventListener(nom, lireCurseur);
document.addEventListener("selectionchange", () => {
  if (document.activeElement === saisie) lireCurseur();
});
gouttiere.addEventListener("wheel", (evenement) => {
  saisie.scrollTop += evenement.deltaY;
}, { passive: true });
new ResizeObserver(planifier).observe(zone);

policesPretes.then(() => {
  const style = getComputedStyle(saisie);
  oublierMesures();
  largeurCar = largeurTexte("0".repeat(40), `${style.fontSize} ${style.fontFamily}`) / 40 || largeurCar;
  sale = true;
  planifier();
});
