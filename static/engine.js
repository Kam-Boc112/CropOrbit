/* CropOrbit — silnik obliczeń w przeglądarce (Web Worker).
   Ładuje Pyodide (Python w WebAssembly) i te same moduły Pythona co serwer (z folderu py/, kopiowanego przy
   wdrożeniu na GitHub Pages). Dzięki temu wersja bez serwera liczy dowolne pole: dane pobiera prosto z NASA POWER,
   SoilGrids, Open-Meteo i GUGiK. */
"use strict";
importScripts("https://cdn.jsdelivr.net/pyodide/v0.28.3/full/pyodide.js");

const MODULES = ["i18n", "crops", "agro", "data_sources", "parcels", "rotation", "analysis"];
const CALLS = {
  analyze: "analysis.run(_a)",
  parcel_point: "parcels.at_point(float(_a['lat']), float(_a['lon']))",
  parcel_id: "parcels.by_id(str(_a['id'])[:60])",
  parcel_search: "{'results': parcels.search(str(_a['q']))}",
};

let py = null;
async function boot() {
  py = await loadPyodide();
  py.FS.mkdirTree("/app");
  for (const m of MODULES) {
    const r = await fetch(`py/${m}.py?v=${new URL(self.location.href).searchParams.get("v") || ""}`); // ta sama wersja co strona
    if (!r.ok) throw new Error(`py/${m}.py: HTTP ${r.status}`);
    py.FS.writeFile(`/app/${m}.py`, await r.text());
  }
  py.runPython("import sys, json; sys.path.insert(0, '/app'); import analysis, parcels; from i18n import set_lang");
}
const ready = boot();

// ostatnia linia wyjątku Pythona, bez śladu stosu
const pyMessage = (e) => (String(e && e.message || e).trim().split("\n").filter(Boolean).pop() || "Error").replace(/^\w+(Error|Exception): /, "");

self.onmessage = async ({ data: { id, fn, args, lang } }) => {
  try {
    await ready;
    if (!CALLS[fn]) throw new Error("unknown call " + fn);
    py.globals.set("_args", JSON.stringify(args || {}));
    const out = py.runPython(`set_lang(${JSON.stringify(lang === "pl" ? "pl" : "en")})
_a = json.loads(_args)
json.dumps(${CALLS[fn]}, ensure_ascii=False)`);
    self.postMessage({ id, ok: true, data: JSON.parse(out) });
  } catch (e) {
    self.postMessage({ id, ok: false, error: pyMessage(e) });
  }
};
