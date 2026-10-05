-- Lua 5.4 : tables, fonctions, attributs locaux et operateurs.
local PI <const> = 3.141592653589793
local catalogue = {
    titre = "Catalogue Lua",
    ["octets"] = "\x00\255",
    0x1.fp+3,
}

local function compter(...)
    local total = 0
    for _, valeur in ipairs({...}) do
        total = total + valeur
    end
    return total
end

function catalogue:prix(quantite)
    if quantite <= 0 then
        return nil, "Quantite invalide"
    elseif quantite > 10 then
        return quantite * PI // 2
    else
        return quantite * PI
    end
end

local masque = (1 << 4) | 3
repeat
    masque = masque >> 1
until masque == 0

return catalogue, compter(1, 2, 3)
