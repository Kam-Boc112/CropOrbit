"""Płodozmiany: kalendarz pola (miesiąc po miesiącu), 7 osi oceny, generator alternatyw
oparty na regułach agronomicznych i karty strategii (dlaczego / dowody / korzyści / luki / ryzyka).
"""
import itertools
import math

from crops import CROP_BY_ID, cn, fam
from i18n import tr

AXES = ["woda", "gleba", "erozja", "azot", "choroby", "dochod", "pasza"]
AXIS_NAME = {"woda": ("Woda", "Water"), "gleba": ("Gleba (próchnica)", "Soil (humus)"), "erozja": ("Erozja", "Erosion"),
             "azot": ("Azot", "Nitrogen"), "choroby": ("Choroby i szkodniki", "Diseases and pests"),
             "dochod": ("Dochód", "Income"), "pasza": ("Pasza", "Fodder")}


def axn(k):
    return tr(*AXIS_NAME[k])


def axis_names():
    return {k: axn(k) for k in AXES}
LATE_SOW_OK = {"wheat_w", "triticale_w", "rye_w"}  # mogą iść po późnym zbiorze (opóźniony siew)
RESIDUE_IDS = {"wheat_w", "rye_w", "barley_w", "triticale_w", "barley_s", "oats", "maize_g",
               "sorghum", "rapeseed_w", "sunflower", "soy", "pea", "faba", "lupin", "buckwheat"}


def clamp(x, a=0.0, b=100.0):
    return max(a, min(b, x))


def transition(prev, nxt):
    """Zwraca (wykonalne, opóźniony_siew, efektywna_data_siewu)."""
    if not nxt["winter"]:
        return True, False, nxt["sow"]
    gap = nxt["sow"] - prev["harvest"]
    if gap >= 0.3:
        return True, False, nxt["sow"]
    if nxt["id"] in LATE_SOW_OK and prev["harvest"] + 0.3 <= nxt["sow"] + 1.3:
        return True, True, min(prev["harvest"] + 0.3, 11.9)
    return False, False, None


def timeline(seq, covers):
    """Kalendarz L lat × 12 miesięcy: ('crop', id, faza) | ('bare',) | ('cover',)."""
    L = len(seq)
    crops = [CROP_BY_ID[c] for c in seq]
    grid = [[("bare",) for _ in range(12)] for _ in range(L)]
    flags = {"late": [], "infeasible": [], "covers": 0}
    sows = []
    for i in range(L):
        prev, c = crops[i - 1], crops[i]
        ok, late, sow = transition(prev, c)
        if not ok:
            flags["infeasible"].append((prev["id"], c["id"]))
            sow = c["sow"]
        if late:
            flags["late"].append((prev["id"], c["id"]))
        sows.append(sow)
    for i, c in enumerate(crops):
        sow, hv = sows[i], c["harvest"]
        cells = []
        if c["winter"]:
            cells += [((i - 1) % L, m) for m in range(1, 13) if m + 0.5 >= sow]
            cells += [(i, m) for m in range(1, 13) if m + 0.5 <= hv]
        else:
            cells += [(i, m) for m in range(1, 13) if sow <= m + 0.5 <= hv]
        for k, (y, m) in enumerate(cells):
            phase = "early" if k < (2 if c["row"] else 1) else ("winter" if c["winter"] and m in (12, 1, 2, 3) else "est")
            grid[y][m - 1] = ("crop", c["id"], phase)
    if covers:
        for i, c in enumerate(crops):
            nxt = crops[(i + 1) % L]
            if nxt["winter"] or c["harvest"] > 8.7:
                continue
            start, end = c["harvest"] + 0.3, nxt["sow"] - 0.3
            ny = (i + 1) % L
            placed = False
            for m in range(1, 13):
                if m + 0.5 >= start and grid[i][m - 1][0] == "bare":
                    grid[i][m - 1] = ("cover",)
                    placed = True
                if m + 0.5 <= end and grid[ny][m - 1][0] == "bare":
                    grid[ny][m - 1] = ("cover",)
            flags["covers"] += placed
    return grid, flags


def cover_type(seq):
    has_legume = any(CROP_BY_ID[c]["family"] == "Fabaceae" for c in seq)
    return (tr("facelia (bez bobowatych — rotacja ma już strączkowe)", "phacelia (no legumes — the rotation already has pulses)")
            if has_legume else tr("facelia + wyka (mieszanka z bobowatymi)", "phacelia + vetch (mix with legumes)"))


def evaluate(seq, ctx, covers):
    """Ocena płodozmianu w 7 osiach (0–100) + metryki źródłowe."""
    L = len(seq)
    suit = ctx["suit"]
    crops = [CROP_BY_ID[c] for c in seq]
    grid, flags = timeline(seq, covers)
    legume_cover = covers and not any(c["family"] == "Fabaceae" for c in crops)

    # --- erozja: A = R·K·LS·Σ(udział R w miesiącu · C miesiąca)
    share = ctx["r_share"]
    a_years, bare = [], []
    for y in range(L):
        cs = 0.0
        for m in range(12):
            cell = grid[y][m]
            if cell[0] == "crop":
                cr = CROP_BY_ID[cell[1]]
                cval = cr["c_early"] if cell[2] == "early" else 0.25 if cell[2] == "winter" else cr["c_est"]
            elif cell[0] == "cover":
                cval = 0.15
            else:
                cval = 0.6
            cs += share[m] * cval
        a_years.append(ctx["r"] * ctx["k"] * ctx["ls"] * cs)
        bare.append(sum(1 for m in range(12) if grid[y][m][0] == "bare"))
    A = sum(a_years) / L
    bare_mean = sum(bare) / L

    # --- próchnica (VDLUFA) [kg C/ha/rok]
    humus = sum(c["humus"] for c in crops) + 100 * flags["covers"]
    if ctx["residues"]:
        humus += 150 * sum(1 for c in crops if c["id"] in RESIDUE_IDS)
    humus /= L

    # --- azot
    n_idx = (sum(c["n_idx"] for c in crops) + (0.5 * flags["covers"] if legume_cover else 0)) / L

    # --- choroby i szkodniki
    pen, notes = 0.0, []
    for i in range(L):
        a, b = crops[i - 1], crops[i]
        if a["id"] == b["id"]:
            pen += 30
            notes.append(tr(f"{cn(b)} po sobie (monokultura)", f"{cn(b)} after itself (monoculture)"))
        elif a["cereal"] and b["cereal"]:
            pen += 8 if "oats" in (a["id"], b["id"]) else 18
            notes.append(tr(f"zboże po zbożu: {cn(a)} → {cn(b)} (choroby podstawy źdźbła)",
                            f"cereal after cereal: {cn(a)} → {cn(b)} (stem-base diseases)"))
        if a["maize"] and b["id"] in ("wheat_w", "triticale_w"):
            pen += 12
            notes.append(tr(f"{cn(b)} po kukurydzy — ryzyko fuzarioz i mykotoksyn (DON)",
                            f"{cn(b)} after maize — risk of Fusarium and mycotoxins (DON)"))
    for i in range(L):
        for j in range(i + 1, L):
            ci, cj = crops[i], crops[j]
            d = min(j - i, L - (j - i))
            if ci["family"] == cj["family"] and ci["family"] != "Poaceae":
                need = max(ci["brk"], cj["brk"])
                if d < need:
                    pen += 25
                    notes.append(tr(f"{fam(ci['family'])} co {d} lata (zalecana przerwa ≥ {need})",
                                    f"{fam(ci['family'])} every {d} years (recommended break ≥ {need})"))
            if ci["sclero"] and cj["sclero"] and d < 2 and ci["id"] != cj["id"]:
                pen += 8
                notes.append(tr(f"{cn(ci)} i {cn(cj)} blisko siebie — wspólna zgnilizna twardzikowa",
                                f"{cn(ci)} and {cn(cj)} close together — shared Sclerotinia rot"))
    cer = sum(c["cereal"] for c in crops) / L
    if cer > 0.5:
        pen += 40 * (cer - 0.5)
    nfam = len({c["family"] for c in crops})
    if nfam == 1:
        pen += 25
        notes.append(tr("tylko jedna rodzina botaniczna — choroby i szkodniki nie mają przerwy",
                        "only one plant family — diseases and pests get no break"))
    elif nfam == 2:
        pen += 15
        notes.append(tr("tylko dwie rodziny botaniczne — mała różnorodność (np. zachodnia stonka kukurydziana, mątwiki)",
                        "only two plant families — low diversity (e.g. western corn rootworm, cyst nematodes)"))
    choroby = clamp(100 - pen)

    # --- woda (deficyt sezonowy z bilansu ETc − opad efektywny − woda glebowa)
    deficit = sum(suit[c["id"]]["deficit_mm"] for c in crops) / L
    woda = 100 * math.exp(-deficit / 150)
    if covers and ctx["season_balance"] < -100:
        woda -= 3 * flags["covers"]

    margin_key = "margin_ls" if ctx["livestock"] else "margin"
    dochod = sum(c[margin_key] * suit[c["id"]]["score"] / 100 for c in crops) / L
    pasza = sum((100 if c["fodder"] else 0) * suit[c["id"]]["score"] / 100 for c in crops) / L
    if flags["late"]:
        dochod -= 4 * len(flags["late"])

    axes = {"woda": woda, "gleba": 50 + humus / 5, "erozja": 100 * math.exp(-A / 8),
            "azot": 50 + 20 * n_idx, "choroby": choroby, "dochod": dochod, "pasza": pasza}
    axes = {k: round(clamp(v)) for k, v in axes.items()}
    w = ctx["weights"]
    wsum = sum(w.values()) or 1
    total = round(sum(axes[k] * w.get(k, 0) for k in AXES) / wsum)
    return {
        "seq": list(seq), "names": [cn(c) for c in crops], "axes": axes, "total": total,
        "metrics": {"erosion_t_ha": round(A, 2), "bare_months": round(bare_mean, 1),
                    "humus_kg_c": round(humus), "n_index": round(n_idx, 2), "deficit_mm": round(deficit),
                    "cereal_share": round(cer * 100), "covers": flags["covers"],
                    "families": len({c["family"] for c in crops})},
        "disease_notes": notes, "late": flags["late"], "infeasible": flags["infeasible"],
        "covers": covers, "cover_type": cover_type(seq) if covers and flags["covers"] else None,
        "calendar": [[("crop:" + c[1]) if c[0] == "crop" else c[0] for c in row] for row in grid],
        "min_suit": min(((suit[c["id"]]["score"], c["id"]) for c in crops)),
    }


def _canon(seq):
    L = len(seq)
    return min(tuple(seq[i:] + seq[:i]) for i in range(L))


def _hard_ok(seq):
    L = len(seq)
    crops = [CROP_BY_ID[c] for c in seq]
    for i in range(L):
        if crops[i]["id"] == crops[i - 1]["id"]:
            return False
        if not transition(crops[i - 1], crops[i])[0]:
            return False
    for i in range(L):
        for j in range(i + 1, L):
            if crops[i]["family"] == crops[j]["family"] and crops[i]["family"] != "Poaceae":
                if min(j - i, L - (j - i)) < max(crops[i]["brk"], crops[j]["brk"]):
                    return False
    if sum(c["cereal"] for c in crops) / L > 0.75:
        return False
    return True


def generate(current, ctx, n=3):
    suit = ctx["suit"]
    ranked = sorted(suit.values(), key=lambda s: (-s["score"], -s["geo"]))
    cands = [s["id"] for s in ranked if s["score"] >= 45][:10]
    for s in ranked:  # zawsze daj szansę co najmniej jednej bobowatej
        if CROP_BY_ID[s["id"]]["family"] == "Fabaceae" and s["score"] >= 35:
            if s["id"] not in cands:
                cands.append(s["id"])
            break
    if len(cands) < 3:
        cands = [s["id"] for s in ranked[:6]]
    L = 4 if len(current) <= 4 else 5
    seen, scored = set(), []
    cur_c = _canon(list(current)) if current else None  # nowe pole: brak płodozmianu odniesienia
    for seq in itertools.product(cands, repeat=L):
        c = _canon(list(seq))
        if c in seen or c == cur_c:
            continue
        seen.add(c)
        if not _hard_ok(list(c)):
            continue
        scored.append(evaluate(list(c), ctx, covers=True))
    scored.sort(key=lambda r: (-r["total"], -r["min_suit"][0]))
    picked = []
    for min_diff in (4, 3, 2):  # najpierw wyraźnie różne strategie, potem luzujemy kryterium
        for r in scored:
            if len(picked) == n:
                break
            if r["min_suit"][0] < 40 or r in picked:
                continue
            if all(len(set(r["seq"]) ^ set(p["seq"])) >= min_diff for p in picked):
                picked.append(r)
    picked.sort(key=lambda r: -r["total"])
    return picked, len(scored)


def strategy_title(ev, current):
    """Tytuł = co nowego wchodzi do płodozmianu + cechy strategii."""
    crops = [CROP_BY_ID[c] for c in ev["seq"]]
    new = [cn(c) for c in dict.fromkeys(ev["seq"]) if c not in current]
    tags = []
    if any(c["family"] == "Fabaceae" for c in crops):
        tags.append(tr("bobowate", "legumes"))
    if ev["metrics"]["covers"]:
        tags.append(tr("międzyplony", "cover crops"))
    if sum(c["r_min"] <= 0.35 for c in crops) >= 2:
        tags.append(tr("odporna na suszę", "drought-tolerant"))
    if not current:  # nowe pole: wszystkie uprawy są „nowe”
        head = tr("Uprawy: ", "Crops: ") + " + ".join(new[:3])
    else:
        head = (tr("Nowe: ", "New: ") + " + ".join(new[:3])) if new else tr("Zmiana kolejności upraw", "Reordered crops")
    return head + (" · " + ", ".join(tags) if tags else "")


def card(ev, cur, ctx, is_current, new_field=False):
    """Karta strategii: dlaczego / dowody / korzyści / luki w danych / ryzyka / do sprawdzenia.

    new_field: pole bez dotychczasowej uprawy — `cur` to najlepsza propozycja (A), a nie obecny płodozmian.
    """
    ind, suit, src = ctx["ind"], ctx["suit"], ctx["src"]
    m, cm = ev["metrics"], cur["metrics"]
    diffs = {k: ev["axes"][k] - cur["axes"][k] for k in AXES}
    w = ctx["weights"]
    why = []
    is_ref = new_field and ev is cur
    if new_field:
        why.append(tr(f"Najlepiej oceniona propozycja dla tego pola: {ev['total']}/100 przy Twoich priorytetach.",
                      f"Best-rated proposal for this field: {ev['total']}/100 with your priorities.") if is_ref else
                   tr(f"Ocena przy Twoich priorytetach: {ev['total']}/100 (propozycja A: {cur['total']}/100).",
                      f"Score with your priorities: {ev['total']}/100 (proposal A: {cur['total']}/100)."))
        if is_ref:
            top = sorted(ev["axes"].items(), key=lambda kv: -kv[1] * (w.get(kv[0], 0) + 0.01))[:2]
            why.append(tr("Najmocniejsze strony: ", "Strongest points: ") + ", ".join(f"{axn(k)} ({v}/100)" for k, v in top) + ".")
    elif is_current:
        why.append(tr(f"To Twój obecny płodozmian — punkt odniesienia. Ocena przy Twoich priorytetach: {ev['total']}/100.",
                      f"This is your current rotation — the baseline. Score with your priorities: {ev['total']}/100."))
    else:
        why.append(tr(f"Ocena przy Twoich priorytetach: {ev['total']}/100 (obecny: {cur['total']}/100).",
                      f"Score with your priorities: {ev['total']}/100 (current: {cur['total']}/100)."))
        top = sorted(((d * (w.get(k, 0) + 0.01), k) for k, d in diffs.items() if d > 0), reverse=True)[:2]
        if top:
            why.append(tr("Największy zysk w osiach, które są dla Ciebie ważne: ", "Biggest gains on the axes that matter to you: ") +
                       ", ".join(f"{axn(k)} (+{diffs[k]})" for _, k in top) + ".")
    weak_s, weak_id = ev["min_suit"]
    why.append(tr(f"Najsłabiej dopasowana uprawa: {cn(weak_id)} ({weak_s}/100 — {suit[weak_id]['limiting_label']}).",
                  f"Weakest-fitting crop: {cn(weak_id)} ({weak_s}/100 — {suit[weak_id]['limiting_label']})."))

    def vs(val):  # porównanie z punktem odniesienia: „(obecnie X)” / „(w A: X)”
        if is_current or is_ref:
            return ""
        return " (" + (tr("w A: ", "in A: ") if new_field else tr("obecnie ", "now ")) + f"{val})"

    ev_list = [
        tr(f"Klimatyczny bilans wodny lipca (opad − ET₀): {ind['july_balance']} mm, trend {ind['july_trend_dec']:+} mm/dekadę — {src['power']}, ET₀ wg FAO‑56.",
           f"July climatic water balance (rain − ET₀): {ind['july_balance']} mm, trend {ind['july_trend_dec']:+} mm/decade — {src['power']}, ET₀ per FAO‑56."),
        tr(f"Średni deficyt wody upraw w sezonie: {m['deficit_mm']} mm", f"Average crop water deficit in the season: {m['deficit_mm']} mm")
        + vs(f"{cm['deficit_mm']} mm") + tr(" — bilans ETc = ET₀·Kc.", " — balance ETc = ET₀·Kc."),
        tr(f"Okres gołej gleby: {m['bare_months']} mies./rok", f"Bare soil period: {m['bare_months']} months/year")
        + vs(cm['bare_months']) + tr(" — model kalendarza upraw.", " — crop calendar model."),
        tr(f"Ryzyko erozji RUSLE: {m['erosion_t_ha']} t/ha/rok", f"RUSLE erosion risk: {m['erosion_t_ha']} t/ha/year")
        + vs(cm['erosion_t_ha']) + tr(f" — R z opadów POWER, K z SoilGrids, LS z SRTM (nachylenie {ctx['slope']}%).",
                                      f" — R from POWER rainfall, K from SoilGrids, LS from SRTM (slope {ctx['slope']}%)."),
        tr(f"Bilans próchnicy: {m['humus_kg_c']:+} kg C/ha/rok", f"Humus balance: {m['humus_kg_c']:+} kg C/ha/year")
        + vs(f"{cm['humus_kg_c']:+}") + tr(" — współczynniki VDLUFA (Eich & Kundler).", " — VDLUFA coefficients (Eich & Kundler)."),
    ]
    pts = tr("pkt", "pts")
    benefits = [f"{axn(k)}: +{d} {pts}" for k, d in sorted(diffs.items(), key=lambda x: -x[1]) if d >= 5]
    cover_txt = tr(f"Międzyplon ścierniskowy: {ev['cover_type']}.", f"Stubble cover crop: {ev['cover_type']}.")
    if not is_current:
        if m["bare_months"] < cm["bare_months"] - 0.5:
            dm = round(cm['bare_months'] - m['bare_months'], 1)
            benefits.append(tr(f"Pole pokryte roślinami o {dm} mies./rok dłużej — mniej erozji i wymywania azotu.",
                               f"Field covered by plants {dm} months/year longer — less erosion and nitrogen leaching."))
        if ev["cover_type"]:
            benefits.append(cover_txt)
        if any(CROP_BY_ID[c]["nfix"] for c in ev["seq"]) and not any(CROP_BY_ID[c]["nfix"] for c in cur["seq"]):
            benefits.append(tr("Bobowate wiążą azot z powietrza — mniejsze dawki nawozów N dla następnej uprawy.",
                               "Legumes fix nitrogen from the air — lower N fertiliser rates for the next crop."))
    if is_ref:
        benefits = [f"{axn(k)}: {v}/100" for k, v in sorted(ev["axes"].items(), key=lambda kv: -kv[1])[:3]]
        if ev["cover_type"]:
            benefits.append(cover_txt)
    if not benefits and not is_current:
        benefits.append(tr("Niewielka poprawa względem obecnego — rozważ tylko przy zmianie rynku lub sprzętu.",
                           "Small improvement over the current one — consider only if your market or machinery changes."))

    gaps = [
        tr("Klimat z siatki NASA POWER ~0,5° (≈50 km) — z korektą wysokości, ale bez lokalnych mrozowisk i gradobić.",
           "Climate from the NASA POWER grid ~0.5° (≈50 km) — corrected for elevation, but without local frost pockets or hail."),
        tr("Wilgotność gleby GWETROOT to model (MERRA‑2), nie pomiar; SMAP 9 km zaplanowany jako rozszerzenie.",
           "GWETROOT soil moisture is a model (MERRA‑2), not a measurement; SMAP 9 km is planned as an extension."),
        tr("Gleba z SoilGrids (250 m, model) — warto zrobić analizę gleby w stacji chemiczno‑rolniczej.",
           "Soil from SoilGrids (250 m, model) — a lab soil test is worth doing."),
        tr("Brak lokalnych danych o presji chorób i szkodników, plonach i cenach — oś „Dochód” to względny indeks.",
           "No local data on disease and pest pressure, yields or prices — the “Income” axis is a relative index."),
        tr("Czynnik R erozji z miesięcznych opadów (indeks Fourniera), bez natężenia ulew z GPM IMERG — wartości bezwzględne orientacyjne, porównanie strategii wiarygodniejsze.",
           "Erosion R factor from monthly rainfall (Fournier index), without storm intensity from GPM IMERG — absolute values are indicative, comparing strategies is more reliable."),
    ]
    if ctx["errors"].get("ndvi"):
        gaps.append(tr("Profil NDVI (MODIS) niedostępny w tej analizie — okresy gołej gleby z modelu kalendarza.",
                       "NDVI profile (MODIS) unavailable in this analysis — bare-soil periods come from the calendar model."))
    risks = []
    for d in ev["disease_notes"][:3]:
        risks.append(d)
    for k, d in diffs.items():
        if d <= -5 and not is_current:
            risks.append(tr(f"Pogorszenie osi „{axn(k)}” o {-d} pkt.", f"“{axn(k)}” gets worse by {-d} pts."))
    for a, b in ev["late"]:
        risks.append(tr(f"{cn(a)} → {cn(b)}: późny zbiór wymusza opóźniony siew.", f"{cn(a)} → {cn(b)}: late harvest forces delayed sowing."))
    for a, b in ev["infeasible"]:
        risks.append(tr(f"{cn(a)} → {cn(b)}: zbiór zbyt późno na typowy termin siewu.", f"{cn(a)} → {cn(b)}: harvest too late for the usual sowing date."))
    for c in set(ev["seq"]):
        s = suit[c]
        if s["score"] < 60:
            risks.append(tr(f"{s['name']}: {s['limiting_label']} (ocena {s['score']}/100).", f"{s['name']}: {s['limiting_label']} (score {s['score']}/100)."))
    if ev["metrics"]["covers"] and ind["season_balance"] < -100:
        risks.append(tr("Międzyplon zużywa wodę — w suche lata zakończ go wcześniej (np. luty–marzec).",
                        "A cover crop uses water — in dry years end it earlier (e.g. February–March)."))
    if ind["drought_freq_recent"] > ind["drought_freq_early"] + 5:
        risks.append(tr(f"Susze glebowe częstsze w ostatnich latach ({ind['drought_freq_recent']}% mies. vs {ind['drought_freq_early']}% na początku okresu).",
                        f"Soil droughts more frequent in recent years ({ind['drought_freq_recent']}% of months vs {ind['drought_freq_early']}% at the start of the period)."))
    check = []
    new = sorted(set(ev["seq"])) if new_field else [c for c in set(ev["seq"]) if c not in cur["seq"]]
    if new_field:
        check.append(tr("Pierwszy rok na nowym polu (odłóg, łąka): zbadaj glebę (pH, P, K, Mg) i zwapnuj w razie potrzeby; "
                        "po starej darni spodziewaj się drutowców i dużej ilości chwastów.",
                        "First year on a new field (fallow, meadow): test the soil (pH, P, K, Mg) and lime if needed; "
                        "after old sod expect wireworms and many weeds."))
        if ctx.get("grassland"):
            check.append(tr("Działka ma w ewidencji łąki lub pastwiska — zaoranie trwałych użytków zielonych może być zakazane "
                            "lub wymagać zgody (warunkowość GAEC 1, obszary Natura 2000). Sprawdź w ARiMR przed orką.",
                            "The land register lists meadows or pastures on this parcel — ploughing permanent grassland may be banned "
                            "or need a permit (GAEC 1 conditionality, Natura 2000 sites). Check with the paying agency (ARiMR) before ploughing."))
    if new:
        check.append(tr("Rynek zbytu i ceny dla: ", "Market and prices for: ") + ", ".join(cn(c) for c in new) + ".")
        check.append(tr("Dostępność nasion/odmian dla regionu i potrzebny sprzęt (siewnik, kombajn, przechowywanie).",
                        "Seed/variety availability for the region and the machinery needed (drill, combine, storage)."))
    check.append(tr("Lokalna presja chorób, szkodników i chwastów — z doradcą ODR / agronomem.",
                    "Local pressure from diseases, pests and weeds — with an extension adviser / agronomist."))
    check.append(tr("Wymogi dopłat (ekoschematy, warunkowość — np. dywersyfikacja upraw, okrywa zimowa).",
                    "Subsidy requirements (eco-schemes, conditionality — e.g. crop diversification, winter cover)."))
    return {"why": why, "evidence": ev_list, "benefits": benefits, "gaps": gaps,
            "risks": risks or [tr("Brak istotnych ryzyk wykrytych w danych — sprawdź warunki lokalne.",
                                  "No significant risks found in the data — check local conditions.")], "check": check}
