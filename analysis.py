"""Orkiestracja analizy pola: dane → wskaźniki → ranking upraw → płodozmiany → wyjaśnienia.

Wszystkie teksty powstają z szablonów wypełnianych WYLICZONYMI liczbami (zero halucynacji).
Język tekstów (en/pl) ustawia serwer na czas zapytania — patrz i18n.tr.
"""
import datetime as dt

import agro
import parcels as parcels_mod
import rotation
from crops import CROP_BY_ID, CROPS, cn
from data_sources import fetch_all
from i18n import tr


def sources():
    return {
        "power": tr("NASA POWER (MERRA‑2/CERES, dziennie)", "NASA POWER (MERRA‑2/CERES, daily)"),
        "soil": "SoilGrids 2.0 (ISRIC, 250 m)",
        "srtm": tr("SRTM 30 m (NASA/USGS, przez OpenTopoData)", "SRTM 30 m (NASA/USGS, via OpenTopoData)"),
        "ndvi": "MODIS MOD13Q1 NDVI 250 m (NASA, ORNL DAAC)",
        "egib": tr("EGiB — kontury klasyfikacyjne (GUGiK: ULDK + Krajowa Integracja Ewidencji Gruntów)",
                   "EGiB land register — soil class contours (GUGiK: ULDK + National Land Register Integration)"),
    }


# id → (termin PL, termin EN, opis PL, opis EN)
GLOSSARY = {
    "GDD": ("GDD", "GDD",
            "Suma temperatur efektywnych — dodajemy, o ile stopni każdy dzień był cieplejszy od progu wzrostu rośliny. Mówi, czy uprawa „uzbiera” dość ciepła, żeby dojrzeć.",
            "Growing degree days — we add up how many degrees each day was warmer than the plant's growth threshold. It tells whether the crop gathers enough heat to ripen."),
    "ET0": ("ET0", "ET0",
            "Ewapotranspiracja wzorcowa — ile wody (mm) odparowałoby z gleby i trawy dobrze zaopatrzonej w wodę. Liczona metodą FAO‑56 z temperatury, wilgotności, wiatru i promieniowania.",
            "Reference evapotranspiration — how much water (mm) would evaporate from soil and well-watered grass. Computed with FAO‑56 from temperature, humidity, wind and radiation."),
    "Kc": ("Kc", "Kc",
           "Współczynnik uprawowy — mnożnik ET₀ dla konkretnej rośliny i fazy rozwoju (np. kukurydza w pełni lata ≈ 1,2).",
           "Crop coefficient — multiplier of ET₀ for a given crop and growth stage (e.g. maize in midsummer ≈ 1.2)."),
    "water_balance": ("Bilans wodny", "Water balance",
                      "Opad minus ET₀. Wartość ujemna = w danym miesiącu odparowuje więcej wody, niż spada z deszczem; rośliny korzystają wtedy z zapasu w glebie.",
                      "Rainfall minus ET₀. A negative value means more water evaporates that month than falls as rain; plants then draw on soil reserves."),
    "moisture_anomaly": ("Anomalia wilgotności", "Moisture anomaly",
                         "O ile wilgotność gleby w danym miesiącu odbiega od średniej wieloletniej, w jednostkach odchylenia standardowego (z‑score). Poniżej −1 = wyraźnie sucho.",
                         "How far soil moisture in a month departs from the long-term mean, in standard deviations (z‑score). Below −1 = clearly dry."),
    "NDVI": ("NDVI", "NDVI",
             "Wskaźnik zieloności z satelity (0–1). Poniżej ~0,3 pole jest zwykle gołe lub z bardzo rzadką roślinnością.",
             "Satellite greenness index (0–1). Below ~0.3 a field is usually bare or very sparsely vegetated."),
    "RUSLE": ("RUSLE", "RUSLE",
              "Model strat gleby przez erozję wodną: A = R·K·LS·C·P (deszcz × podatność gleby × stok × pokrycie roślinami × zabiegi przeciwerozyjne).",
              "Soil loss model for water erosion: A = R·K·LS·C·P (rain × soil erodibility × slope × plant cover × conservation practices)."),
    "humus": ("Próchnica", "Humus",
              "Materia organiczna gleby. Bilans liczymy metodą współczynników reprodukcji/degradacji (VDLUFA, Eich & Kundler): okopowe ją zużywają, bobowate i międzyplony odbudowują.",
              "Soil organic matter. The balance uses reproduction/degradation coefficients (VDLUFA, Eich & Kundler): root crops deplete it, legumes and cover crops rebuild it."),
    "soil_class": ("Klasa gruntu", "Soil class",
                   "Klasa bonitacyjna z ewidencji gruntów (EGiB): I = gleby najlepsze, VI = najsłabsze. Litery przed klasą to użytek: R grunty orne, Ł łąki, Ps pastwiska. Klasy IIIa/IIIb i IVa/IVb dotyczą gruntów ornych.",
                   "Soil quality class from the Polish land register (EGiB): I = best soils, VI = poorest. Letters before the class give the land use: R arable land, Ł meadows, Ps pastures. Classes IIIa/IIIb and IVa/IVb apply to arable land."),
    "p90": ("Percentyl 90", "90th percentile",
            "Wartość, której nie przekracza 9 na 10 lat. „Ostatni przymrozek p90 = 15.05” znaczy: tylko w 1 roku na 10 przymrozek zdarza się później.",
            "The value not exceeded in 9 out of 10 years. “Last frost p90 = 15.05” means that only in 1 year in 10 does frost occur later."),
}


def glossary():
    return {k: {"term": tr(v[0], v[1]), "text": tr(v[2], v[3])} for k, v in GLOSSARY.items()}


DEFAULT_WEIGHTS = {"woda": 3, "gleba": 3, "erozja": 2, "azot": 2, "choroby": 2, "dochod": 3, "pasza": 0}


def _ndvi_windows(ndvi, thr=0.3):
    if not ndvi:
        return None
    prof = ndvi["profile"]
    wins, start = [], None
    for k, p in enumerate(prof):
        low = p["ndvi"] < thr
        if low and start is None:
            start = p["doy"]
        if (not low or k == len(prof) - 1) and start is not None:
            end = p["doy"] + 15 if low else p["doy"] - 1
            wins.append((start, end))
            start = None

    def lab(doy):
        d = dt.date(2001, 1, 1) + dt.timedelta(days=min(doy, 365) - 1)
        return f"{d.day:02d}.{d.month:02d}"

    return {"profile": prof, "threshold": thr, "years": ndvi["years"],
            "bare_windows": [{"from": lab(a), "to": lab(b), "days": b - a + 1} for a, b in wins]}


def _tile(key, title, status, value, sentence, conf, conf_why, source, glossary_ids):
    return {"key": key, "title": title, "status": status, "value": value, "text": sentence,
            "confidence": conf, "confidence_why": conf_why, "source": source, "glossary": glossary_ids}


KCAL_PERSON_YEAR = 2500 * 365  # dzienne zapotrzebowanie dorosłego × rok


def _energy(ranking, area_ha):
    """Energia żywności z hektara: kcal/kg × plon typowy × (ocena przydatności / 100)."""
    # shortcut: plon skalowany liniowo oceną 0–100 — zgrubny szacunek; do zastąpienia modelem plonu lub danymi GUS dla gminy
    out = []
    for s in ranking:
        c = CROP_BY_ID[s["id"]]
        if c["kcal_kg"] is None:
            out.append({"id": c["id"], "name": cn(c), "fodder": True, "kcal_kg": None, "yield_ref_t": None,
                        "yield_t": None, "kcal_ha": 0, "kcal_field": None, "persons_ha": None, "persons": None,
                        "score": s["score"]})
            continue
        y = round(c["yield_t"] * s["score"] / 100, 2)
        kcal_ha = round(c["kcal_kg"] * y * 1000)
        field = round(kcal_ha * area_ha) if area_ha else None
        out.append({"id": c["id"], "name": cn(c), "fodder": False, "kcal_kg": c["kcal_kg"], "yield_ref_t": c["yield_t"],
                    "yield_t": y, "kcal_ha": kcal_ha, "kcal_field": field,
                    "persons_ha": round(kcal_ha / KCAL_PERSON_YEAR, 1),
                    "persons": round(field / KCAL_PERSON_YEAR, 1) if field else None, "score": s["score"]})
    return sorted(out, key=lambda e: -e["kcal_ha"])


def _uses(ps):
    """Kody użytków z konturów podsumowania (np. „ŁIV” → „Ł”)."""
    return [c["use"] for c in parcels_mod.parse_classes(",".join(ps.get("codes", [])))]


def _class_tile(ps):
    """Kafelek „Klasy gruntu” z EGiB dla wybranych działek."""
    src, gl, title = sources()["egib"], ["soil_class"], tr("Klasy gruntu", "Soil classes")
    if not ps["has_data"]:
        return _tile("classes", title, "warn", tr("brak danych EGiB", "no land-register data"),
                     tr("Usługa powiatowa nie zwróciła konturów klasyfikacyjnych dla wybranych działek.",
                        "The county service returned no soil class contours for the selected parcels."),
                     tr("niska", "low"), tr("Dane EGiB udostępnia starosta — część powiatów nie publikuje konturów.",
                                            "Land-register data come from the county office — some counties do not publish contours."), src, gl)
    codes = ", ".join(ps["codes"])
    if not ps["agricultural"]:
        return _tile("classes", title, "warn", tr("działka nierolna", "non-agricultural parcel"),
                     tr(f"Kontury: {codes}. Brak gruntów ornych, łąk ani pastwisk — analiza upraw ma ograniczony sens.",
                        f"Contours: {codes}. No arable land, meadows or pastures — crop analysis is of limited use."),
                     tr("wysoka", "high"), tr("Oznaczenia wprost z ewidencji gruntów.", "Codes taken directly from the land register."), src, gl)
    best, worst = ps["best"], ps["worst"]
    rank = best["rank"] if best else 9
    rng = best["cls"] if best is worst or not worst or best["cls"] == worst["cls"] else f"{best['cls']}–{worst['cls']}"
    n = ps["n"]
    text = (tr(f"Kontury na {n} dział{'ce' if n == 1 else 'kach'}: {codes}. ", f"Contours on {n} parcel{'' if n == 1 else 's'}: {codes}. ")
            + (tr(f"Najlepszy: {best['code']} ({best['use_pl']}, {best['quality']}). ",
                  f"Best: {best['code']} ({best['use_pl']}, {best['quality']}). ") if best else "")
            + (tr(f"Najsłabszy: {worst['code']} ({worst['quality']}). ", f"Weakest: {worst['code']} ({worst['quality']}). ")
               if worst and worst is not best else "")
            + (tr(f"W ocenie upraw liczymy klasę {ps['field_class']['cls']} ({ps['field_class']['basis']}).",
                  f"Crop scoring uses class {ps['field_class']['cls']} ({ps['field_class']['basis']}).")
               if ps.get("field_class") else ""))
    return _tile("classes", title, "good" if rank <= 3 else "warn" if rank <= 6 else "bad",
                 tr(f"klasa {rng}", f"class {rng}") if best else codes, text,
                 tr("wysoka", "high"), tr("Klasy z urzędowej ewidencji gruntów — nie mówią o pH ani zasobności, te sprawdzi analiza gleby.",
                                          "Classes from the official land register — they say nothing about pH or nutrients; a soil test will."), src, gl)


def run(req):
    lat, lon = float(req["lat"]), float(req["lon"])
    if not (-60 <= lat <= 72 and -180 <= lon <= 180):
        raise ValueError(tr("Współrzędne poza zakresem obsługiwanym przez analizę", "Coordinates outside the range supported by the analysis"))
    new_field = bool(req.get("new_field"))
    current = [] if new_field else [c for c in req.get("rotation", []) if c in CROP_BY_ID]
    if not new_field and not 2 <= len(current) <= 6:
        raise ValueError(tr("Podaj obecny płodozmian (od 2 do 6 upraw) albo zaznacz, że to nowe pole",
                            "Enter your current rotation (2 to 6 crops) or mark the field as new"))
    area_ha = float(req.get("area_ha") or 0) or None
    irrigation = bool(req.get("irrigation"))
    livestock = bool(req.get("livestock"))
    parcel_ids = [str(i)[:60] for i in (req.get("parcels") or [])][:20]
    weights = {k: float(v) for k, v in (req.get("weights") or DEFAULT_WEIGHTS).items() if k in rotation.AXES}
    SRC = sources()

    data = fetch_all(lat, lon)
    errors = data["errors"]
    if not data.get("power"):
        raise RuntimeError(tr("Nie udało się pobrać danych NASA POWER: ", "Could not download NASA POWER data: ") + errors.get("power", "?"))
    terrain = data.get("terrain") or {}
    clim = agro.Climate(data["power"], lat, terrain.get("elev"))
    cs = clim.summary()
    ind = cs["ind"]
    soil = agro.soil_props(data.get("soil"))
    slope = terrain.get("slope_pct")
    slope_v = slope if slope is not None else 2.0

    parcel_sum = None
    if parcel_ids:
        recs = []
        for pid in parcel_ids:
            try:
                if rec := parcels_mod.by_id(pid):
                    recs.append(rec)
            except Exception as e:  # noqa: BLE001 — GUGiK niedostępny nie może zatrzymać analizy klimatu
                errors["egib"] = f"{type(e).__name__}: {e}"[:200]
        parcel_sum = parcels_mod.summary(recs)
        area_ha = area_ha or parcel_sum["area_ha"]
    soil_class = parcel_sum and parcel_sum["field_class"]
    suit = {c["id"]: agro.suitability(c, clim, cs, soil, terrain, irrigation, soil_class) for c in CROPS}
    ranking = sorted(suit.values(), key=lambda s: (-s["score"], -s["geo"]))

    ep = cs["monthly"]["erosive_p"]
    tot = sum(ep) or 1
    ctx = {
        "suit": suit, "ind": ind, "src": SRC, "errors": errors, "weights": weights, "livestock": livestock,
        "residues": bool(req.get("residues")), "season_balance": ind["season_balance"],
        "r": agro.rusle_r(cs["monthly"]["p"]), "k": soil["k"], "ls": agro.rusle_ls(slope_v),
        "r_share": [v / tot for v in ep], "slope": round(slope_v, 1),
        "grassland": bool(parcel_sum and any(u in ("Ł", "Ps") for u in _uses(parcel_sum))),
    }
    alts, n_checked = rotation.generate(current, ctx)
    if new_field:
        if not alts:
            raise RuntimeError(tr("Nie znaleziono płodozmianu spełniającego reguły dla tego pola",
                                  "No rotation meeting the rules was found for this field"))
        cur, ref_name, strategies = alts[0], tr("proponowany płodozmian A", "proposed rotation A"), []
    else:
        cur, ref_name = rotation.evaluate(current, ctx, covers=bool(req.get("cover_now"))), tr("obecny płodozmian", "current rotation")
        strategies = [dict(cur, label="Obecny", title=tr("Twój obecny płodozmian", "Your current rotation"), is_current=True,
                           card=rotation.card(cur, cur, ctx, True))]
    for i, a in enumerate(alts):
        strategies.append(dict(a, label="ABC"[i], title=rotation.strategy_title(a, current),
                               is_current=False, card=rotation.card(a, cur, ctx, False, new_field)))
    energy = _energy(ranking, area_ha)
    kcal_ha = {e["id"]: e["kcal_ha"] for e in energy}
    for s in strategies:  # średnia energia żywności płodozmianu (pastewne = 0)
        s["metrics"]["energy_mkcal_ha"] = round(sum(kcal_ha.get(c, 0) for c in s["seq"]) / len(s["seq"]) / 1e6, 1)

    # ----- kafelki „Warunki na polu”
    fl, fa = ind["frost_last_spring"], ind["frost_first_autumn"]
    low, medium, high = tr("niska", "low"), tr("średnia", "medium"), tr("wysoka", "high")
    soil_conf = low if soil["missing"] else medium
    t_conf = medium if abs(ind["lapse_corr"]) < 1.5 else low
    grid_e, field_e = round(ind['grid_elev'] or 0), round(terrain.get('elev') or 0)
    lapse_txt = (tr(f"korekta wysokości {ind['lapse_corr']:+.1f} °C (komórka POWER {grid_e} m, pole {field_e} m)",
                    f"elevation correction {ind['lapse_corr']:+.1f} °C (POWER cell {grid_e} m, field {field_e} m)")
                 if terrain.get("elev") is not None else tr("bez korekty wysokości (brak SRTM)", "no elevation correction (no SRTM)"))
    deficit = ", ".join(ind['deficit_months']) or tr("brak", "none")
    e_t = cur["metrics"]["erosion_t_ha"]
    tiles = [
        _tile("season", tr("Sezon wegetacyjny", "Growing season"),
              "good" if ind["ffd_median"] >= 165 else "warn" if ind["ffd_median"] >= 135 else "bad",
              tr(f"{ind['ffd_median']} dni bez przymrozków", f"{ind['ffd_median']} frost-free days"),
              tr(f"Zwykle od {fl['p50']} do {fa['p50']}. Suma ciepła GDD (>5 °C): {ind['gdd5']} °C·d/rok. "
                 f"Średnia temperatura {ind['tmean']} °C, trend {ind['t_trend_dec']:+.2f} °C na dekadę.",
                 f"Usually from {fl['p50']} to {fa['p50']} (dd.mm). Heat sum GDD (>5 °C): {ind['gdd5']} °C·d/year. "
                 f"Mean temperature {ind['tmean']} °C, trend {ind['t_trend_dec']:+.2f} °C per decade."),
              t_conf, tr(f"Siatka ~50 km; {lapse_txt}.", f"~50 km grid; {lapse_txt}."), SRC["power"], ["GDD"]),
        _tile("frost", tr("Przymrozki", "Frost"),
              "good" if ind["frost_spring_p90_doy"] < 125 else "warn" if ind["frost_spring_p90_doy"] < 145 else "bad",
              tr(f"ostatni wiosną: {fl['p50']} (1 na 10 lat: {fl['p90']})", f"last in spring: {fl['p50']} (1 in 10 years: {fl['p90']})"),
              tr(f"Pierwszy jesienny zwykle {fa['p50']}, w 1 na 10 lat już {fa['p10']}. "
                 f"Najzimniejsza noc w 1 na 10 zim: {ind['tmin_p10']} °C. Ciepłolubne (kukurydza, soja) siej po {fl['p90']}.",
                 f"First autumn frost usually {fa['p50']}, in 1 in 10 years as early as {fa['p10']}. "
                 f"Coldest night in 1 in 10 winters: {ind['tmin_p10']} °C. Sow warmth-loving crops (maize, soybean) after {fl['p90']}."),
              t_conf, tr("Mrozowiska w dolinach mogą mieć przymrozki później niż pokazuje siatka.",
                         "Frost pockets in valleys can get frost later than the grid shows."), SRC["power"], ["p90"]),
        _tile("water", tr("Bilans wodny", "Water balance"),
              "good" if ind["season_balance"] > -50 else "warn" if ind["season_balance"] > -175 else "bad",
              tr(f"{ind['season_balance']:+} mm (IV–IX)", f"{ind['season_balance']:+} mm (Apr–Sep)"),
              tr(f"Miesiące z deficytem (opad < ET₀): {deficit}. "
                 f"Lipiec: {ind['july_balance']:+} mm, trend {ind['july_trend_dec']:+} mm na dekadę. "
                 f"Roczny opad {ind['p_annual']} mm, ET₀ {ind['et0_annual']} mm.",
                 f"Months with a deficit (rain < ET₀): {deficit}. "
                 f"July: {ind['july_balance']:+} mm, trend {ind['july_trend_dec']:+} mm per decade. "
                 f"Annual rainfall {ind['p_annual']} mm, ET₀ {ind['et0_annual']} mm."),
              medium, tr("Opad z reanalizy (komórka ~50 km) — burze lokalne mogą się różnić.",
                         "Rainfall from a reanalysis (~50 km cell) — local storms may differ."), SRC["power"] + ", FAO‑56", ["ET0", "water_balance"]),
        _tile("drought", tr("Susza glebowa", "Soil drought"),
              "bad" if ind["drought_freq_recent"] > ind["drought_freq_early"] + 10 else
              "warn" if ind["drought_freq_recent"] > ind["drought_freq_early"] else "good",
              tr(f"{ind['drought_freq']}% miesięcy IV–IX", f"{ind['drought_freq']}% of months Apr–Sep"),
              tr(f"Tyle miesięcy sezonu miało wyraźnie suchą glebę (z‑score < −1). Ostatnie 8 lat: {ind['drought_freq_recent']}%, "
                 f"pierwsze 8 lat: {ind['drought_freq_early']}%.",
                 f"Share of season months with clearly dry soil (z‑score < −1). Last 8 years: {ind['drought_freq_recent']}%, "
                 f"first 8 years: {ind['drought_freq_early']}%."),
              low, tr("Wilgotność strefy korzeni GWETROOT to model (MERRA‑2), nie pomiar satelitarny SMAP.",
                      "GWETROOT root-zone moisture is a model (MERRA‑2), not a SMAP satellite measurement."),
              SRC["power"] + " — GWETROOT", ["moisture_anomaly"]),
        _tile("heat", tr("Upał", "Heat"),
              "good" if ind["heat_days"] < 5 else "warn" if ind["heat_days"] < 15 else "bad",
              tr(f"{ind['heat_days']} dni/rok z Tmax ≥ 30 °C", f"{ind['heat_days']} days/year with Tmax ≥ 30 °C"),
              tr(f"Wcześniej {ind['heat_days_early']}, ostatnio {ind['heat_days_recent']} dni/rok (trend {ind['heat_trend_dec']:+} na dekadę). "
                 "Upał w czasie kwitnienia obniża zawiązywanie ziarna.",
                 f"Earlier {ind['heat_days_early']}, recently {ind['heat_days_recent']} days/year (trend {ind['heat_trend_dec']:+} per decade). "
                 "Heat during flowering reduces grain set."),
              t_conf, tr("Temperatura powietrza 2 m z siatki; ECOSTRESS (70 m) zaplanowany jako rozszerzenie.",
                         "2 m air temperature from the grid; ECOSTRESS (70 m) is planned as an extension."), SRC["power"], []),
        _tile("erosion", tr("Erozja wodna", "Water erosion"),
              "good" if e_t < 2 else "warn" if e_t < 6 else "bad",
              tr(f"{e_t} t/ha/rok ({ref_name})", f"{e_t} t/ha/year ({ref_name})"),
              tr(f"Nachylenie {round(slope_v, 1)}%, gleba {soil['texture']} (K={soil['k']}). "
                 f"Ulewy ≥ 20 mm: {ind['heavy_rain_days']} dni/rok. Goła gleba: {cur['metrics']['bare_months']} mies./rok.",
                 f"Slope {round(slope_v, 1)}%, soil {soil['texture']} (K={soil['k']}). "
                 f"Downpours ≥ 20 mm: {ind['heavy_rain_days']} days/year. Bare soil: {cur['metrics']['bare_months']} months/year."),
              low if slope is None else medium,
              tr("LS z SRTM 30 m w punkcie pola (zakładana długość stoku 100 m); R z indeksu Fourniera (Arnoldus), bez danych o natężeniu deszczu.",
                 "LS from SRTM 30 m at the field point (assumed slope length 100 m); R from the Fournier index (Arnoldus), without rain intensity data."),
              SRC["srtm"] + ", " + SRC["soil"], ["RUSLE"]),
        _tile("soil", tr("Gleba", "Soil"),
              "good" if 5.5 <= soil["ph"] <= 7.5 else "warn",
              f"pH {soil['ph']} · {soil['texture']}",
              tr(f"Węgiel organiczny {soil['oc_pct']}% (≈ {round(soil['oc_pct'] * 1.72, 1)}% próchnicy). Piasek {soil['sand']}%, pył {soil['silt']}%, ił {soil['clay']}%. "
                 f"Woda dostępna dla roślin ≈ {soil['awc_mm_m']} mm na 1 m gleby." + (" (dane domyślne — SoilGrids niedostępny)" if soil["missing"] else ""),
                 f"Organic carbon {soil['oc_pct']}% (≈ {round(soil['oc_pct'] * 1.72, 1)}% humus). Sand {soil['sand']}%, silt {soil['silt']}%, clay {soil['clay']}%. "
                 f"Plant-available water ≈ {soil['awc_mm_m']} mm per 1 m of soil." + (" (default values — SoilGrids unavailable)" if soil["missing"] else "")),
              soil_conf, tr("SoilGrids to model 250 m — pojedyncze pole może się różnić; zalecana analiza gleby.",
                            "SoilGrids is a 250 m model — a single field may differ; a soil test is recommended."), SRC["soil"], ["humus"]),
    ]

    if parcel_sum:
        tiles.insert(0, _class_tile(parcel_sum))

    conf_field = None
    if area_ha:
        conf_field = (tr("Pole mniejsze niż piksel MODIS (6,25 ha) — NDVI to mieszanka z sąsiednimi działkami.",
                         "Field smaller than a MODIS pixel (6.25 ha) — NDVI mixes in neighbouring plots.")
                      if area_ha < 6.25 else tr("Pole większe niż piksel MODIS — profil NDVI reprezentatywny.",
                                                "Field larger than a MODIS pixel — the NDVI profile is representative."))

    return {
        "parcels": parcel_sum, "new_field": new_field, "energy": energy,
        "field": {"lat": lat, "lon": lon, "area_ha": area_ha, "elev": terrain.get("elev"), "slope_pct": slope,
                  "aspect": terrain.get("aspect"), "hemisphere": "S" if lat < 0 else "N"},
        "inputs": {"new_field": new_field, "rotation": current, "irrigation": irrigation, "livestock": livestock, "weights": weights,
                   "cover_now": bool(req.get("cover_now")), "residues": bool(req.get("residues"))},
        "climate": {"monthly": cs["monthly"], "yearly": cs["yearly"], "ind": ind},
        "soil": soil, "tiles": tiles, "ranking": ranking,
        "ndvi": _ndvi_windows(data.get("ndvi")), "ndvi_note": conf_field,
        "strategies": strategies, "n_checked": n_checked,
        "axes": rotation.AXES, "axis_pl": rotation.axis_names(),
        "crop_names": {c["id"]: cn(c) for c in CROPS},
        "sources": SRC, "errors": errors, "glossary": glossary(),
        "generated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
