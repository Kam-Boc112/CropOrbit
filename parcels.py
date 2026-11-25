"""Działki ewidencyjne i klasy gruntu (tylko Polska), z publicznych usług GUGiK bez kont i kluczy.

- ULDK (uldk.gugik.gov.pl): identyfikator i granice działki — po kliknięciu (XY) albo po nazwie „Obręb 123/4”.
- KIEG (Krajowa Integracja Ewidencji Gruntów, WMS GetFeatureInfo): powierzchnia z EGiB i oznaczenia konturów
  klasyfikacyjnych (np. „RIIIa, ŁIV, PsV”) — z nich bierzemy klasy bonitacyjne gleby.
"""
import html
import re
import urllib.parse

from data_sources import _cached, http_bytes
from i18n import tr

ULDK = "https://uldk.gugik.gov.pl/"
KIEG = "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow"
ULDK_FIELDS = "id,voivodeship,county,commune,region,parcel,geom_wkt"

USE_PL = {
    "R": "grunty orne", "Ł": "łąki trwałe", "Ps": "pastwiska trwałe", "S": "sady", "Br": "grunty rolne zabudowane",
    "Wsr": "grunty pod stawami", "Lzr": "zadrzewione na gruntach rolnych", "W": "rowy", "Ls": "lasy",
    "Lz": "zadrzewione i zakrzewione", "N": "nieużytki",
}
USE_EN = {
    "R": "arable land", "Ł": "permanent meadows", "Ps": "permanent pastures", "S": "orchards", "Br": "built-up agricultural land",
    "Wsr": "land under ponds", "Lzr": "wooded agricultural land", "W": "ditches", "Ls": "forests",
    "Lz": "wooded and shrub land", "N": "wasteland",
}
QUALITY_EN = {"najlepsza": "best", "bardzo dobra": "very good", "dobra": "good", "średnio dobra": "fairly good",
              "średnia": "average", "średnia gorsza": "below average", "słaba": "poor", "najsłabsza": "poorest",
              "najsłabsza, pod zalesienie": "poorest, for afforestation"}
AGRI_USES = {"R", "Ł", "Ps", "S", "Br", "Wsr", "Lzr", "W"}
# klasa → (ranga 1 = najlepsza, opis jakości)
CLASS_INFO = {
    "I": (1, "najlepsza"), "II": (2, "bardzo dobra"), "IIIa": (3, "dobra"), "III": (3, "średnio dobra"),
    "IIIb": (4, "średnio dobra"), "IVa": (5, "średnia"), "IV": (5, "średnia"), "IVb": (6, "średnia gorsza"),
    "V": (7, "słaba"), "VI": (8, "najsłabsza"), "VIz": (8, "najsłabsza, pod zalesienie"),
}
_CLS_RE = re.compile(r"^(.*?)(VIz|VI|V|IVb|IVa|IV|IIIb|IIIa|III|II|I)$")
PL_BBOX = (48.9, 55.0, 14.0, 24.2)  # lat_min, lat_max, lon_min, lon_max


def in_poland(lat, lon):
    a, b, c, d = PL_BBOX
    return a <= lat <= b and c <= lon <= d


def _get_text(url, timeout=40):
    raw = http_bytes(url, timeout)  # serwer: urllib; przeglądarka (Pyodide): XHR
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1250", errors="replace")  # KIEG odpowiada bez charset, w cp1250


# ---------------------------------------------------------------- parsowanie
def parse_rings(wkt):
    """WKT POLYGON/MULTIPOLYGON → lista pierścieni [[lat, lon], …]."""
    # shortcut: dziury w poligonie traktujemy jak zwykłe pierścienie — w działkach rolnych to rzadkość
    rings = []
    for ring in re.findall(r"\(([^()]+)\)", wkt.split(";", 1)[-1]):
        pts = [p.split() for p in ring.split(",")]
        rings.append([[round(float(y), 7), round(float(x), 7)] for x, y in pts])
    return rings


def parse_classes(text):
    """„Br/PsIV,RIVa,ŁV” → lista konturów z użytkiem i klasą."""
    out = []
    for tok in (t.strip() for t in (text or "").split(",")):
        if not tok:
            continue
        base = tok.split("/")[-1].split("-")[-1]  # Br/PsIV → PsIV, S-RIIIa → RIIIa
        m = _CLS_RE.match(base)
        use, cls = (m.group(1), m.group(2)) if m else (base, None)
        rank, quality = CLASS_INFO.get(cls, (None, None))
        out.append({"code": tok, "use": use, "use_pl": USE_PL.get(use, use), "cls": cls,
                    "rank": rank, "quality": quality})
    return out


def _parse_uldk(text):
    lines = [l for l in text.strip().splitlines() if l.strip()]
    if not lines or not lines[0].strip().isdigit() or lines[0].strip() == "-1":
        return []
    out = []
    for line in lines[1:]:
        f = line.split("|")
        if len(f) < 7:
            continue
        out.append({"id": f[0], "voivodeship": f[1], "county": f[2], "commune": f[3], "region": f[4],
                    "number": f[5], "rings": parse_rings(f[6])})
    return out


def _parse_kieg(page):
    cells = [html.unescape(re.sub(r"\s+", " ", re.sub("<[^>]+>", "", c))).strip()
             for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", page, re.S)]
    kv = dict(zip(cells[::2], cells[1::2]))
    get = lambda prefix: next((v for k, v in kv.items() if k.startswith(prefix)), "")  # noqa: E731
    area = get("Pole pow.").replace(",", ".")
    return {"id": get("Identyfikator"), "area_ha": float(area) if re.fullmatch(r"[\d.]+", area) else None,
            "contours": get("Oznaczenie konturu"), "uses": get("Oznaczenie użytku")}


# ---------------------------------------------------------------- usługi
def _uldk(request, **params):
    q = urllib.parse.urlencode({"request": request, **params, "result": ULDK_FIELDS, "srid": 4326})
    return _parse_uldk(_get_text(ULDK + "?" + q))


def _egib(lat, lon):
    d = 0.0004
    q = urllib.parse.urlencode({
        "SERVICE": "WMS", "VERSION": "1.1.1", "REQUEST": "GetFeatureInfo", "LAYERS": "kontury,uzytki",
        "QUERY_LAYERS": "kontury,uzytki", "STYLES": "", "SRS": "EPSG:4326",
        "BBOX": f"{lon - d},{lat - d},{lon + d},{lat + d}", "WIDTH": 101, "HEIGHT": 101, "X": 50, "Y": 50,
        "INFO_FORMAT": "text/html", "FORMAT": "image/png"})
    return _parse_kieg(_get_text(KIEG + "?" + q, timeout=60))


def _localized(rec):
    """Opisy użytków i klas w języku zapytania (cache trzyma kody, opisy liczymy przy odczycie)."""
    for c in (rec or {}).get("classes", []):
        rank_q = CLASS_INFO.get(c["cls"], (None, None))[1]
        c["use_pl"] = tr(USE_PL.get(c["use"], c["use"]), USE_EN.get(c["use"], c["use"]))
        c["quality"] = rank_q and tr(rank_q, QUALITY_EN[rank_q])
    return rec


def _centroid(ring):
    return sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)


def _enrich(p, lat, lon):
    """Dokleja z EGiB powierzchnię i klasy; brak EGiB nie blokuje wyboru działki."""
    try:
        e = _egib(lat, lon)
    except Exception as ex:  # noqa: BLE001 — usługa powiatowa bywa niedostępna
        e, p["egib_error"] = {}, f"{type(ex).__name__}: {ex}"[:160]
    same = e.get("id") == p["id"]  # punkt mógł trafić w sąsiednią działkę
    p["area_ha"] = e.get("area_ha") if same else None
    p["classes"] = parse_classes(e.get("contours")) if same else []
    p["agricultural"] = any(c["use"] in AGRI_USES for c in p["classes"])
    return p


def at_point(lat, lon):
    """Działka pod klikniętym punktem albo None."""
    lat, lon = round(lat, 6), round(lon, 6)
    if not in_poland(lat, lon):
        return None

    def go():
        found = _uldk("GetParcelByXY", xy=f"{lon},{lat},4326")
        return _enrich(found[0], lat, lon) if found else None

    rec = _cached(f"parcel-xy:{lat}:{lon}", go)
    if rec:
        _cached(f"parcel-id:{rec['id']}", lambda: rec)
    return _localized(rec)


def by_id(pid):
    def go():
        found = _uldk("GetParcelById", id=pid)
        return _enrich(found[0], *_centroid(found[0]["rings"][0])) if found else None

    return _localized(_cached(f"parcel-id:{pid}", go))


def search(text):
    """„Trzciana 723/1” albo pełny identyfikator TERYT → do 5 działek (bez klas — te po wybraniu)."""
    text = text.strip()[:120]
    if not text:
        return []
    return _cached(f"parcel-q:{text.lower()}", lambda: _uldk("GetParcelByIdOrNr", id=text)[:5])


def summary(parcels):
    """Zbiorcze podsumowanie klas dla wybranych działek (do kafelka „Klasy gruntu”)."""
    classes = [c for p in parcels for c in p.get("classes", [])]
    ranked = [c for c in classes if c["rank"]]
    agri = [c for c in classes if c["use"] in AGRI_USES]
    return {
        "n": len(parcels), "ids": [p["id"] for p in parcels],
        "area_ha": round(sum(p.get("area_ha") or 0 for p in parcels), 4) or None,
        "codes": sorted({c["code"] for c in classes}),
        "best": min(ranked, key=lambda c: c["rank"]) if ranked else None,
        "worst": max(ranked, key=lambda c: c["rank"]) if ranked else None,
        "agricultural": bool(agri), "has_data": bool(classes),
        "field_class": field_class(classes),
    }


def field_class(classes):
    """Klasa „typowa” pola do oceny upraw: górna mediana rang konturów ornych (R), a bez nich — łąk i pastwisk."""
    # shortcut: EGiB nie podaje powierzchni konturów, więc mediana jest po liczbie konturów, nie po hektarach
    for uses, basis in (({"R"}, tr("grunty orne", "arable land")),
                        ({"Ł", "Ps"}, tr("użytki zielone — orientacyjnie dla upraw polowych", "grassland — indicative for field crops"))):
        ranks = sorted(c["rank"] for c in classes if c["use"] in uses and c["rank"])
        if ranks:
            r = ranks[len(ranks) // 2]
            # łąki/pastwiska mają klasy bez a/b: IV traktujemy jak IVa, III jak IIIa
            return {"rank": r, "cls": next(c["cls"] for c in classes if c["rank"] == r and c["use"] in uses), "basis": basis}
    return None


if __name__ == "__main__":  # samosprawdzenie parserów (bez sieci)
    from i18n import set_lang
    set_lang("pl")
    assert _localized({"classes": parse_classes("ŁIV")})["classes"][0]["quality"] == "średnia"
    assert set(QUALITY_EN) == {q for _, q in CLASS_INFO.values()}
    c = parse_classes("Br/PsIV,RIVa,ŁV,S-RIIIa,Ls")
    assert [x["cls"] for x in c] == ["IV", "IVa", "V", "IIIa", None], c
    assert [x["use"] for x in c] == ["Ps", "R", "Ł", "R", "Ls"], c
    r = parse_rings("SRID=4326;MULTIPOLYGON(((21 50,22 50,22 51,21 50)),((1 2,3 4,5 6,1 2)))")
    assert r[0][1] == [50.0, 22.0] and len(r) == 2, r
    assert _parse_uldk("-1 brak wyników") == []
    s = summary([{"id": "x", "area_ha": 1.5, "classes": c}])
    assert s["best"]["cls"] == "IIIa" and s["worst"]["cls"] == "V" and s["agricultural"]
    assert s["field_class"] == {"rank": 5, "cls": "IVa", "basis": "grunty orne"}, s["field_class"]
    assert field_class(parse_classes("ŁIV,ŁV,PsVI"))["cls"] == "V"
    assert field_class(parse_classes("Ls,N")) is None
    print("parcels.py: OK")
