"""Baza cech upraw (klimat umiarkowany, kalendarz półkuli północnej — dla półkuli
południowej analiza przesuwa kalendarz o pół roku).

Źródła parametrów (wartości orientacyjne, do kalibracji z doradcą):
- przedziały temperatur, opadów, pH: FAO Ecocrop / GAEZ v4,
- współczynniki uprawowe Kc: FAO-56 (tab. 12),
- współczynniki bilansu próchnicy [kg C-próchnicy/ha/rok]: metoda VDLUFA (wartości dolne),
  wywodząca się z prac Eicha i Kundlera, stosowana też przez IUNG-PIB,
- wskaźnik C (RUSLE): wartości literaturowe dla Europy Środkowej (Panagos i in. 2015),
- cls_ok: najsłabsza klasa bonitacyjna bez obniżki oceny (ranga 1=I … 4=IIIb, 5=IVa, 6=IVb, 7=V, 8=VI),
  wg kompleksów przydatności rolniczej IUNG — wartości orientacyjne,
- „margin” to WZGLĘDNY indeks opłacalności 0–100 (nie ceny!) — do zastąpienia notowaniami.

Miesiące jako liczby zmiennoprzecinkowe: 7.9 = koniec lipca, 8.6 ≈ 20 sierpnia.
"""

from i18n import tr

FAMILY_PL = {
    "Poaceae": "wiechlinowate (zboża, trawy)", "Brassicaceae": "kapustowate",
    "Fabaceae": "bobowate", "Asteraceae": "astrowate", "Amaranthaceae": "szarłatowate (burak)",
    "Solanaceae": "psiankowate", "Polygonaceae": "rdestowate",
}


def _c(id, name, family, winter, sow, harvest, tbase, gdd, ph, *, frost_kill=None, ffd=None,
       heat=(32, 6), r_min=0.5, kc=(0.4, 1.1, 0.4), root=1.0, n_idx=-1.0, humus=-280,
       c_est=0.1, c_early=0.45, row=False, margin=50, margin_ls=None, fodder=False,
       cereal=False, maize=False, sclero=False, brk=2, max_sand=None, max_clay=None, cls_ok=6, note=""):
    return dict(id=id, name=name, family=family, winter=winter, sow=sow, harvest=harvest,
                tbase=tbase, gdd=gdd, ph=ph, frost_kill=frost_kill, ffd=ffd, heat_t=heat[0],
                heat_month=heat[1], r_min=r_min, kc=kc, root=root, n_idx=n_idx, humus=humus,
                c_est=c_est, c_early=c_early, row=row, margin=margin,
                margin_ls=margin_ls if margin_ls is not None else margin, fodder=fodder,
                cereal=cereal, maize=maize, sclero=sclero, brk=brk, max_sand=max_sand,
                max_clay=max_clay, cls_ok=cls_ok, nfix=n_idx >= 2, note=note)


CROPS = [
    _c("wheat_w", "Pszenica ozima", "Poaceae", True, 9.8, 7.9, 0, 2000, (5.0, 6.0, 7.5, 8.5),
       frost_kill=-20, heat=(32, 6), r_min=0.45, kc=(0.7, 1.15, 0.4), root=1.5, n_idx=-1,
       margin=60, cereal=True, max_sand=70, cls_ok=4),
    _c("rye_w", "Żyto ozime", "Poaceae", True, 9.6, 7.8, 0, 1750, (4.5, 5.0, 7.0, 8.0),
       frost_kill=-27, r_min=0.35, kc=(0.7, 1.1, 0.4), root=1.8, n_idx=-0.5, margin=40,
       fodder=True, cereal=True, note="najlepsze zboże na gleby lekkie i kwaśne", cls_ok=7),
    _c("barley_w", "Jęczmień ozimy", "Poaceae", True, 9.6, 7.2, 0, 1700, (5.5, 6.2, 7.8, 8.5),
       frost_kill=-15, r_min=0.45, kc=(0.7, 1.15, 0.3), root=1.2, margin=50, fodder=True,
       cereal=True, max_sand=75, note="wczesny zbiór otwiera okno na rzepak i międzyplon", cls_ok=4),
    _c("triticale_w", "Pszenżyto ozime", "Poaceae", True, 9.7, 7.9, 0, 1900, (4.8, 5.5, 7.5, 8.5),
       frost_kill=-20, r_min=0.4, kc=(0.7, 1.15, 0.4), root=1.5, margin=50, fodder=True, cereal=True),
    _c("barley_s", "Jęczmień jary", "Poaceae", False, 3.8, 7.8, 0, 1500, (5.5, 6.2, 7.8, 8.5),
       heat=(32, 6), r_min=0.5, kc=(0.3, 1.15, 0.25), root=1.0, margin=45, fodder=True, cereal=True, cls_ok=5),
    _c("oats", "Owies", "Poaceae", False, 3.7, 8.0, 0, 1500, (4.8, 5.3, 7.0, 8.0),
       heat=(32, 6), r_min=0.55, kc=(0.3, 1.15, 0.25), root=1.0, n_idx=-0.5, margin=35, fodder=True,
       cereal=True, note="zboże „fitosanitarne” — nie jest żywicielem zgorzeli podstawy źdźbła"),
    _c("maize_g", "Kukurydza na ziarno", "Poaceae", False, 4.8, 10.4, 10, 1250, (5.0, 5.8, 7.5, 8.5),
       ffd=140, heat=(35, 7), r_min=0.5, kc=(0.3, 1.2, 0.6), root=1.5, n_idx=-2, humus=-560,
       c_est=0.35, c_early=0.7, row=True, margin=70, fodder=True, cereal=True, maize=True, cls_ok=5),
    _c("maize_s", "Kukurydza na kiszonkę", "Poaceae", False, 4.8, 9.3, 10, 1050, (5.0, 5.8, 7.5, 8.5),
       ffd=125, heat=(35, 7), r_min=0.5, kc=(0.3, 1.2, 0.6), root=1.5, n_idx=-2, humus=-560,
       c_est=0.35, c_early=0.7, row=True, margin=20, margin_ls=65, fodder=True, cereal=True, maize=True),
    _c("sorghum", "Sorgo", "Poaceae", False, 5.2, 10.0, 10, 1200, (5.5, 6.0, 7.8, 8.5),
       ffd=140, heat=(38, 7), r_min=0.3, kc=(0.3, 1.0, 0.55), root=1.8, n_idx=-1.5, humus=-400,
       c_est=0.35, c_early=0.7, row=True, margin=40, margin_ls=55, fodder=True, cereal=True,
       note="odporne na suszę i upał"),
    _c("rapeseed_w", "Rzepak ozimy", "Brassicaceae", True, 8.6, 7.6, 0, 1800, (5.5, 6.2, 7.5, 8.2),
       frost_kill=-15, heat=(30, 5), r_min=0.5, kc=(0.6, 1.1, 0.35), root=1.5, n_idx=-2,
       c_est=0.12, c_early=0.5, margin=75, sclero=True, brk=4, max_sand=70,
       note="przerwa ≥ 4 lata (kiła kapusty, zgnilizna twardzikowa)", cls_ok=4),
    _c("sunflower", "Słonecznik", "Asteraceae", False, 4.6, 9.6, 6, 1450, (5.5, 6.0, 7.8, 8.5),
       ffd=130, heat=(37, 7), r_min=0.35, kc=(0.35, 1.1, 0.35), root=2.0, n_idx=-1,
       c_est=0.3, c_early=0.6, row=True, margin=55, sclero=True, brk=4, note="głęboki korzeń, tolerancja suszy", cls_ok=5),
    _c("soy", "Soja", "Fabaceae", False, 4.9, 9.6, 10, 1100, (5.5, 6.0, 7.5, 8.0),
       ffd=125, heat=(35, 7), r_min=0.55, kc=(0.4, 1.15, 0.5), root=1.2, n_idx=2, humus=160,
       c_est=0.3, c_early=0.6, row=True, margin=55, fodder=True, sclero=True, brk=3, cls_ok=4),
    _c("pea", "Groch siewny", "Fabaceae", False, 3.6, 7.6, 0, 1300, (5.5, 6.0, 7.5, 8.2),
       heat=(32, 6), r_min=0.5, kc=(0.5, 1.15, 0.3), root=0.8, n_idx=2, humus=160,
       c_est=0.15, c_early=0.5, margin=45, fodder=True, sclero=True, brk=4,
       note="wczesny zbiór → idealne miejsce na rzepak lub międzyplon", cls_ok=5),
    _c("faba", "Bobik", "Fabaceae", False, 3.6, 8.3, 0, 1500, (5.8, 6.3, 7.8, 8.5),
       heat=(28, 6), r_min=0.6, kc=(0.5, 1.15, 0.3), root=1.0, n_idx=2, humus=160,
       c_est=0.15, c_early=0.5, margin=40, fodder=True, sclero=True, brk=4, max_sand=60, cls_ok=4),
    _c("lupin", "Łubin wąskolistny", "Fabaceae", False, 3.8, 8.2, 0, 1400, (4.5, 5.0, 6.5, 7.2),
       heat=(30, 6), r_min=0.45, kc=(0.5, 1.1, 0.3), root=1.5, n_idx=2, humus=160,
       c_est=0.15, c_early=0.5, margin=30, fodder=True, brk=4, max_clay=35,
       note="bobowata gleb lekkich i kwaśnych", cls_ok=7),
    _c("sugarbeet", "Burak cukrowy", "Amaranthaceae", False, 4.0, 10.5, 5, 1700, (5.5, 6.3, 7.8, 8.5),
       heat=(32, 7), r_min=0.6, kc=(0.35, 1.2, 0.7), root=1.5, n_idx=-2, humus=-760,
       c_est=0.35, c_early=0.75, row=True, margin=80, brk=4, max_sand=60, max_clay=45,
       note="wymaga kontraktu z cukrownią", cls_ok=3),
    _c("potato", "Ziemniak", "Solanaceae", False, 4.3, 9.3, 5, 1400, (4.8, 5.2, 6.5, 7.5),
       ffd=110, heat=(30, 7), r_min=0.6, kc=(0.5, 1.15, 0.75), root=0.6, n_idx=-1.5, humus=-760,
       c_est=0.35, c_early=0.75, row=True, margin=75, brk=3, max_clay=40),
    _c("buckwheat", "Gryka", "Polygonaceae", False, 5.6, 9.0, 5, 1000, (4.8, 5.0, 6.5, 7.5),
       ffd=100, heat=(30, 7), r_min=0.5, kc=(0.35, 1.0, 0.4), root=0.8, n_idx=0,
       c_est=0.25, c_early=0.6, margin=45, brk=2, max_clay=40, note="krótki sezon, roślina miododajna", cls_ok=7),
    _c("clover", "Koniczyna z trawami (1 rok uż.)", "Fabaceae", False, 3.8, 10.0, 0, 1500, (5.5, 6.2, 7.5, 8.2),
       heat=(32, 7), r_min=0.55, kc=(0.6, 1.0, 0.9), root=1.5, n_idx=3, humus=600,
       c_est=0.02, c_early=0.3, margin=15, margin_ls=55, fodder=True, brk=4,
       note="najsilniej odbudowuje próchnicę; bez zwierząt — sprzedaż sianokiszonki/biogaz", cls_ok=5),
    _c("alfalfa", "Lucerna (1 rok uż.)", "Fabaceae", False, 3.8, 10.0, 0, 1500, (5.5, 6.5, 7.8, 8.5),
       heat=(35, 7), r_min=0.3, kc=(0.5, 1.1, 1.0), root=3.0, n_idx=3, humus=600,
       c_est=0.02, c_early=0.3, margin=25, margin_ls=60, fodder=True, brk=4, max_clay=45,
       note="bardzo głęboki korzeń — odporna na suszę, rozluźnia podglebie", cls_ok=4),
]

# Energia żywności: (kcal na 1 kg plonu handlowego, typowy plon w Polsce [t/ha]).
# kcal: USDA FoodData Central (ziarno/nasiona suche, ziemniak surowy); rzepak i słonecznik — całe nasiona z łuską,
# szacunek ze składu (tłuszcz·9 + białko·4 + węglowodany·4); burak — cukier możliwy do uzyskania (~16% masy × 3870 kcal/kg).
# Plony: przybliżone średnie GUS 2020–2024. None = uprawa pastewna (energia dla zwierząt, nie liczymy jako żywność).
ENERGY = {
    "wheat_w": (3390, 6.0), "rye_w": (3380, 3.6), "barley_w": (3540, 5.6), "triticale_w": (3360, 4.8),
    "barley_s": (3540, 4.2), "oats": (3890, 3.4), "maize_g": (3650, 7.0), "maize_s": None,
    "sorghum": (3290, 5.0), "rapeseed_w": (5400, 3.2), "sunflower": (5000, 2.6), "soy": (4460, 2.7),
    "pea": (3410, 3.0), "faba": (3410, 3.4), "lupin": (3710, 2.2), "sugarbeet": (620, 65.0),
    "potato": (770, 30.0), "buckwheat": (3430, 1.8), "clover": None, "alfalfa": None,
}
for _c_ in CROPS:
    _c_["kcal_kg"], _c_["yield_t"] = ENERGY[_c_["id"]] or (None, None)

NAME_EN = {
    "wheat_w": "Winter wheat", "rye_w": "Winter rye", "barley_w": "Winter barley", "triticale_w": "Winter triticale",
    "barley_s": "Spring barley", "oats": "Oats", "maize_g": "Grain maize", "maize_s": "Silage maize",
    "sorghum": "Sorghum", "rapeseed_w": "Winter oilseed rape", "sunflower": "Sunflower", "soy": "Soybean",
    "pea": "Field pea", "faba": "Faba bean", "lupin": "Narrow-leaved lupin", "sugarbeet": "Sugar beet",
    "potato": "Potato", "buckwheat": "Buckwheat", "clover": "Clover-grass (1 year)", "alfalfa": "Alfalfa (1 year)",
}
NOTE_EN = {
    "rye_w": "best cereal for light, acidic soils",
    "barley_w": "early harvest opens a window for oilseed rape and a cover crop",
    "oats": "a “break” cereal — not a host of take-all",
    "sorghum": "drought- and heat-tolerant",
    "rapeseed_w": "break of ≥ 4 years (clubroot, Sclerotinia stem rot)",
    "sunflower": "deep roots, drought-tolerant",
    "pea": "early harvest → ideal before oilseed rape or a cover crop",
    "lupin": "legume for light, acidic soils",
    "sugarbeet": "needs a contract with a sugar factory",
    "buckwheat": "short season, good bee plant",
    "clover": "rebuilds humus the most; without livestock — sell haylage or use for biogas",
    "alfalfa": "very deep roots — drought-tolerant, loosens the subsoil",
}
FAMILY_EN = {
    "Poaceae": "grasses (cereals)", "Brassicaceae": "brassicas", "Fabaceae": "legumes", "Asteraceae": "daisy family",
    "Amaranthaceae": "amaranth family (beet)", "Solanaceae": "nightshades", "Polygonaceae": "knotweed family",
}

CROP_BY_ID = {c["id"]: c for c in CROPS}
FODDER_IDS = {c["id"] for c in CROPS if c["fodder"]}


def cn(c):
    """Nazwa uprawy w języku zapytania (c: słownik uprawy albo id)."""
    c = CROP_BY_ID[c] if isinstance(c, str) else c
    return tr(c["name"], NAME_EN[c["id"]])


def cnote(c):
    return tr(c["note"], NOTE_EN.get(c["id"], ""))


def fam(family):
    return tr(FAMILY_PL.get(family, family), FAMILY_EN.get(family, family))


def public_list():
    return [{"id": c["id"], "name": cn(c), "family": c["family"],
             "family_pl": fam(c["family"]), "winter": c["winter"], "nfix": c["nfix"]} for c in CROPS]


assert set(NAME_EN) == set(CROP_BY_ID) and set(NOTE_EN) <= {c["id"] for c in CROPS if c["note"]}
