"""Turkish / English vocabulary: layer-name roles, room-name -> usage, view titles, number parsing."""
from __future__ import annotations

import re
import unicodedata

_TR_MAP = str.maketrans({"ç": "c", "Ç": "C", "ğ": "g", "Ğ": "G", "ı": "i", "İ": "I", "ö": "o", "Ö": "O", "ş": "s", "Ş": "S", "ü": "u", "Ü": "U",
                         "â": "a", "Â": "A", "î": "i", "û": "u"})


def fold(s: str) -> str:
    """Upper-case ASCII fold of Turkish text: 'Kapı Pencere' -> 'KAPI PENCERE'."""
    s = (s or "").translate(_TR_MAP)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.upper()


# ---------------------------------------------------------------------------------------------- layer roles
# (regex on folded layer name, role, confidence).  First match with highest confidence wins.
LAYER_NAME_RULES: list[tuple[str, str, float]] = [
    (r"(^|[^A-Z])(ARSA|PARSEL|PARCEL|PLOT|SITE ?BOUND|TAPU)($|[^A-Z])", "parcel", 0.75),
    (r"(^|[^A-Z])(MAHAL|ODA|ROOM|SPACE|MEKAN|ZONE)($|[^A-Z])|TEXT_MEKAN|MEKAN_ISIM", "room_label", 0.8),
    (r"(^|[^A-Z])(ALAN|AREA)($|[^A-Z])", "area_label", 0.7),
    (r"(^|[^A-Z])(OLCU|DIM|DIMS|DIMENSION|DIMENSIONS|OLCULENDIRME)($|[^A-Z])|IC OLCU|DIS OLCU", "dimension", 0.85),
    (r"(^|[^A-Z])(KOT|LEVEL|ELEV|ELEVATION|SPOT)($|[^A-Z])", "level_mark", 0.8),
    (r"MERDIVEN|(^|[^A-Z])(MER|MERD|STAIR|STAIRS|STEP)($|[^A-Z])", "stair", 0.85),
    (r"PENCERE|DOGRAMA|WINDOW|(^|[^A-Z])(WIN|PNC|CAM)($|[^A-Z])", "window", 0.8),
    (r"(^|[^A-Z])(KAPI|DOOR|KAPILAR)($|[^A-Z])", "door", 0.85),
    (r"(^|[^A-Z])KAPEN($|[^A-Z])", "door", 0.4),
    (r"DUVAR|(^|[^A-Z])(WALL|WALLS|MUR)($|[^A-Z])", "wall", 0.85),
    (r"KOLON|COLUMN|(^|[^A-Z])COL($|[^A-Z])", "column", 0.85),
    (r"(^|[^A-Z])(AKS|AKSLAR|GRID|AXIS|AXES|CENTERLINE)($|[^A-Z])", "grid", 0.85),
    (r"TEFRIS|MOBILYA|FURN|EKIPMAN|SIHHI|SANITARY|APAREY", "furniture", 0.8),
    (r"TARA|HATCH|DOLGU|PATTERN", "hatch", 0.7),
    (r"YAZI|TEXT|NOT(LAR)?($|[^A-Z])|ACIKLAMA|ANNO", "text", 0.6),
    (r"DEFPOINTS", "ignored", 0.95),
    (r"CATI|ROOF|KIRIS|BEAM|SIVA|YALITIM|BOYA|METAL|SUZGEC|SABITEL|DENIZLIK|INS($|[^A-Z])|IZOTO|TUGLA|CERCEVE", "annotation", 0.3),
]

ROLES = ["parcel", "wall", "door", "window", "stair", "room_label", "area_label", "dimension", "level_mark", "column", "grid",
         "furniture", "hatch", "text", "annotation", "ignored", "unknown"]


def role_from_name(name: str) -> tuple[str, float]:
    f = fold(name)
    f2 = re.sub(r"[_\-\.]+", " ", f).strip()
    best = ("unknown", 0.0)
    for pat, role, conf in LAYER_NAME_RULES:
        if re.search(pat, f2) or re.search(pat, f):
            if conf > best[1]:
                best = (role, conf)
    return best


# ---------------------------------------------------------------------------------------------- room usage
# vocabulary identical to CONTRACTS space.usage:
# living_room|bedroom|kitchen|bathroom|wc|corridor|hall|stair|storage|balcony|terrace|technical|garage|commercial|other
USAGE_RULES: list[tuple[str, str]] = [
    (r"\bWC\b|TUVALET|LAVABO WC|\bLV\b ?-? ?WC|\bLV-WC\b|KLOZET", "wc"),
    (r"BANYO|\bDUS\b|DUSLU|HAMAM|BATH|SHOWER|\bLV\b|LAVABO", "bathroom"),
    (r"MUTFAK|KITCHEN|ASPIRATOR|\bMTF\b|YEMEK ODASI|AMERIKAN", "kitchen"),
    (r"YATAK|BEDROOM|\bY\.? ?ODA|COCUK ODASI|EB\.? ?Y|MISAFIR ODASI|ODA ?\d", "bedroom"),
    (r"SALON|OTURMA|LIVING|SALA|ISTIRAHAT|TV ODASI|M\.?K\.?A\.?$|GENEL ODA|YASAM", "living_room"),
    (r"MERDIVEN|STAIR|YANGIN MERD|MERD\.", "stair"),
    (r"ASANSOR|ELEVATOR|\bLIFT\b|ASANS", "technical"),
    (r"KORIDOR|CORRIDOR|KOR\.|GECIS|BEKLEME", "corridor"),
    (r"\bHOL\b|HOLU|\bHALL\b|ANTRE|GIRIS|LOBI|LOBBY|KAT HOL|FUAYE|FOYER|VESTIYER", "hall"),
    (r"BALKON|BALCONY|LOCA", "balcony"),
    (r"TERAS|TERRACE|CATI KATI", "terrace"),
    (r"DEPO|KILER|STORAGE|ARSIV|ESYA|AMBAR|GIYINME|DRESSING|GARDROP|WARDROBE|CAMASIR", "storage"),
    (r"KAZAN|JENERATOR|SIGINAK|SIGINAK|HIDROFOR|POMPA|ELEKTRIK|ELEK\.|PANO|TESISAT|SAFT|SU DEPO|TEKNIK|MEKANIK|HABERLES|SAYAC|TRAFO|HAVALANDIRMA|BACA|KOMBI|ISI MERKEZI|SU YALITIM", "technical"),
    (r"OTOPARK|GARAJ|GARAGE|PARKING|ARAC", "garage"),
    (r"DUKKAN|MAGAZA|OFIS|BURO|OFFICE|SHOP|STORE|RESTORAN|LOKANTA|KAFE|ISYERI|TICARET|BANKA|DEPO-?\d|TOPLANTI", "commercial"),
]


def usage_from_name(name: str) -> str | None:
    f = fold(name)
    for pat, usage in USAGE_RULES:
        if re.search(pat, f):
            return usage
    return None


# words that make a text look like a room label (used for content-based role detection)
ROOM_WORDS = re.compile(
    r"\b(SALON|OTURMA|YATAK|EB\.?|MUTFAK|BANYO|WC|LV|HOL|HOLU|ANTRE|KORIDOR|BALKON|TERAS|DEPO|KILER|GIYINME|DUS|MERDIVEN|ASANSOR|DUKKAN|SIGINAK|"
    r"KAZAN|JENERATOR|HIDROFOR|OTOPARK|GARAJ|BEKLEME|MESCIT|ODA|ODASI|M\.?K\.?A\.?|LAVABO|TUVALET|GIRIS|BODRUM|OFIS|BURO|SALONU|HAVUZ|BAHCE|ZEMIN KAT HOLU|KAT HOLU)\b")


# ---------------------------------------------------------------------------------------------- view titles
VIEW_RULES: list[tuple[str, str]] = [
    (r"VAZIYET|APLIKASYON|SITE PLAN|PLOT PLAN|IMAR DURUMU|1/500|1/1000", "site_plan"),
    (r"KESIT|SECTION", "section"),
    (r"CEPHE|GORUNUS|ELEVATION|FACADE", "elevation"),
    (r"DETAY|DETAIL", "detail"),
    (r"KAT PLAN|KATLAR PLAN|KATI PLAN|PLANI|FLOOR PLAN|\bPLAN\b|CATI PLAN|TEMEL PLAN|KALIP PLAN", "floor_plan"),
]


def view_kind_from_title(title: str) -> str | None:
    f = fold(title)
    for pat, kind in VIEW_RULES:
        if re.search(pat, f):
            return kind
    return None


def level_hint_from_title(title: str) -> int | None:
    """Storey index hint from a Turkish title: ZEMIN KAT=0, BODRUM=-1, 1. KAT=1, '2-7. KATLAR' -> 2 (first), CATI -> None."""
    f = fold(title)
    if re.search(r"CATI", f) and not re.search(r"KAT", f.replace("CATI", "")):
        return None
    if re.search(r"BODRUM", f):
        m = re.search(r"(\d+)\s*\.?\s*BODRUM", f)
        return -int(m.group(1)) if m else -1
    if re.search(r"ZEMIN", f):
        return 0
    m = re.search(r"(\d+)\s*[-–]\s*(\d+)\s*\.?\s*KAT", f)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*\.?\s*(NORMAL\s*)?KAT", f)
    if m:
        return int(m.group(1))
    m = re.search(r"\+\s*(\d+[.,]\d+)\s*KOT", f)
    if m:
        return None
    return None


# ---------------------------------------------------------------------------------------------- numbers
_NUM = r"[-+]?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|[-+]?\d+(?:[.,]\d+)?"


def parse_number(s: str) -> float | None:
    """Parse '12,50', '12.50', '1.234,56', '1,234.56', '+3.00' -> float. None if no number."""
    m = re.search(_NUM, s or "")
    if not m:
        return None
    t = m.group(0)
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        parts = t.split(",")
        if len(parts) == 2 and len(parts[1]) == 3 and len(parts[0].lstrip("+-")) <= 3 and False:
            t = t.replace(",", "")
        else:
            t = t.replace(",", ".")
    elif t.count(".") > 1:
        t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


AREA_RE = re.compile(r"(?:^|[^A-Za-z])(?:A|ALAN|AREA|BRUT|NET|ALANI)?\s*[:=]?\s*(" + _NUM + r")\s*(?:m\s*[²2]|M\s*[²2]|mt\s*[²2]|sqm)", re.I)
AREA_PREFIX_RE = re.compile(r"^\s*(?:A|ALAN|AREA)\s*[:=]\s*(" + _NUM + r")\s*(?:m\s*[²2]?|M\s*[²2]?)?\s*$", re.I)


def parse_area_text(s: str) -> float | None:
    """'A:12,50m²' / '12.50 m2' / 'Alan:77.20 m²' -> 12.5. Returns None if the text is not an area label."""
    if not s:
        return None
    t = s.replace("\xb2", "2").replace("²", "2")
    m = re.search(r"(" + _NUM + r")\s*(?:m\s*2|M\s*2|mt\s*2|sqm|m\^2)\b", t)
    if m and len(t) <= 40:
        return parse_number(m.group(1))
    m = AREA_PREFIX_RE.match(t)
    if m:
        return parse_number(m.group(1))
    return None


LEVEL_RE = re.compile(r"^\s*([+\-±]\s*\d{1,3}[.,]\d{1,3})\s*$")


def parse_level_text(s: str) -> float | None:
    m = LEVEL_RE.match(s or "")
    if not m:
        return None
    t = m.group(1).replace("±", "+").replace(" ", "")
    return parse_number(t)
