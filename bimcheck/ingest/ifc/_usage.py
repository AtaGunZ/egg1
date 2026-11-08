"""Space usage classification from names/properties in Turkish, English and German.

Vocabulary (CONTRACTS section 1): living_room | bedroom | kitchen | bathroom | wc | corridor | hall | stair |
storage | balcony | terrace | technical | garage | commercial | other
"""
from __future__ import annotations

import re
import unicodedata

from ._props import PropBag, norm_key

_TR_MAP = str.maketrans({
    "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ç": "c", "Ç": "c", "ğ": "g", "Ğ": "g",
    "ö": "o", "Ö": "o", "ü": "u", "Ü": "u", "ä": "a", "Ä": "a", "ß": "ss",
})


def fold(text: str) -> str:
    """Lower-case, strip diacritics (Turkish/German), collapse German transliterations (oe/ue/ae)."""
    text = text.translate(_TR_MAP).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


# (usage, regex over folded text). Order matters: first match wins. Regexes use \b on folded text.
_RULES: list[tuple[str, str]] = [
    # --- explicit compound / specific first ------------------------------------------------------
    ("stair", r"\b(merdiven\w*|treppe\w*|stair\w*|staircase|stairwell|escalier|trappenhaus)\b"),
    ("garage", r"\b(garaj\w*|garage\w*|otopark\w*|carport|parking|park\w* yeri|tiefgarage|stellplatz\w*)\b"),
    ("balcony", r"\b(balkon\w*|balcon\w*|balcony|loggia|altan)\b"),
    ("terrace", r"\b(teras\w*|terrace|terrasse\w*|dachterrasse|veranda|patio|sundeck|dachgarten|roof ?garden)\b"),
    ("bathroom", r"\b(banyo\w*|bad|bade\w*|badezimmer|bath\w*|dus\w*|duschbad|shower\w*|wanne|hamam|sauna|wellness|"
                 r"tam banyo|ebeveyn banyo\w*|wetroom|wet room|ensuite|en suite)\b"),
    ("wc", r"\b(wc\w*|toilet\w*|toilette\w*|tuvalet\w*|lavabo\w*|restroom|rest room|washroom|lavatory|powder room|"
           r"gaste[- ]?wc|klo|aborte?|gaestewc|cloakroom|urinal)\b"),
    ("kitchen", r"\b(mutfak\w*|kitchen\w*|kuche\w*|kueche\w*|kochen|koch\w*|kuchen|pantry|kiler mutfak|cocina|"
                r"yemek pisirme|amerikan mutfak|teekueche|teekuche)\b"),
    ("corridor", r"\b(koridor\w*|corridor\w*|korridor\w*|flur\w*|gang|gange|hallway\w*|passage\w*|passageway|"
                 r"circulation|verkehrsfl\w*|erschliessung\w*|walkway|arcade|galeri koridor)\b"),
    ("hall", r"\b(hol|hol\w*|hall|halle|diele|foyer\w*|giris\w*|antre|lobby|vestibule|vestibul\w*|entrance\w*|entry|"
             r"eingang\w*|entree|windfang|empfang\w*|reception|lounge area|vorraum|vorplatz)\b"),
    ("technical", r"\b(teknik\w*|technik\w*|technical|mechanical|mekanik\w*|kazan\w*|boiler\w*|heizung\w*|heizraum\w*|"
                  r"heiz\w*|utility|utilities|hauswirtschaft\w*|hwr|waschkuche|waschkueche|waschraum|laundry|"
                  r"camasir\w*|electrical|elektrik\w*|elektro\w*|server|plant room|machine room|shaft|schacht|"
                  r"sig?inak|siginak|asansor\w*|aufzug\w*|elevator\w*|lift|tank\w*|janitor|hausanschluss\w*|"
                  r"hvac|riser|cooling|kuhl\w*|kuehl\w*)\b"),
    ("storage", r"\b(depo\w*|kiler\w*|esya\w*|abstell\w*|speicher|lager\w*|storage|store ?room|closet|wardrobe|"
                r"garderobe\w*|giyinme|dolap|dressing|archive|archiv\w*|arsiv\w*|besenkammer|kammer|stauraum|"
                r"cupboard|locker|ambar|sundurma|trockenraum|keller\w*|basement store|cellar)\b"),
    ("commercial", r"\b(dukkan\w*|magaza\w*|shop|store|office\w*|buro\w*|buero\w*|ofis\w*|retail|geschaft\w*|"
                   r"geschaeft\w*|laden|ladenlokal|restoran\w*|restaurant\w*|cafe\w*|kafe\w*|isyeri\w*|is yeri|"
                   r"praxis|kanzlei|studio apartment office|toplanti|meeting|conference|konferenz\w*|"
                   r"sinif\w*|classroom|workshop|werkstatt|atolye\w*|showroom|market|kiosk|"
                   r"eczane|pharmacy|clinic|klinik\w*)\b"),
    # --- habitable rooms --------------------------------------------------------------------------
    ("bedroom", r"\b(yatak\w*|ebeveyn\w*|cocuk\w*|bedroom\w*|bed room|bed|master\w*|schlaf\w*|kind|kinder\w*|"
                r"eltern\w*|gastezimmer|gaestezimmer|guest ?room\w*|misafir odasi|misafir|children\w*|nursery|"
                r"kid\w*|dormitor\w*|suite|jugendzimmer|teen\w*|sleeping)\b"),
    ("living_room", r"\b(salon\w*|oturma\w*|yasam\w*|yasama|living\w*|lounge|sitting|wohn\w*|stube|familien\w*|"
                    r"family room|essen|esszimmer\w*|speis\w*|dining\w*|yemek\w*|aile odasi|konut odasi|"
                    r"wohnzimmer|wohnkuche|wohnkueche|great room|tv room|tv odasi|arbeitszimmer|study|"
                    r"calisma odasi\w*|library|kutuphane|bibliothek|loft|ofis odasi|"
                    r"hobby\w*|music room|wintergarten|winter garden|kis bahcesi|living/dining|"
                    r"wohn-?/?\s?essbereich|wohnbereich|aufenthalt\w*|common room|room)\b"),
]
_COMPILED = [(u, re.compile(rx)) for u, rx in _RULES]

# Property-based hints: map category descriptions of other tools to the vocabulary.
_PROP_NAME_KEYS = [
    "OccupancyType", "Category Description", "Raumkategorie", "Kategorie", "SpaceType", "Space Type", "Function",
    "Usage", "Use", "RoomType", "Room Type", "Raumart", "Nutzung", "Kullanim", "OmniClass Table 13 Category",
    "Raumname", "RoomName", "Room Name", "Name",
]


def classify_text(text: str | None):
    """Return (usage, matched_token) or (None, None)."""
    if not text or not isinstance(text, str):
        return None, None
    f = fold(text)
    # bathroom beats wc ("Bad/WC"); wc rule precedes none that would steal it
    for usage, rx in _COMPILED:
        m = rx.search(f)
        if m:
            # do not let generic 'room' word make living_room unless that is all there is
            tok = m.group(0)
            if usage == "living_room" and tok == "room":
                return None, None
            return usage, tok
    return None, None


def classify_space(name, long_name, object_type, description, bag: PropBag | None):
    """-> (usage, usage_source, matched_text)."""
    # 1) names (LongName is usually the descriptive one: ArchiCAD/Revit put the number into Name)
    for label, txt in (("LongName", long_name), ("Name", name), ("ObjectType", object_type), ("Description", description)):
        usage, tok = classify_text(txt)
        if usage:
            return usage, "name", f"{label}:{tok}"
    # 2) properties
    if bag is not None:
        for key in _PROP_NAME_KEYS:
            nk = norm_key(key)
            for sname, d in bag.psets.items():
                for k, v in d.items():
                    if norm_key(k) == nk and isinstance(v, str):
                        usage, tok = classify_text(v)
                        if usage:
                            return usage, "property", f"{sname}.{k}:{tok}"
    return "other", "none", None
