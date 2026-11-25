/* CropOrbit — frontend bez frameworków: mapa i działki, formularz, wyniki rysowane leniwie per zakładka.
   Język: t("polski", "English"); wybór zapisany w localStorage, serwer dostaje ?lang=. */
"use strict";

const LANG_KEY = "croporbit-lang", RESTORE_KEY = "croporbit-restore";
const LANG = (() => {
  const q = new URLSearchParams(location.search).get("lang"); // ?lang=pl w linku ma pierwszeństwo
  if (q === "pl" || q === "en") return q;
  try { return localStorage.getItem(LANG_KEY) === "pl" ? "pl" : "en"; } catch { return "en"; }
})();
const t = (pl, en) => (LANG === "pl" ? pl : en);

const AXES = [
  ["woda", t("Oszczędność wody", "Saving water"), 3], ["gleba", t("Poprawa gleby (próchnica)", "Improving soil (humus)"), 3],
  ["erozja", t("Ograniczenie erozji", "Reducing erosion"), 2], ["azot", t("Azot (mniej nawozów)", "Nitrogen (less fertiliser)"), 2],
  ["choroby", t("Przerwanie chorób", "Breaking disease cycles"), 2], ["dochod", t("Dochód", "Income"), 3],
  ["pasza", t("Pasza dla zwierząt", "Animal fodder"), 0],
];
// paleta wykresów w duchu systemu: zielenie, ochra, ziemia; niebieski tylko dla wody
const C = { green: "#2a6a43", green2: "#6f9a52", ochre: "#b07a1e", rust: "#9c3424", water: "#3f6f8f", earth: "#8b6b46", ink: "#1d2a21", muted: "#56604f", line: "#e6dfcf" };
const STRAT_COLORS = { current: "#6b675c", A: "#2a6a43", B: "#55702a", C: "#8a5d12" };
const CROP_COLORS = {
  wheat_w: "#e2b84a", rye_w: "#c99a3c", barley_w: "#efd27a", triticale_w: "#d6a94e", barley_s: "#f3df9a",
  oats: "#e9cf8f", maize_g: "#e48a2c", maize_s: "#f0aa5f", sorghum: "#c26d34", rapeseed_w: "#e8d53a",
  sunflower: "#f2c22a", soy: "#86b56f", pea: "#62a362", faba: "#4f8a55", lupin: "#9585c4",
  sugarbeet: "#b5587e", potato: "#9a6b4a", buckwheat: "#d3a3a3", clover: "#3e9a7a", alfalfa: "#2f8a8f",
};
const PL = [48.9, 55.0, 14.0, 24.2];
const STATE_TXT = { good: t("dobrze", "good"), warn: t("uwaga", "caution"), bad: t("ryzyko", "risk") };

const state = { point: null, drawnArea: null, parcels: new Map(), rotation: ["wheat_w", "maize_g", "wheat_w"], crops: [], res: null, demos: [], demoId: null };
// Tryb statyczny: brak serwera Pythona (np. GitHub Pages) — działają pola przykładowe z gotowych wyników w demo/.
let STATIC = false;
async function snap(name) {
  const r = await fetch("demo/" + name);
  if (!r.ok) throw new Error(r.statusText);
  return r.json();
}
const charts = {};
const rendered = new Set();
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (x, d = 1) => (+x).toLocaleString(t("pl-PL", "en-GB"), { maximumFractionDigits: d });
const cropName = (id) => (state.crops.find((c) => c.id === id) || {}).name || id;
const inPL = (lat, lon) => lat >= PL[0] && lat <= PL[1] && lon >= PL[2] && lon <= PL[3];
const nParcels = (n) => `${n} ${t(n === 1 ? "działka" : n < 5 ? "działki" : "działek", n === 1 ? "parcel" : "parcels")}`;
const stratColor = (s) => (s.is_current ? STRAT_COLORS.current : STRAT_COLORS[s.label]);
const stratShort = (s) => (s.is_current ? t("Ob.", "Now") : s.label);
const stratName = (s) => (s.is_current ? t("Obecny", "Current") : s.label);
// dwa przyciski „Analizuj” (pod mapą na komputerze, pod formularzem na telefonie) — widoczny jest zawsze jeden
function status(msg, err = false) { $$(".status").forEach((s) => { s.textContent = msg; s.classList.toggle("err", err); }); }
async function getJSON(url, opts) {
  if (url.startsWith("/api/")) url += (url.includes("?") ? "&" : "?") + "lang=" + LANG;
  const r = await fetch(url, opts);
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { const e = new Error(d.error || r.statusText); e.code = r.status; throw e; }
  return d;
}

// ================================================================== język: teksty statyczne z index.html i przełącznik
function applyStaticLang() {
  document.documentElement.lang = LANG;
  if (LANG === "en") {
    $$("[data-en]").forEach((el) => { el.innerHTML = el.dataset.en; });
    for (const a of ["placeholder", "aria-label", "title"]) $$(`[data-en-${a}]`).forEach((el) => el.setAttribute(a, el.getAttribute(`data-en-${a}`)));
    document.title = "CropOrbit — crop rotation from NASA data";
  }
  $$("[data-lang]").forEach((b) => {
    b.setAttribute("aria-pressed", b.dataset.lang === LANG);
    b.onclick = () => switchLang(b.dataset.lang);
  });
}
function localStorageOk() { try { return localStorage.getItem(LANG_KEY) !== null; } catch { return false; } }
function switchLang(lang) {
  if (lang === LANG) return;
  try {
    localStorage.setItem(LANG_KEY, lang);
    const c = map.getCenter();
    sessionStorage.setItem(RESTORE_KEY, JSON.stringify({
      view: [c.lat, c.lng, map.getZoom()], point: state.point, drawnArea: state.drawnArea,
      parcels: [...state.parcels.keys()], rotation: state.rotation, analyzed: !!state.res, demoId: state.demoId,
      checks: Object.fromEntries(["newField", "irrigation", "livestock", "coverNow", "residues"].map((id) => [id, $("#" + id).checked])),
      weights: Object.fromEntries(AXES.map(([k]) => [k, $("#w_" + k).value])),
    }));
  } catch { /* bez pamięci przeglądarki zmiana języka zaczyna od pustego formularza */ }
  // ?lang= i ?demo= z linku miałyby pierwszeństwo przed wyborem użytkownika — usuwamy je z adresu
  const u = new URL(location.href);
  u.searchParams.delete("lang"); u.searchParams.delete("demo");
  if (!localStorageOk()) u.searchParams.set("lang", lang);
  location.replace(u.toString());
}
applyStaticLang();

// ================================================================== mapa
const map = L.map("map").setView([50.03, 21.95], 7);
const osm = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "© OpenStreetMap" });
const sat = L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "Esri World Imagery" }).addTo(map);
const KIEG = "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow";
const wms = (layers) => L.tileLayer.wms(KIEG, { layers, format: "image/png", transparent: true, minZoom: 15, maxZoom: 19, attribution: "GUGiK (EGiB)" });
const parcelsWms = wms("dzialki,numery_dzialek").addTo(map);
L.control.layers({ [t("Satelita (Esri)", "Satellite (Esri)")]: sat, [t("Mapa (OSM)", "Map (OSM)")]: osm },
  { [t("Działki ewidencyjne (GUGiK)", "Cadastral parcels (GUGiK)")]: parcelsWms, [t("Kontury klas gruntu (EGiB)", "Soil class contours (EGiB)")]: wms("kontury") }).addTo(map);

const sel = new L.FeatureGroup().addTo(map);   // zaznaczone działki
const drawn = new L.FeatureGroup().addTo(map); // własny obrys albo punkt
map.addControl(new L.Control.Draw({
  draw: { polygon: { allowIntersection: false, shapeOptions: { color: "#f2c22a", weight: 3 } }, rectangle: { shapeOptions: { color: "#f2c22a" } }, polyline: false, circle: false, circlemarker: false, marker: false },
  edit: { featureGroup: drawn, remove: true },
}));
const parcelStyle = { color: "#f2c22a", weight: 3, fillColor: "#f2c22a", fillOpacity: 0.18 };

function clearSelection() { state.parcels.clear(); sel.clearLayers(); drawn.clearLayers(); state.point = null; state.drawnArea = null; }

function setPoint(lat, lon, area = null, layer = null) {
  clearSelection();
  state.point = { lat: +lat.toFixed(5), lon: +lon.toFixed(5) };
  state.drawnArea = area;
  drawn.addLayer(layer || L.circleMarker([lat, lon], { radius: 8, color: "#f2c22a", weight: 3, fillOpacity: 0.3 }));
  renderField();
}

function addParcel(p, { fit = false } = {}) {
  if (state.point) { drawn.clearLayers(); state.point = null; state.drawnArea = null; }
  const layer = L.polygon(p.rings, parcelStyle).bindTooltip(`${p.region} ${p.number}`);
  layer.on("click", (e) => { L.DomEvent.stopPropagation(e); removeParcel(p.id); });
  p._layer = layer; sel.addLayer(layer); state.parcels.set(p.id, p);
  if (fit) map.fitBounds(layer.getBounds(), { maxZoom: 17 });
  renderField();
}
function removeParcel(id) {
  const p = state.parcels.get(id); if (!p) return;
  sel.removeLayer(p._layer); state.parcels.delete(id); renderField();
  status(t(`Odznaczono działkę ${p.number}.`, `Parcel ${p.number} deselected.`));
}

map.on("click", async (e) => {
  const { lat, lng } = e.latlng;
  if (!inPL(lat, lng) || map.getZoom() < 15) {
    if (inPL(lat, lng)) status(t("Przybliż mapę (≥ 15), by zaznaczać działki — na razie wskazano punkt.", "Zoom in (≥ 15) to select parcels — a point was marked for now."));
    return setPoint(lat, lng);
  }
  status(t("Szukam działki w ewidencji (GUGiK)…", "Looking up the parcel in the land register (GUGiK)…"));
  try {
    const p = await getJSON(`/api/parcel?lat=${lat.toFixed(6)}&lon=${lng.toFixed(6)}`);
    if (state.parcels.has(p.id)) return removeParcel(p.id);
    addParcel(p);
    status(t(`Zaznaczono działkę ${p.number} (${p.region}).`, `Parcel ${p.number} (${p.region}) selected.`));
  } catch (err) {
    setPoint(lat, lng);
    status(err.code === 404 ? t("Brak działki w tym miejscu — wskazano punkt.", "No parcel here — a point was marked.")
      : `${err.message} ${t("Wskazano punkt.", "A point was marked.")}`, err.code !== 404);
  }
});
map.on(L.Draw.Event.CREATED, (e) => {
  const area = L.GeometryUtil.geodesicArea(e.layer.getLatLngs()[0]) / 10000;
  const c = e.layer.getBounds().getCenter();
  setPoint(c.lat, c.lng, area, e.layer);
});
map.on(L.Draw.Event.DELETED, () => { state.drawnArea = null; renderField(); });

// ---------------------------------------------------------- wybrane pole (panel)
const clsQ = (c) => !c.rank ? "" : c.rank <= 3 ? "q-good" : c.rank <= 6 ? "q-mid" : "q-low";
function fieldGeom() {
  if (state.parcels.size) {
    const pts = [...state.parcels.values()].flatMap((p) => p.rings[0]);
    const area = [...state.parcels.values()].reduce((a, p) => a + (p.area_ha ?? L.GeometryUtil.geodesicArea(p.rings[0].map((x) => L.latLng(x))) / 10000), 0);
    return { lat: pts.reduce((a, p) => a + p[0], 0) / pts.length, lon: pts.reduce((a, p) => a + p[1], 0) / pts.length, area };
  }
  return state.point ? { ...state.point, area: state.drawnArea } : null;
}
function renderField() {
  const box = $("#fieldBox"), g = fieldGeom();
  if (!g) {
    box.innerHTML = `<p class="field-empty">${t("Kliknij działkę na mapie, wyszukaj ją po numerze albo narysuj obrys pola narzędziem po lewej stronie mapy.",
      "Click a parcel on the map, search for it by number, or draw the field outline with the tool on the left of the map.")}</p>`;
    return;
  }
  if (!state.parcels.size) {
    box.innerHTML = `<p class="field-sum">${t("Punkt", "Point")} ${g.lat.toFixed(4)}, ${g.lon.toFixed(4)}${g.area ? ` · ${t("obrys", "outline")} <b>${fmt(g.area)} ha</b>` : ""}</p>`;
    return;
  }
  box.innerHTML = `<ul class="parcel-list">${[...state.parcels.values()].map((p) => `
    <li class="parcel"><div><b>${esc(p.region)} ${esc(p.number)}</b>
      <span class="meta">${esc(p.commune)}, ${esc(p.county)}${p.area_ha ? ` · ${fmt(p.area_ha, 2)} ha` : ""}</span>
      <div class="classes">${p.classes?.length ? p.classes.map((c) => `<span class="cls ${clsQ(c)}" title="${esc(c.use_pl)}${c.quality ? t(", klasa ", ", class ") + esc(c.quality) : ""}">${esc(c.code)}</span>`).join("")
        : `<span class="meta">${p.egib_error ? t("EGiB niedostępny", "land register unavailable") : t("brak klas w EGiB", "no soil classes in the land register")}</span>`}</div></div>
      <button type="button" class="icon-btn" data-rm="${esc(p.id)}" aria-label="${t("Odznacz działkę", "Deselect parcel")} ${esc(p.number)}">×</button></li>`).join("")}</ul>
    <p class="field-sum">${nParcels(state.parcels.size)} · ${t("razem", "total")} <b>${fmt(g.area, 2)} ha</b></p>`;
  $$("[data-rm]", box).forEach((b) => b.onclick = () => removeParcel(b.dataset.rm));
}

// ---------------------------------------------------------- wyszukiwarka
async function search() {
  const q = $("#searchInput").value.trim(), out = $("#searchResults");
  out.innerHTML = "";
  if (!q) return;
  const coords = q.match(/^(-?\d+(?:[.,]\d+)?)\s*[,; ]\s*(-?\d+(?:[.,]\d+)?)$/);
  if (coords) { const [a, b] = [coords[1], coords[2]].map((x) => +x.replace(",", ".")); map.setView([a, b], 15); return setPoint(a, b); }
  if (/\d/.test(q)) { // wygląda na działkę: „Trzciana 723/1” albo identyfikator TERYT
    status(t("Szukam działki…", "Looking for the parcel…"));
    try {
      const { results } = await getJSON("/api/parcel?q=" + encodeURIComponent(q));
      if (results.length === 1) return pickParcel(results[0].id);
      if (results.length > 1) {
        status(t(`Znaleziono ${results.length} działki — wybierz właściwą.`, `Found ${results.length} parcels — pick the right one.`));
        out.innerHTML = results.map((r) => `<button type="button" data-id="${esc(r.id)}">${esc(r.region)} ${esc(r.number)} — ${esc(r.commune)}, ${esc(r.county)}</button>`).join("");
        return $$("button", out).forEach((b) => b.onclick = () => { out.innerHTML = ""; pickParcel(b.dataset.id); });
      }
    } catch { /* przejdź do wyszukiwania miejsc */ }
  }
  try {
    const d = await getJSON(`https://nominatim.openstreetmap.org/search?format=json&limit=1&accept-language=${LANG}&q=` + encodeURIComponent(q));
    if (d[0]) { map.setView([+d[0].lat, +d[0].lon], 15); status(t(`Pokazano: ${d[0].display_name.split(",").slice(0, 2).join(",")}. Kliknij działkę.`, `Showing: ${d[0].display_name.split(",").slice(0, 2).join(",")}. Click a parcel.`)); }
    else status(t("Nie znaleziono. Wpisz miejscowość albo „Obręb numer”, np. Trzciana 723/1.", "Not found. Type a place name or “Precinct number”, e.g. Trzciana 723/1."), true);
  } catch { status(t("Wyszukiwarka niedostępna — kliknij pole na mapie.", "Search unavailable — click the field on the map."), true); }
}
async function pickParcel(id) {
  status(t("Pobieram działkę i klasy gruntu…", "Loading the parcel and soil classes…"));
  try {
    const p = await getJSON("/api/parcel?id=" + encodeURIComponent(id));
    if (!state.parcels.has(p.id)) addParcel(p, { fit: true });
    status(t(`Zaznaczono działkę ${p.number} (${p.region}).`, `Parcel ${p.number} (${p.region}) selected.`));
  } catch (err) { status(err.message, true); }
}
$("#searchBtn").onclick = search;
$("#searchInput").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); search(); } });

// ================================================================== formularz
function renderChips() {
  const el = $("#rotChips");
  if (!state.rotation.length) { el.innerHTML = `<span class="muted small">${t("Dodaj uprawy w kolejności lat.", "Add crops in the order of years.")}</span>`; return; }
  el.innerHTML = state.rotation.map((id, i) => `${i ? '<span class="arrow" aria-hidden="true">→</span>' : ""}<span class="chip">${i + 1}. ${esc(cropName(id))}<button type="button" class="icon-btn" data-i="${i}" aria-label="${t(`Usuń ${esc(cropName(id))} z roku ${i + 1}`, `Remove ${esc(cropName(id))} from year ${i + 1}`)}">×</button></span>`).join("");
  $$("button", el).forEach((b) => b.onclick = () => { state.rotation.splice(+b.dataset.i, 1); renderChips(); });
}
$("#addCrop").onclick = () => {
  if (state.rotation.length >= 6) return status(t("Płodozmian może mieć najwyżej 6 lat.", "A rotation can have at most 6 years."), true);
  state.rotation.push($("#cropSelect").value); renderChips();
};
$("#clearRot").onclick = () => { state.rotation = []; renderChips(); };
$("#newField").onchange = (e) => {
  const on = e.target.checked;
  $("#rotChips").hidden = $("#rotRow").hidden = on; $("#newFieldHint").hidden = !on;
  $("#coverNow").disabled = on; if (on) $("#coverNow").checked = false;
};
$("#sliders").innerHTML = AXES.map(([k, label, v]) =>
  `<label class="slider" for="w_${k}"><span>${label}</span><input type="range" min="0" max="5" step="1" value="${v}" id="w_${k}"><output id="o_${k}" for="w_${k}">${v}</output></label>`).join("");
AXES.forEach(([k]) => { $("#w_" + k).oninput = (e) => { $("#o_" + k).textContent = e.target.value; }; });
$("#livestock").onchange = (e) => { if (e.target.checked && $("#w_pasza").value === "0") { $("#w_pasza").value = 3; $("#o_pasza").textContent = 3; } };

const analyzeLabel = t("Analizuj pole", "Analyse field");
$("#panel").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (STATIC) {
    status(t("To wersja pokazowa bez serwera: działają pola przykładowe. Analiza własnego pola wymaga pełnej wersji (python server.py).",
      "This is the demo version without a server: the example fields work. Analysing your own field needs the full version (python server.py)."), true);
    return;
  }
  const g = fieldGeom();
  if (!g) { status(t("Najpierw wskaż pole na mapie albo wyszukaj działkę.", "First mark the field on the map or search for a parcel."), true); return $("#searchInput").focus(); }
  const newField = $("#newField").checked;
  if (!newField && state.rotation.length < 2) { status(t("Podaj obecny płodozmian — co najmniej 2 uprawy.", "Enter your current rotation — at least 2 crops."), true); return $("#cropSelect").focus(); }
  const body = {
    lat: +g.lat.toFixed(5), lon: +g.lon.toFixed(5), area_ha: g.area, rotation: newField ? [] : state.rotation, new_field: newField, parcels: [...state.parcels.keys()],
    irrigation: $("#irrigation").checked, livestock: $("#livestock").checked, cover_now: $("#coverNow").checked, residues: $("#residues").checked,
    weights: Object.fromEntries(AXES.map(([k]) => [k, +$("#w_" + k).value])),
  };
  const btns = $$(".analyze"), label = (txt) => btns.forEach((b) => { b.textContent = txt; });
  btns.forEach((b) => { b.disabled = true; });
  const t0 = Date.now();
  status(t("Pobieram dane NASA (24 lata), teren, glebę… Pierwsza analiza nowego pola trwa do ok. 40 s.",
    "Downloading NASA data (24 years), terrain and soil… The first analysis of a new field takes up to ~40 s."));
  const tick = setInterval(() => { label(`${t("Analizuję…", "Analysing…")} ${Math.round((Date.now() - t0) / 1000)} s`); }, 1000);
  try {
    const d = await getJSON("/api/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    status(t(`Gotowe w ${fmt((Date.now() - t0) / 1000)} s. Sprawdzono ${d.n_checked} wariantów płodozmianu.`,
      `Done in ${fmt((Date.now() - t0) / 1000)} s. Checked ${d.n_checked} rotation variants.`));
    state.res = d; state.demoId = null; showResults(d);
  } catch (err) { status(t("Błąd: ", "Error: ") + err.message, true); }
  finally { clearInterval(tick); btns.forEach((b) => { b.disabled = false; }); label(analyzeLabel); }
});

// ================================================================== zakładki (ARIA, strzałki) i podpowiedzi
const RENDER = { conditions: renderConditions, crops: renderCrops, rotations: renderRotations, calendar: renderCalendar, report: renderReport };
const tabs = $$("[role=tab]");
function selectTab(tab, focus = false) {
  tabs.forEach((x) => { const on = x === tab; x.setAttribute("aria-selected", on); x.tabIndex = on ? 0 : -1; $("#" + x.getAttribute("aria-controls")).hidden = !on; });
  const key = tab.id.slice(2);
  if (state.res && !rendered.has(key)) { RENDER[key](state.res); rendered.add(key); }
  if (focus) tab.focus();
}
tabs.forEach((x, i) => {
  x.onclick = () => selectTab(x);
  x.onkeydown = (e) => {
    const n = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: tabs.length - 1 }[e.key];
    if (n !== undefined) { e.preventDefault(); selectTab(tabs[(n + tabs.length) % tabs.length], true); }
  };
});

const tip = $("#tooltip");
function showTip(el) {
  tip.textContent = el.dataset.tip; tip.hidden = false; el.setAttribute("aria-describedby", "tooltip");
  const r = el.getBoundingClientRect();
  tip.style.left = Math.max(8, Math.min(r.left, innerWidth - 340)) + "px"; tip.style.top = (r.bottom + 6) + "px";
}
const hideTip = () => { tip.hidden = true; };
document.addEventListener("mouseover", (e) => { const el = e.target.closest("[data-tip]"); el ? showTip(el) : hideTip(); });
document.addEventListener("focusin", (e) => { const el = e.target.closest("[data-tip]"); el ? showTip(el) : hideTip(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") hideTip(); });
addEventListener("scroll", hideTip, { passive: true });

Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
Chart.defaults.color = C.muted;
Chart.defaults.borderColor = C.line;
Chart.defaults.maintainAspectRatio = false;
function chart(id, cfg, label) {
  if (charts[id]) charts[id].destroy();
  const el = document.getElementById(id);
  el.setAttribute("role", "img"); el.setAttribute("aria-label", label);
  charts[id] = new Chart(el, cfg);
}
const gloss = (res, keys) => keys.map((k) => {
  const g = res.glossary[k];
  return g ? `<button type="button" class="info" data-tip="${esc(g.term + ": " + g.text)}" aria-label="${esc(t("Co to jest: ", "What is: ") + g.term)}">i</button>` : "";
}).join(" ");
const linFit = (xs, ys) => {
  const n = xs.length, mx = xs.reduce((a, b) => a + b, 0) / n, my = ys.reduce((a, b) => a + b, 0) / n;
  let sxy = 0, sxx = 0; xs.forEach((x, i) => { sxy += (x - mx) * (ys[i] - my); sxx += (x - mx) ** 2; });
  const b = sxx ? sxy / sxx : 0; return (x) => +(my + b * (x - mx)).toFixed(1);
};
const mix = (a, b, k) => { k = Math.max(0, Math.min(1, k)); const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)); const A = p(a), B = p(b); return `rgb(${A.map((x, i) => Math.round(x + (B[i] - x) * k)).join(",")})`; };
const sgn = (v) => (v > 0 ? "+" : "");

// ================================================================== wyniki
function showResults(res, scroll = true) {
  Object.values(charts).forEach((c) => c.destroy());
  Object.keys(charts).forEach((k) => delete charts[k]);
  rendered.clear();
  tabs.forEach((x) => { $("#" + x.getAttribute("aria-controls")).innerHTML = ""; });
  renderSummary(res);
  renderAsk(res);
  $("#results").classList.remove("hidden");
  selectTab(tabs[0]);
  if (scroll) $("#results").scrollIntoView({ block: "start" });
}

const bestStrategy = (res) => res.new_field ? res.strategies[0] : res.strategies.slice(1).sort((a, b) => b.total - a.total)[0];
const mkcal = (k) => fmt(k / 1e6);
const pts = t("pkt", "pts");

function renderSummary(res) {
  const S = res.strategies, cur = S[0], best = bestStrategy(res);
  const en = res.energy.find((e) => !e.fodder);
  const top = res.ranking[0], ps = res.parcels;
  const worst = res.tiles.find((x) => x.status === "bad") || res.tiles.find((x) => x.status === "warn");
  const where = ps?.n ? nParcels(ps.n) : `${res.field.lat.toFixed(3)}, ${res.field.lon.toFixed(3)}`;
  const card = (k, v, d, cls = "") => `<div class="card ${cls}"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`;
  // główna odpowiedź: rekomendowany płodozmian, wyróżniony i szerszy niż karty pomocnicze
  const signed = (v, d) => (v > 0 ? "+" : "") + fmt(v, d);
  const gain = (k, unit, d = 1, sign = false) => { const f = sign ? signed : fmt; return `${f(cur.metrics[k], d)} → <b>${f(best.metrics[k], d)}</b> ${unit}`; };
  const hero = !best ? "" : `<div class="card hl"><div class="k">${res.new_field ? t("Proponowany płodozmian", "Proposed rotation") : t("Co polecamy", "Our recommendation")}</div>
    <div class="v">${esc(best.names.join(" → "))}${best.cover_type ? ` <span class="plus">+ ${t("międzyplony", "cover crops")}</span>` : ""}</div>
    <div class="d">${res.new_field ? `${t("ocena", "score")} ${best.total}/100`
      : `${t("ocena", "score")} ${cur.total} → <b>${best.total}</b> · ${t("goła gleba", "bare soil")} ${gain("bare_months", t("mies./rok", "months/yr"))} · ${t("próchnica", "humus")} ${gain("humus_kg_c", t("kg C/ha/rok", "kg C/ha/yr"), 0, true)}`}</div></div>`;
  $("#summary").innerHTML = [
    hero,
    card(t("Pole", "Field"), esc(where), `${res.field.area_ha ? fmt(res.field.area_ha, 2) + " ha · " : ""}${res.field.elev ?? "?"} ${t("m n.p.m.", "m a.s.l.")}${ps?.best ? ` · ${t("klasa", "class")} ${esc(ps.best.cls)}${ps.worst && ps.worst.cls !== ps.best.cls ? "–" + esc(ps.worst.cls) : ""}` : ""}`),
    card(t("Najlepiej pasuje", "Best fit"), esc(top.name), `${t("ocena", "score")} ${top.score}/100`),
    en ? card(t("Najwięcej energii", "Most food energy"), esc(en.name), `${mkcal(en.kcal_ha)} ${t("mln kcal/ha", "M kcal/ha")} · ≈ ${fmt(en.persons_ha)} ${t("os./rok z 1 ha", "people/yr per ha")}`) : "",
    worst ? card(t("Na co uważać", "Watch out for"), esc(worst.title), esc(worst.value)) : card(t("Na co uważać", "Watch out for"), t("brak wyraźnych ryzyk", "no clear risks"), ""),
  ].join("");
}

// ---------------------------------------------------------- „Zapytaj o swoje pole” (Claude, tylko z liczb analizy)
function renderAsk(res) {
  const el = $("#ask"), st = state.aiStatus;
  const off = st !== "ok";
  const why = st === "static" ? t("W wersji pokazowej bez serwera pytania są wyłączone — działają w pełnej wersji.", "Questions are off in the demo version without a server — they work in the full version.")
    : st === "no_key" ? t("Moduł wyłączony: ustaw klucz ANTHROPIC_API_KEY i uruchom serwer ponownie.", "Module off: set the ANTHROPIC_API_KEY key and restart the server.")
    : st === "no_sdk" ? t("Moduł wyłączony: zainstaluj SDK (pip install anthropic).", "Module off: install the SDK (pip install anthropic).") : "";
  const best = bestStrategy(res), worst = res.tiles.find((x) => x.status === "bad") || res.tiles.find((x) => x.status === "warn");
  const sugg = [
    best && t(`Dlaczego polecacie płodozmian ${best.label}?`, `Why do you recommend rotation ${best.label}?`),
    worst && t(`Co oznacza „${worst.title}” dla mojego pola?`, `What does “${worst.title}” mean for my field?`),
    t("Czego ta analiza nie wie o moim polu?", "What does this analysis not know about my field?"),
  ].filter(Boolean);
  el.innerHTML = `<div class="ask-head"><h3 id="askTitle">${t("Zapytaj o swoje pole", "Ask about your field")} <span class="badge">AI</span></h3>
      <p class="small muted">${t("Odpowiada Claude, ale tylko z liczb policzonych powyżej — z nazwą wskaźnika i źródłem. Czego nie ma w danych, mówi wprost.",
        "Claude answers, but only from the numbers computed above — naming the indicator and source. If something is not in the data, it says so.")}</p></div>
    <form class="ask-form" novalidate>
      <label for="askInput" class="sr-only">${t("Twoje pytanie", "Your question")}</label>
      <input id="askInput" type="text" maxlength="500" autocomplete="off" ${off ? "disabled" : ""}
        placeholder="${t("np. Czy mogę siać kukurydzę na tym polu?", "e.g. Can I grow maize on this field?")}">
      <button type="submit" class="primary" ${off ? "disabled" : ""}>${t("Zapytaj", "Ask")}</button>
    </form>
    <div class="ask-sugg">${sugg.map((q) => `<button type="button" class="chip-btn" ${off ? "disabled" : ""}>${esc(q)}</button>`).join("")}</div>
    ${off ? `<p class="small ask-off">${why}</p>` : ""}
    <div class="ask-out" aria-live="polite"></div>`;
  if (off) return;
  const out = $(".ask-out", el), input = $("#askInput", el), btns = $$("button", el);
  const send = async (q) => {
    q = q.trim(); if (!q) return input.focus();
    btns.forEach((b) => { b.disabled = true; }); input.disabled = true;
    out.innerHTML = `<p class="muted small">${t("Claude czyta wyniki analizy…", "Claude is reading the analysis results…")}</p>`;
    try {
      const d = await getJSON("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q, result: res }) });
      out.innerHTML = `<div class="qa"><p class="q">${esc(q)}</p><div class="a">${esc(d.answer).replace(/\n/g, "<br>")}</div>
        <p class="note">${t("Odpowiedź modelu językowego na podstawie liczb z tej analizy — sprawdź ważne decyzje z doradcą.", "A language model's answer based on the numbers from this analysis — check important decisions with an adviser.")}${d.truncated ? t(" (odpowiedź ucięta)", " (answer cut off)") : ""}</p></div>`;
    } catch (err) { out.innerHTML = `<p class="status err">${esc(err.message)}</p>`; }
    finally { btns.forEach((b) => { b.disabled = false; }); input.disabled = false; }
  };
  $(".ask-form", el).onsubmit = (e) => { e.preventDefault(); send(input.value); };
  $$(".chip-btn", el).forEach((b) => b.onclick = () => { input.value = b.textContent; send(b.textContent); });
}

function renderConditions(res) {
  const ind = res.climate.ind, errs = Object.keys(res.errors || {});
  const el = $("#tab-conditions");
  el.innerHTML = `
    ${errs.length ? `<div class="warnbox">${t(`Niektóre źródła nie odpowiedziały (${errs.map(esc).join(", ")}). Tam, gdzie to potrzebne, analiza użyła wartości zastępczych i opisała to w „lukach w danych”.`,
      `Some sources did not respond (${errs.map(esc).join(", ")}). Where needed the analysis used fallback values and described this under “Data gaps”.`)}</div>` : ""}
    <p class="lead">${t(`${ind.n_years} lat danych (${ind.period}) · wysokość ${res.field.elev ?? "?"} m · nachylenie ${res.field.slope_pct ?? "?"}%`,
      `${ind.n_years} years of data (${ind.period}) · elevation ${res.field.elev ?? "?"} m · slope ${res.field.slope_pct ?? "?"}%`)}${res.field.hemisphere === "S" ? t(" · półkula południowa (kalendarz przesunięty)", " · southern hemisphere (calendar shifted)") : ""}.</p>
    <div class="stack">
      <div class="grid g3">${res.tiles.map((x) => `
        <article class="card tile ${x.status}">
          <div class="tile-head"><h3>${esc(x.title)} ${gloss(res, x.glossary)}</h3><span class="state ${x.status}">${STATE_TXT[x.status] || ""}</span></div>
          <div class="val">${esc(x.value)}</div>
          <p>${esc(x.text)}</p>
          <div class="meta"><span class="conf" data-tip="${esc(x.confidence_why)}" tabindex="0">${t("Pewność", "Confidence")}: ${esc(x.confidence)}</span><span>· ${esc(x.source)}</span></div>
        </article>`).join("")}
      </div>
      <div class="grid g2">
        <div class="card"><h3>${t("Opad a parowanie (ET₀) w roku", "Rainfall vs evaporation (ET₀) over the year")} ${gloss(res, ["ET0", "water_balance"])}</h3><div class="chartbox"><canvas id="cClimate"></canvas></div></div>
        <div class="card"><h3>${t("Bilans wodny sezonu IV–IX, rok po roku", "Season water balance Apr–Sep, year by year")}</h3><div class="chartbox"><canvas id="cTrend"></canvas></div></div>
      </div>
      <details class="more" id="moreCharts"><summary>${t("Więcej wykresów: susza glebowa i upały", "More charts: soil drought and heat")}</summary>
        <div class="grid g2" style="margin-top:12px">
          <div class="card"><h3>${t("Suche miesiące gleby w sezonie", "Dry soil months in the season")} ${gloss(res, ["moisture_anomaly"])}</h3><div class="chartbox"><canvas id="cDrought"></canvas></div></div>
          <div class="card"><h3>${t("Dni upalne (Tmax ≥ 30 °C) na rok", "Hot days (Tmax ≥ 30 °C) per year")}</h3><div class="chartbox"><canvas id="cHeat"></canvas></div></div>
        </div></details>
    </div>`;
  const m = res.climate.monthly, y = res.climate.yearly;
  chart("cClimate", { data: { labels: m.labels, datasets: [
    { type: "bar", label: t("Opad [mm]", "Rainfall [mm]"), data: m.p, backgroundColor: C.water + "cc", yAxisID: "y" },
    { type: "bar", label: "ET₀ [mm]", data: m.et0, backgroundColor: C.ochre + "cc", yAxisID: "y" },
    { type: "line", label: t("Temp. średnia [°C]", "Mean temp. [°C]"), data: m.tmean, borderColor: C.rust, backgroundColor: C.rust, yAxisID: "y2", tension: .3 },
  ] }, options: { scales: { y: { title: { display: true, text: t("mm/miesiąc", "mm/month") } }, y2: { position: "right", grid: { display: false }, title: { display: true, text: "°C" } } } } },
  t("Wykres miesięcznego opadu, parowania ET0 i temperatury", "Chart of monthly rainfall, ET0 evaporation and temperature"));
  const trend = linFit(y.years, y.season_balance);
  chart("cTrend", { data: { labels: y.years, datasets: [
    { type: "bar", label: t("Opad − ET₀ [mm]", "Rainfall − ET₀ [mm]"), data: y.season_balance, backgroundColor: y.season_balance.map((v) => v < 0 ? C.rust + "bb" : C.water + "bb") },
    { type: "line", label: `Trend ${sgn(ind.season_trend_dec)}${ind.season_trend_dec} ${t("mm/dekadę", "mm/decade")}`, data: y.years.map((x) => trend(x)), borderColor: C.ink, borderDash: [6, 4], pointRadius: 0 },
  ] } }, t(`Bilans wodny sezonu w kolejnych latach, trend ${ind.season_trend_dec} mm na dekadę`, `Season water balance by year, trend ${ind.season_trend_dec} mm per decade`));
  $("#moreCharts").addEventListener("toggle", (e) => {
    if (!e.target.open || charts.cDrought) return;
    chart("cDrought", { type: "bar", data: { labels: y.years, datasets: [{ label: t("suche miesiące (z 6)", "dry months (of 6)"), data: y.drought_months, backgroundColor: C.earth }] }, options: { scales: { y: { max: 6 } } } },
      t("Liczba suchych miesięcy gleby w kolejnych latach", "Number of dry soil months by year"));
    const ht = linFit(y.years, y.heat_days);
    chart("cHeat", { data: { labels: y.years, datasets: [
      { type: "bar", label: t("dni upalne", "hot days"), data: y.heat_days, backgroundColor: C.ochre + "bb" },
      { type: "line", label: `Trend ${sgn(ind.heat_trend_dec)}${ind.heat_trend_dec} ${t("dni/dekadę", "days/decade")}`, data: y.years.map((x) => ht(x)), borderColor: C.ink, borderDash: [6, 4], pointRadius: 0 },
    ] } }, t(`Dni upalne w kolejnych latach, trend ${ind.heat_trend_dec} dni na dekadę`, `Hot days by year, trend ${ind.heat_trend_dec} days per decade`));
  });
}

function heatRow(label, vals, colorFn, f) {
  const ink = (rgb) => { const [r, g, b] = rgb.match(/\d+/g).map(Number); return 0.299 * r + 0.587 * g + 0.114 * b < 140 ? "#fff" : C.ink; }; // kontrast tekstu w komórce
  return `<div class="y">${label}</div>` + vals.map((v) => { const bg = colorFn(v); return `<div class="c" style="background:${bg};color:${ink(bg)}">${f(v)}</div>`; }).join("");
}
function calendarGrid(s, res) {
  return `<div class="scroll-x"><div class="cal" aria-hidden="true"><div></div>${res.climate.monthly.labels.map((l) => `<div class="h">${l}</div>`).join("")}
    ${s.calendar.map((row, i) => `<div class="y">${t("rok", "yr")} ${i + 1}</div>` + row.map((c) => {
      if (c === "bare") return `<div class="c bare" data-tip="${t("goła gleba", "bare soil")}"></div>`;
      if (c === "cover") return `<div class="c cover" data-tip="${t("międzyplon", "cover crop")}: ${esc(s.cover_type || "")}"></div>`;
      const id = c.slice(5); return `<div class="c" style="background:${CROP_COLORS[id] || "#999"}" data-tip="${esc(res.crop_names[id])}"></div>`;
    }).join("")).join("")}</div></div>`;
}
function calLegend(s, res) {
  return `<div class="legend">${[...new Set(s.seq)].map((id) => `<span><i style="background:${CROP_COLORS[id]}"></i>${esc(res.crop_names[id])}</span>`).join("")}
    <span><i class="bare"></i>${t("goła gleba", "bare soil")}</span>${s.metrics.covers ? `<span><i class="cover"></i>${t("międzyplon", "cover crop")}</span>` : ""}</div>`;
}

function renderCalendar(res) {
  const m = res.climate.monthly, cur = res.strategies[0], nd = res.ndvi;
  $("#tab-calendar").innerHTML = `<div class="stack">
    <div class="card"><h3>${t("Rok na Twoim polu — kiedy jest groźnie?", "A year on your field — when is it risky?")}</h3>
      <div class="scroll-x"><div class="heat">
        <div></div>${m.labels.map((l) => `<div class="h">${l}</div>`).join("")}
        ${heatRow(t("Przymrozek (% dni)", "Frost (% of days)"), m.frost_prob, (v) => mix("#ffffff", C.water, v * 1.6), (v) => v > 0.005 ? Math.round(v * 100) : "")}
        ${heatRow(t("Opad − ET₀ [mm]", "Rainfall − ET₀ [mm]"), m.balance, (v) => v < 0 ? mix("#ffffff", C.rust, -v / 80) : mix("#ffffff", C.water, v / 80), (v) => Math.round(v))}
        ${heatRow(t("Dni ≥ 30 °C", "Days ≥ 30 °C"), m.heat30_days, (v) => mix("#ffffff", C.ochre, v / 8), (v) => v >= 0.1 ? fmt(v) : "")}
        ${heatRow(t("Ulewy [mm]", "Downpours [mm]"), m.erosive_p, (v) => mix("#ffffff", C.earth, v / 50), (v) => Math.round(v) || "")}
        ${heatRow(t("Wilgotność gleby", "Soil moisture"), m.gw, (v) => mix("#f4efe3", C.green2, (v - 0.3) / 0.5), (v) => v != null ? fmt(v, 2) : "")}
      </div></div>
      <p class="note" style="margin-top:8px">${t(`Średnie wieloletnie (${res.climate.ind.period}) z NASA POWER. Wilgotność gleby: GWETROOT 0–1 (model MERRA‑2). Liczby w komórkach są wartościami, kolor tylko je wzmacnia.`,
        `Long-term averages (${res.climate.ind.period}) from NASA POWER. Soil moisture: GWETROOT 0–1 (MERRA‑2 model). The numbers in the cells are the values; colour only reinforces them.`)}</p>
    </div>
    <div class="grid g2">
      <div class="card"><h3>${res.new_field ? t("Propozycja A", "Proposal A") : t("Obecny płodozmian", "Current rotation")}: ${t("kiedy gleba jest goła?", "when is the soil bare?")}</h3>${calendarGrid(cur, res)}${calLegend(cur, res)}
        <p class="small" style="margin-top:8px">${t("Goła gleba średnio", "Bare soil on average")} <b>${cur.metrics.bare_months} ${t("mies./rok", "months/year")}</b>. ${cur.metrics.bare_months >= 3 ? t("To okno na międzyplon — zobacz zakładkę „Płodozmiany”.", "That is a window for a cover crop — see the “Rotations” tab.") : ""}</p></div>
      <div class="card"><h3>${t("Z satelity: zieleń pola (NDVI, MODIS)", "From satellite: field greenness (NDVI, MODIS)")} ${gloss(res, ["NDVI"])}</h3>
        ${nd ? `<div class="chartbox"><canvas id="cNdvi"></canvas></div>
          <p class="small" style="margin-top:8px">${t("Okresy z NDVI", "Periods with NDVI")} &lt; ${nd.threshold} (${t("zwykle goła gleba", "usually bare soil")}): ${nd.bare_windows.map((w) => `${w.from}–${w.to}`).join(", ") || t("brak", "none")}. ${esc(res.ndvi_note || "")}</p>`
        : `<p class="muted small">${t("Serwis MODIS (ORNL DAAC) nie odpowiedział — okresy gołej gleby pokazujemy z modelu kalendarza upraw (obok). Po udanym pobraniu dane trafią do pamięci podręcznej.",
          "The MODIS service (ORNL DAAC) did not respond — bare-soil periods are shown from the crop calendar model (next to this). Once downloaded, the data are cached.")}</p>`}
      </div>
    </div></div>`;
  if (nd) chart("cNdvi", { type: "line", data: { labels: nd.profile.map((p) => doyLabel(p.doy)), datasets: [
    { label: `NDVI (${t("średnia", "mean")} ${nd.years.join(", ")})`, data: nd.profile.map((p) => p.ndvi), borderColor: C.green, backgroundColor: C.green + "22", fill: true, tension: .3 },
    { label: t("próg gołej gleby", "bare-soil threshold"), data: nd.profile.map(() => nd.threshold), borderColor: C.earth, borderDash: [5, 4], pointRadius: 0 },
  ] }, options: { scales: { y: { min: 0, max: 1 } } } }, t("Sezonowy profil NDVI pola z progiem gołej gleby", "Seasonal NDVI profile of the field with the bare-soil threshold"));
}
function doyLabel(doy) { const d = new Date(Date.UTC(2001, 0, doy)); return `${String(d.getUTCDate()).padStart(2, "0")}.${String(d.getUTCMonth() + 1).padStart(2, "0")}`; }

function energyCard(res) {
  const food = res.energy.filter((e) => !e.fodder).slice(0, 10), max = food[0]?.kcal_ha || 1, area = res.field.area_ha;
  const fodder = res.energy.filter((e) => e.fodder).map((e) => e.name);
  return `<div class="card scroll-x"><h3>${t("Wydajność energetyczna — ile jedzenia da hektar", "Energy yield — how much food a hectare gives")}</h3>
    <p class="small muted" style="margin-bottom:12px">${t("Energia = kalorie w 1 kg plonu × typowy plon w Polsce × ocena przydatności dla tego pola.", "Energy = calories in 1 kg of harvest × typical yield in Poland × suitability score for this field.")}
      ${area ? t(`Dla Twojego pola (${fmt(area, 2)} ha) podajemy też, ilu osobom wystarczyłoby to jedzenie przez rok (2500 kcal dziennie).`, `For your field (${fmt(area, 2)} ha) we also show how many people this food would feed for a year (2,500 kcal a day).`)
        : t("Zaznacz działki lub narysuj pole, by zobaczyć wynik dla całej powierzchni.", "Select parcels or draw the field to see the result for the whole area.")}</p>
    <table class="rank"><thead><tr><th scope="col">${t("Uprawa", "Crop")}</th><th scope="col">kcal/kg</th><th scope="col">${t("Plon szac. [t/ha]", "Est. yield [t/ha]")}</th>
      <th scope="col" style="width:32%">${t("Energia [mln kcal/ha]", "Energy [M kcal/ha]")}</th><th scope="col">${area ? t("Twoje pole: osób przez rok", "Your field: people per year") : t("Osób z 1 ha / rok", "People per ha / year")}</th></tr></thead>
    <tbody>${food.map((e) => `<tr><td><b>${esc(e.name)}</b></td><td>${fmt(e.kcal_kg, 0)}</td>
      <td>${fmt(e.yield_t)} <span class="muted small">${t("z", "of")} ${fmt(e.yield_ref_t)}</span></td>
      <td><div style="display:flex;gap:8px;align-items:center"><div class="bar" aria-hidden="true"><i style="width:${100 * e.kcal_ha / max}%;background:${C.green}"></i></div><span class="score">${mkcal(e.kcal_ha)}</span></div></td>
      <td>${area ? fmt(e.persons) : fmt(e.persons_ha)}</td></tr>`).join("")}</tbody></table>
    <p class="note" style="margin-top:8px">${t("Plon szacowany zgrubnie (typowy plon × ocena 0–100). Burak liczony jako cukier możliwy do uzyskania.", "Yield is a rough estimate (typical yield × score 0–100). Sugar beet is counted as extractable sugar.")}
      ${fodder.length ? t(`Uprawy pastewne (${fodder.map(esc).join(", ")}) karmią zwierzęta, nie ludzi — pominięte.`, `Fodder crops (${fodder.map(esc).join(", ")}) feed animals, not people — left out.`) : ""}</p></div>`;
}

function renderCrops(res, all = false) {
  const col = (v) => v >= 75 ? C.green : v >= 50 ? C.ochre : C.rust;
  const rows = all ? res.ranking : res.ranking.slice(0, 8);
  $("#tab-crops").innerHTML = `
    <p class="lead">${t("Ocena 0–100 metodą typu FAO Ecocrop: każdy czynnik (ciepło, woda, pH, zimowanie, przymrozki, upał, gleba, stok, a przy zaznaczonych działkach także klasa gruntu z EGiB) dostaje 0–100, a <b>ocena końcowa = najsłabszy czynnik</b> (prawo minimum). Rozwiń uprawę, by zobaczyć wyliczenia.",
      "Score 0–100 using an FAO Ecocrop-style method: each factor (heat, water, pH, winter survival, frost, heat stress, soil, slope and, for selected parcels, the land-register soil class) gets 0–100, and the <b>final score = the weakest factor</b> (law of the minimum). Expand a crop to see the calculations.")}</p>
    ${energyCard(res)}
    <h3 style="margin:24px 0 12px">${t("Przydatność upraw", "Crop suitability")}</h3>
    <div class="card scroll-x"><table class="rank">
      <thead><tr><th scope="col">#</th><th scope="col">${t("Uprawa", "Crop")}</th><th scope="col" style="width:34%">${t("Ocena", "Score")}</th><th scope="col">${t("Główne ograniczenie", "Main limitation")}</th></tr></thead>
      <tbody>${rows.map((s, i) => `
        <tr><td>${i + 1}</td><td><button type="button" class="toggle" aria-expanded="false" aria-controls="cd${i}">${esc(s.name)}</button><div class="muted" style="font-size:13px">${esc(s.note || "")}</div></td>
          <td><div style="display:flex;gap:8px;align-items:center"><div class="bar" aria-hidden="true"><i style="width:${s.score}%;background:${col(s.score)}"></i></div><span class="score">${s.score}</span></div>
            <div class="factors">${s.factors.map((f) => `<span class="factor ${f.value < 50 ? "lo" : f.value < 85 ? "mid" : ""}">${esc(f.name)} ${f.value}</span>`).join("")}</div></td>
          <td>${esc(s.limiting_label)}</td></tr>
        <tr class="detail" id="cd${i}" hidden><td></td><td colspan="3"><ul>${s.factors.map((f) => `<li><b>${esc(f.name)} (${f.value}/100):</b> ${esc(f.detail)}</li>`).join("")}</ul></td></tr>`).join("")}
      </tbody></table>
      ${all ? "" : `<p style="margin-top:12px"><button type="button" class="link" id="allCrops">${t("Pokaż wszystkie uprawy", "Show all crops")} (${res.ranking.length})</button></p>`}
    </div>`;
  $$("#tab-crops .toggle").forEach((b) => b.onclick = () => {
    const open = b.getAttribute("aria-expanded") !== "true";
    b.setAttribute("aria-expanded", open); $("#" + b.getAttribute("aria-controls")).hidden = !open;
  });
  $("#allCrops")?.addEventListener("click", () => renderCrops(res, true));
}

function renderRotations(res) {
  const S = res.strategies, cur = S[0], ax = res.axes;
  const lbl = (s) => `<span class="lbl" style="background:${stratColor(s)}">${stratShort(s)}</span>`;
  $("#tab-rotations").innerHTML = `
    <p class="lead">${res.new_field ? t(`Nowe pole: ${S.length} propozycje płodozmianu`, `New field: ${S.length} rotation proposals`) : t(`Twój płodozmian i ${S.length - 1} alternatywy`, `Your rotation and ${S.length - 1} alternatives`)}
    ${t(`wybrane spośród ${res.n_checked} wariantów zgodnych z regułami agronomicznymi (przerwy dla rodzin, terminy zbioru i siewu, udział zbóż). <b>Ocena łączna</b> = średnia osi ważona Twoimi priorytetami.`,
      `chosen from ${res.n_checked} variants that follow agronomic rules (breaks between plant families, harvest and sowing dates, cereal share). <b>Total score</b> = average of the axes weighted by your priorities.`)}</p>
    <div class="stack">
      <div class="strats">${S.map((s) => stratCard(s, cur, res, lbl)).join("")}</div>
      <div class="grid g2">
        <div class="card"><h3>${t("Profil strategii (0–100, więcej = lepiej)", "Strategy profile (0–100, higher = better)")}</h3><div class="chartbox" style="height:360px"><canvas id="cRadar"></canvas></div></div>
        <div class="card scroll-x"><h3>${t("Kluczowe liczby", "Key figures")}</h3><table class="rank ktable">
          <thead><tr><th scope="col"><span class="sr-only">${t("Wskaźnik", "Indicator")}</span></th>${S.map((s) => `<th scope="col">${lbl(s)}</th>`).join("")}</tr></thead>
          <tbody>
            <tr><td>${t("Ocena łączna", "Total score")}</td>${S.map((s) => `<td class="score">${s.total}</td>`).join("")}</tr>
            <tr><td>${t("Goła gleba [mies./rok]", "Bare soil [months/yr]")}</td>${S.map((s) => `<td>${s.metrics.bare_months}</td>`).join("")}</tr>
            <tr><td>${t("Erozja [t/ha/rok]", "Erosion [t/ha/yr]")}</td>${S.map((s) => `<td>${s.metrics.erosion_t_ha}</td>`).join("")}</tr>
            <tr><td>${t("Energia żywności [mln kcal/ha/rok]", "Food energy [M kcal/ha/yr]")}</td>${S.map((s) => `<td>${fmt(s.metrics.energy_mkcal_ha)}</td>`).join("")}</tr>
            <tr><td>${t("Bilans próchnicy [kg C/ha/rok]", "Humus balance [kg C/ha/yr]")}</td>${S.map((s) => `<td>${sgn(s.metrics.humus_kg_c)}${s.metrics.humus_kg_c}</td>`).join("")}</tr>
            <tr><td>${t("Deficyt wody upraw [mm]", "Crop water deficit [mm]")}</td>${S.map((s) => `<td>${s.metrics.deficit_mm}</td>`).join("")}</tr>
            <tr><td>${t("Udział zbóż [%]", "Cereal share [%]")}</td>${S.map((s) => `<td>${s.metrics.cereal_share}</td>`).join("")}</tr>
            <tr><td>${t("Rodziny botaniczne", "Plant families")}</td>${S.map((s) => `<td>${s.metrics.families}</td>`).join("")}</tr>
          </tbody></table></div>
      </div>
    </div>`;
  chart("cRadar", { type: "radar", data: { labels: ax.map((k) => res.axis_pl[k]), datasets: S.map((s) => ({
    label: s.is_current ? stratName(s) : `${s.label}: ${s.names.join(" → ")}`, data: ax.map((k) => s.axes[k]),
    borderColor: stratColor(s), backgroundColor: stratColor(s) + "1a", borderWidth: s.is_current ? 3 : 2, borderDash: s.is_current ? [6, 4] : [],
  })) }, options: { scales: { r: { min: 0, max: 100, ticks: { stepSize: 25, display: false } } }, plugins: { legend: { position: "bottom" } } } },
  t("Wykres radarowy porównujący strategie na 7 osiach; te same liczby są w kartach i tabeli", "Radar chart comparing the strategies on 7 axes; the same numbers are in the cards and the table"));
}

function stratCard(s, cur, res, lbl) {
  const c = s.card, li = (arr) => `<ul>${arr.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
  const sec = (title, arr, open = false) => arr?.length ? `<details ${open ? "open" : ""}><summary>${title}</summary>${li(arr)}</details>` : "";
  return `<article class="card strat ${s.is_current ? "current" : ""}">
    <h3><span>${lbl(s)} ${esc(s.title)}</span><span class="total" aria-label="${t("ocena", "score")} ${s.total}">${s.total}</span></h3>
    <div class="seq">${s.names.map(esc).join(" → ")}${s.cover_type ? ` <span class="muted">+ ${t("międzyplony", "cover crops")}</span>` : ""}</div>
    <div class="axes">${res.axes.map((k) => { const d = s.axes[k] - cur.axes[k]; return `<div class="${s.is_current ? "" : d >= 5 ? "up" : d <= -5 ? "down" : ""}"><b>${s.axes[k]}</b>${esc(res.axis_pl[k].split(" ")[0])}</div>`; }).join("")}</div>
    ${calendarGrid(s, res)}
    ${sec(t("Dlaczego?", "Why?"), c.why, true)}${sec(t("Korzyści", "Benefits"), c.benefits)}${sec(t("Ryzyka", "Risks"), c.risks)}
    ${sec(t("Dowody (dane i metody)", "Evidence (data and methods)"), c.evidence)}${sec(t("Luki w danych", "Data gaps"), c.gaps)}${sec(t("Do sprawdzenia z doradcą", "To check with an adviser"), c.check)}
  </article>`;
}

function renderReport(res) {
  const ind = res.climate.ind, S = res.strategies, best = bestStrategy(res), ps = res.parcels;
  $("#tab-report").innerHTML = `<div class="card report">
    <div class="noprint row" style="justify-content:flex-end"><button type="button" onclick="window.print()">${t("Drukuj / zapisz PDF", "Print / save PDF")}</button><button type="button" id="dlJson">${t("Pobierz dane (JSON)", "Download data (JSON)")}</button></div>
    <h2>${t("Raport CropOrbit — pole", "CropOrbit report — field")} ${res.field.lat.toFixed(4)}, ${res.field.lon.toFixed(4)}${res.field.area_ha ? ` (${fmt(res.field.area_ha, 2)} ha)` : ""}</h2>
    <p class="muted">${t(`Wygenerowano ${esc(res.generated)} · dane ${ind.period} · narzędzie wspiera, a nie zastępuje decyzji rolnika i doradcy.`,
      `Generated ${esc(res.generated)} · data ${ind.period} · this tool supports, not replaces, the decisions of the farmer and adviser.`)}</p>
    ${ps?.n ? `<h3>${t("Działki", "Parcels")}</h3><p>${ps.ids.map(esc).join(", ")} · ${t("kontury", "contours")}: ${ps.codes.map(esc).join(", ") || t("brak danych", "no data")}</p>` : ""}
    <h3>${t("Warunki na polu", "Field conditions")}</h3>
    <table><tbody>${res.tiles.map((x) => `<tr><th scope="row">${esc(x.title)}</th><td>${esc(x.value)}</td><td>${esc(x.text)}</td><td>${t("pewność", "confidence")}: ${esc(x.confidence)}</td></tr>`).join("")}</tbody></table>
    <h3>${t("Najwięcej energii z hektara", "Most food energy per hectare")}</h3>
    <p>${res.energy.filter((e) => !e.fodder).slice(0, 5).map((e) => `${esc(e.name)} (${mkcal(e.kcal_ha)} ${t("mln kcal/ha", "M kcal/ha")})`).join(" · ")}</p>
    <h3>${t("Najlepiej dopasowane uprawy", "Best-fitting crops")}</h3>
    <p>${res.ranking.slice(0, 8).map((s) => `${esc(s.name)} (${s.score})`).join(" · ")}</p>
    <h3>${t("Porównanie płodozmianów", "Rotation comparison")}</h3>
    <p class="small muted">${t("Priorytety", "Priorities")}: ${Object.entries(res.inputs.weights).filter(([, v]) => v > 0).map(([k, v]) => `${res.axis_pl[k]} ×${v}`).join(", ")}</p>
    <div class="scroll-x"><table><thead><tr><th>${t("Strategia", "Strategy")}</th><th>${t("Sekwencja", "Sequence")}</th><th>${t("Ocena", "Score")}</th>${res.axes.map((k) => `<th>${esc(res.axis_pl[k])}</th>`).join("")}</tr></thead>
      <tbody>${S.map((s) => `<tr><td>${stratName(s)}</td><td>${s.names.map(esc).join(" → ")}${s.cover_type ? ` + ${t("międzyplony", "cover crops")}` : ""}</td><td><b>${s.total}</b></td>${res.axes.map((k) => `<td>${s.axes[k]}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
    ${best ? `<h3>${t("Rekomendacja do rozmowy z doradcą", "Recommendation to discuss with an adviser")}: ${best.label} — ${esc(best.title)}</h3>
      <ul>${best.card.why.concat(best.card.benefits.slice(0, 4)).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
      <p><b>${t("Ryzyka", "Risks")}:</b></p><ul>${best.card.risks.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
      <p><b>${t("Do sprawdzenia lokalnie", "To check locally")}:</b></p><ul>${best.card.check.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>` : ""}
    <h3>${t("Luki w danych", "Data gaps")}</h3><ul>${S[0].card.gaps.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    <h3>${t("Źródła", "Sources")}</h3><ul>${Object.values(res.sources).map((x) => `<li>${esc(x)}</li>`).join("")}<li>${t("Metody", "Methods")}: FAO‑56 Penman‑Monteith, FAO Ecocrop/GAEZ, RUSLE (Williams K, Arnoldus R), VDLUFA (Eich & Kundler)</li></ul>
  </div>`;
  $("#dlJson").onclick = () => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([JSON.stringify(res, null, 1)], { type: "application/json" }));
    a.download = `croporbit_${res.field.lat.toFixed(3)}_${res.field.lon.toFixed(3)}.json`; a.click();
  };
}

// ================================================================== start
async function restoreAfterLangSwitch() {
  let r = null;
  try { r = JSON.parse(sessionStorage.getItem(RESTORE_KEY)); sessionStorage.removeItem(RESTORE_KEY); } catch { /* brak stanu */ }
  if (!r) return;
  map.setView([r.view[0], r.view[1]], r.view[2]);
  state.rotation = r.rotation || []; renderChips();
  Object.entries(r.checks || {}).forEach(([id, v]) => { $("#" + id).checked = v; });
  $("#newField").dispatchEvent(new Event("change"));
  Object.entries(r.weights || {}).forEach(([k, v]) => { $("#w_" + k).value = v; $("#o_" + k).textContent = v; });
  if (r.parcels?.length) {
    status(t("Przywracam zaznaczone działki…", "Restoring the selected parcels…"));
    for (const id of r.parcels) { try { addParcel(await getJSON("/api/parcel?id=" + encodeURIComponent(id))); } catch { /* działka niedostępna */ } }
    status("");
  } else if (r.point) setPoint(r.point.lat, r.point.lon, r.drawnArea); // shortcut: narysowany obrys wraca jako punkt z powierzchnią
  const demo = r.demoId && state.demos.find((d) => d.id === r.demoId);
  if (demo) return openDemo(demo, { scroll: false });
  if (r.analyzed && fieldGeom()) $("#panel").requestSubmit();
}

// ---------------------------------------------------------- pola przykładowe: gotowe wyniki od ręki
function resetForm() {
  $("#newField").checked = false; $("#newField").dispatchEvent(new Event("change"));
  ["irrigation", "livestock", "coverNow"].forEach((id) => { $("#" + id).checked = false; });
  $("#residues").checked = true;
  AXES.forEach(([k, , v]) => { $("#w_" + k).value = v; $("#o_" + k).textContent = v; });
}
async function openDemo(d, { scroll = true } = {}) {
  clearSelection(); resetForm();
  state.rotation = [...d.rotation]; renderChips();
  let ps = [];
  if (d.parcels?.length) { try { ps = await snap(`parcels_${d.id}.json`); } catch { /* bez obrysu — pokażemy punkt */ } }
  if (ps.length) ps.forEach((p) => addParcel(p, { fit: true }));
  else { map.setView([d.lat, d.lon], 14); setPoint(d.lat, d.lon); }
  try {
    const res = await snap(`${d.id}.${LANG}.json`);
    state.res = res; state.demoId = d.id;
    status(t(`Przykład: ${d.name}. Wynik zapisany wcześniej — ta sama analiza co na żywo (${res.n_checked} wariantów płodozmianu).`,
      `Example: ${d.name}. Saved result — the same analysis as live (${res.n_checked} rotation variants).`));
    showResults(res, scroll);
  } catch {
    if (!STATIC) $("#panel").requestSubmit();
    else status(t("Nie udało się wczytać przykładu.", "Could not load the example."), true);
  }
}

// liczby na pierwszym ekranie liczone z zapisanego wyniku działki przykładowej (nie wpisane na sztywno)
async function renderHeroStats() {
  const box = $("#heroStats");
  try {
    const res = await snap(`trzciana.${LANG}.json`), cur = res.strategies[0], best = bestStrategy(res);
    const m = (k, d = 1) => [fmt(cur.metrics[k], d), fmt(best.metrics[k], d)];
    const row = (label, [a, b], unit) => `<div><dt>${label}</dt><dd><span class="from">${a}</span> → <b>${b}</b> <small>${unit}</small></dd></div>`;
    box.innerHTML = `<p class="stats-title">${t("Działka Trzciana 723/1 · obecny płodozmian → propozycja", "Parcel Trzciana 723/1 · current rotation → proposal")} ${best.label}</p>
      ${row(t("Ocena płodozmianu", "Rotation score"), [cur.total, best.total], "/100")}
      ${row(t("Goła gleba", "Bare soil"), m("bare_months"), t("mies./rok", "months/yr"))}
      ${row(t("Bilans próchnicy", "Humus balance"), [cur.metrics.humus_kg_c, best.metrics.humus_kg_c].map((v) => (v > 0 ? "+" : "") + fmt(v, 0)), t("kg C/ha/rok", "kg C/ha/yr"))}
      ${row(t("Udział zbóż", "Cereal share"), m("cereal_share", 0), "%")}
      <p class="stats-foot">${t(`Sprawdzono ${res.n_checked} wariantów · dane NASA ${res.climate.ind.period}`, `${res.n_checked} variants checked · NASA data ${res.climate.ind.period}`)}</p>`;
    renderHeroYear(res, cur, best);
  } catch { box.hidden = true; }
}

// pasek 12 miesięcy: kiedy gleba jest goła — obecny płodozmian vs propozycja (pierwszy rok kalendarza)
function renderHeroYear(res, cur, best) {
  const months = res.climate.monthly.labels;
  const cell = (c) => c === "bare" ? `<i class="yb bare" title="${t("goła gleba", "bare soil")}"></i>`
    : c === "cover" ? `<i class="yb cover" title="${t("międzyplon", "cover crop")}"></i>`
    : `<i class="yb" style="background:${CROP_COLORS[c.slice(5)] || "#999"}" title="${esc(res.crop_names[c.slice(5)] || "")}"></i>`;
  const bare = (s) => s.calendar[0].filter((c) => c === "bare").length;
  const row = (label, s) => `<div class="yr"><span class="yl">${label}</span><div class="ycells">${s.calendar[0].map(cell).join("")}</div><span class="yn">${bare(s)} ${t("mies.", "mo")}</span></div>`;
  $("#heroYear").innerHTML = `<p class="stats-title">${t("Pierwszy rok płodozmianu — kiedy gleba leży goła", "First year of the rotation — when the soil lies bare")}</p>
    <div class="yr ym"><span class="yl"></span><div class="ycells">${months.map((m) => `<span>${esc(m.slice(0, 1))}</span>`).join("")}</div><span class="yn"></span></div>
    ${row(t("Obecny", "Current"), cur)}${row(t("Propozycja", "Proposal") + " " + best.label, best)}
    <p class="ylegend"><span><i class="yb bare"></i>${t("goła gleba", "bare soil")}</span><span><i class="yb cover"></i>${t("międzyplon", "cover crop")}</span><span><i class="yb crop"></i>${t("uprawa", "crop")}</span></p>`;
}

// sekcja „Problem”: bilans wodny sezonu rok po roku i trend — z zapisanej analizy pola pod Rzeszowem
async function renderWhy() {
  try {
    const res = await snap(`rzeszow.${LANG}.json`), y = res.climate.yearly, ind = res.climate.ind;
    const W = 560, H = 230, pad = { l: 40, r: 12, t: 14, b: 26 };
    const vals = y.season_balance, n = vals.length;
    const lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
    const X = (i) => pad.l + (i + 0.5) * (W - pad.l - pad.r) / n, Y = (v) => pad.t + (hi - v) * (H - pad.t - pad.b) / (hi - lo || 1);
    const bw = (W - pad.l - pad.r) / n * 0.68, fit = linFit(y.years, vals);
    const ticks = [lo, 0, hi].map((v) => Math.round(v / 50) * 50).filter((v, i, a) => a.indexOf(v) === i);
    $("#whySvg").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t(`Bilans wodny sezonu IV–IX w latach ${ind.period}; trend ${ind.season_trend_dec} mm na dekadę`, `Season water balance Apr–Sep in ${ind.period}; trend ${ind.season_trend_dec} mm per decade`))}">
      ${ticks.map((v) => `<line x1="${pad.l}" x2="${W - pad.r}" y1="${Y(v)}" y2="${Y(v)}" class="gl${v === 0 ? " zero" : ""}"/><text x="${pad.l - 6}" y="${Y(v) + 4}" class="tk" text-anchor="end">${v}</text>`).join("")}
      ${vals.map((v, i) => `<rect x="${X(i) - bw / 2}" y="${Math.min(Y(v), Y(0))}" width="${bw}" height="${Math.max(1, Math.abs(Y(v) - Y(0)))}" rx="2" class="${v < 0 ? "neg" : "pos"}"><title>${y.years[i]}: ${sgn(v)}${Math.round(v)} mm</title></rect>`).join("")}
      <line x1="${X(0)}" y1="${Y(fit(y.years[0]))}" x2="${X(n - 1)}" y2="${Y(fit(y.years[n - 1]))}" class="trend"/>
      <text x="${X(0)}" y="${H - 6}" class="tk" text-anchor="middle">${y.years[0]}</text><text x="${X(n - 1)}" y="${H - 6}" class="tk" text-anchor="middle">${y.years[n - 1]}</text>
    </svg>`;
    $("#whyCap").innerHTML = `<b>${t("Pole pod Rzeszowem", "Field near Rzeszów")}</b> · ${t("opad minus parowanie w sezonie IV–IX, mm", "rainfall minus evaporation, Apr–Sep, mm")} · NASA POWER ${esc(ind.period)}`;
    const fact = (big, unit, txt) => `<div class="fact"><b>${big}</b><span class="fu">${unit}</span><p>${txt}</p></div>`;
    $("#whyFacts").innerHTML = [
      fact(`${sgn(ind.season_trend_dec)}${fmt(ind.season_trend_dec, 0)}`, t("mm / dekadę", "mm / decade"), t("tyle wody ubywa w sezonie wegetacyjnym", "less water in the growing season each decade")),
      fact(`${fmt(ind.heat_days_early, 0)} → ${fmt(ind.heat_days_recent, 0)}`, t("dni ≥ 30 °C / rok", "days ≥ 30 °C / yr"), t("dni upalnych na początku i na końcu okresu", "hot days at the start and end of the period")),
      fact("24", t("lata danych dziennych", "years of daily data"), t("ponad 8700 dni pomiarów dla jednego punktu", "over 8,700 days of data for one point")),
    ].join("");
  } catch { $(".why")?.setAttribute("hidden", ""); }
}

(async function init() {
  renderField();
  try {
    state.crops = await getJSON("/api/crops");
    state.demos = await getJSON("/api/demo");
    state.aiStatus = (await getJSON("/api/ai").catch(() => ({}))).status || "no_sdk";
  } catch {
    STATIC = true; state.aiStatus = "static";
    state.crops = await snap(`crops.${LANG}.json`);
    state.demos = await snap(`demo.${LANG}.json`);
    const note = $("#staticNote");
    note.hidden = false;
    note.textContent = t("Wersja pokazowa: pola przykładowe otwierają się od razu. Własne pole policzysz w pełnej wersji (python server.py).",
      "Demo version: the example fields open instantly. Your own field is analysed in the full version (python server.py).");
  }
  $("#cropSelect").innerHTML = state.crops.map((c) => `<option value="${c.id}">${esc(c.name)}</option>`).join("");
  renderChips();
  $("#demoBtns").innerHTML = state.demos.map((d, i) => `<button type="button" data-i="${i}">${esc(d.name.split(" (")[0])}</button>`).join(" ");
  $$("#demoBtns button").forEach((b) => b.onclick = () => openDemo(state.demos[+b.dataset.i]));
  $("#heroDemo").onclick = () => openDemo(state.demos.find((d) => d.id === "trzciana") || state.demos[0]);
  renderHeroStats();
  renderWhy();
  // link bezpośrednio do wyniku przykładu, np. ?demo=trzciana (do README i zgłoszeń)
  const linked = state.demos.find((d) => d.id === new URLSearchParams(location.search).get("demo"));
  if (linked && !sessionStorage.getItem(RESTORE_KEY)) {
    await openDemo(linked, { scroll: false });
    $("#results").scrollIntoView({ block: "start", behavior: "instant" });
    return;
  }
  await restoreAfterLangSwitch();
})();
