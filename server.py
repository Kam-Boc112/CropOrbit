"""CropOrbit — serwer (tylko biblioteka standardowa Pythona, bez instalacji pakietów).

Uruchomienie:   python server.py            → http://localhost:8000
Pobranie danych pól demo z wyprzedzeniem:   python server.py --prefetch
"""
import json
import mimetypes
import os
import sys
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import ai
import analysis
import parcels
from crops import public_list
from i18n import lang, set_lang, tr

for _s in (sys.stdout, sys.stderr):  # konsola Windows (cp1252) nie zna polskich znaków
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")

DEMO = os.path.join(STATIC, "demo")  # gotowe wyniki pól przykładowych: python server.py --snapshot

# Pola przykładowe. Wyniki z --snapshot pokazują się od ręki, także na hostingu statycznym (bez Pythona).
DEMO_FIELDS = [
    {"id": "trzciana", "name": ("Działka Trzciana 723/1 (Podkarpacie)", "Parcel Trzciana 723/1 (Poland)"), "lat": 50.08061, "lon": 21.85008,
     "parcels": ["181612_2.0009.723/1"], "rotation": ["barley_w", "wheat_w", "rapeseed_w", "barley_w", "triticale_w", "oats"]},
    {"id": "rzeszow", "name": ("Pole pod Rzeszowem (Podkarpacie)", "Field near Rzeszów (Poland)"), "lat": 50.03, "lon": 21.95,
     "rotation": ["wheat_w", "maize_g", "wheat_w"]},
    {"id": "iowa", "name": ("Pole w Iowa (Corn Belt, USA)", "Field in Iowa (Corn Belt, USA)"), "lat": 42.015, "lon": -93.765,
     "rotation": ["maize_g", "soy"]},
]


def demo_list():
    return [dict(f, name=tr(*f["name"])) for f in DEMO_FIELDS]


def demo_request(f):
    """To samo zapytanie, które wysyła przycisk pola przykładowego (ustawienia domyślne formularza)."""
    return {"lat": f["lat"], "lon": f["lon"], "rotation": f["rotation"], "parcels": f.get("parcels", []),
            "residues": True, "weights": dict(analysis.DEFAULT_WEIGHTS)}


class Handler(BaseHTTPRequestHandler):
    server_version = "CropOrbit/0.5"

    def _route(self):
        """Ścieżka bez zapytania; ustawia język odpowiedzi z ?lang=en|pl (domyślnie en)."""
        parts = urllib.parse.urlsplit(self.path)
        set_lang((urllib.parse.parse_qs(parts.query).get("lang") or ["en"])[0])
        return parts.path

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self._route()
        if path == "/api/crops":
            return self._send(200, public_list())
        if path == "/api/demo":
            return self._send(200, demo_list())
        if path == "/api/ai":
            return self._send(200, {"status": ai.status()})
        if path == "/api/parcel":
            return self._parcel(urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query))
        if path in ("/", "/index.html"):
            path = "/index.html"
        elif path.startswith("/static/"):
            path = path[len("/static"):]
        full = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self._send(404, {"error": tr("nie znaleziono", "not found")})
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        with open(full, "rb") as f:
            self._send(200, f.read(), ctype)

    def _parcel(self, q):
        """?lat=&lon= → działka pod punktem; ?q=Obręb 12/3 → lista; ?id= → działka po identyfikatorze."""
        one = lambda k: (q.get(k) or [""])[0]  # noqa: E731
        try:
            if one("q"):
                return self._send(200, {"results": parcels.search(one("q"))})
            rec = parcels.by_id(one("id")[:60]) if one("id") else parcels.at_point(float(one("lat")), float(one("lon")))
        except ValueError:
            return self._send(400, {"error": tr("podaj lat i lon albo q", "give lat and lon or q")})
        except Exception as e:  # noqa: BLE001 — usługi GUGiK bywają niedostępne
            return self._send(502, {"error": tr("Usługa działek (GUGiK) nie odpowiedziała: ", "The parcel service (GUGiK) did not respond: ") + type(e).__name__})
        return self._send(200, rec) if rec else self._send(404, {"error": tr("brak działki w tym miejscu", "no parcel at this spot")})

    def _ask(self, req):
        """POST /api/ask {question, result} → odpowiedź wyłącznie z liczb wyniku analizy."""
        q = str(req.get("question") or "").strip()[:500]
        res = req.get("result")
        if not q or not isinstance(res, dict) or "strategies" not in res:
            return self._send(400, {"error": tr("Podaj pytanie i wynik analizy", "Give a question and an analysis result")})
        if not ai.available():
            return self._send(503, {"error": tr("Moduł AI wyłączony: brak SDK anthropic albo klucza ANTHROPIC_API_KEY.",
                                                "AI module off: the anthropic SDK or the ANTHROPIC_API_KEY key is missing.")})
        try:
            out = ai.ask(q, res, lang())
        except ai.anthropic.RateLimitError:
            return self._send(429, {"error": tr("Za dużo pytań naraz — spróbuj za chwilę.", "Too many questions at once — try again shortly.")})
        except ai.anthropic.APIConnectionError:
            return self._send(502, {"error": tr("Brak połączenia z Claude API.", "No connection to the Claude API.")})
        except ai.anthropic.APIStatusError as e:
            return self._send(502, {"error": tr("Claude API zwróciło błąd ", "The Claude API returned error ") + str(e.status_code)})
        if out.get("refused"):
            out["answer"] = tr("Model odmówił odpowiedzi na to pytanie. Zapytaj inaczej albo o inną rzecz z analizy.",
                               "The model declined this question. Rephrase it or ask about something else in the analysis.")
        return self._send(200, out)

    def do_POST(self):
        route = self._route()
        if route not in ("/api/analyze", "/api/ask"):
            return self._send(404, {"error": tr("nie znaleziono", "not found")})
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n > (400_000 if route == "/api/ask" else 100_000):
                return self._send(413, {"error": tr("zbyt duże zapytanie", "request too large")})
            req = json.loads(self.rfile.read(n) or b"{}")
            if route == "/api/ask":
                return self._ask(req)
            return self._send(200, analysis.run(req))
        except (ValueError, KeyError) as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            return self._send(500, {"error": tr("Błąd analizy: ", "Analysis error: ") + str(e)})

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))


def prefetch():
    for f in DEMO_FIELDS:
        print("Pobieram dane:", f["name"][0], flush=True)
        analysis.run(demo_request(f))
    print("Gotowe — dane pól demo są w cache/.")


def _write(name, obj):
    with open(os.path.join(DEMO, name), "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))


def snapshot():
    """Zapisuje do static/demo/ wyniki pól przykładowych, listę upraw i działki — po polsku i po angielsku."""
    os.makedirs(DEMO, exist_ok=True)
    for lg in ("pl", "en"):
        set_lang(lg)
        _write(f"crops.{lg}.json", public_list())
        _write(f"demo.{lg}.json", demo_list())
        for f in DEMO_FIELDS:
            print(f"[{lg}] {f['name'][0]}", flush=True)
            res = analysis.run(demo_request(f))
            res["demo_id"] = f["id"]
            _write(f"{f['id']}.{lg}.json", res)
            if f.get("parcels") and lg == "pl":
                _write(f"parcels_{f['id']}.json", [parcels.by_id(pid) for pid in f["parcels"]])
    print("Gotowe — wyniki pól przykładowych są w static/demo/.")


if __name__ == "__main__":
    if "--prefetch" in sys.argv:
        prefetch()
        sys.exit(0)
    if "--snapshot" in sys.argv:
        snapshot()
        sys.exit(0)
    port = int(os.environ.get("PORT", 8000))
    print(f"CropOrbit działa: http://localhost:{port}", flush=True)
    host = os.environ.get("HOST", "127.0.0.1")  # w Codespaces/kontenerze HOST=0.0.0.0
    ThreadingHTTPServer((host, port), Handler).serve_forever()
