"""CropOrbit — „Zapytaj o swoje pole”: odpowiedź na pytanie rolnika wyłącznie z liczb policzonych w analizie.

Moduł opcjonalny. Reszta aplikacji działa na samej bibliotece standardowej; ten moduł potrzebuje
oficjalnego SDK (`pip install anthropic`) i klucza w zmiennej ANTHROPIC_API_KEY. Bez nich available() == False,
a interfejs pokazuje, czego brakuje.

Zasada uczciwości z reszty aplikacji zostaje: model dostaje tylko wyniki analizy (kafle, ranking, płodozmiany,
źródła) i ma odpowiadać wyłącznie z nich, z nazwą wskaźnika i źródłem; czego nie ma w danych — mówi wprost.
"""
import json
import os

try:
    import anthropic
except ImportError:  # SDK nie jest wymagany do reszty aplikacji
    anthropic = None

MODEL = "claude-opus-5-5"
_client = None

SYSTEM = """You answer a farmer's question about one field analysed by CropOrbit.

You receive FIELD_DATA: the numbers CropOrbit computed for this field from NASA POWER, SRTM, MODIS, ISRIC SoilGrids \
and the Polish land register (condition tiles, crop suitability ranking, the current rotation and alternatives with \
their metrics, reasons, risks and data gaps). These numbers are the only facts you may use.

Rules:
- Answer only from FIELD_DATA. Quote the exact numbers with their units and name the indicator or tile they come from.
- If the answer is not in FIELD_DATA (prices, subsidies, pests, local weather, fertiliser doses, anything else), say \
plainly that the analysis does not contain it and suggest checking it with a local agricultural adviser.
- Never invent numbers, sources or crop facts that are not in FIELD_DATA.
- Mention the confidence level when a number has low confidence.
- Write for a farmer: plain words, short sentences, 3 to 6 sentences, no headings and no tables. Bullet points only \
if the question asks for a list.
- Reply in the language given in LANGUAGE."""


def available():
    return anthropic is not None and bool(os.environ.get("ANTHROPIC_API_KEY"))


def status():
    if anthropic is None:
        return "no_sdk"
    return "ok" if os.environ.get("ANTHROPIC_API_KEY") else "no_key"


def _client_once():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def facts(res):
    """Zwięzły wyciąg z wyniku /api/analyze — tylko to, co pokazuje interfejs, bez wykresów dziennych."""
    ind = res.get("climate", {}).get("ind", {})
    return {
        "field": res.get("field"),
        "parcels": res.get("parcels") and {k: res["parcels"].get(k) for k in ("n", "area_ha", "codes", "field_class")},
        "inputs": res.get("inputs"),
        "data_period": ind.get("period"),
        "conditions": [{k: x.get(k) for k in ("title", "status", "value", "text", "confidence", "confidence_why", "source")}
                       for x in res.get("tiles", [])],
        "crop_ranking": [{"crop": s.get("name"), "score": s.get("score"), "main_limitation": s.get("limiting_label"),
                          "factors": {f.get("name"): f.get("value") for f in s.get("factors", [])}}
                         for s in res.get("ranking", [])],
        "rotations": [{"label": s.get("label"), "title": s.get("title"), "is_current": s.get("is_current"),
                       "sequence": s.get("names"), "cover_crops": s.get("cover_type"), "total_score": s.get("total"),
                       "axes_0_100": s.get("axes"), "metrics": s.get("metrics"), "card": s.get("card")}
                      for s in res.get("strategies", [])],
        "axis_names": res.get("axis_pl"),
        "rotation_variants_checked": res.get("n_checked"),
        "food_energy": [{k: e.get(k) for k in ("name", "kcal_ha", "yield_t", "persons_ha", "fodder")} for e in res.get("energy", [])[:10]],
        "data_errors": res.get("errors"),
        "sources": res.get("sources"),
    }


def ask(question, res, lang):
    """Zwraca {"answer": str, "model": str} albo podnosi wyjątek SDK (obsługa w server.py)."""
    language = "Polish" if lang == "pl" else "English"
    data = json.dumps(facts(res), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    response = _client_once().beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        output_config={"effort": "low"},  # krótka odpowiedź na pytanie, nie zadanie wieloetapowe
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",  # odmowa klasyfikatora → ta sama prośba na modelu zapasowym
        system=SYSTEM,
        messages=[{"role": "user", "content": [
            # dane pola na początku i w pamięci podręcznej: kolejne pytania o to samo pole są tańsze
            {"type": "text", "text": f"FIELD_DATA:\n{data}", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": f"LANGUAGE: {language}\n\nQUESTION: {question}"},
        ]}],
    )
    if response.stop_reason == "refusal":
        return {"answer": None, "refused": True, "model": response.model}
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return {"answer": text, "model": response.model, "truncated": response.stop_reason == "max_tokens"}
