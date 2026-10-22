"""Outils Claude pour interroger en direct l'API BDM de l'INSEE (data.gouv.fr « api-bdm », gratuite, sans clé).

Complète le référentiel figé (data/referentiel) : quand une affirmation chiffrée sort des 15 séries emploi,
Claude peut chercher lui-même la série officielle (dette, prix, PIB, pauvreté…) au lieu d'un article web.

Trois outils, dans l'ordre d'usage :
  insee_chercher_themes   mots-clés → thèmes (« dataflows ») de la BDM
  insee_lister_series     thème → séries (idbank, titre, dernier point)
  insee_lire_serie        idbank → observations datées + URL de la page INSEE (à citer)

Limites de l'API : 30 appels/min par IP (on espace les appels), réponses XML SDMX, et les très gros
thèmes (ex. IPC-2025) sont refusés en bloc (HTTP 413) — d'où les idbanks fréquents listés plus bas.
"""
from __future__ import annotations

import json
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET  # expat récent : pas d'entités externes ni de « billion laughs »

API = "https://bdm.insee.fr/series/sdmx"
SERIES_URL = "https://www.insee.fr/fr/statistiques/serie/{}"
CACHE_TTL = 6 * 3600          # les séries bougent au mieux une fois par mois
MIN_INTERVAL = 2.1            # 30 appels/min max
MAX_SERIES_LISTED = 40
MAX_OBS_DEFAULT = 40
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

# Séries vérifiées sur l'API le 2026-10-22, pour aller droit au but sans passer par la recherche.
FREQUENT = {
    "011814632": "Inflation : glissement annuel de l'indice des prix à la consommation (IPC base 2025), ensemble, France, mensuel",
    "011814630": "Indice des prix à la consommation (IPC base 2025), ensemble des ménages, France, mensuel",
    "010777608": "Dette publique au sens de Maastricht, en % du PIB, trimestrielle",
    "010777616": "Dette publique au sens de Maastricht, en milliards d'euros, trimestrielle",
    "001688527": "Taux de chômage BIT, France hors Mayotte, trimestriel",
}

_cache: dict[str, tuple[float, bytes]] = {}
_lock = threading.Lock()
_last_call = 0.0


class InseeError(RuntimeError):
    pass


def _get(path: str, timeout: int = 60) -> bytes:
    url = f"{API}/{path}"
    now = time.time()
    if (hit := _cache.get(url)) and now - hit[0] < CACHE_TTL:
        return hit[1]
    global _last_call
    with _lock:  # espace les appels réels entre threads (vérifications en parallèle)
        wait = MIN_INTERVAL - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 413:
            raise InseeError("réponse trop volumineuse : ce thème contient trop de séries pour être listé en bloc")
        if e.code == 404:
            raise InseeError("introuvable (thème ou idbank inexistant)")
        raise InseeError(f"API INSEE : HTTP {e.code}")
    except urllib.error.URLError as e:
        raise InseeError(f"API INSEE injoignable : {e.reason}")
    _cache[url] = (now, body)
    return body


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _series_elements(xml: bytes) -> list[ET.Element]:
    return [e for e in ET.fromstring(xml).iter() if e.tag == "Series" or e.tag.endswith("}Series")]


def _value(raw: str | None) -> float | None:
    return None if raw in (None, "", "NaN") else float(raw)


def search_dataflows(query: str) -> list[dict]:
    root = ET.fromstring(_get("dataflow/FR1/all"))
    words = [_norm(w) for w in query.split() if len(w) > 2]
    out = []
    for f in (e for e in root.iter() if e.tag.endswith("}Dataflow")):
        name = next((n.text for n in f if n.tag.endswith("}Name") and n.get(XML_LANG) == "fr"), "") or ""
        hay = _norm(f"{f.get('id')} {name}")
        score = sum(w in hay for w in words)
        if score:
            out.append((score, {"theme": f.get("id"), "nom": name}))
    out.sort(key=lambda x: -x[0])
    return [d for _, d in out[:25]]


def parse_series(xml: bytes) -> list[dict]:
    """XML SDMX → séries avec leurs observations triées par période (testé dans selftest)."""
    out = []
    for s in _series_elements(xml):
        mult = int(s.get("UNIT_MULT") or 0)
        obs = sorted(((o.get("TIME_PERIOD"), _value(o.get("OBS_VALUE"))) for o in s), key=lambda x: x[0] or "")
        out.append({
            "idbank": s.get("IDBANK"),
            "titre": s.get("TITLE_FR"),
            "unite": s.get("UNIT_MEASURE"),
            "puissance_de_10": mult,  # 9 = valeurs en milliards
            "frequence": s.get("FREQ"),
            "derniere_maj": s.get("LAST_UPDATE"),
            "observations": [[p, v] for p, v in obs if v is not None],
        })
    return out


def list_series(theme: str, filtre: str = "") -> dict:
    series = parse_series(_get(f"data/{urllib.parse.quote(theme)}?lastNObservations=1"))
    words = [_norm(w) for w in filtre.split() if len(w) > 2]
    if words:
        series = [s for s in series if all(w in _norm(s["titre"] or "") for w in words)]
    return {
        "theme": theme,
        "nb_series": len(series),
        "series": [{"idbank": s["idbank"], "titre": s["titre"], "unite": s["unite"],
                    "puissance_de_10": s["puissance_de_10"],
                    "dernier_point": s["observations"][-1] if s["observations"] else None}
                   for s in series[:MAX_SERIES_LISTED]],
        **({"note": f"{len(series) - MAX_SERIES_LISTED} séries non affichées : précise le filtre"}
           if len(series) > MAX_SERIES_LISTED else {}),
    }


def get_series(idbank: str, debut: str = "", fin: str = "") -> dict:
    if not idbank.isdigit():
        raise InseeError("idbank invalide : 9 chiffres attendus, ex. 001759970")
    params = {k: v for k, v in (("startPeriod", debut), ("endPeriod", fin)) if v}
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    found = parse_series(_get(f"data/SERIES_BDM/{idbank}{query}"))
    if not found:
        raise InseeError("aucune donnée pour cet idbank et cette période")
    s = found[0]
    if not params and len(s["observations"]) > MAX_OBS_DEFAULT:
        s["observations"] = s["observations"][-MAX_OBS_DEFAULT:]
        s["note"] = f"{MAX_OBS_DEFAULT} derniers points ; utilise debut/fin pour une autre période"
    s["url"] = SERIES_URL.format(idbank)
    s["editeur"] = "INSEE"
    return s


TOOLS = [
    {
        "name": "insee_chercher_themes",
        "description": ("Cherche des thèmes (dataflows) de la base de données macroéconomiques (BDM) de l'INSEE par "
                        "mots-clés en français, ex. « dette publique », « prix consommation », « pauvreté ». "
                        "Renvoie les identifiants de thème à passer à insee_lister_series. Préfère la base la plus récente "
                        "(suffixe -2020 ou -2025) : les anciennes bases sont arrêtées. Séries fréquentes "
                        "utilisables directement avec insee_lire_serie : "
                        + " ; ".join(f"{k} = {v}" for k, v in FREQUENT.items())),
        "input_schema": {"type": "object", "properties": {"mots_cles": {"type": "string"}},
                         "required": ["mots_cles"], "additionalProperties": False},
    },
    {
        "name": "insee_lister_series",
        "description": ("Liste les séries d'un thème INSEE (idbank, titre, unité, dernier point). `filtre` garde les "
                        "séries dont le titre contient tous ces mots (ex. « ensemble PIB »). Les très gros thèmes "
                        "(indices de prix) sont refusés : utilise alors un idbank fréquent."),
        "input_schema": {"type": "object", "properties": {
            "theme": {"type": "string", "description": "identifiant renvoyé par insee_chercher_themes"},
            "filtre": {"type": "string"}},
            "required": ["theme"], "additionalProperties": False},
    },
    {
        "name": "insee_lire_serie",
        "description": ("Lit les observations officielles d'une série INSEE par son idbank, avec l'URL de sa page "
                        "insee.fr à citer comme source. Périodes au format AAAA, AAAA-MM ou AAAA-Qn. Sans debut/fin : "
                        f"les {MAX_OBS_DEFAULT} derniers points. Tiens compte de puissance_de_10 (9 = milliards)."),
        "input_schema": {"type": "object", "properties": {
            "idbank": {"type": "string"}, "debut": {"type": "string"}, "fin": {"type": "string"}},
            "required": ["idbank"], "additionalProperties": False},
    },
]
TOOL_NAMES = {t["name"] for t in TOOLS}


def run_tool(name: str, args: dict) -> tuple[str, list[dict], bool]:
    """Exécute un outil. Renvoie (résultat JSON pour Claude, sources consultées, erreur ?)."""
    try:
        if name == "insee_chercher_themes":
            result: object = search_dataflows(str(args.get("mots_cles", "")))
        elif name == "insee_lister_series":
            result = list_series(str(args["theme"]), str(args.get("filtre", "")))
        elif name == "insee_lire_serie":
            result = get_series(str(args["idbank"]).strip(), str(args.get("debut", "")), str(args.get("fin", "")))
        else:
            return f"outil inconnu : {name}", [], True
    except (InseeError, KeyError, ValueError, ET.ParseError) as e:
        return f"Erreur : {e}", [], True
    seen = ([{"title": result["titre"], "url": result["url"], "publisher": "INSEE"}]
            if name == "insee_lire_serie" else [])
    return json.dumps(result, ensure_ascii=False), seen, False
