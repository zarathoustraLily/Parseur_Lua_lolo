-- Résolution d'une attaque : un exemple pour lire la mécanique des décisions.
-- Ouvrez l'onglet « Décisions » et placez le curseur dans une fonction.
local Regles <const> = {
    CritiqueDeBase = 0.05,
    MultiplicateurCritique = 2,
    SeuilExecution = 0.15,
}

local Bestiaire = {
    Squelette = { Vie = 40, Armure = 2, Faiblesses = { "contondant" } },
    Spectre = { Vie = 25, Armure = 0, Intangible = true },
    Gardien = { Vie = 120, Armure = 8, Bouclier = 3 },
}

local function contient(liste, valeur)
    for _, element in ipairs(liste or {}) do
        if element == valeur then
            return true
        end
    end
    return false
end

local function chanceDeCritique(heros, arme)
    local chance = Regles.CritiqueDeBase + (arme.Critique or 0)
    if heros.Benedictions.Artemis then
        chance = chance + 0.15
    end
    if heros.Vie < heros.VieMax * 0.25 and heros.Benedictions.Ares then
        chance = chance * 2
    end
    return math.min(chance, 1)
end

function ResoudreAttaque(heros, cible, arme)
    if not cible or cible.Vie <= 0 then
        return false, "cible invalide"
    end
    if cible.Intangible and arme.Type ~= "magique" then
        Annoncer("L'attaque traverse " .. cible.Nom)
        return false, "intangible"
    end

    local degats = arme.Degats + heros.Force
    if contient(cible.Faiblesses, arme.Type) then
        degats = degats * 1.5
    elseif cible.Bouclier and cible.Bouclier > 0 then
        cible.Bouclier = cible.Bouclier - 1
        return true, 0
    else
        degats = degats - cible.Armure
    end

    if math.random() < chanceDeCritique(heros, arme) then
        degats = degats * Regles.MultiplicateurCritique
        Annoncer("Coup critique !")
    end

    for _, effet in ipairs(heros.Effets) do
        if effet.Expire then
            goto suivant
        end
        degats = effet:Modifier(degats, cible)
        ::suivant::
    end

    cible.Vie = cible.Vie - math.max(degats, 0)
    if cible.Vie <= cible.VieMax * Regles.SeuilExecution and heros.Benedictions.Thanatos then
        cible.Vie = 0
    end
    if cible.Vie <= 0 then
        Evenements.Declencher("mort", cible, function(temoin)
            temoin:Reagir(cible)
        end)
    end
    return true, degats
end

Evenements.Ecouter("mort", function(cible)
    while #cible.Butin > 0 do
        local objet = table.remove(cible.Butin)
        if objet.Rare or math.random() < 0.5 then
            Monde.Deposer(objet, cible.Position)
        end
    end
end)

return { Resoudre = ResoudreAttaque, Bestiaire = Bestiaire }
