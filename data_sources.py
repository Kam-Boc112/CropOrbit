"""Pobieranie danych: NASA POWER, SoilGrids (ISRIC), SRTM (OpenTopoData), MODIS NDVI (ORNL DAAC).

Wszystkie źródła są publiczne i nie wymagają kont. Wyniki są zapisywane w cache/ na dysku.
"""
import concurrent.futures as cf
import hashlib
import json
import math
import os
import time
import urllib.parse
import urllib.request

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
UA = "CropOrbit/0.1 (NASA Space Apps prototype)"
_FAIL_UNTIL = {}  # źródło → znacznik czasu; nie czekamy wielokrotnie na niedziałający serwis

POWER_START, POWER_END = 2001, 2024
POWER_PARAMS = ["T2M_MAX", "T2M_MIN", "T2M", "RH2M", "WS2M",
                "ALLSKY_SFC_SW_DWN", "PRECTOTCORR", "GWETROOT", "GWETTOP", "SNODP"]


def _get_json(url, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


COOLDOWN_MSG = "źródło niedostępne (ponowna próba za kilka minut)"


def _cached(key, fn, cache_only=False):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, hashlib.sha1(key.encode()).hexdigest()[:20] + ".json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    if cache_only:  # serwis chwilowo wyłączony po błędzie — bez pliku w cache nie próbujemy sieci
        raise RuntimeError(COOLDOWN_MSG)
    val = fn()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(val, f)
    return val


# ---------------------------------------------------------------- NASA POWER
def fetch_power(lat, lon):
    """Dzienne dane klimatyczne NASA POWER (community AG), 2001–2024."""
    lat, lon = round(lat, 3), round(lon, 3)

    def go():
        q = urllib.parse.urlencode({
            "parameters": ",".join(POWER_PARAMS), "community": "AG",
            "latitude": lat, "longitude": lon,
            "start": f"{POWER_START}0101", "end": f"{POWER_END}1231", "format": "JSON",
        })
        d = _get_json("https://power.larc.nasa.gov/api/temporal/daily/point?" + q, timeout=180)
        par = d["properties"]["parameter"]
        dates = sorted(par["T2M_MAX"].keys())
        out = {"dates": dates, "grid_elev": d["geometry"]["coordinates"][2]}
        for p in POWER_PARAMS:
            out[p] = [(None if (v := par[p].get(k)) is None or v <= -998 else v) for k in dates]
        return out

    return _cached(f"power:{lat}:{lon}:{POWER_START}:{POWER_END}:{','.join(POWER_PARAMS)}", go)


# ---------------------------------------------------------------- SoilGrids
def fetch_soil(lat, lon):
    """Średnie właściwości gleby 0–30 cm z SoilGrids 2.0 (250 m)."""
    lat, lon = round(lat, 4), round(lon, 4)

    def go():
        props = ["phh2o", "clay", "sand", "silt", "soc", "bdod"]
        depths = [("0-5cm", 5), ("5-15cm", 10), ("15-30cm", 15)]
        q = urllib.parse.urlencode([("lon", lon), ("lat", lat)] + [("property", p) for p in props]
                                   + [("depth", d) for d, _ in depths] + [("value", "mean")])
        d = _get_json("https://rest.isric.org/soilgrids/v2.0/properties/query?" + q, timeout=60)
        out = {}
        for layer in d["properties"]["layers"]:
            fac = layer["unit_measure"].get("d_factor", 1) or 1
            acc, wsum = 0.0, 0
            for dep in layer["depths"]:
                w = dict(depths).get(dep["label"], 0)
                v = dep["values"].get("mean")
                if v is not None and w:
                    acc += v / fac * w
                    wsum += w
            out[layer["name"]] = round(acc / wsum, 3) if wsum else None
        # jednostki po d_factor: pH, clay/sand/silt [%], soc [g/kg], bdod [g/cm3]
        return out

    return _cached(f"soil:{lat}:{lon}", go)


# ---------------------------------------------------------------- SRTM
def fetch_terrain(lat, lon, step_m=60):
    """Wysokość, nachylenie i ekspozycja z SRTM 30 m (siatka 3x3, metoda Horna)."""
    lat, lon = round(lat, 5), round(lon, 5)

    def go():
        dlat = step_m / 111320.0
        dlon = step_m / (111320.0 * math.cos(math.radians(lat)))
        pts = [(lat + r * dlat, lon + c * dlon) for r in (1, 0, -1) for c in (-1, 0, 1)]
        locs = "|".join(f"{a:.6f},{b:.6f}" for a, b in pts)
        d = _get_json("https://api.opentopodata.org/v1/srtm30m?locations=" + locs, timeout=60)
        z = [r["elevation"] for r in d["results"]]
        if any(v is None for v in z):
            return {"elev": z[4], "slope_pct": None, "aspect": None}
        a, b, c, dd, e, f, g, h, i = z
        dzdx = ((c + 2 * f + i) - (a + 2 * dd + g)) / (8 * step_m)
        dzdy = ((a + 2 * b + c) - (g + 2 * h + i)) / (8 * step_m)
        slope = math.hypot(dzdx, dzdy) * 100
        aspect = (math.degrees(math.atan2(-dzdx, -dzdy)) + 360) % 360  # kierunek spadku
        return {"elev": e, "slope_pct": round(slope, 2), "aspect": round(aspect),
                "relief_m": round(max(z) - min(z), 1)}

    return _cached(f"srtm:{lat}:{lon}:{step_m}", go)


# ---------------------------------------------------------------- MODIS NDVI
def fetch_ndvi(lat, lon, years=(2021, 2022, 2023), cache_only=False):
    """Profil NDVI z MODIS MOD13Q1 (250 m, kompozyty 16-dniowe) przez ORNL DAAC REST."""
    lat, lon = round(lat, 4), round(lon, 4)

    def chunk(year, k):
        doys = [1 + 16 * j for j in range(23)][k * 10:(k + 1) * 10]
        q = urllib.parse.urlencode({
            "latitude": lat, "longitude": lon, "band": "250m_16_days_NDVI",
            "startDate": f"A{year}{doys[0]:03d}", "endDate": f"A{year}{doys[-1]:03d}",
            "kmAboveBelow": 0, "kmLeftRight": 0})
        d = _get_json("https://modis.ornl.gov/rst/api/v1/MOD13Q1/subset?" + q, timeout=20)
        res = []
        for s in d.get("subset", []):
            v = s["data"][0]
            if v is not None and v > -2000:
                res.append((int(s["modis_date"][5:]), v * 0.0001))
        return year, res

    def go():
        jobs = [(y, k) for y in years for k in range(3)]
        series = {}
        with cf.ThreadPoolExecutor(max_workers=6) as ex:
            for y, res in ex.map(lambda a: chunk(*a), jobs):
                for doy, v in res:
                    series.setdefault(doy, []).append(v)
        if not series:
            raise RuntimeError("brak danych NDVI")
        prof = [{"doy": d, "ndvi": round(sum(v) / len(v), 3), "n": len(v)} for d, v in sorted(series.items())]
        return {"years": list(years), "profile": prof}

    return _cached(f"ndvi:{lat}:{lon}:{years}", go, cache_only)


def fetch_all(lat, lon):
    """Pobiera wszystkie źródła równolegle; błąd jednego źródła nie zatrzymuje analizy."""
    tasks = {"power": fetch_power, "soil": fetch_soil, "terrain": fetch_terrain, "ndvi": fetch_ndvi}
    limits = {"power": 240, "soil": 70, "terrain": 70, "ndvi": 25}  # NDVI jest opcjonalne
    out, errors = {}, {}
    now = time.time()
    ex = cf.ThreadPoolExecutor(max_workers=4)
    futs = {}
    cooling = set()
    for k, fn in tasks.items():
        if _FAIL_UNTIL.get(k, 0) > now:  # tylko NDVI: po błędzie przez 10 min czytamy jedynie cache
            cooling.add(k)
            futs[k] = ex.submit(fn, lat, lon, cache_only=True)
        else:
            futs[k] = ex.submit(fn, lat, lon)
    for k, fut in futs.items():
        try:
            out[k] = fut.result(timeout=limits[k])
        except Exception as e:  # noqa: BLE001 — każde źródło może zawieść niezależnie
            out[k] = None
            errors[k] = COOLDOWN_MSG if k in cooling else (f"{type(e).__name__}: {e}"[:200] or type(e).__name__)
            if k == "ndvi" and k not in cooling:
                _FAIL_UNTIL[k] = time.time() + 600
    ex.shutdown(wait=False, cancel_futures=True)
    out["errors"] = errors
    return out
