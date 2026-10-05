// La mécanique des décisions d'une fonction, dessinée comme un organigramme
// (le dessin lui-même est dans organigramme.js) et reliée au texte de l'éditeur.

import {
  $, etat, sur, api, annoncer, differer, echapper, frais, pluriel, nombre, borne,
  policesPretes, rienEncore,
} from "./noyau.js";
import * as editeur from "./editeur.js";
import { construire, estReplie, niveauComplexite, niveauDuPli, nomFonction } from "./organigramme.js";
import { estVisible } from "./volets.js";

const vue = $("vue-decisions");
const choix = $("choix-fonction");
const suivreCase = $("suivre-decisions");
const resume = $("decisions-resume");
const toile = $("decisions-toile");

let source = null;          // analyse valide dont viennent les fonctions listées
let fonctions = [];
let courante = null;        // fonction affichée
let aRefaire = true;
let demande = 0;
let dessin = null;          // { largeur, hauteur } du diagramme affiché
let cleAffichee = "";
let zoom = 1;
let ajuste = true;
let etapes = [];            // { a, b, element } pour chaque forme liée au texte
let active = null;
let donnees = null;         // dernière réponse du serveur, pour redessiner sans la redemander
let niveauMax = Infinity;   // niveaux d'imbrication dessinés ; les corps plus profonds sont repliés
let bascules = new Set();   // corps dont l'état est l'inverse de celui que donne le niveau

// ------------------------------------------------------------------ fonctions
function libelle(f) {
  if (f.genre === "script") return `Script, niveau principal, complexité ${f.complexity}`;
  return `${nomFonction(f)}, ligne ${f.ligne}, complexité ${f.complexity}`;
}

/** Nom et rang parmi les homonymes : reconnaît une fonction d'une analyse à la suivante. */
function cleFonction(f) {
  let rang = 0;
  for (const autre of fonctions) {
    if (autre === f) break;
    if (autre.nom === f.nom) rang++;
  }
  return `${f.nom}#${rang}`;
}

function fonctionA(position) {
  let trouvee = fonctions[0];
  for (const f of fonctions) {
    if (f.a > position) break;
    if (position <= f.b) trouvee = f;       // la dernière trouvée est la plus intérieure
  }
  return trouvee;
}

function choisirFonction(nouveau) {
  if (!fonctions.length) return null;
  if (nouveau) {
    return fonctions.reduce((meilleure, f) => (f.complexity > meilleure.complexity ? f : meilleure));
  }
  if (suivreCase.checked) return fonctionA(editeur.curseurActuel().position);
  return fonctions.find((f) => cleFonction(f) === cleAffichee) || fonctions[0];
}

function remplirChoix() {
  let html = "";
  for (const f of fonctions) html += `<option value="${f.id}">${echapper(libelle(f))}</option>`;
  choix.innerHTML = html;
  choix.disabled = fonctions.length === 0;
}

// --------------------------------------------------------------------- rendu
function tuile(valeur, nom, aide) {
  return `<div class="chiffre" title="${echapper(aide)}"><span class="chiffre-valeur">${nombre(valeur)}</span>`
    + `<span class="chiffre-nom">${nom}</span></div>`;
}

function dessinerResume(mesures, termes) {
  const c = mesures.complexity;
  let html = tuile(c, `complexité ${niveauComplexite(c)}`,
    "1, plus 1 par test, par boucle et par « and » ou « or » dans une condition")
    + tuile(mesures.decisions, mesures.decisions > 1 ? "tests" : "test", "Conditions if et elseif")
    + tuile(mesures.loops, mesures.loops > 1 ? "boucles" : "boucle", "Boucles while, repeat et for")
    + tuile(mesures.nesting, mesures.nesting > 1 ? "niveaux imbriqués" : "niveau imbriqué",
      "Profondeur maximale des tests et des boucles")
    + tuile(mesures.exits, mesures.exits > 1 ? "sorties return" : "sortie return", "Instructions return")
    + tuile(mesures.statements, mesures.statements > 1 ? "instructions" : "instruction",
      "Instructions de la fonction, sans compter celles des fonctions qu'elle contient");
  if (termes.length) {
    html += `<div class="termes"><div class="termes-titre">Ce que lisent les conditions</div>`
      + `<div class="termes-liste">`;
    for (const terme of termes) {
      html += `<span class="terme" title="${pluriel(terme.nombre, "lecture", "lectures")}">`
        + `${echapper(terme.nom)}<b>${terme.nombre}</b></span>`;
    }
    html += `</div></div>`;
  }
  resume.innerHTML = html;
}

function appliquerZoom() {
  const svg = toile.firstElementChild;
  if (!dessin || !svg || svg.tagName.toLowerCase() !== "svg" || !toile.clientWidth) return;
  // Ajusté à la largeur du volet, sans descendre sous une taille lisible.
  if (ajuste) zoom = borne((toile.clientWidth - 6) / dessin.largeur, 0.8, 1);
  svg.setAttribute("width", Math.round(dessin.largeur * zoom));
  svg.setAttribute("height", Math.round(dessin.hauteur * zoom));
}

function definirZoom(valeur) {
  ajuste = false;
  zoom = borne(valeur, 0.25, 2.5);
  appliquerZoom();
}

function marquerActive(position, defiler) {
  let meilleure = null;
  for (const etape of etapes) {
    if (etape.a <= position && position <= etape.b
        && (!meilleure || etape.b - etape.a < meilleure.b - meilleure.a)) meilleure = etape;
  }
  if (active && (!meilleure || active !== meilleure.element)) active.classList.remove("actif");
  active = meilleure ? meilleure.element : null;
  if (!active) return;
  active.classList.add("actif");
  if (defiler) active.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function vider(titre, texte) {
  dessin = null;
  etapes = [];
  active = null;
  resume.innerHTML = "";
  toile.innerHTML = `<div class="vide"><strong>${titre}</strong>${texte}</div>`;
}

async function rafraichir() {
  if (!estVisible("decisions")) return;
  if (!source) {
    vue.classList.remove("perime");
    choix.innerHTML = "";
    choix.disabled = true;
    if (rienEncore()) return;
    vider("Pas encore de diagramme",
      "Le diagramme des décisions apparaît dès que la syntaxe du script est valide.");
    return;
  }
  vue.classList.toggle("perime", !frais());
  if (!frais() || !aRefaire || !courante) return;
  aRefaire = false;
  const f = courante;
  const numero = ++demande;
  choix.value = String(f.id);
  let reponse;
  try {
    reponse = await api("decisions", { doc: source.doc, fonction: f.id });
  } catch (erreur) {
    if (numero === demande) {
      aRefaire = true;
      if (erreur.statut !== 410) annoncer(erreur.message);
    }
    return;
  }
  await policesPretes;
  if (numero !== demande) return;
  const memeFonction = cleFonction(f) === cleAffichee;
  cleAffichee = cleFonction(f);
  if (!memeFonction) bascules = new Set();
  donnees = reponse;
  dessinerResume(reponse.mesures, reponse.termes);
  tracer(memeFonction);
}

/** Dessine la dernière réponse reçue ; `garder` conserve le zoom et la position de lecture. */
function tracer(garder) {
  if (!donnees || !courante) return;
  const titre = courante.genre === "script" ? `script ${etat.nom}` : nomFonction(courante);
  dessin = construire(donnees.flux, titre, { niveauMax, bascules });
  toile.innerHTML = dessin.svg;
  etapes = [];
  for (const element of toile.querySelectorAll("g.etape, g.pli[data-a]")) {
    etapes.push({ a: Number(element.dataset.a), b: Number(element.dataset.b), element });
  }
  active = null;
  if (!garder) {
    ajuste = true;
    toile.scrollTop = 0;
    toile.scrollLeft = 0;
  }
  appliquerZoom();
  marquerActive(editeur.curseurActuel().position, false);
}

// --------------------------------------------------------------------- replis
const enTete = (clePli) => toile.querySelector(`g.etape[data-plis~="${clePli}"]`);

/** Replie les corps ouverts parmi `cles` ; s'ils sont tous repliés, les déplie. */
function basculerPlis(cles) {
  const ouverts = cles.filter((clePli) => !estReplie(niveauDuPli(clePli), clePli, { niveauMax, bascules }));
  for (const clePli of ouverts.length ? ouverts : cles) {
    if (bascules.has(clePli)) bascules.delete(clePli);
    else bascules.add(clePli);
  }
  // Le test ou la boucle concernés restent à la même place sous les yeux.
  const avant = enTete(cles[0]);
  const hautAvant = avant ? avant.getBoundingClientRect().top : null;
  tracer(true);
  const apres = enTete(cles[0]);
  if (apres && hautAvant !== null) toile.scrollTop += apres.getBoundingClientRect().top - hautAvant;
}

const boutonsNiveau = [...document.querySelectorAll("#niveaux [data-niveau]")];
for (const bouton of boutonsNiveau) {
  bouton.addEventListener("click", () => {
    niveauMax = bouton.dataset.niveau === "tout" ? Infinity : Number(bouton.dataset.niveau) - 1;
    bascules = new Set();
    for (const autre of boutonsNiveau) autre.setAttribute("aria-pressed", String(autre === bouton));
    tracer(false);
    if (active) active.scrollIntoView({ block: "center", inline: "nearest" });
  });
}

function montrer(f) {
  if (!f) return;
  courante = f;
  aRefaire = true;
  rafraichir();
}

// ---------------------------------------------------------------- interactions
choix.addEventListener("change", () => {
  const f = fonctions.find((candidate) => String(candidate.id) === choix.value);
  if (!f) return;
  suivreBientot.annuler();
  montrer(f);
  if (!frais()) return;
  editeur.marquer("sel", f.a, Math.min(f.b, editeur.finDeLigne(editeur.ligneDe(f.a))));
  editeur.montrer(f.a, "haut");
  editeur.poserCurseur(f.a, f.a, { source: "decisions" });
});

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

function allerEtape(element, focus = false) {
  if (!frais()) return;
  if (active && active !== element) active.classList.remove("actif");
  active = element;
  element.classList.add("actif");
  editeur.selectionner(Number(element.dataset.a), Number(element.dataset.b), { source: "decisions", focus });
}

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
  if (element) allerEtape(element);
});

toile.addEventListener("dblclick", (evenement) => {
  if (depliAuClic) return;
  const element = evenement.target.closest("g.etape[data-plis]");
  if (!element) return;
  evenement.preventDefault();
  basculerPlis(element.dataset.plis.split(" "));
});

toile.addEventListener("pointerover", (evenement) => {
  const element = evenement.target.closest("g.etape, g.pli[data-a]");
  if (element && frais()) editeur.marquer("survol", Number(element.dataset.a), Number(element.dataset.b));
  else editeur.demarquer("survol");
});
toile.addEventListener("pointerleave", () => editeur.demarquer("survol"));

toile.addEventListener("keydown", (evenement) => {
  if (!etapes.length) return;
  const rang = etapes.findIndex((etape) => etape.element === document.activeElement);
  let cible = -1;
  if (evenement.key === "ArrowDown" || evenement.key === "ArrowRight") cible = Math.min(etapes.length - 1, rang + 1);
  else if (evenement.key === "ArrowUp" || evenement.key === "ArrowLeft") cible = Math.max(0, rang - 1);
  else if ((evenement.key === "Enter" || evenement.key === " ") && rang >= 0) {
    evenement.preventDefault();
    const choisie = etapes[rang].element;
    if (choisie.dataset.pli) basculerPlis([choisie.dataset.pli]);
    else allerEtape(choisie, evenement.key === "Enter");
    return;
  } else return;
  evenement.preventDefault();
  const element = etapes[cible].element;
  element.focus({ preventScroll: true });
  element.scrollIntoView({ block: "nearest", inline: "nearest" });
  allerEtape(element);
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

const suivreBientot = differer((curseur) => {
  if (!source || !frais() || !estVisible("decisions")) return;
  if (suivreCase.checked) {
    const f = fonctionA(curseur.position);
    if (f !== courante) {
      montrer(f);
      return;
    }
  }
  if (curseur.source !== "decisions") marquerActive(curseur.position, true);
}, 80);

suivreCase.addEventListener("change", () => {
  if (suivreCase.checked) suivreBientot(editeur.curseurActuel());
});

sur("analyse", ({ nouveau }) => {
  if (etat.valide !== source) {
    source = etat.valide;
    fonctions = source ? source.fonctions : [];
    remplirChoix();
    courante = choisirFonction(nouveau);
    if (nouveau) cleAffichee = "";
    aRefaire = true;
  }
  rafraichir();
});

sur("curseur", (curseur) => {
  if (curseur.source !== "chargement") suivreBientot(curseur);
});

sur("fonction", ({ id }) => {
  suivreBientot.annuler();
  montrer(fonctions.find((f) => f.id === id));
});

sur("vue", ({ id }) => {
  if (id === "decisions") rafraichir();
});
