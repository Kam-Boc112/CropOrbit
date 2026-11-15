"""Wskaźniki agroklimatyczne i ocena przydatności upraw.

Metody: GDD, daty przymrozków (percentyle), ET0 FAO-56 Penman-Monteith, bilans wodny
uprawy (ET0·Kc vs opad efektywny + woda glebowa), anomalie wilgotności gleby (z-score),
stres cieplny, RUSLE (K, LS, R), ocena przydatności w stylu FAO Ecocrop (prawo minimum).
"""
import datetime as dt
import math

from crops import cn, cnote
from i18n import tr

MONTHS_PL = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"]
MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DIM = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
LAPSE = 0.0065  # °C/m


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * q
    f = math.floor(k)
    c = min(f + 1, len(xs) - 1)
    return xs[f] + (xs[c] - xs[f]) * (k - f)


def linreg(xs, ys):
    pts = [(x, y) for x, y in zip(xs, ys) if y is not None]
    n = len(pts)
    if n < 3:
        return 0.0, 0.0
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts)
    b = sxy / sxx if sxx else 0.0
    return b, my - b * mx


def mf_to_md(mf):
    """Miesiąc zmiennoprzecinkowy → (miesiąc, dzień)."""
    m = int(mf)
    d = 1 + int((mf - m) * DIM[m - 1])
    return m, min(d, DIM[m - 1])


def _sat_vp(t):
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


def et0_fao56(tmax, tmin, rh, u2, rs, lat_rad, z, doy):
    """Ewapotranspiracja wzorcowa ET0 [mm/d], FAO-56 Penman-Monteith (krok dobowy)."""
    t = (tmax + tmin) / 2
    es = (_sat_vp(tmax) + _sat_vp(tmin)) / 2
    ea = es * clamp(rh, 1, 100) / 100
    delta = 4098 * _sat_vp(t) / (t + 237.3) ** 2
    p = 101.3 * ((293 - 0.0065 * z) / 293) ** 5.26
    gamma = 0.000665 * p
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365)
    dec = 0.409 * math.sin(2 * math.pi * doy / 365 - 1.39)
    ws = math.acos(clamp(-math.tan(lat_rad) * math.tan(dec), -1, 1))
    ra = 24 * 60 / math.pi * 0.0820 * dr * (ws * math.sin(lat_rad) * math.sin(dec)
                                           + math.cos(lat_rad) * math.cos(dec) * math.sin(ws))
    rso = max((0.75 + 2e-5 * z) * ra, 0.1)
    rns = 0.77 * rs
    rnl = 4.903e-9 * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2 * \
        (0.34 - 0.14 * math.sqrt(ea)) * (1.35 * clamp(rs / rso, 0.25, 1.0) - 0.35)
    rn = rns - rnl
    et0 = (0.408 * delta * rn + gamma * 900 / (t + 273) * u2 * (es - ea)) / (delta + gamma * (1 + 0.34 * u2))
    return max(0.0, et0)


class Climate:
    """Szeregi dobowe z NASA POWER w „kalendarzu agronomicznym”
    (dla półkuli południowej przesunięte o 182 dni, by sezony odpowiadały północnym)."""

    def __init__(self, power, lat, field_elev):
        self.lat = lat
        self.shift = 182 if lat < 0 else 0
        grid_elev = power.get("grid_elev")
        self.grid_elev = grid_elev
        self.field_elev = field_elev
        if field_elev is not None and grid_elev is not None:
            self.lapse = -LAPSE * (field_elev - grid_elev)
            z = field_elev
        else:
            self.lapse, z = 0.0, grid_elev or 100.0
        self.z = z

        def ffill(arr, default):
            out, last = [], default
            for v in arr:
                last = v if v is not None else last
                out.append(last)
            return out

        tmax = [v + self.lapse for v in ffill(power["T2M_MAX"], 10)]
        tmin = [v + self.lapse for v in ffill(power["T2M_MIN"], 0)]
        rh = ffill(power["RH2M"], 75)
        ws = ffill(power["WS2M"], 2)
        rs = ffill(power["ALLSKY_SFC_SW_DWN"], 10)
        self.p = [v if v is not None else 0.0 for v in power["PRECTOTCORR"]]
        self.gw = power["GWETROOT"]
        self.snow = ffill(power.get("SNODP") or [0.0] * len(self.p), 0.0)
        self.tmax, self.tmin = tmax, tmin
        self.tmean = [(a + b) / 2 for a, b in zip(tmax, tmin)]
        real = [dt.date(int(s[:4]), int(s[4:6]), int(s[6:])) for s in power["dates"]]
        lat_rad = math.radians(lat)
        self.et0 = [et0_fao56(tmax[i], tmin[i], rh[i], ws[i], rs[i], lat_rad, z, real[i].timetuple().tm_yday)
                    for i in range(len(real))]
        self.dates = [d + dt.timedelta(days=self.shift) for d in real]
        self.d0 = self.dates[0]
        counts = {}
        for d in self.dates:
            counts[d.year] = counts.get(d.year, 0) + 1
        self.years = sorted(y for y, c in counts.items() if c >= 365)

    # ---- pomocnicze
    def idx(self, d):
        i = (d - self.d0).days
        return i if 0 <= i < len(self.dates) else None

    def real_label(self, agro_doy):
        d = dt.date(2001, 1, 1) + dt.timedelta(days=int(round(agro_doy)) - 1 - self.shift)
        return f"{d.day:02d}.{d.month:02d}"

    def month_labels(self):
        months = tr(MONTHS_PL, MONTHS_EN)
        return [months[(m - 1 - (6 if self.shift else 0)) % 12] for m in range(1, 13)]

    def season(self, sow, harvest, winter, year):
        sm, sd = mf_to_md(sow)
        hm, hd = mf_to_md(harvest)
        a = self.idx(dt.date(year - 1 if winter else year, sm, sd))
        b = self.idx(dt.date(year, hm, hd))
        if a is None or b is None or b <= a:
            return None
        return range(a, b + 1)

    # ---- wskaźniki pola
    def summary(self):
        ys = self.years
        by_ym = {}
        for i, d in enumerate(self.dates):
            if d.year in ys:
                by_ym.setdefault((d.year, d.month), []).append(i)

        def agg(arr, fn):
            return {k: fn([arr[i] for i in v]) for k, v in by_ym.items()}

        P = agg(self.p, sum)
        E = agg(self.et0, sum)
        T = agg(self.tmean, lambda x: sum(x) / len(x))
        TX = agg(self.tmax, lambda x: sum(x) / len(x))
        TN = agg(self.tmin, lambda x: sum(x) / len(x))
        GW = agg(self.gw, mean)
        FR = agg(self.tmin, lambda x: sum(1 for v in x if v < 0) / len(x))
        FR2 = agg(self.tmin, lambda x: sum(1 for v in x if v < -2) / len(x))
        H30 = agg(self.tmax, lambda x: sum(1 for v in x if v >= 30))
        EROS = agg(self.p, lambda x: sum(v for v in x if v >= 12.7))

        def clim(D):
            return [round(mean([D[(y, m)] for y in ys]), 2) for m in range(1, 13)]

        monthly = {"labels": self.month_labels(), "p": clim(P), "et0": clim(E), "tmean": clim(T),
                   "tmax": clim(TX), "tmin": clim(TN), "gw": clim(GW), "frost_prob": clim(FR),
                   "frost2_prob": clim(FR2), "heat30_days": clim(H30), "erosive_p": clim(EROS)}
        monthly["balance"] = [round(a - b, 1) for a, b in zip(monthly["p"], monthly["et0"])]

        # z-score wilgotności gleby (GWETROOT) w miesiącach IV–IX
        gw_stats = {}
        for m in range(1, 13):
            vals = [GW[(y, m)] for y in ys if GW.get((y, m)) is not None]
            mu = mean(vals)
            sd = (sum((v - mu) ** 2 for v in vals) / (len(vals) - 1)) ** 0.5 if len(vals) > 2 else None
            gw_stats[m] = (mu, sd)
        drought_months, gw_z = {}, {}
        for y in ys:
            n = 0
            zs = []
            for m in range(4, 10):
                mu, sd = gw_stats[m]
                v = GW.get((y, m))
                if v is None or not sd:
                    continue
                z = (v - mu) / sd
                zs.append(z)
                n += z < -1
            drought_months[y] = n
            gw_z[y] = round(mean(zs), 2) if zs else None

        # przymrozki, GDD, upał, ekstremalne opady — per rok
        frost_spring, frost_autumn, ffd, tmin_min, gdd5, gdd10, heat_days, heavy_rain = {}, {}, {}, {}, {}, {}, {}, {}
        for y in ys:
            ii = [i for i, d in enumerate(self.dates) if d.year == y]
            sp = [self.dates[i].timetuple().tm_yday for i in ii if self.tmin[i] < 0 and self.dates[i].timetuple().tm_yday <= 196]
            au = [self.dates[i].timetuple().tm_yday for i in ii if self.tmin[i] < 0 and self.dates[i].timetuple().tm_yday > 196]
            frost_spring[y] = max(sp) if sp else 0
            frost_autumn[y] = min(au) if au else 366
            ffd[y] = frost_autumn[y] - frost_spring[y] - 1
            tmin_min[y] = min(self.tmin[i] for i in ii)
            gdd5[y] = sum(max(0, self.tmean[i] - 5) for i in ii)
            gdd10[y] = sum(max(0, self.tmean[i] - 10) for i in ii if 5 <= self.dates[i].month <= 9)
            heat_days[y] = sum(1 for i in ii if self.tmax[i] >= 30)
            heavy_rain[y] = sum(1 for i in ii if self.p[i] >= 20)

        yearly = {
            "years": ys,
            "tmean": [round(mean([T[(y, m)] for m in range(1, 13)]), 2) for y in ys],
            "p": [round(sum(P[(y, m)] for m in range(1, 13))) for y in ys],
            "et0": [round(sum(E[(y, m)] for m in range(1, 13))) for y in ys],
            "july_balance": [round(P[(y, 7)] - E[(y, 7)], 1) for y in ys],
            "season_balance": [round(sum(P[(y, m)] - E[(y, m)] for m in range(4, 10)), 1) for y in ys],
            "drought_months": [drought_months[y] for y in ys],
            "gw_z": [gw_z[y] for y in ys],
            "heat_days": [heat_days[y] for y in ys],
            "ffd": [ffd[y] for y in ys],
        }
        sl_t, _ = linreg(ys, yearly["tmean"])
        sl_j, _ = linreg(ys, yearly["july_balance"])
        sl_s, _ = linreg(ys, yearly["season_balance"])
        sl_h, _ = linreg(ys, yearly["heat_days"])
        p_ann = mean(yearly["p"])
        half = len(ys) // 2

        ind = {
            "period": f"{ys[0]}–{ys[-1]}", "n_years": len(ys),
            "lapse_corr": round(self.lapse, 2), "grid_elev": self.grid_elev, "field_elev": self.field_elev,
            "tmean": round(mean(yearly["tmean"]), 1), "t_trend_dec": round(sl_t * 10, 2),
            "p_annual": round(p_ann), "et0_annual": round(mean(yearly["et0"])),
            "gdd5": round(mean(gdd5.values())), "gdd10_may_sep": round(mean(gdd10.values())),
            "gdd10_p10": round(pct(gdd10.values(), 0.1)),
            "frost_last_spring": {q: self.real_label(pct(frost_spring.values(), v)) for q, v in (("p10", .1), ("p50", .5), ("p90", .9))},
            "frost_first_autumn": {q: self.real_label(pct(frost_autumn.values(), v)) for q, v in (("p10", .1), ("p50", .5), ("p90", .9))},
            "frost_spring_p90_doy": round(pct(frost_spring.values(), .9)),
            "ffd_median": round(pct(ffd.values(), 0.5)), "ffd_p10": round(pct(ffd.values(), 0.1)),
            "tmin_p10": round(pct(tmin_min.values(), 0.1), 1),
            "july_balance": round(mean(yearly["july_balance"])), "july_trend_dec": round(sl_j * 10, 1),
            "season_balance": round(mean(yearly["season_balance"])), "season_trend_dec": round(sl_s * 10, 1),
            "deficit_months": [monthly["labels"][m] for m in range(12) if monthly["balance"][m] < -20],
            "drought_freq": round(mean([drought_months[y] / 6 for y in ys]) * 100),
            "drought_freq_recent": round(mean([drought_months[y] / 6 for y in ys[-8:]]) * 100),
            "drought_freq_early": round(mean([drought_months[y] / 6 for y in ys[:8]]) * 100),
            "heat_days": round(mean(yearly["heat_days"]), 1), "heat_trend_dec": round(sl_h * 10, 1),
            "heat_days_recent": round(mean(yearly["heat_days"][half:]), 1),
            "heat_days_early": round(mean(yearly["heat_days"][:half]), 1),
            "heavy_rain_days": round(mean(heavy_rain.values()), 1),
            "max_daily_p": round(max(self.p), 1),
        }
        return {"monthly": monthly, "yearly": yearly, "ind": ind,
                "_ffd": list(ffd.values()), "_tmin_min": list(tmin_min.values())}


# ---------------------------------------------------------------- gleba i erozja
def soil_props(soil):
    s = dict(soil or {})
    missing = not s or any(s.get(k) is None for k in ("phh2o", "clay", "sand", "silt", "soc"))
    defaults = {"phh2o": 6.3, "clay": 18, "sand": 40, "silt": 42, "soc": 12, "bdod": 1.4}
    for k, v in defaults.items():
        if s.get(k) is None:
            s[k] = v
    oc = s["soc"] / 10  # g/kg → %
    sand, silt, clay = s["sand"], s["silt"], s["clay"]
    # Indeks erodowalności K (Williams 1995, EPIC), przeliczony na t·ha·h/(ha·MJ·mm)
    fcsand = 0.2 + 0.3 * math.exp(-0.256 * sand * (1 - silt / 100))
    fclsi = (silt / max(clay + silt, 1)) ** 0.3
    forgc = 1 - 0.25 * oc / (oc + math.exp(3.72 - 2.95 * oc))
    sn1 = 1 - sand / 100
    fhis = 1 - 0.7 * sn1 / (sn1 + math.exp(-5.51 + 22.9 * sn1))
    k = fcsand * fclsi * forgc * fhis * 0.1317
    awc = clamp(200 - 1.3 * max(0, sand - 20) - 0.8 * max(0, clay - 35), 70, 220)
    tex = texture_class(sand, clay)
    return {"ph": round(s["phh2o"], 1), "clay": round(clay), "sand": round(sand), "silt": round(silt),
            "oc_pct": round(oc, 2), "bdod": s.get("bdod"), "k": round(k, 4), "awc_mm_m": round(awc),
            "texture": tex, "missing": missing}


def texture_class(sand, clay):
    if sand >= 85:
        return tr("piasek", "sand")
    if sand >= 70:
        return tr("piasek gliniasty", "loamy sand")
    if clay >= 40:
        return tr("ił / glina ciężka", "clay / heavy loam")
    if clay >= 27:
        return tr("glina ilasta", "clay loam")
    if sand >= 50:
        return tr("glina piaszczysta", "sandy loam")
    if sand < 20 and clay < 27:
        return tr("pył / glina pylasta", "silt / silt loam")
    return tr("glina", "loam")


def rusle_r(monthly_p):
    """Erozyjność opadów R [MJ·mm/(ha·h·rok)] ze zmodyfikowanego indeksu Fourniera
    MFI = Σ p_i² / P (Arnoldus 1977, FAO): R = 0.302 · MFI^1.93. Przybliżenie — bez danych 30-min."""
    P = sum(monthly_p) or 1
    mfi = sum(p * p for p in monthly_p) / P
    return 0.302 * mfi ** 1.93


def rusle_ls(slope_pct, length_m=100):
    s = slope_pct or 0.0
    th = math.atan(s / 100)
    m = 0.2 if s < 1 else 0.3 if s < 3 else 0.4 if s < 5 else 0.5
    L = (length_m / 22.13) ** m
    S = 10.8 * math.sin(th) + 0.03 if s < 9 else 16.8 * math.sin(th) - 0.5
    return L * S


# ---------------------------------------------------------------- przydatność upraw
FACTOR_LABEL = {
    "klasa": ("za słaba klasa gruntu (EGiB)", "soil class too low (land register)"),
    "temp": ("za mało ciepła — uprawa może nie dojrzeć", "not enough heat — the crop may not ripen"),
    "water": ("ryzyko niedoboru wody w sezonie", "risk of water shortage in the season"),
    "ph": ("nieodpowiednie pH gleby", "unsuitable soil pH"),
    "winter": ("ryzyko wymarznięcia zimą", "risk of winterkill"),
    "frostfree": ("za krótki okres bez przymrozków", "frost-free period too short"),
    "heat": ("stres cieplny w okresie kwitnienia", "heat stress during flowering"),
    "texture": ("niedopasowany typ gleby", "unsuitable soil type"),
    "slope": ("zbyt strome pole dla uprawy szerokorzędowej", "field too steep for a row crop"),
}
FACTOR_NAME = {"temp": ("Ciepło (GDD)", "Heat (GDD)"), "water": ("Woda", "Water"), "ph": ("pH", "pH"),
               "winter": ("Zimowanie", "Winter survival"), "frostfree": ("Okres bezprzymrozkowy", "Frost-free period"),
               "heat": ("Upał", "Heat stress"), "texture": ("Gleba", "Soil"), "slope": ("Nachylenie", "Slope"),
               "klasa": ("Klasa gruntu", "Soil class")}


def crop_season_stats(crop, clim, awc_mm_m):
    """Statystyki sezonu uprawy dla każdego roku: GDD, ETc, opad efektywny, deficyt."""
    kc_i, kc_m, kc_e = crop["kc"]
    awc_root = awc_mm_m * min(crop["root"], 1.5) * 0.5  # łatwo dostępna woda w strefie korzeni
    out = []
    for y in clim.years:
        rng = clim.season(crop["sow"], crop["harvest"], crop["winter"], y)
        if rng is None:
            continue
        n = len(rng)
        gdd = etc = p = heat = 0.0
        for j, i in enumerate(rng):
            f = j / max(n - 1, 1)
            kc = kc_i if f < 0.25 else kc_i + (kc_m - kc_i) * (f - 0.25) / 0.15 if f < 0.4 else \
                kc_m if f < 0.75 else kc_m + (kc_e - kc_m) * (f - 0.75) / 0.25
            if crop["winter"] and clim.tmean[i] < 5:
                kc = min(kc, kc_i)
            gdd += max(0.0, clim.tmean[i] - crop["tbase"])
            etc += kc * clim.et0[i]
            p += clim.p[i]
            if clim.dates[i].month == crop["heat_month"] and clim.tmax[i] > crop["heat_t"]:
                heat += 1
        peff = 0.75 * p
        out.append({"year": y, "gdd": gdd, "etc": etc, "p": p, "peff": peff,
                    "ratio": (peff + awc_root) / etc if etc else 2.0,
                    "deficit": max(0.0, etc - peff - awc_root), "heat": heat})
    return out


def winter_kill_share(clim, frost_kill, snow_cm=3.0):
    """Udział zim z „gołoledziowym” mrozem: Tmin < próg przy braku ochronnej pokrywy śnieżnej
    (grubość śniegu SNODP z NASA POWER/MERRA-2)."""
    hits = n = 0
    for y in clim.years[1:]:
        a, b = clim.idx(dt.date(y - 1, 11, 1)), clim.idx(dt.date(y, 3, 31))
        if a is None or b is None:
            continue
        n += 1
        hits += any(clim.tmin[i] < frost_kill and clim.snow[i] < snow_cm for i in range(a, b + 1))
    return hits / n if n else 0.0


CLASS_NAME = {1: "I", 2: "II", 3: "IIIa", 4: "IIIb", 5: "IVa", 6: "IVb", 7: "V", 8: "VI"}


def class_factor(rank, ok):
    """Każda klasa poniżej wymaganej obniża ocenę o 20 pkt, nie mniej niż 30."""
    return 1.0 if rank <= ok else clamp(1 - 0.2 * (rank - ok), 0.3, 1.0)


def suitability(crop, clim, cs, soil, terrain, irrigation, soil_class=None):
    stats = crop_season_stats(crop, clim, soil["awc_mm_m"])
    f = {}
    det = {}
    g = [s["gdd"] / crop["gdd"] for s in stats]
    f["temp"] = mean([clamp((r - 0.75) / 0.25) for r in g])
    g_avg, g_p10 = round(mean([s['gdd'] for s in stats])), round(pct([s['gdd'] for s in stats], .1))
    det["temp"] = tr(f"średnio {g_avg} °C·d (baza {crop['tbase']} °C), wymagane ~{crop['gdd']}; w najchłodniejszym 1 na 10 lat {g_p10}",
                     f"average {g_avg} °C·d (base {crop['tbase']} °C), needed ~{crop['gdd']}; in the coolest 1 in 10 years {g_p10}")
    ratios = [s["ratio"] for s in stats]
    if irrigation:
        f["water"] = 1.0
    else:
        f["water"] = mean([clamp((r - crop["r_min"]) / (0.9 - crop["r_min"])) for r in ratios])
    dry_share = sum(1 for r in ratios if r < 0.8) / max(len(ratios), 1)
    etc, peff, dry = round(mean([s['etc'] for s in stats])), round(mean([s['peff'] for s in stats])), round(dry_share * 100)
    det["water"] = tr(f"zapotrzebowanie ETc ~{etc} mm, opad efektywny ~{peff} mm + woda glebowa; deficyt w {dry}% lat"
                      + (" (nawadnianie pokrywa niedobór)" if irrigation else ""),
                      f"crop demand ETc ~{etc} mm, effective rain ~{peff} mm + soil water; deficit in {dry}% of years"
                      + (" (irrigation covers the shortfall)" if irrigation else ""))
    a, o1, o2, b = crop["ph"]
    ph = soil["ph"]
    f["ph"] = 1.0 if o1 <= ph <= o2 else clamp((ph - a) / (o1 - a)) if ph < o1 else clamp((b - ph) / (b - o2))
    det["ph"] = f"pH {ph}; optimum {o1}–{o2}" + (tr(" — gleba za kwaśna (wapnowanie?)", " — soil too acidic (liming?)") if ph < o1
                                                 else tr(" — gleba zbyt zasadowa", " — soil too alkaline") if ph > o2 else "")
    if crop["winter"] and crop["frost_kill"] is not None:
        share = winter_kill_share(clim, crop["frost_kill"])
        f["winter"] = clamp(1 - 2.5 * share, 0.3, 1.0)
        det["winter"] = tr(f"mróz poniżej {crop['frost_kill']} °C przy pokrywie śnieżnej < 3 cm w "
                           f"{round(share * 100)}% zim (najzimniejsza noc w 1 na 10 zim: {cs['ind']['tmin_p10']} °C)",
                           f"frost below {crop['frost_kill']} °C with snow cover < 3 cm in "
                           f"{round(share * 100)}% of winters (coldest night in 1 in 10 winters: {cs['ind']['tmin_p10']} °C)")
    if crop["ffd"]:
        med = cs["ind"]["ffd_median"]
        f["frostfree"] = clamp((med - (crop["ffd"] - 30)) / 30)
        det["frostfree"] = tr(f"okres bez przymrozków (mediana) {med} dni; potrzeba ~{crop['ffd']}",
                              f"frost-free period (median) {med} days; needs ~{crop['ffd']}")
    hd = mean([s["heat"] for s in stats]) or 0
    f["heat"] = clamp(1 - (hd - 2) * 0.4 / 10, 0.6, 1.0)  # upał obniża plon, rzadko wyklucza uprawę
    hm = clim.month_labels()[crop['heat_month'] - 1]
    det["heat"] = tr(f"średnio {hd:.1f} dni z Tmax > {crop['heat_t']} °C w krytycznym miesiącu ({hm})",
                     f"on average {hd:.1f} days with Tmax > {crop['heat_t']} °C in the critical month ({hm})")
    tx = 1.0
    tdet = tr(f"{soil['texture']} (piasek {soil['sand']}%, ił {soil['clay']}%)", f"{soil['texture']} (sand {soil['sand']}%, clay {soil['clay']}%)")
    too_light = bool(crop["max_sand"] and soil["sand"] > crop["max_sand"])
    if too_light:
        tx = min(tx, clamp(1 - (soil["sand"] - crop["max_sand"]) / 20 * 0.6, 0.4, 1))
        tdet += tr(" — za lekka", " — too light")
    if crop["max_clay"] and soil["clay"] > crop["max_clay"]:
        tx = min(tx, clamp(1 - (soil["clay"] - crop["max_clay"]) / 20 * 0.6, 0.4, 1))
        tdet += tr(" — za ciężka", " — too heavy")
    f["texture"] = tx
    det["texture"] = tdet
    slope = (terrain or {}).get("slope_pct") or 0
    if crop["row"]:
        f["slope"] = 0.6 if slope > 12 else 0.8 if slope > 8 else 1.0
        det["slope"] = tr(f"nachylenie {slope:.1f}%", f"slope {slope:.1f}%")
    if soil_class:  # klasa bonitacyjna z EGiB (tylko Polska, gdy zaznaczono działki)
        f["klasa"] = class_factor(soil_class["rank"], crop["cls_ok"])
        ok = CLASS_NAME[crop['cls_ok']]
        det["klasa"] = tr(f"klasa {soil_class['cls']} ({soil_class['basis']}); bez obniżki do klasy {ok}"
                          + (" — gleba słabsza niż wymaga uprawa" if f["klasa"] < 1 else ""),
                          f"class {soil_class['cls']} ({soil_class['basis']}); no penalty down to class {ok}"
                          + (" — soil weaker than the crop needs" if f["klasa"] < 1 else ""))
    lim = min(f, key=f.get)
    geo = math.exp(sum(math.log(max(v, 0.01)) for v in f.values()) / len(f))
    score = round(100 * f[lim])
    label = tr(*FACTOR_LABEL[lim])
    if lim == "ph":
        label = tr("gleba za kwaśna", "soil too acidic") if ph < o1 else tr("gleba zbyt zasadowa", "soil too alkaline")
    if lim == "texture":
        label = tr("gleba zbyt lekka", "soil too light") if too_light else tr("gleba zbyt ciężka", "soil too heavy")
    return {
        "id": crop["id"], "name": cn(crop), "family": crop["family"], "score": score,
        "geo": round(100 * geo), "limiting": lim if f[lim] < 0.999 else None,
        "limiting_label": label if f[lim] < 0.999 else tr("brak istotnych ograniczeń", "no significant limits"),
        "factors": [{"key": k, "name": tr(*FACTOR_NAME[k]), "value": round(v * 100), "detail": det[k]} for k, v in f.items()],
        "deficit_mm": round(mean([s["deficit"] for s in stats]) or 0),
        "dry_share": round(dry_share * 100), "water_m": f["water"], "note": cnote(crop),
    }
