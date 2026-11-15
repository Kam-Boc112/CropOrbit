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

import analysis
import parcels
from crops import public_list
from i18n import set_lang, tr

for _s in (sys.stdout, sys.stderr):  # konsola Windows (cp1252) nie zna polskich znaków
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = os.path.dirname(os.path.abspath(__file__))
STATIC = os.path.join(ROOT, "static")

DEMO_FIELDS = [
    {"id": "rzeszow", "name": ("Pole pod Rzeszowem (Podkarpacie)", "Field near Rzeszów (Poland)"), "lat": 50.03, "lon": 21.95,
     "rotation": ["wheat_w", "maize_g", "wheat_w"]},
    {"id": "iowa", "name": ("Pole w Iowa (Corn Belt, USA)", "Field in Iowa (Corn Belt, USA)"), "lat": 42.015, "lon": -93.765,
     "rotation": ["maize_g", "soy"]},
]


def demo_list():
    return [dict(f, name=tr(*f["name"])) for f in DEMO_FIELDS]


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

    def do_POST(self):
        if self._route() != "/api/analyze":
            return self._send(404, {"error": tr("nie znaleziono", "not found")})
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n > 100_000:
                return self._send(413, {"error": tr("zbyt duże zapytanie", "request too large")})
            req = json.loads(self.rfile.read(n) or b"{}")
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
        analysis.run({"lat": f["lat"], "lon": f["lon"], "rotation": f["rotation"]})
    print("Gotowe — dane pól demo są w cache/.")


if __name__ == "__main__":
    if "--prefetch" in sys.argv:
        prefetch()
        sys.exit(0)
    port = int(os.environ.get("PORT", 8000))
    print(f"CropOrbit działa: http://localhost:{port}", flush=True)
    host = os.environ.get("HOST", "127.0.0.1")  # w Codespaces/kontenerze HOST=0.0.0.0
    ThreadingHTTPServer((host, port), Handler).serve_forever()
