-- Un fichier volontairement faux, pour voir comment une erreur est signalée.
local inventaire = { "épée", "arc", "bouclier" }

local function compter(liste)
    local total = 0
    for _, objet in ipairs(liste) do
        total = total + 1
    end
    return total
end

if compter(inventaire) > 2 then
    print("Inventaire plein")
else
    print("Encore de la place"
end
